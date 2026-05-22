from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import polars as pl


@dataclass(frozen=True)
class LapQualityManifestConfig:
    baseline_collection_labels: tuple[str, ...] = ("none",)
    baseline_collection_designs: tuple[str, ...] = ("baseline",)
    fuel_drift_warning_l: float = 0.15
    lap_time_drift_warning_s: float = 1.0
    brake_reference_drift_warning_m: float = 20.0
    min_valid_zone_pass_rate: float = 0.80
    min_telemetry_sample_count: int = 100
    max_time_gap_s: float = 0.5
    max_distance_gap_m: float = 80.0
    max_distance_monotonic_violations: int = 2
    max_fuel_increase_l: float = 0.02
    max_speed_jump_kph: float = 80.0
    throttle_min_pct: float = -1.0
    throttle_max_pct: float = 101.0
    brake_min_pct: float = -1.0
    brake_max_pct: float = 101.0


def build_lap_quality_manifest(
    lap_summary: pl.DataFrame,
    *,
    lap_samples: pl.DataFrame | None = None,
    zone_passes: pl.DataFrame | None = None,
    config: LapQualityManifestConfig | None = None,
) -> pl.DataFrame:
    """Build a run/lap manifest that flags telemetry collection quality risks."""

    manifest_config = config or LapQualityManifestConfig()
    if lap_summary.is_empty():
        return empty_lap_quality_manifest_frame()
    _validate_lap_summary_columns(lap_summary)

    baseline = _baseline_reference(lap_summary, config=manifest_config)
    sample_metrics = summarize_lap_sample_quality(
        lap_samples,
        config=manifest_config,
    )
    zone_metrics = _zone_pass_lap_metrics(zone_passes)
    rows = []
    summary_with_zones = lap_summary.join(
        sample_metrics,
        on=["run_id", "lap_number"],
        how="left",
    ).join(
        zone_metrics,
        on=["run_id", "lap_number"],
        how="left",
    )
    for row in summary_with_zones.iter_rows(named=True):
        rows.append(_manifest_row(row, baseline, config=manifest_config))

    return pl.DataFrame(
        rows,
        schema=_LAP_QUALITY_MANIFEST_SCHEMA,
        strict=False,
    ).select(_LAP_QUALITY_MANIFEST_COLUMNS)


def write_lap_quality_manifest_csv(manifest: pl.DataFrame, path: str | Path) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _csv_safe_frame(manifest).write_csv(output_path)
    return output_path


def empty_lap_quality_manifest_frame() -> pl.DataFrame:
    return pl.DataFrame(schema=_LAP_QUALITY_MANIFEST_SCHEMA)


def summarize_lap_sample_quality(
    lap_samples: pl.DataFrame | None,
    *,
    config: LapQualityManifestConfig | None = None,
) -> pl.DataFrame:
    """Summarize raw lap sample continuity and value-range checks by lap."""

    if lap_samples is None or lap_samples.is_empty():
        return pl.DataFrame(schema=_LAP_SAMPLE_METRICS_SCHEMA)
    sample_config = config or LapQualityManifestConfig()
    _validate_lap_sample_columns(lap_samples)

    rows = []
    for group in _sample_groups(lap_samples):
        samples = _filter_sample_group(lap_samples, group)
        rows.append(
            {
                **group,
                "telemetry_sample_count": samples.height,
                "lap_elapsed_span_s": _span(samples, "lap_elapsed_s"),
                "max_time_gap_s": _max_diff(samples, "lap_elapsed_s"),
                "max_distance_gap_m": _max_diff(samples, "lap_distance_m"),
                "distance_monotonic_violation_count": _negative_diff_count(
                    samples,
                    "lap_distance_m",
                ),
                "fuel_increase_count": _positive_diff_count(samples, "fuel_level_l"),
                "max_fuel_increase_l": _max_diff(samples, "fuel_level_l"),
                "speed_jump_count": _abs_diff_count(
                    samples,
                    "ground_speed_kph",
                    threshold=sample_config.max_speed_jump_kph,
                ),
                "max_speed_jump_kph": _max_abs_diff(samples, "ground_speed_kph"),
                "throttle_out_of_range_count": _range_violation_count(
                    samples,
                    "throttle_pct",
                    minimum=sample_config.throttle_min_pct,
                    maximum=sample_config.throttle_max_pct,
                ),
                "brake_out_of_range_count": _range_violation_count(
                    samples,
                    "brake_pct",
                    minimum=sample_config.brake_min_pct,
                    maximum=sample_config.brake_max_pct,
                ),
            }
        )
    return pl.DataFrame(rows, schema=_LAP_SAMPLE_METRICS_SCHEMA, strict=False)


