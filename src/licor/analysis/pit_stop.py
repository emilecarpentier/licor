from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import polars as pl

from licor.analysis.lap_summary import RunLapLabels
from licor.ingestion import LmuTelemetryDatabase


@dataclass(frozen=True)
class PitStopConfig:
    stationary_speed_threshold_kph: float = 1.0
    min_stationary_duration_s: float = 1.0
    refill_delta_threshold_l: float = 0.01
    max_refill_gap_s: float = 0.25
    min_refill_added_l: float = 1.0
    min_refill_duration_s: float = 1.0
    ignore_initial_active_interval: bool = True
    initial_interval_elapsed_tolerance_s: float = 1.0
    reference_refill_rate_lps: float | None = None


def extract_pit_stop_observations(
    telemetry: LmuTelemetryDatabase,
    *,
    run_labels: RunLapLabels | None = None,
    config: PitStopConfig | None = None,
) -> pl.DataFrame:
    """Extract pit stop and refill observations from a dedicated telemetry file."""

    pit_config = config or PitStopConfig()
    if "In Pits" not in telemetry.events() or "Speed Limiter" not in telemetry.events():
        return _empty_pit_stop_frame()
    if "Fuel Level" not in telemetry.channels() or "Ground Speed" not in telemetry.channels():
        return _empty_pit_stop_frame()

    session_start_ts = telemetry.session_start_ts()
    in_pits = telemetry.event_series("In Pits")
    speed_limiter = telemetry.event_series("Speed Limiter")
    fuel = _channel(telemetry, "Fuel Level", "fuel_level_l")
    speed = _channel(telemetry, "Ground Speed", "ground_speed_kph")

    rows = []
    pit_intervals = _active_intervals(
        in_pits,
        session_start_ts=session_start_ts,
        config=pit_config,
    )
    limiter_intervals = _active_intervals(
        speed_limiter,
        session_start_ts=session_start_ts,
        config=pit_config,
    )

    for pit_index, pit_interval in enumerate(pit_intervals, start=1):
        limiter_interval = _best_overlapping_interval(pit_interval, limiter_intervals)
        stationary_interval = _stationary_interval(speed, pit_interval, config=pit_config)
        refill_interval = _refill_interval(fuel, pit_interval, config=pit_config)
        rows.append(
            _pit_stop_row(
                pit_index,
                pit_interval,
                limiter_interval,
                stationary_interval,
                refill_interval,
                run_labels=run_labels,
                config=pit_config,
            )
        )

    if not rows:
        return _empty_pit_stop_frame()
    return pl.DataFrame(rows, schema=_PIT_STOP_SCHEMA, strict=False).select(_PIT_STOP_COLUMNS)


def _channel(
    telemetry: LmuTelemetryDatabase,
    channel_name: str,
    output_column: str,
) -> pl.DataFrame:
    return telemetry.fixed_channel(channel_name).select(
        "ts",
        "elapsed_s",
        pl.col("value").alias(output_column),
    )


def _active_intervals(
    events: pl.DataFrame,
    *,
    session_start_ts: float,
    config: PitStopConfig,
) -> list[dict[str, float]]:
    if events.is_empty() or not {"ts", "value"}.issubset(events.columns):
        return []

    rows = list(events.sort("ts").iter_rows(named=True))
    intervals = []
    active_start: dict[str, Any] | None = None
    for row in rows:
        is_active = bool(row["value"])
        if is_active and active_start is None:
            active_start = row
        elif not is_active and active_start is not None:
            intervals.append(_interval_from_rows(active_start, row))
            active_start = None

    filtered = []
    for interval in intervals:
        starts_at_session_open = (
            abs(interval["start_ts"] - session_start_ts)
            <= config.initial_interval_elapsed_tolerance_s
            or interval["start_elapsed_s"] <= config.initial_interval_elapsed_tolerance_s
        )
        if config.ignore_initial_active_interval and starts_at_session_open:
            continue
        filtered.append(interval)
    return filtered


