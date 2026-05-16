from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import polars as pl


@dataclass(frozen=True)
class LiveCueRunnerConfig:
    run_id: str = ""
    file_name: str = ""
    audio_cue_kind: str = "beep"
    track_length_m: float | None = None
    default_cue_tolerance_m: float = 5.0
    max_initial_late_distance_m: float = 30.0


def load_live_cue_plan(path: str | Path) -> pl.DataFrame:
    """Load an exported live cue plan and validate the minimum runtime columns."""

    plan = pl.read_csv(path)
    _validate_live_cue_plan(plan)
    return plan


def validate_live_cue_plan(live_cue_plan: pl.DataFrame) -> None:
    _validate_live_cue_plan(live_cue_plan)


def simulate_live_cue_events(
    live_cue_plan: pl.DataFrame,
    telemetry_samples: pl.DataFrame,
    *,
    config: LiveCueRunnerConfig | None = None,
) -> pl.DataFrame:
    """Replay telemetry samples through the cue trigger logic.

    This is the testable offline version of the future live audio loop: every
    returned row is a cue that would have been emitted by the runtime.
    """

    runner_config = config or LiveCueRunnerConfig()
    _validate_live_cue_plan(
        live_cue_plan,
        track_length_m=runner_config.track_length_m,
    )
    _validate_telemetry_samples(telemetry_samples)
    if live_cue_plan.is_empty() or telemetry_samples.is_empty():
        return empty_live_cue_event_log_frame()
    track_length_m = _track_length_m(live_cue_plan, runner_config.track_length_m)
    cues = _cue_rows(live_cue_plan)
    triggered_by_lap: dict[int, set[tuple[str, str]]] = {}
    previous_by_lap: dict[int, dict[str, Any]] = {}
    events = []

    for sample_index, sample in enumerate(
        telemetry_samples.sort(["lap_number", "ts"]).iter_rows(named=True)
    ):
        lap_number = int(sample["lap_number"])
        lap_distance_m = float(sample["lap_distance_m"])
        previous_sample = previous_by_lap.get(lap_number)
        triggered_zones = triggered_by_lap.setdefault(lap_number, set())

        for cue in cues:
            cue_key = _cue_key(cue)
            if cue_key in triggered_zones:
                continue
            if not _should_trigger_cue(
                cue_distance_m=float(cue["cue_distance_m"]),
                previous_distance_m=_distance_from_sample(previous_sample),
                current_distance_m=lap_distance_m,
                track_length_m=track_length_m,
                max_initial_late_distance_m=runner_config.max_initial_late_distance_m,
            ):
                continue
            triggered_zones.add(cue_key)
            events.append(
                _cue_event_row(
                    cue,
                    sample,
                    sample_index=sample_index,
                    config=runner_config,
                    track_length_m=track_length_m,
                )
            )

        previous_by_lap[lap_number] = sample

    if not events:
        return empty_live_cue_event_log_frame()
    return pl.DataFrame(events, schema=_LIVE_CUE_EVENT_LOG_SCHEMA, strict=False).select(
        _LIVE_CUE_EVENT_LOG_COLUMNS
    )


def summarize_live_cue_event_accuracy(cue_events: pl.DataFrame) -> pl.DataFrame:
    """Summarize cue trigger accuracy by plan and zone."""

    if cue_events.is_empty():
        return empty_live_cue_accuracy_frame()
    return (
        cue_events.with_columns(
            pl.col("cue_error_m").abs().alias("abs_cue_error_m"),
            (pl.col("trigger_status") == "fired_on_time").alias("is_on_time"),
        )
        .group_by("plan_id", "zone_id", "display_label")
        .agg(
            pl.len().alias("cue_count"),
            pl.col("is_on_time").mean().alias("on_time_rate"),
            pl.col("cue_error_m").mean().alias("mean_cue_error_m"),
            pl.col("abs_cue_error_m").median().alias("median_abs_cue_error_m"),
            pl.col("abs_cue_error_m").max().alias("max_abs_cue_error_m"),
        )
        .sort(["plan_id", "zone_id"])
        .select(_LIVE_CUE_ACCURACY_COLUMNS)
    )