def _baseline_reference(
    lap_summary: pl.DataFrame,
    *,
    config: LapQualityManifestConfig,
) -> dict[str, float | None]:
    baseline = lap_summary
    if "collection_design" in baseline.columns and _has_non_empty_values(
        baseline,
        "collection_design",
    ):
        baseline = baseline.filter(
            pl.col("collection_design").is_in(config.baseline_collection_designs)
        )
    else:
        baseline = baseline.filter(
            pl.col("collection_label").is_in(config.baseline_collection_labels)
        )
    baseline = baseline.filter(pl.col("is_valid_lap"))
    return {
        "baseline_mean_fuel_used_l": _mean_or_none(baseline, "fuel_used_l"),
        "baseline_mean_lap_time_s": _mean_or_none(baseline, "lap_time_s"),
    }


def _zone_pass_lap_metrics(zone_passes: pl.DataFrame | None) -> pl.DataFrame:
    if zone_passes is None or zone_passes.is_empty():
        return pl.DataFrame(schema=_ZONE_LAP_METRICS_SCHEMA)
    _validate_zone_pass_columns(zone_passes)
    return (
        zone_passes.group_by(["run_id", "lap_number"])
        .agg(
            pl.len().alias("zone_pass_count"),
            (pl.col("validity_label") == "valid").sum().alias("valid_zone_pass_count"),
            (pl.col("validity_label") != "valid").sum().alias("invalid_zone_pass_count"),
            pl.col("has_lico").fill_null(False).sum().alias("detected_lico_zone_count"),
            pl.col("zone_start_zero_throttle")
            .fill_null(False)
            .sum()
            .alias("zone_start_zero_throttle_count"),
            (
                (pl.col("brake_start_m") - pl.col("brake_reference_m"))
                .abs()
                .max()
            ).alias("max_abs_brake_reference_delta_m"),
        )
        .with_columns(
            (
                pl.col("valid_zone_pass_count") / pl.col("zone_pass_count")
            ).alias("valid_zone_pass_rate")
        )
    )