def _interval_from_rows(start: dict[str, Any], end: dict[str, Any]) -> dict[str, float]:
    return {
        "start_ts": float(start["ts"]),
        "end_ts": float(end["ts"]),
        "start_elapsed_s": float(start["elapsed_s"]),
        "end_elapsed_s": float(end["elapsed_s"]),
        "duration_s": float(end["ts"]) - float(start["ts"]),
    }


def _best_overlapping_interval(
    target: dict[str, float],
    candidates: list[dict[str, float]],
) -> dict[str, float] | None:
    best = None
    best_overlap_s = 0.0
    for candidate in candidates:
        overlap_s = min(target["end_ts"], candidate["end_ts"]) - max(
            target["start_ts"],
            candidate["start_ts"],
        )
        if overlap_s > best_overlap_s:
            best = candidate
            best_overlap_s = overlap_s
    return best


def _stationary_interval(
    speed: pl.DataFrame,
    pit_interval: dict[str, float],
    *,
    config: PitStopConfig,
) -> dict[str, float] | None:
    window = speed.filter(
        (pl.col("ts") >= pit_interval["start_ts"])
        & (pl.col("ts") <= pit_interval["end_ts"])
        & (pl.col("ground_speed_kph") <= config.stationary_speed_threshold_kph)
    ).sort("ts")
    if window.is_empty():
        return None

    segments = _continuous_sample_segments(window, max_gap_s=0.25)
    if not segments:
        return None
    best = max(segments, key=lambda segment: segment["duration_s"])
    if best["duration_s"] < config.min_stationary_duration_s:
        return None
    return best


def _refill_interval(
    fuel: pl.DataFrame,
    pit_interval: dict[str, float],
    *,
    config: PitStopConfig,
) -> dict[str, float] | None:
    window = (
        fuel.filter(
            (pl.col("ts") >= pit_interval["start_ts"])
            & (pl.col("ts") <= pit_interval["end_ts"])
        )
        .sort("ts")
        .with_columns((pl.col("fuel_level_l") - pl.col("fuel_level_l").shift(1)).alias("delta_l"))
    )
    positive = window.with_row_index("_row_index").filter(
        pl.col("delta_l") > config.refill_delta_threshold_l
    )
    if positive.is_empty():
        return None

    segments = _positive_refill_segments(positive, window, config=config)
    candidates = [
        segment
        for segment in segments
        if segment["fuel_added_l"] >= config.min_refill_added_l
        and segment["duration_s"] >= config.min_refill_duration_s
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda segment: segment["fuel_added_l"])


def _positive_refill_segments(
    positive: pl.DataFrame,
    window: pl.DataFrame,
    *,
    config: PitStopConfig,
) -> list[dict[str, float]]:
    segments = []
    active: list[dict[str, Any]] = []
    for row in positive.iter_rows(named=True):
        if active and float(row["ts"]) - float(active[-1]["ts"]) > config.max_refill_gap_s:
            segments.append(_refill_segment_from_rows(active, window))
            active = []
        active.append(row)
    if active:
        segments.append(_refill_segment_from_rows(active, window))
    return segments


def _refill_segment_from_rows(
    positive_rows: list[dict[str, Any]],
    window: pl.DataFrame,
) -> dict[str, float]:
    first_positive = positive_rows[0]
    last_positive = positive_rows[-1]
    start_index = max(0, int(first_positive["_row_index"]) - 1)
    start = window.row(start_index, named=True)
    end = dict(last_positive)
    duration_s = float(end["ts"]) - float(start["ts"])
    fuel_added_l = float(end["fuel_level_l"]) - float(start["fuel_level_l"])
    return {
        "start_ts": float(start["ts"]),
        "end_ts": float(end["ts"]),
        "start_elapsed_s": float(start["elapsed_s"]),
        "end_elapsed_s": float(end["elapsed_s"]),
        "duration_s": duration_s,
        "fuel_start_l": float(start["fuel_level_l"]),
        "fuel_end_l": float(end["fuel_level_l"]),
        "fuel_added_l": fuel_added_l,
        "observed_refill_rate_lps": fuel_added_l / duration_s if duration_s > 0 else None,
    }