def empty_live_cue_event_log_frame() -> pl.DataFrame:
    return pl.DataFrame(schema=_LIVE_CUE_EVENT_LOG_SCHEMA)


def empty_live_cue_accuracy_frame() -> pl.DataFrame:
    return pl.DataFrame(schema=_LIVE_CUE_ACCURACY_SCHEMA)


def _validate_live_cue_plan(
    live_cue_plan: pl.DataFrame,
    *,
    track_length_m: float | None = None,
) -> None:
    required_columns = {
        "plan_id",
        "zone_id",
        "display_label",
        "cue_distance_m",
        "planned_lift_start_m",
        "cue_tolerance_m",
    }
    missing_columns = required_columns - set(live_cue_plan.columns)
    if missing_columns:
        missing = ", ".join(sorted(missing_columns))
        raise ValueError(f"live cue plan is missing required columns: {missing}")
    null_critical_columns = [
        column
        for column in required_columns
        if live_cue_plan.filter(pl.col(column).is_null()).height
    ]
    if null_critical_columns:
        missing = ", ".join(sorted(null_critical_columns))
        raise ValueError(f"live cue plan has null required values: {missing}")
    if "schema_version" in live_cue_plan.columns:
        schema_versions = set(live_cue_plan["schema_version"].drop_nulls().to_list())
        if schema_versions and schema_versions != {1}:
            raise ValueError("live cue plan schema_version must be 1")
        if live_cue_plan.filter(pl.col("schema_version").is_null()).height:
            raise ValueError("live cue plan schema_version must not be null")
    if live_cue_plan.filter(pl.col("cue_tolerance_m") <= 0.0).height:
        raise ValueError("live cue plan cue_tolerance_m values must be positive")
    duplicate_count = (
        live_cue_plan.group_by("plan_id", "zone_id").len().filter(pl.col("len") > 1).height
    )
    if duplicate_count:
        raise ValueError("live cue plan contains duplicate plan_id/zone_id rows")
    if live_cue_plan.filter(pl.col("cue_distance_m") < 0.0).height:
        raise ValueError("live cue plan cue_distance_m values must be non-negative")
    if live_cue_plan.filter(pl.col("planned_lift_start_m") < 0.0).height:
        raise ValueError("live cue plan planned_lift_start_m values must be non-negative")
    effective_track_length_m = _validated_track_length_m(
        live_cue_plan,
        config_track_length_m=track_length_m,
    )
    if effective_track_length_m is not None:
        invalid_distance_count = live_cue_plan.filter(
            (pl.col("cue_distance_m") >= effective_track_length_m)
            | (pl.col("planned_lift_start_m") >= effective_track_length_m)
        ).height
        if invalid_distance_count:
            raise ValueError("live cue plan distances must be below track_length_m")


def _validated_track_length_m(
    live_cue_plan: pl.DataFrame,
    *,
    config_track_length_m: float | None,
) -> float | None:
    if config_track_length_m is not None and config_track_length_m <= 0.0:
        raise ValueError("track_length_m must be positive")
    if "track_length_m" in live_cue_plan.columns:
        if live_cue_plan.filter(pl.col("track_length_m") <= 0.0).height:
            raise ValueError("live cue plan track_length_m values must be positive")
        track_lengths = set(
            float(value)
            for value in live_cue_plan["track_length_m"].drop_nulls().to_list()
        )
        if len(track_lengths) > 1:
            raise ValueError("live cue plan track_length_m values must be consistent")
        plan_track_length_m = next(iter(track_lengths), None)
        if (
            config_track_length_m is not None
            and plan_track_length_m is not None
            and abs(config_track_length_m - plan_track_length_m) > 1e-9
        ):
            raise ValueError("config track_length_m conflicts with live cue plan")
        if plan_track_length_m is not None:
            return plan_track_length_m
    return config_track_length_m


