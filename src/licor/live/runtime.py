from __future__ import annotations

import csv
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Protocol

import polars as pl

from licor.analysis import (
    LiveCueRunnerConfig,
    load_live_cue_plan,
    summarize_live_cue_event_accuracy,
)
from licor.live.audio import AudioCue, AudioCueAdapter, NullAudioCueAdapter
from licor.live.lmu_shared_memory import LmuLiveTelemetrySample, LMUSharedMemoryReader


_MAX_SCORING_DISTANCE_PROJECTION_S = 0.25
_UNKNOWN_TRACK_WRAP_THRESHOLD_M = 100.0


@dataclass(frozen=True)
class LiveStaticCueSessionConfig(LiveCueRunnerConfig):
    update_timeout_ms: int = 250
    write_accuracy_log: bool = True
    overwrite_existing_logs: bool = False
    max_laps: int | None = None
    max_events: int | None = None
    cue_lap_numbers: tuple[int, ...] | None = None
    stop_after_lap_number: int | None = None
    lap_plan_schedule: tuple[tuple[int, str], ...] | None = None


class LiveTelemetrySampleSource(Protocol):
    def read_next_sample(self, *, timeout_ms: int) -> LmuLiveTelemetrySample | None:
        """Read the next available live telemetry sample."""

    def close(self) -> None:
        """Release any open resources."""


class LMUSharedMemorySampleSource:
    def __init__(self, reader: LMUSharedMemoryReader) -> None:
        self._reader = reader

    def read_next_sample(self, *, timeout_ms: int) -> LmuLiveTelemetrySample | None:
        return self._reader.read_next_player_sample(timeout_ms=timeout_ms)

    def close(self) -> None:
        self._reader.close()


def run_static_live_cue_session(
    *,
    plan_path: str | Path,
    event_log_path: str | Path,
    accuracy_log_path: str | Path | None = None,
    telemetry_log_path: str | Path | None = None,
    sample_source: LiveTelemetrySampleSource,
    audio_adapter: AudioCueAdapter | None = None,
    config: LiveStaticCueSessionConfig | None = None,
) -> pl.DataFrame:
    session_config = config or LiveStaticCueSessionConfig()
    plan = load_live_cue_plan(plan_path)
    runtime = _LiveCueRuntime(plan, config=session_config)
    event_path = _prepare_csv_output(
        event_log_path,
        overwrite_existing=session_config.overwrite_existing_logs,
        header=_LIVE_CUE_EVENT_LOG_COLUMNS,
    )
    emitted_rows: list[dict[str, object]] = []
    adapter = audio_adapter or NullAudioCueAdapter()
    telemetry_handle = None

    try:
        if telemetry_log_path is not None:
            telemetry_columns = [field.name for field in fields(LmuLiveTelemetrySample)]
            telemetry_path = _prepare_csv_output(
                telemetry_log_path,
                overwrite_existing=session_config.overwrite_existing_logs,
                header=telemetry_columns,
            )
            telemetry_handle = telemetry_path.open("a", newline="", encoding="utf-8")
            telemetry_writer = csv.DictWriter(
                telemetry_handle, fieldnames=telemetry_columns
            )
            telemetry_count = 0
        while True:
            sample = sample_source.read_next_sample(
                timeout_ms=session_config.update_timeout_ms
            )
            if sample is None:
                continue
            if telemetry_handle is not None:
                telemetry_writer.writerow(asdict(sample))
                telemetry_count += 1
                if telemetry_count % 100 == 0:
                    telemetry_handle.flush()
            for event in runtime.process_sample(sample):
                _append_csv_row(
                    event_path, header=_LIVE_CUE_EVENT_LOG_COLUMNS, row=event
                )
                emitted_rows.append(event)
                if not event["cue_enabled"]:
                    continue
                adapter.emit(
                    AudioCue(
                        plan_id=str(event["plan_id"]),
                        zone_id=str(event["zone_id"]),
                        display_label=str(event["display_label"]),
                        lap_number=int(event["lap_number"]),
                        trigger_status=str(event["trigger_status"]),
                        audio_cue_kind=str(event["audio_cue_kind"]),
                    )
                )
            if runtime.should_stop():
                break
    except KeyboardInterrupt:
        pass
    finally:
        if telemetry_handle is not None:
            telemetry_handle.close()
        sample_source.close()

    events = (
        pl.DataFrame(
            emitted_rows, schema=_LIVE_CUE_EVENT_LOG_SCHEMA, strict=False
        ).select(_LIVE_CUE_EVENT_LOG_COLUMNS)
        if emitted_rows
        else pl.DataFrame(schema=_LIVE_CUE_EVENT_LOG_SCHEMA)
    )
    if session_config.write_accuracy_log:
        accuracy_path = accuracy_log_path or _default_accuracy_log_path(event_path)
        accuracy = summarize_live_cue_event_accuracy(
            events.filter(pl.col("cue_enabled"))
        )
        _write_frame(
            accuracy,
            accuracy_path,
            overwrite_existing=session_config.overwrite_existing_logs,
        )
    return events