def _continuous_sample_segments(
    samples: pl.DataFrame,
    *,
    max_gap_s: float,
) -> list[dict[str, float]]:
    segments = []
    active: list[dict[str, Any]] = []
    for row in samples.sort("ts").iter_rows(named=True):
        if active and float(row["ts"]) - float(active[-1]["ts"]) > max_gap_s:
            segments.append(_sample_segment_from_rows(active))
            active = []
        active.append(row)
    if active:
        segments.append(_sample_segment_from_rows(active))
    return segments


def _sample_segment_from_rows(rows: list[dict[str, Any]]) -> dict[str, float]:
    start = rows[0]
    end = rows[-1]
    return {
        "start_ts": float(start["ts"]),
        "end_ts": float(end["ts"]),
        "start_elapsed_s": float(start["elapsed_s"]),
        "end_elapsed_s": float(end["elapsed_s"]),
        "duration_s": float(end["ts"]) - float(start["ts"]),
    }


def _pit_stop_row(
    pit_index: int,
    pit_interval: dict[str, float],
    limiter_interval: dict[str, float] | None,
    stationary_interval: dict[str, float] | None,
    refill_interval: dict[str, float] | None,
    *,
    run_labels: RunLapLabels | None,
    config: PitStopConfig,
) -> dict[str, Any]:
    reference_rate = config.reference_refill_rate_lps
    observed_rate = (
        refill_interval["observed_refill_rate_lps"] if refill_interval is not None else None
    )
    return {
        "file_name": run_labels.file if run_labels is not None else None,
        "run_id": run_labels.run_id if run_labels is not None else None,
        "track_name": run_labels.track if run_labels is not None else None,
        "car_class": run_labels.car_class if run_labels is not None else None,
        "pit_stop_index": pit_index,
        "pit_entry_ts": pit_interval["start_ts"],
        "pit_exit_ts": pit_interval["end_ts"],
        "pit_entry_elapsed_s": pit_interval["start_elapsed_s"],
        "pit_exit_elapsed_s": pit_interval["end_elapsed_s"],
        "in_pits_duration_s": pit_interval["duration_s"],
        "speed_limiter_on_ts": _field(limiter_interval, "start_ts"),
        "speed_limiter_off_ts": _field(limiter_interval, "end_ts"),
        "speed_limiter_on_elapsed_s": _field(limiter_interval, "start_elapsed_s"),
        "speed_limiter_off_elapsed_s": _field(limiter_interval, "end_elapsed_s"),
        "speed_limiter_duration_s": _field(limiter_interval, "duration_s"),
        "stationary_start_ts": _field(stationary_interval, "start_ts"),
        "stationary_end_ts": _field(stationary_interval, "end_ts"),
        "stationary_start_elapsed_s": _field(stationary_interval, "start_elapsed_s"),
        "stationary_end_elapsed_s": _field(stationary_interval, "end_elapsed_s"),
        "stationary_duration_s": _field(stationary_interval, "duration_s"),
        "refill_start_ts": _field(refill_interval, "start_ts"),
        "refill_end_ts": _field(refill_interval, "end_ts"),
        "refill_start_elapsed_s": _field(refill_interval, "start_elapsed_s"),
        "refill_end_elapsed_s": _field(refill_interval, "end_elapsed_s"),
        "refill_duration_s": _field(refill_interval, "duration_s"),
        "fuel_start_l": _field(refill_interval, "fuel_start_l"),
        "fuel_end_l": _field(refill_interval, "fuel_end_l"),
        "fuel_added_l": _field(refill_interval, "fuel_added_l"),
        "observed_refill_rate_lps": observed_rate,
        "reference_refill_rate_lps": reference_rate,
        "refill_rate_delta_lps": (
            observed_rate - reference_rate
            if observed_rate is not None and reference_rate is not None
            else None
        ),
        "refill_rate_ratio_to_reference": (
            observed_rate / reference_rate
            if observed_rate is not None and reference_rate is not None and reference_rate > 0
            else None
        ),
        "pit_lane_commitment_time_s": _field(limiter_interval, "duration_s"),
        "tire_change_included": False,
        "validity_label": _validity_label(limiter_interval, stationary_interval, refill_interval),
        "notes": "",
    }


