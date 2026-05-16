from __future__ import annotations

from dataclasses import dataclass

import polars as pl


@dataclass(frozen=True)
class LiveCuePlanConfig:
    plan_id: str
    track_name: str = ""
    car_class: str = ""
    race_context_id: str = ""
    minimum_confidence_label: str = ""
    cue_tolerance_m: float = 5.0
    track_length_m: float | None = None
    include_zero_lico: bool = False
    notes: str = ""


def build_live_cue_plan(
    zone_plan: pl.DataFrame,
    track_zones: pl.DataFrame,
    *,
    config: LiveCuePlanConfig,
) -> pl.DataFrame:
    """Build a versioned plan table for replay/live cue execution."""

    if zone_plan.is_empty():
        return empty_live_cue_plan_frame()

    selected = zone_plan
    if not config.include_zero_lico:
        selected = selected.filter(pl.col("is_selected_for_lico"))
    if selected.is_empty():
        return empty_live_cue_plan_frame()

    plan = selected.join(_track_zone_references(track_zones), on="zone_id", how="left")
    rows = []
    for row in plan.iter_rows(named=True):
        brake_reference_m = row["brake_reference_m"]
        if brake_reference_m is None:
            raise ValueError(f"missing brake_reference_m for zone {row['zone_id']}")
        selected_distance_m = float(row["selected_lico_distance_m"])
        planned_lift_start_m = _planned_lift_start_m(
            float(brake_reference_m),
            selected_distance_m,
            track_length_m=config.track_length_m,
        )
        rows.append(
            {
                "schema_version": 1,
                "plan_id": config.plan_id,
                "track_name": config.track_name,
                "car_class": config.car_class,
                "race_context_id": config.race_context_id,
                "zone_id": str(row["zone_id"]),
                "display_label": str(row["display_label"]),
                "brake_reference_m": float(brake_reference_m),
                "selected_lico_distance_m": selected_distance_m,
                "planned_lift_start_m": planned_lift_start_m,
                "cue_distance_m": planned_lift_start_m,
                "cue_tolerance_m": config.cue_tolerance_m,
                "track_length_m": config.track_length_m,
                "minimum_confidence_label": (
                    config.minimum_confidence_label or _confidence_label(row)
                ),
                "expected_fuel_saved_l": float(row["predicted_fuel_saved_l"]),
                "expected_time_lost_s": float(row["predicted_time_lost_s"]),
                "plan_status": str(row["plan_status"]),
                "source_model_status": str(row.get("model_status") or ""),
                "source_quality_flags": row.get("quality_flags") or "",
                "strategy_role": row.get("strategy_role") or "",
                "notes": config.notes or row.get("strategy_prior_notes") or "",
            }
        )

    return pl.DataFrame(rows, schema=_LIVE_CUE_PLAN_SCHEMA, strict=False).select(
        _LIVE_CUE_PLAN_COLUMNS
    )


def build_live_cue_executions_from_zone_passes(
    live_cue_plan: pl.DataFrame,
    zone_passes: pl.DataFrame,
    *,
    track_length_m: float | None = None,
) -> pl.DataFrame:
    """Build replay-style planned-vs-executed rows from observed zone passes."""

    if live_cue_plan.is_empty() or zone_passes.is_empty():
        return empty_live_cue_execution_frame()

    joined = zone_passes.join(
        live_cue_plan.select(
            [
                "plan_id",
                "zone_id",
                "cue_distance_m",
                "planned_lift_start_m",
                *(
                    ["track_length_m"]
                    if "track_length_m" in live_cue_plan.columns
                    else []
                ),
            ]
        ),
        on="zone_id",
        how="inner",
    )
    if joined.is_empty():
        return empty_live_cue_execution_frame()

    rows = []
    for row in joined.iter_rows(named=True):
        actual_lift_start_m = row["lico_start_m"]
        planned_lift_start_m = float(row["planned_lift_start_m"])
        effective_track_length_m = _optional_float(
            track_length_m
            if track_length_m is not None
            else row.get("track_length_m")
        )
        actual_lift_start_float = _optional_float(actual_lift_start_m)
        rows.append(
            {
                "schema_version": 1,
                "plan_id": str(row["plan_id"]),
                "file_name": str(row.get("file_name") or ""),
                "run_id": str(row.get("run_id") or ""),
                "lap_number": int(row["lap_number"]),
                "zone_id": str(row["zone_id"]),
                "cue_trigger_m": float(row["cue_distance_m"]),
                "planned_lift_start_m": planned_lift_start_m,
                "actual_lift_start_m": actual_lift_start_float,
                "actual_lift_distance_before_brake_m": _optional_float(
                    row.get("lico_start_distance_before_brake_m")
                ),
                "actual_brake_start_m": _optional_float(row.get("brake_start_m")),
                "cue_error_m": _signed_distance_delta_m(
                    actual_lift_start_float,
                    planned_lift_start_m,
                    track_length_m=effective_track_length_m,
                ),
                "fuel_saved_vs_baseline_l": _first_optional_float(
                    row,
                    ("fuel_saved_vs_baseline_l", "fuel_delta_l"),
                ),
                "time_lost_vs_baseline_s": _first_optional_float(
                    row,
                    ("time_lost_vs_baseline_s", "time_delta_s"),
                ),
                "execution_quality": str(row.get("validity_label") or "unknown"),
                "notes": str(row.get("notes") or ""),
            }
        )

    return pl.DataFrame(rows, schema=_LIVE_CUE_EXECUTION_SCHEMA, strict=False).select(
        _LIVE_CUE_EXECUTION_COLUMNS
    )


