from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import polars as pl

from licor.ingestion import LmuTelemetryDatabase


REQUIRED_LAP_CHANNELS = (
    "Fuel Level",
    "Lap Dist",
    "Ground Speed",
    "Throttle Pos",
    "Brake Pos",
)


@dataclass(frozen=True)
class LapSummaryConfig:
    min_lap_distance_m: float = 6500.0
    max_lap_distance_m: float = 7500.0
    required_channels: tuple[str, ...] = REQUIRED_LAP_CHANNELS


@dataclass(frozen=True)
class RunLapLabels:
    run_id: str
    file: str
    track: str
    car_class: str
    car: str
    session_type: str
    run_type: str
    collection_label: str
    labels_quality: str
    valid_laps: frozenset[int] = field(default_factory=frozenset)
    borderline_laps: frozenset[int] = field(default_factory=frozenset)
    context_laps: frozenset[int] = field(default_factory=frozenset)
    excluded_laps: frozenset[int] = field(default_factory=frozenset)
    include_in_lap_summary: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RunLapLabels:
        return cls(
            run_id=str(data["run_id"]),
            file=str(data["file"]),
            track=str(data["track"]),
            car_class=str(data["car_class"]),
            car=str(data["car"]),
            session_type=str(data["session_type"]),
            run_type=str(data["run_type"]),
            collection_label=str(data["collection_label"]),
            labels_quality=str(data["labels_quality"]),
            valid_laps=frozenset(int(lap) for lap in data.get("valid_laps", [])),
            borderline_laps=frozenset(
                int(lap) for lap in data.get("borderline_laps", [])
            ),
            context_laps=frozenset(int(lap) for lap in data.get("context_laps", [])),
            excluded_laps=frozenset(int(lap) for lap in data.get("excluded_laps", [])),
            include_in_lap_summary=bool(data.get("include_in_lap_summary", True)),
        )

    def driver_label_for_lap(self, lap_number: int) -> str:
        if lap_number in self.excluded_laps:
            return "excluded"
        if lap_number in self.borderline_laps:
            return "borderline"
        if lap_number in self.valid_laps:
            return "valid"
        if lap_number in self.context_laps:
            return "context"
        return "unlabeled"

    def driver_includes_lap(self, lap_number: int) -> bool:
        return self.driver_label_for_lap(lap_number) in {"valid", "borderline"}


@dataclass(frozen=True)
class DatasetLapLabels:
    dataset_id: str
    description: str
    runs: tuple[RunLapLabels, ...]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DatasetLapLabels:
        return cls(
            dataset_id=str(data["dataset_id"]),
            description=str(data.get("description", "")),
            runs=tuple(RunLapLabels.from_dict(run) for run in data.get("runs", [])),
        )


def load_dataset_lap_labels(path: str | Path) -> DatasetLapLabels:
    with Path(path).open(encoding="utf-8") as file:
        return DatasetLapLabels.from_dict(json.load(file))


def summarize_labeled_dataset(
    label_file: str | Path,
    *,
    project_root: str | Path = ".",
    config: LapSummaryConfig | None = None,
    include_pitstop_runs: bool = False,
) -> pl.DataFrame:
    labels = load_dataset_lap_labels(label_file)
    root = Path(project_root)
    frames = []
    for run in labels.runs:
        if not run.include_in_lap_summary and not include_pitstop_runs:
            continue
        path = root / run.file
        with LmuTelemetryDatabase(path) as telemetry:
            frames.append(summarize_laps(telemetry, run_labels=run, config=config))
    if not frames:
        return pl.DataFrame()
    return pl.concat(frames, how="diagonal")