def run_lmu_static_live_cue_session(
    *,
    plan_path: str | Path,
    event_log_path: str | Path,
    accuracy_log_path: str | Path | None = None,
    telemetry_log_path: str | Path | None = None,
    audio_adapter: AudioCueAdapter | None = None,
    config: LiveStaticCueSessionConfig | None = None,
) -> pl.DataFrame:
    sample_source = LMUSharedMemorySampleSource(LMUSharedMemoryReader())
    return run_static_live_cue_session(
        plan_path=plan_path,
        event_log_path=event_log_path,
        accuracy_log_path=accuracy_log_path,
        telemetry_log_path=telemetry_log_path,
        sample_source=sample_source,
        audio_adapter=audio_adapter,
        config=config,
    )


class _LiveCueRuntime:
    def __init__(
        self, live_cue_plan: pl.DataFrame, *, config: LiveStaticCueSessionConfig
    ) -> None:
        self._config = config
        self._cues = list(live_cue_plan.sort("cue_distance_m").iter_rows(named=True))
        self._lap_plan_by_number = _validate_lap_plan_schedule(live_cue_plan, config)
        self._track_length_m = _track_length_m(live_cue_plan, config.track_length_m)
        self._triggered_by_lap: dict[int, set[tuple[str, str]]] = {}
        self._distance_anchor_by_lap: dict[int, LmuLiveTelemetrySample] = {}
        self._previous_distance_by_lap: dict[int, float] = {}
        self._sample_index = 0
        self._event_count = 0
        self._first_lap_number: int | None = None
        self._max_lap_seen: int | None = None

    def process_sample(self, sample: LmuLiveTelemetrySample) -> list[dict[str, object]]:
        if self._first_lap_number is None:
            self._first_lap_number = sample.lap_number
        self._max_lap_seen = (
            sample.lap_number
            if self._max_lap_seen is None
            else max(self._max_lap_seen, sample.lap_number)
        )
        if (
            self._config.stop_after_lap_number is not None
            and sample.lap_number > self._config.stop_after_lap_number
        ):
            return []

        (
            effective_distance_m,
            distance_anchor,
            distance_method,
            projection_age_s,
        ) = _effective_lap_distance_m(
            sample,
            anchor=self._distance_anchor_by_lap.get(sample.lap_number),
            track_length_m=self._track_length_m,
        )
        self._distance_anchor_by_lap[sample.lap_number] = distance_anchor
        previous_distance_m = self._previous_distance_by_lap.get(sample.lap_number)
        effective_distance_m = _stabilize_effective_lap_distance_m(
            effective_distance_m,
            previous_distance_m=previous_distance_m,
            track_length_m=self._track_length_m,
        )
        triggered_zones = self._triggered_by_lap.setdefault(sample.lap_number, set())
        events: list[dict[str, object]] = []

        for cue in self._cues:
            scheduled_plan = self._lap_plan_by_number.get(sample.lap_number)
            if scheduled_plan is not None and str(cue["plan_id"]) != scheduled_plan:
                continue
            cue_key = (str(cue["plan_id"]), str(cue["zone_id"]))
            if cue_key in triggered_zones:
                continue
            if not _should_trigger_cue(
                cue_distance_m=float(cue["cue_distance_m"]),
                previous_distance_m=previous_distance_m,
                current_distance_m=effective_distance_m,
                track_length_m=self._track_length_m,
                max_initial_late_distance_m=self._config.max_initial_late_distance_m,
            ):
                continue
            triggered_zones.add(cue_key)
            event = _cue_event_row(
                cue,
                sample,
                actual_cue_distance_m=effective_distance_m,
                cue_distance_method=distance_method,
                distance_projection_age_s=projection_age_s,
                sample_index=self._sample_index,
                config=self._config,
                track_length_m=self._track_length_m,
            )
            events.append(event)
            self._event_count += 1

        self._sample_index += 1
        self._previous_distance_by_lap[sample.lap_number] = effective_distance_m
        return events

    def should_stop(self) -> bool:
        if (
            self._config.stop_after_lap_number is not None
            and self._max_lap_seen is not None
            and self._max_lap_seen > self._config.stop_after_lap_number
        ):
            return True
        if (
            self._config.max_events is not None
            and self._event_count >= self._config.max_events
        ):
            return True
        if (
            self._config.max_laps is not None
            and self._first_lap_number is not None
            and self._max_lap_seen is not None
            and (self._max_lap_seen - self._first_lap_number + 1)
            > self._config.max_laps
        ):
            return True
        return False