def _manifest_row(
    row: dict[str, Any],
    baseline: dict[str, float | None],
    *,
    config: LapQualityManifestConfig,
) -> dict[str, Any]:
    fuel_delta = _delta(row.get("fuel_used_l"), baseline["baseline_mean_fuel_used_l"])
    lap_time_delta = _delta(row.get("lap_time_s"), baseline["baseline_mean_lap_time_s"])
    flags = _quality_flags(
        row,
        fuel_delta_l=fuel_delta,
        lap_time_delta_s=lap_time_delta,
        config=config,
    )
    return {
        "run_id": row.get("run_id"),
        "file_name": row.get("file_name"),
        "lap_number": row.get("lap_number"),
        "collection_label": row.get("collection_label"),
        "collection_protocol_id": row.get("collection_protocol_id"),
        "collection_design": row.get("collection_design"),
        "execution_quality": row.get("execution_quality"),
        "labels_quality": row.get("labels_quality"),
        "driver_lap_label": row.get("driver_lap_label"),
        "is_valid_lap": bool(row.get("is_valid_lap")),
        "lap_time_s": row.get("lap_time_s"),
        "fuel_used_l": row.get("fuel_used_l"),
        "baseline_mean_lap_time_s": baseline["baseline_mean_lap_time_s"],
        "baseline_mean_fuel_used_l": baseline["baseline_mean_fuel_used_l"],
        "lap_time_delta_vs_baseline_s": lap_time_delta,
        "fuel_delta_vs_baseline_l": fuel_delta,
        "max_lap_distance_m": row.get("max_lap_distance_m"),
        "mean_throttle_pct": row.get("mean_throttle_pct"),
        "max_brake_pct": row.get("max_brake_pct"),
        "telemetry_sample_count": _int_or_zero(row.get("telemetry_sample_count")),
        "lap_elapsed_span_s": _float_or_none(row.get("lap_elapsed_span_s")),
        "max_time_gap_s": _float_or_none(row.get("max_time_gap_s")),
        "max_distance_gap_m": _float_or_none(row.get("max_distance_gap_m")),
        "distance_monotonic_violation_count": _int_or_zero(
            row.get("distance_monotonic_violation_count")
        ),
        "fuel_increase_count": _int_or_zero(row.get("fuel_increase_count")),
        "max_fuel_increase_l": _float_or_none(row.get("max_fuel_increase_l")),
        "speed_jump_count": _int_or_zero(row.get("speed_jump_count")),
        "max_speed_jump_kph": _float_or_none(row.get("max_speed_jump_kph")),
        "throttle_out_of_range_count": _int_or_zero(
            row.get("throttle_out_of_range_count")
        ),
        "brake_out_of_range_count": _int_or_zero(row.get("brake_out_of_range_count")),
        "zone_pass_count": _int_or_zero(row.get("zone_pass_count")),
        "valid_zone_pass_count": _int_or_zero(row.get("valid_zone_pass_count")),
        "invalid_zone_pass_count": _int_or_zero(row.get("invalid_zone_pass_count")),
        "valid_zone_pass_rate": _float_or_none(row.get("valid_zone_pass_rate")),
        "detected_lico_zone_count": _int_or_zero(row.get("detected_lico_zone_count")),
        "zone_start_zero_throttle_count": _int_or_zero(
            row.get("zone_start_zero_throttle_count")
        ),
        "max_abs_brake_reference_delta_m": _float_or_none(
            row.get("max_abs_brake_reference_delta_m")
        ),
        "exclusion_reason": row.get("exclusion_reason"),
        "quality_status": _quality_status(flags),
        "quality_flags": flags,
        "recommended_uses": _recommended_uses(row, flags),
    }


def _quality_flags(
    row: dict[str, Any],
    *,
    fuel_delta_l: float | None,
    lap_time_delta_s: float | None,
    config: LapQualityManifestConfig,
) -> list[str]:
    flags = []
    if not row.get("is_valid_lap"):
        flags.append("invalid_lap_summary")
    if not row.get("driver_included"):
        flags.append("not_driver_included")
    if not _non_empty(row.get("collection_design")):
        flags.append("missing_collection_design")
    if not _non_empty(row.get("collection_protocol_id")):
        flags.append("missing_collection_protocol_id")
    if fuel_delta_l is None:
        flags.append("missing_fuel_baseline")
    elif abs(fuel_delta_l) > config.fuel_drift_warning_l:
        flags.append("fuel_delta_vs_baseline_warning")
    if lap_time_delta_s is None:
        flags.append("missing_lap_time_baseline")
    elif abs(lap_time_delta_s) > config.lap_time_drift_warning_s:
        flags.append("lap_time_delta_vs_baseline_warning")

    sample_count = _int_or_zero(row.get("telemetry_sample_count"))
    if sample_count == 0:
        flags.append("missing_lap_samples")
    elif sample_count < config.min_telemetry_sample_count:
        flags.append("low_telemetry_sample_count")
    if _float_or_zero(row.get("max_time_gap_s")) > config.max_time_gap_s:
        flags.append("large_time_gap")
    if _float_or_zero(row.get("max_distance_gap_m")) > config.max_distance_gap_m:
        flags.append("large_distance_gap")
    if (
        _int_or_zero(row.get("distance_monotonic_violation_count"))
        > config.max_distance_monotonic_violations
    ):
        flags.append("distance_monotonicity_warning")
    if _float_or_zero(row.get("max_fuel_increase_l")) > config.max_fuel_increase_l:
        flags.append("fuel_increase_warning")
    if _float_or_zero(row.get("max_speed_jump_kph")) > config.max_speed_jump_kph:
        flags.append("speed_jump_warning")
    if _int_or_zero(row.get("throttle_out_of_range_count")) > 0:
        flags.append("throttle_out_of_range")
    if _int_or_zero(row.get("brake_out_of_range_count")) > 0:
        flags.append("brake_out_of_range")

    zone_pass_count = _int_or_zero(row.get("zone_pass_count"))
    if zone_pass_count == 0:
        flags.append("missing_zone_passes")
    elif _float_or_zero(row.get("valid_zone_pass_rate")) < config.min_valid_zone_pass_rate:
        flags.append("low_valid_zone_pass_rate")
    if _int_or_zero(row.get("zone_start_zero_throttle_count")) > 0:
        flags.append("zone_start_zero_throttle")
    if (
        _float_or_zero(row.get("max_abs_brake_reference_delta_m"))
        > config.brake_reference_drift_warning_m
    ):
        flags.append("brake_reference_drift_warning")
    if _int_or_zero(row.get("detected_lico_zone_count")) > 0:
        flags.append("detected_lico")
    return flags