def summarize_laps(
    telemetry: LmuTelemetryDatabase,
    *,
    run_labels: RunLapLabels | None = None,
    config: LapSummaryConfig | None = None,
) -> pl.DataFrame:
    summary_config = config or LapSummaryConfig()
    channels = telemetry.channels()
    channel_frames = {
        channel: telemetry.fixed_channel(channel)
        for channel in summary_config.required_channels
        if channel in channels
    }
    in_pits = (
        telemetry.event_series("In Pits")
        if "In Pits" in telemetry.events()
        else pl.DataFrame({"ts": [], "value": []})
    )

    rows = []
    for interval in telemetry.lap_intervals():
        fuel = _channel_window(channel_frames.get("Fuel Level"), interval.start_ts, interval.end_ts)
        distance = _channel_window(channel_frames.get("Lap Dist"), interval.start_ts, interval.end_ts)
        speed = _channel_window(
            channel_frames.get("Ground Speed"), interval.start_ts, interval.end_ts
        )
        throttle = _channel_window(
            channel_frames.get("Throttle Pos"), interval.start_ts, interval.end_ts
        )
        brake = _channel_window(channel_frames.get("Brake Pos"), interval.start_ts, interval.end_ts)

        fuel_start = _first_value(fuel)
        fuel_end = _last_value(fuel)
        fuel_used = (
            fuel_start - fuel_end if fuel_start is not None and fuel_end is not None else None
        )
        max_lap_distance = _max_value(distance)
        min_speed = _min_value(speed)
        max_speed = _max_value(speed)
        mean_speed = _mean_value(speed)
        mean_throttle = _mean_value(throttle)
        max_brake = _max_value(brake)

        has_required_channels = all(
            channel in channel_frames for channel in summary_config.required_channels
        )
        complete_required_coverage = all(
            _channel_window(channel_frames.get(channel), interval.start_ts, interval.end_ts).height
            > 0
            for channel in summary_config.required_channels
        )
        distance_in_range = (
            max_lap_distance is not None
            and summary_config.min_lap_distance_m
            <= max_lap_distance
            <= summary_config.max_lap_distance_m
        )
        has_positive_fuel_burn = fuel_used is not None and fuel_used >= 0.0
        in_pit_interval = _event_active_in_interval(in_pits, interval.start_ts, interval.end_ts)
        passes_basic_validation = (
            has_required_channels
            and complete_required_coverage
            and distance_in_range
            and has_positive_fuel_burn
            and not in_pit_interval
        )

        driver_label = (
            run_labels.driver_label_for_lap(interval.lap_number)
            if run_labels is not None
            else "unlabeled"
        )
        driver_included = (
            run_labels.driver_includes_lap(interval.lap_number)
            if run_labels is not None
            else True
        )

        row = {
            "run_id": run_labels.run_id if run_labels is not None else None,
            "file_name": Path(run_labels.file).name if run_labels is not None else telemetry.path.name,
            "track": run_labels.track if run_labels is not None else None,
            "car_class": run_labels.car_class if run_labels is not None else None,
            "run_type": run_labels.run_type if run_labels is not None else None,
            "collection_label": run_labels.collection_label if run_labels is not None else None,
            "labels_quality": run_labels.labels_quality if run_labels is not None else None,
            "lap_number": interval.lap_number,
            "lap_start_ts": interval.start_ts,
            "lap_end_ts": interval.end_ts,
            "lap_time_s": interval.duration_s,
            "fuel_start_l": fuel_start,
            "fuel_end_l": fuel_end,
            "fuel_used_l": fuel_used,
            "max_lap_distance_m": max_lap_distance,
            "min_ground_speed_kph": min_speed,
            "max_ground_speed_kph": max_speed,
            "mean_ground_speed_kph": mean_speed,
            "mean_throttle_pct": mean_throttle,
            "max_brake_pct": max_brake,
            "fuel_samples": fuel.height,
            "distance_samples": distance.height,
            "speed_samples": speed.height,
            "throttle_samples": throttle.height,
            "brake_samples": brake.height,
            "has_required_channels": has_required_channels,
            "complete_required_coverage": complete_required_coverage,
            "distance_in_expected_range": distance_in_range,
            "has_positive_fuel_burn": has_positive_fuel_burn,
            "in_pits": in_pit_interval,
            "passes_basic_validation": passes_basic_validation,
            "driver_lap_label": driver_label,
            "driver_included": driver_included,
            "is_valid_lap": passes_basic_validation and driver_included,
            "exclusion_reason": _exclusion_reason(
                driver_label=driver_label,
                has_required_channels=has_required_channels,
                complete_required_coverage=complete_required_coverage,
                distance_in_range=distance_in_range,
                has_positive_fuel_burn=has_positive_fuel_burn,
                in_pits=in_pit_interval,
            ),
        }
        rows.append(row)

    return pl.DataFrame(rows)


def filter_valid_laps(summary: pl.DataFrame) -> pl.DataFrame:
    return summary.filter(pl.col("is_valid_lap")).sort(["run_id", "lap_number"])


def _channel_window(frame: pl.DataFrame | None, start_ts: float, end_ts: float) -> pl.DataFrame:
    if frame is None:
        return pl.DataFrame({"ts": [], "value": []})
    return frame.filter((pl.col("ts") >= start_ts) & (pl.col("ts") < end_ts))


def _first_value(frame: pl.DataFrame) -> float | None:
    if frame.is_empty():
        return None
    return float(frame["value"][0])


def _last_value(frame: pl.DataFrame) -> float | None:
    if frame.is_empty():
        return None
    return float(frame["value"][-1])


def _min_value(frame: pl.DataFrame) -> float | None:
    if frame.is_empty():
        return None
    return float(frame["value"].min())


def _max_value(frame: pl.DataFrame) -> float | None:
    if frame.is_empty():
        return None
    return float(frame["value"].max())


def _mean_value(frame: pl.DataFrame) -> float | None:
    if frame.is_empty():
        return None
    return float(frame["value"].mean())


def _event_active_in_interval(events: pl.DataFrame, start_ts: float, end_ts: float) -> bool:
    if events.is_empty():
        return False
    before_end = events.filter(pl.col("ts") < end_ts)
    if before_end.is_empty():
        return False
    active_at_start = before_end.filter(pl.col("ts") <= start_ts)
    if not active_at_start.is_empty() and int(active_at_start["value"][-1]) != 0:
        return True
    events_inside = before_end.filter(pl.col("ts") >= start_ts)
    return bool((events_inside["value"] != 0).any()) if not events_inside.is_empty() else False


def _exclusion_reason(
    *,
    driver_label: str,
    has_required_channels: bool,
    complete_required_coverage: bool,
    distance_in_range: bool,
    has_positive_fuel_burn: bool,
    in_pits: bool,
) -> str | None:
    reasons = []
    if driver_label == "excluded":
        reasons.append("driver_excluded")
    if driver_label in {"context", "unlabeled"}:
        reasons.append(f"driver_{driver_label}")
    if not has_required_channels:
        reasons.append("missing_required_channel")
    if not complete_required_coverage:
        reasons.append("incomplete_required_coverage")
    if not distance_in_range:
        reasons.append("distance_out_of_range")
    if not has_positive_fuel_burn:
        reasons.append("fuel_burn_not_positive")
    if in_pits:
        reasons.append("in_pits")
    return ", ".join(reasons) if reasons else None