def _field(interval: dict[str, float] | None, key: str) -> float | None:
    return interval[key] if interval is not None else None


def _validity_label(
    limiter_interval: dict[str, float] | None,
    stationary_interval: dict[str, float] | None,
    refill_interval: dict[str, float] | None,
) -> str:
    missing = []
    if limiter_interval is None:
        missing.append("speed_limiter")
    if stationary_interval is None:
        missing.append("stationary")
    if refill_interval is None:
        missing.append("refill")
    return "valid" if not missing else "missing_" + "_".join(missing)


def _empty_pit_stop_frame() -> pl.DataFrame:
    return pl.DataFrame(schema=_PIT_STOP_SCHEMA)


_PIT_STOP_COLUMNS = [
    "file_name",
    "run_id",
    "track_name",
    "car_class",
    "pit_stop_index",
    "pit_entry_ts",
    "pit_exit_ts",
    "pit_entry_elapsed_s",
    "pit_exit_elapsed_s",
    "in_pits_duration_s",
    "speed_limiter_on_ts",
    "speed_limiter_off_ts",
    "speed_limiter_on_elapsed_s",
    "speed_limiter_off_elapsed_s",
    "speed_limiter_duration_s",
    "stationary_start_ts",
    "stationary_end_ts",
    "stationary_start_elapsed_s",
    "stationary_end_elapsed_s",
    "stationary_duration_s",
    "refill_start_ts",
    "refill_end_ts",
    "refill_start_elapsed_s",
    "refill_end_elapsed_s",
    "refill_duration_s",
    "fuel_start_l",
    "fuel_end_l",
    "fuel_added_l",
    "observed_refill_rate_lps",
    "reference_refill_rate_lps",
    "refill_rate_delta_lps",
    "refill_rate_ratio_to_reference",
    "pit_lane_commitment_time_s",
    "tire_change_included",
    "validity_label",
    "notes",
]

_PIT_STOP_SCHEMA = {
    "file_name": pl.String,
    "run_id": pl.String,
    "track_name": pl.String,
    "car_class": pl.String,
    "pit_stop_index": pl.Int64,
    "pit_entry_ts": pl.Float64,
    "pit_exit_ts": pl.Float64,
    "pit_entry_elapsed_s": pl.Float64,
    "pit_exit_elapsed_s": pl.Float64,
    "in_pits_duration_s": pl.Float64,
    "speed_limiter_on_ts": pl.Float64,
    "speed_limiter_off_ts": pl.Float64,
    "speed_limiter_on_elapsed_s": pl.Float64,
    "speed_limiter_off_elapsed_s": pl.Float64,
    "speed_limiter_duration_s": pl.Float64,
    "stationary_start_ts": pl.Float64,
    "stationary_end_ts": pl.Float64,
    "stationary_start_elapsed_s": pl.Float64,
    "stationary_end_elapsed_s": pl.Float64,
    "stationary_duration_s": pl.Float64,
    "refill_start_ts": pl.Float64,
    "refill_end_ts": pl.Float64,
    "refill_start_elapsed_s": pl.Float64,
    "refill_end_elapsed_s": pl.Float64,
    "refill_duration_s": pl.Float64,
    "fuel_start_l": pl.Float64,
    "fuel_end_l": pl.Float64,
    "fuel_added_l": pl.Float64,
    "observed_refill_rate_lps": pl.Float64,
    "reference_refill_rate_lps": pl.Float64,
    "refill_rate_delta_lps": pl.Float64,
    "refill_rate_ratio_to_reference": pl.Float64,
    "pit_lane_commitment_time_s": pl.Float64,
    "tire_change_included": pl.Boolean,
    "validity_label": pl.String,
    "notes": pl.String,
}