def _quality_status(flags: list[str]) -> str:
    if _has_blocking_quality_flags(flags):
        return "needs_review"
    if flags:
        return "review_recommended"
    return "ready"


def _has_blocking_quality_flags(flags: list[str]) -> bool:
    blocking_flags = {
        "invalid_lap_summary",
        "not_driver_included",
        "missing_zone_passes",
        "low_valid_zone_pass_rate",
        "missing_lap_samples",
        "low_telemetry_sample_count",
        "large_time_gap",
        "large_distance_gap",
        "distance_monotonicity_warning",
    }
    return any(flag in blocking_flags for flag in flags)


def _recommended_uses(row: dict[str, Any], flags: list[str]) -> list[str]:
    uses = ["report_only"]
    if _has_blocking_quality_flags(flags):
        return uses
    if row.get("is_valid_lap") and "not_driver_included" not in flags:
        uses.append("lap_summary")
    if (
        "missing_zone_passes" not in flags
        and "low_valid_zone_pass_rate" not in flags
        and "invalid_lap_summary" not in flags
    ):
        uses.append("zone_readiness")
    if (
        "missing_zone_passes" not in flags
        and "low_valid_zone_pass_rate" not in flags
        and "invalid_lap_summary" not in flags
        and "missing_lap_samples" not in flags
        and "low_telemetry_sample_count" not in flags
    ):
        uses.append("curve_update_candidate")
    if (
        row.get("is_valid_lap")
        and _is_baseline_row(row)
        and _int_or_zero(row.get("detected_lico_zone_count")) == 0
    ):
        uses.append("baseline_reference")
    if row.get("collection_design") == "recommendation_execution":
        uses.append("plan_execution_review")
    return uses


def _is_baseline_row(row: dict[str, Any]) -> bool:
    return row.get("collection_design") == "baseline" or row.get("collection_label") == "none"


def _validate_lap_summary_columns(lap_summary: pl.DataFrame) -> None:
    required_columns = {
        "run_id",
        "file_name",
        "lap_number",
        "collection_label",
        "driver_lap_label",
        "driver_included",
        "is_valid_lap",
        "lap_time_s",
        "fuel_used_l",
        "max_lap_distance_m",
        "mean_throttle_pct",
        "max_brake_pct",
        "exclusion_reason",
    }
    missing = required_columns - set(lap_summary.columns)
    if missing:
        missing_text = ", ".join(sorted(missing))
        raise ValueError(f"lap_summary missing required columns: {missing_text}")


def _validate_zone_pass_columns(zone_passes: pl.DataFrame) -> None:
    required_columns = {
        "run_id",
        "lap_number",
        "validity_label",
        "has_lico",
        "zone_start_zero_throttle",
        "brake_start_m",
        "brake_reference_m",
    }
    missing = required_columns - set(zone_passes.columns)
    if missing:
        missing_text = ", ".join(sorted(missing))
        raise ValueError(f"zone_passes missing required columns: {missing_text}")


def _validate_lap_sample_columns(lap_samples: pl.DataFrame) -> None:
    required_columns = {
        "run_id",
        "lap_number",
        "lap_elapsed_s",
        "lap_distance_m",
        "fuel_level_l",
        "ground_speed_kph",
        "throttle_pct",
        "brake_pct",
    }
    missing = required_columns - set(lap_samples.columns)
    if missing:
        missing_text = ", ".join(sorted(missing))
        raise ValueError(f"lap_samples missing required columns: {missing_text}")