def _cue_event_row(
    cue: dict[str, object],
    sample: LmuLiveTelemetrySample,
    *,
    actual_cue_distance_m: float,
    cue_distance_method: str,
    distance_projection_age_s: float,
    sample_index: int,
    config: LiveStaticCueSessionConfig,
    track_length_m: float | None,
) -> dict[str, object]:
    cue_distance_m = float(cue["cue_distance_m"])
    cue_tolerance_m = float(
        cue.get("cue_tolerance_m") or config.default_cue_tolerance_m
    )
    cue_error_m = _signed_distance_delta_m(
        actual_cue_distance_m,
        cue_distance_m,
        track_length_m=track_length_m,
    )
    return {
        "schema_version": 2,
        "plan_id": str(cue["plan_id"]),
        "file_name": config.file_name,
        "run_id": config.run_id,
        "lap_number": sample.lap_number,
        "zone_id": str(cue["zone_id"]),
        "display_label": str(cue["display_label"]),
        "cue_trigger_m": cue_distance_m,
        "planned_lift_start_m": float(cue["planned_lift_start_m"]),
        "actual_cue_distance_m": actual_cue_distance_m,
        "raw_lap_distance_m": sample.lap_distance_m,
        "cue_distance_method": cue_distance_method,
        "distance_projection_age_s": distance_projection_age_s,
        "cue_error_m": cue_error_m,
        "cue_tolerance_m": cue_tolerance_m,
        "trigger_status": _trigger_status(cue_error_m, cue_tolerance_m),
        "sample_index": sample_index,
        "sample_ts": sample.ts,
        "sample_elapsed_s": sample.elapsed_s,
        "audio_cue_kind": config.audio_cue_kind,
        "cue_enabled": (
            (
                config.cue_lap_numbers is None
                or sample.lap_number in config.cue_lap_numbers
            )
            and (
                config.lap_plan_schedule is None
                or dict(config.lap_plan_schedule).get(sample.lap_number)
                == str(cue["plan_id"])
            )
        ),
        "notes": str(cue.get("notes") or ""),
    }