def _validate_telemetry_samples(telemetry_samples: pl.DataFrame) -> None:
    required_columns = {"lap_number", "lap_distance_m", "ts"}
    missing_columns = required_columns - set(telemetry_samples.columns)
    if missing_columns:
        missing = ", ".join(sorted(missing_columns))
        raise ValueError(f"telemetry samples are missing required columns: {missing}")


def _track_length_m(
    live_cue_plan: pl.DataFrame,
    config_track_length_m: float | None,
) -> float | None:
    return _validated_track_length_m(
        live_cue_plan,
        config_track_length_m=config_track_length_m,
    )


def _cue_rows(live_cue_plan: pl.DataFrame) -> list[dict[str, Any]]:
    return list(live_cue_plan.sort("cue_distance_m").iter_rows(named=True))


def _cue_key(cue: dict[str, Any]) -> tuple[str, str]:
    return str(cue["plan_id"]), str(cue["zone_id"])


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


def _cue_event_row(
    cue: dict[str, Any],
    sample: dict[str, Any],
    *,
    sample_index: int,
    config: LiveCueRunnerConfig,
    track_length_m: float | None,
) -> dict[str, Any]:
    cue_distance_m = float(cue["cue_distance_m"])
    triggered_distance_m = float(sample["lap_distance_m"])
    cue_error_m = _signed_distance_delta_m(
        triggered_distance_m,
        cue_distance_m,
        track_length_m=track_length_m,
    )
    cue_tolerance_m = _optional_float(cue.get("cue_tolerance_m"))
    if cue_tolerance_m is None:
        cue_tolerance_m = config.default_cue_tolerance_m
    return {
        "schema_version": 1,
        "plan_id": str(cue["plan_id"]),
        "file_name": config.file_name,
        "run_id": config.run_id,
        "lap_number": int(sample["lap_number"]),
        "zone_id": str(cue["zone_id"]),
        "display_label": str(cue["display_label"]),
        "cue_trigger_m": cue_distance_m,
        "planned_lift_start_m": float(cue["planned_lift_start_m"]),
        "actual_cue_distance_m": triggered_distance_m,
        "cue_error_m": cue_error_m,
        "cue_tolerance_m": cue_tolerance_m,
        "trigger_status": _trigger_status(cue_error_m, cue_tolerance_m),
        "sample_index": sample_index,
        "sample_ts": float(sample["ts"]),
        "sample_elapsed_s": _optional_float(sample.get("elapsed_s")),
        "audio_cue_kind": config.audio_cue_kind,
        "notes": str(cue.get("notes") or ""),
    }


def _distance_from_sample(sample: dict[str, Any] | None) -> float | None:
    if sample is None:
        return None
    return float(sample["lap_distance_m"])


def _trigger_status(cue_error_m: float, cue_tolerance_m: float) -> str:
    if abs(cue_error_m) <= cue_tolerance_m:
        return "fired_on_time"
    if cue_error_m < 0.0:
        return "fired_early"
    return "fired_late"


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    return float(value)


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
    "cue_error_m",
    "cue_tolerance_m",
    "trigger_status",
    "sample_index",
    "sample_ts",
    "sample_elapsed_s",
    "audio_cue_kind",
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
    "cue_error_m": pl.Float64,
    "cue_tolerance_m": pl.Float64,
    "trigger_status": pl.String,
    "sample_index": pl.Int64,
    "sample_ts": pl.Float64,
    "sample_elapsed_s": pl.Float64,
    "audio_cue_kind": pl.String,
    "notes": pl.String,
}

_LIVE_CUE_ACCURACY_COLUMNS = [
    "plan_id",
    "zone_id",
    "display_label",
    "cue_count",
    "on_time_rate",
    "mean_cue_error_m",
    "median_abs_cue_error_m",
    "max_abs_cue_error_m",
]

_LIVE_CUE_ACCURACY_SCHEMA = {
    "plan_id": pl.String,
    "zone_id": pl.String,
    "display_label": pl.String,
    "cue_count": pl.Int64,
    "on_time_rate": pl.Float64,
    "mean_cue_error_m": pl.Float64,
    "median_abs_cue_error_m": pl.Float64,
    "max_abs_cue_error_m": pl.Float64,
}