def _sample_groups(lap_samples: pl.DataFrame) -> list[dict[str, object]]:
    return [
        {"run_id": row[0], "lap_number": row[1]}
        for row in lap_samples.select("run_id", "lap_number").unique().sort(
            ["run_id", "lap_number"]
        ).rows()
    ]


def _filter_sample_group(
    lap_samples: pl.DataFrame,
    group: dict[str, object],
) -> pl.DataFrame:
    return lap_samples.filter(
        (pl.col("run_id") == group["run_id"])
        & (pl.col("lap_number") == group["lap_number"])
    ).sort("lap_elapsed_s")


def _span(frame: pl.DataFrame, column: str) -> float | None:
    if frame.is_empty() or column not in frame.columns:
        return None
    values = frame[column].drop_nulls()
    if values.is_empty():
        return None
    return float(values.max()) - float(values.min())


def _max_diff(frame: pl.DataFrame, column: str) -> float | None:
    diffs = _diff_values(frame, column)
    return max(diffs) if diffs else None


def _max_abs_diff(frame: pl.DataFrame, column: str) -> float | None:
    diffs = [abs(value) for value in _diff_values(frame, column)]
    return max(diffs) if diffs else None


def _negative_diff_count(frame: pl.DataFrame, column: str) -> int:
    return sum(1 for value in _diff_values(frame, column) if value < 0.0)


def _positive_diff_count(frame: pl.DataFrame, column: str) -> int:
    return sum(1 for value in _diff_values(frame, column) if value > 0.0)


def _abs_diff_count(frame: pl.DataFrame, column: str, *, threshold: float) -> int:
    return sum(1 for value in _diff_values(frame, column) if abs(value) > threshold)


def _range_violation_count(
    frame: pl.DataFrame,
    column: str,
    *,
    minimum: float,
    maximum: float,
) -> int:
    if frame.is_empty() or column not in frame.columns:
        return 0
    return frame.filter((pl.col(column) < minimum) | (pl.col(column) > maximum)).height


def _diff_values(frame: pl.DataFrame, column: str) -> list[float]:
    if frame.is_empty() or column not in frame.columns:
        return []
    values = [
        float(value)
        for value in frame[column].drop_nulls().to_list()
    ]
    return [current - previous for previous, current in zip(values, values[1:])]


def _mean_or_none(frame: pl.DataFrame, column: str) -> float | None:
    if frame.is_empty() or column not in frame.columns:
        return None
    value = frame[column].drop_nulls().mean()
    return None if value is None else float(value)


def _delta(value: object, reference: float | None) -> float | None:
    numeric = _float_or_none(value)
    if numeric is None or reference is None:
        return None
    return numeric - reference


def _has_non_empty_values(frame: pl.DataFrame, column: str) -> bool:
    return (
        column in frame.columns
        and frame.filter(pl.col(column).fill_null("").cast(pl.String).str.len_chars() > 0).height
        > 0
    )


def _non_empty(value: object) -> bool:
    return value is not None and str(value).strip() != ""


def _int_or_zero(value: object) -> int:
    if value is None:
        return 0
    try:
        if value != value:
            return 0
    except TypeError:
        return 0
    return int(value)


def _float_or_none(value: object) -> float | None:
    if value is None:
        return None
    try:
        if value != value:
            return None
    except TypeError:
        return None
    return float(value)


def _float_or_zero(value: object) -> float:
    return _float_or_none(value) or 0.0


def _csv_safe_frame(frame: pl.DataFrame) -> pl.DataFrame:
    list_columns = [
        column
        for column, dtype in frame.schema.items()
        if isinstance(dtype, pl.List)
    ]
    if not list_columns:
        return frame
    return frame.with_columns(
        [
            pl.col(column)
            .list.eval(pl.element().cast(pl.String))
            .list.join("|")
            .alias(column)
            for column in list_columns
        ]
    )


_ZONE_LAP_METRICS_SCHEMA = {
    "run_id": pl.String,
    "lap_number": pl.Int64,
    "zone_pass_count": pl.Int64,
    "valid_zone_pass_count": pl.Int64,
    "invalid_zone_pass_count": pl.Int64,
    "detected_lico_zone_count": pl.Int64,
    "zone_start_zero_throttle_count": pl.Int64,
    "max_abs_brake_reference_delta_m": pl.Float64,
    "valid_zone_pass_rate": pl.Float64,
}