def _validate_lap_plan_schedule(
    plan: pl.DataFrame, config: LiveStaticCueSessionConfig
) -> dict[int, str]:
    plan_ids = set(plan["plan_id"].to_list())
    schedule = config.lap_plan_schedule
    if schedule is None:
        if len(plan_ids) > 1:
            raise ValueError(
                "multiple live plans require an explicit lap plan schedule"
            )
        return {}
    mapping: dict[int, str] = {}
    for lap_number, plan_id in schedule:
        if (
            not isinstance(lap_number, int)
            or isinstance(lap_number, bool)
            or lap_number < 0
        ):
            raise ValueError("lap plan schedule requires non-negative integer laps")
        if lap_number in mapping:
            raise ValueError(f"duplicate lap in lap plan schedule: {lap_number}")
        if plan_id not in plan_ids:
            raise ValueError(f"unknown plan_id in lap plan schedule: {plan_id}")
        mapping[lap_number] = plan_id
    if not mapping:
        raise ValueError("lap plan schedule must not be empty")
    if config.cue_lap_numbers is not None:
        missing = set(config.cue_lap_numbers) - set(mapping)
        if missing:
            raise ValueError(
                f"enabled cue laps missing from lap plan schedule: {sorted(missing)}"
            )
    return mapping


def _effective_lap_distance_m(
    sample: LmuLiveTelemetrySample,
    *,
    anchor: LmuLiveTelemetrySample | None,
    track_length_m: float | None,
) -> tuple[float, LmuLiveTelemetrySample, str, float]:
    """Project between LMU's coarser scoring-distance updates using live speed."""
    if anchor is None or abs(sample.lap_distance_m - anchor.lap_distance_m) > 1e-6:
        return sample.lap_distance_m, sample, "raw_scoring", 0.0
    if sample.speed_kph is None or sample.speed_kph < 0.0:
        return sample.lap_distance_m, anchor, "raw_scoring", 0.0
    elapsed_s = _sample_elapsed_delta_s(sample, anchor)
    if elapsed_s <= 0.0 or elapsed_s > _MAX_SCORING_DISTANCE_PROJECTION_S:
        return sample.lap_distance_m, anchor, "raw_scoring", 0.0
    anchor_speed_kph = (
        sample.speed_kph
        if anchor.speed_kph is None or anchor.speed_kph < 0.0
        else anchor.speed_kph
    )
    mean_speed_ms = ((anchor_speed_kph + sample.speed_kph) / 2.0) / 3.6
    projected_m = sample.lap_distance_m + mean_speed_ms * elapsed_s
    if track_length_m is not None:
        projected_m = min(projected_m, track_length_m)
    return projected_m, anchor, "speed_projected", elapsed_s


def _stabilize_effective_lap_distance_m(
    current_distance_m: float,
    *,
    previous_distance_m: float | None,
    track_length_m: float | None,
) -> float:
    """Ignore small backward scoring corrections without hiding a real lap wrap."""
    if previous_distance_m is None or current_distance_m >= previous_distance_m:
        return current_distance_m
    backward_delta_m = previous_distance_m - current_distance_m
    wrap_threshold_m = (
        track_length_m / 2.0
        if track_length_m is not None
        else _UNKNOWN_TRACK_WRAP_THRESHOLD_M
    )
    if backward_delta_m > wrap_threshold_m:
        return current_distance_m
    return previous_distance_m


def _sample_elapsed_delta_s(
    sample: LmuLiveTelemetrySample, anchor: LmuLiveTelemetrySample
) -> float:
    if sample.elapsed_s is not None and anchor.elapsed_s is not None:
        return float(sample.elapsed_s - anchor.elapsed_s)
    return float(sample.ts - anchor.ts)


def _should_trigger_cue(
    *,
    cue_distance_m: float,
    previous_distance_m: float | None,
    current_distance_m: float,
    track_length_m: float | None,
    max_initial_late_distance_m: float,
) -> bool:
    if previous_distance_m is None:
        return 0.0 <= current_distance_m - cue_distance_m <= max_initial_late_distance_m
    if current_distance_m >= previous_distance_m:
        return previous_distance_m < cue_distance_m <= current_distance_m
    if track_length_m is None:
        return False
    return cue_distance_m > previous_distance_m or cue_distance_m <= current_distance_m