def empty_live_cue_plan_frame() -> pl.DataFrame:
    return pl.DataFrame(schema=_LIVE_CUE_PLAN_SCHEMA)


def empty_live_cue_execution_frame() -> pl.DataFrame:
    return pl.DataFrame(schema=_LIVE_CUE_EXECUTION_SCHEMA)


def _track_zone_references(track_zones: pl.DataFrame) -> pl.DataFrame:
    columns = ["zone_id", "brake_reference_m"]
    existing_columns = [column for column in columns if column in track_zones.columns]
    return track_zones.select(existing_columns)


def _planned_lift_start_m(
    brake_reference_m: float,
    selected_lico_distance_m: float,
    *,
    track_length_m: float | None,
) -> float:
    lift_start_m = brake_reference_m - selected_lico_distance_m
    if track_length_m is not None:
        return lift_start_m % track_length_m
    return lift_start_m


def _confidence_label(row: dict[str, object]) -> str:
    if row.get("model_status") == "model_ready":
        return "model_ready"
    if row.get("model_status") == "diagnostic_only":
        return "driver_prior_diagnostic"
    return "review_required"


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    return float(value)


def _first_optional_float(
    row: dict[str, object],
    column_names: tuple[str, ...],
) -> float | None:
    for column_name in column_names:
        value = row.get(column_name)
        if value is not None:
            return float(value)
    return None


def _signed_distance_delta_m(
    actual_m: float | None,
    planned_m: float,
    *,
    track_length_m: float | None,
) -> float | None:
    if actual_m is None:
        return None
    delta_m = actual_m - planned_m
    if track_length_m is None:
        return delta_m
    half_track_m = track_length_m / 2.0
    return ((delta_m + half_track_m) % track_length_m) - half_track_m


_LIVE_CUE_PLAN_COLUMNS = [
    "schema_version",
    "plan_id",
    "track_name",
    "car_class",
    "race_context_id",
    "zone_id",
    "display_label",
    "brake_reference_m",
    "selected_lico_distance_m",
    "planned_lift_start_m",
    "cue_distance_m",
    "cue_tolerance_m",
    "track_length_m",
    "minimum_confidence_label",
    "expected_fuel_saved_l",
    "expected_time_lost_s",
    "plan_status",
    "source_model_status",
    "source_quality_flags",
    "strategy_role",
    "notes",
]

_LIVE_CUE_PLAN_SCHEMA = {
    "schema_version": pl.Int64,
    "plan_id": pl.String,
    "track_name": pl.String,
    "car_class": pl.String,
    "race_context_id": pl.String,
    "zone_id": pl.String,
    "display_label": pl.String,
    "brake_reference_m": pl.Float64,
    "selected_lico_distance_m": pl.Float64,
    "planned_lift_start_m": pl.Float64,
    "cue_distance_m": pl.Float64,
    "cue_tolerance_m": pl.Float64,
    "track_length_m": pl.Float64,
    "minimum_confidence_label": pl.String,
    "expected_fuel_saved_l": pl.Float64,
    "expected_time_lost_s": pl.Float64,
    "plan_status": pl.String,
    "source_model_status": pl.String,
    "source_quality_flags": pl.String,
    "strategy_role": pl.String,
    "notes": pl.String,
}

_LIVE_CUE_EXECUTION_COLUMNS = [
    "schema_version",
    "plan_id",
    "file_name",
    "run_id",
    "lap_number",
    "zone_id",
    "cue_trigger_m",
    "planned_lift_start_m",
    "actual_lift_start_m",
    "actual_lift_distance_before_brake_m",
    "actual_brake_start_m",
    "cue_error_m",
    "fuel_saved_vs_baseline_l",
    "time_lost_vs_baseline_s",
    "execution_quality",
    "notes",
]

_LIVE_CUE_EXECUTION_SCHEMA = {
    "schema_version": pl.Int64,
    "plan_id": pl.String,
    "file_name": pl.String,
    "run_id": pl.String,
    "lap_number": pl.Int64,
    "zone_id": pl.String,
    "cue_trigger_m": pl.Float64,
    "planned_lift_start_m": pl.Float64,
    "actual_lift_start_m": pl.Float64,
    "actual_lift_distance_before_brake_m": pl.Float64,
    "actual_brake_start_m": pl.Float64,
    "cue_error_m": pl.Float64,
    "fuel_saved_vs_baseline_l": pl.Float64,
    "time_lost_vs_baseline_s": pl.Float64,
    "execution_quality": pl.String,
    "notes": pl.String,
}