_LAP_SAMPLE_METRICS_SCHEMA = {
    "run_id": pl.String,
    "lap_number": pl.Int64,
    "telemetry_sample_count": pl.Int64,
    "lap_elapsed_span_s": pl.Float64,
    "max_time_gap_s": pl.Float64,
    "max_distance_gap_m": pl.Float64,
    "distance_monotonic_violation_count": pl.Int64,
    "fuel_increase_count": pl.Int64,
    "max_fuel_increase_l": pl.Float64,
    "speed_jump_count": pl.Int64,
    "max_speed_jump_kph": pl.Float64,
    "throttle_out_of_range_count": pl.Int64,
    "brake_out_of_range_count": pl.Int64,
}

_LAP_QUALITY_MANIFEST_COLUMNS = [
    "run_id",
    "file_name",
    "lap_number",
    "collection_label",
    "collection_protocol_id",
    "collection_design",
    "execution_quality",
    "labels_quality",
    "driver_lap_label",
    "is_valid_lap",
    "lap_time_s",
    "fuel_used_l",
    "baseline_mean_lap_time_s",
    "baseline_mean_fuel_used_l",
    "lap_time_delta_vs_baseline_s",
    "fuel_delta_vs_baseline_l",
    "max_lap_distance_m",
    "mean_throttle_pct",
    "max_brake_pct",
    "telemetry_sample_count",
    "lap_elapsed_span_s",
    "max_time_gap_s",
    "max_distance_gap_m",
    "distance_monotonic_violation_count",
    "fuel_increase_count",
    "max_fuel_increase_l",
    "speed_jump_count",
    "max_speed_jump_kph",
    "throttle_out_of_range_count",
    "brake_out_of_range_count",
    "zone_pass_count",
    "valid_zone_pass_count",
    "invalid_zone_pass_count",
    "valid_zone_pass_rate",
    "detected_lico_zone_count",
    "zone_start_zero_throttle_count",
    "max_abs_brake_reference_delta_m",
    "exclusion_reason",
    "quality_status",
    "quality_flags",
    "recommended_uses",
]

_LAP_QUALITY_MANIFEST_SCHEMA = {
    "run_id": pl.String,
    "file_name": pl.String,
    "lap_number": pl.Int64,
    "collection_label": pl.String,
    "collection_protocol_id": pl.String,
    "collection_design": pl.String,
    "execution_quality": pl.String,
    "labels_quality": pl.String,
    "driver_lap_label": pl.String,
    "is_valid_lap": pl.Boolean,
    "lap_time_s": pl.Float64,
    "fuel_used_l": pl.Float64,
    "baseline_mean_lap_time_s": pl.Float64,
    "baseline_mean_fuel_used_l": pl.Float64,
    "lap_time_delta_vs_baseline_s": pl.Float64,
    "fuel_delta_vs_baseline_l": pl.Float64,
    "max_lap_distance_m": pl.Float64,
    "mean_throttle_pct": pl.Float64,
    "max_brake_pct": pl.Float64,
    "telemetry_sample_count": pl.Int64,
    "lap_elapsed_span_s": pl.Float64,
    "max_time_gap_s": pl.Float64,
    "max_distance_gap_m": pl.Float64,
    "distance_monotonic_violation_count": pl.Int64,
    "fuel_increase_count": pl.Int64,
    "max_fuel_increase_l": pl.Float64,
    "speed_jump_count": pl.Int64,
    "max_speed_jump_kph": pl.Float64,
    "throttle_out_of_range_count": pl.Int64,
    "brake_out_of_range_count": pl.Int64,
    "zone_pass_count": pl.Int64,
    "valid_zone_pass_count": pl.Int64,
    "invalid_zone_pass_count": pl.Int64,
    "valid_zone_pass_rate": pl.Float64,
    "detected_lico_zone_count": pl.Int64,
    "zone_start_zero_throttle_count": pl.Int64,
    "max_abs_brake_reference_delta_m": pl.Float64,
    "exclusion_reason": pl.String,
    "quality_status": pl.String,
    "quality_flags": pl.List(pl.String),
    "recommended_uses": pl.List(pl.String),
}