def _signed_distance_delta_m(
    actual_m: float,
    planned_m: float,
    *,
    track_length_m: float | None,
) -> float:
    delta_m = actual_m - planned_m
    if track_length_m is None:
        return delta_m
    half_track_m = track_length_m / 2.0
    return ((delta_m + half_track_m) % track_length_m) - half_track_m


def _trigger_status(cue_error_m: float, cue_tolerance_m: float) -> str:
    if abs(cue_error_m) <= cue_tolerance_m:
        return "fired_on_time"
    if cue_error_m < 0.0:
        return "fired_early"
    return "fired_late"


def _track_length_m(
    live_cue_plan: pl.DataFrame, config_track_length_m: float | None
) -> float | None:
    if "track_length_m" not in live_cue_plan.columns:
        return config_track_length_m
    non_null = [
        float(value) for value in live_cue_plan["track_length_m"].drop_nulls().to_list()
    ]
    if not non_null:
        return config_track_length_m
    track_lengths = set(non_null)
    if len(track_lengths) != 1:
        raise ValueError("live cue plan track_length_m values must be consistent")
    plan_track_length_m = next(iter(track_lengths))
    if (
        config_track_length_m is not None
        and abs(config_track_length_m - plan_track_length_m) > 1e-9
    ):
        raise ValueError("config track_length_m conflicts with live cue plan")
    return plan_track_length_m


def _prepare_csv_output(
    path: str | Path,
    *,
    overwrite_existing: bool,
    header: list[str],
) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists() and not overwrite_existing:
        raise FileExistsError(f"refusing to overwrite existing log: {output_path}")
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        csv.DictWriter(handle, fieldnames=header).writeheader()
    return output_path


def _append_csv_row(path: Path, *, header: list[str], row: dict[str, object]) -> None:
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=header)
        writer.writerow(row)


def _write_frame(
    frame: pl.DataFrame, path: str | Path, *, overwrite_existing: bool
) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists() and not overwrite_existing:
        raise FileExistsError(f"refusing to overwrite existing log: {output_path}")
    frame.write_csv(output_path)
    return output_path


def _default_accuracy_log_path(event_log_path: str | Path) -> Path:
    path = Path(event_log_path)
    return path.with_name(f"{path.stem}_accuracy{path.suffix}")


_LIVE_CUE_EVENT_LOG_COLUMNS = [
    "schema_version",
    "plan_id",
    "file_name",
    "run_id",
    "lap_number",
    "zone_id",
    "display_label",
    "cue_trigger_m",
    "planned_lift_start_m",
    "actual_cue_distance_m",
    "raw_lap_distance_m",
    "cue_distance_method",
    "distance_projection_age_s",
    "cue_error_m",
    "cue_tolerance_m",
    "trigger_status",
    "sample_index",
    "sample_ts",
    "sample_elapsed_s",
    "audio_cue_kind",
    "cue_enabled",
    "notes",
]

_LIVE_CUE_EVENT_LOG_SCHEMA = {
    "schema_version": pl.Int64,
    "plan_id": pl.String,
    "file_name": pl.String,
    "run_id": pl.String,
    "lap_number": pl.Int64,
    "zone_id": pl.String,
    "display_label": pl.String,
    "cue_trigger_m": pl.Float64,
    "planned_lift_start_m": pl.Float64,
    "actual_cue_distance_m": pl.Float64,
    "raw_lap_distance_m": pl.Float64,
    "cue_distance_method": pl.String,
    "distance_projection_age_s": pl.Float64,
    "cue_error_m": pl.Float64,
    "cue_tolerance_m": pl.Float64,
    "trigger_status": pl.String,
    "sample_index": pl.Int64,
    "sample_ts": pl.Float64,
    "sample_elapsed_s": pl.Float64,
    "audio_cue_kind": pl.String,
    "cue_enabled": pl.Boolean,
    "notes": pl.String,
}
