from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

import polars as pl

from licor.analysis.zone_optimizer import ZoneOptimizerConfig, optimize_zone_lico_plan


@dataclass(frozen=True)
class ZonePlanSensitivityScenario:
    name: str
    target_fuel_margin_l: float = 0.0
    allowed_model_statuses: tuple[str, ...] | None = None
    require_usable_ratio: bool | None = None
    best_ratio_cap: bool = False
    max_lico_distance_by_zone: Mapping[str, float] | None = None
    notes: str = ""


def build_zone_marginal_efficiency(
    zone_models: pl.DataFrame,
    *,
    zone_plan: pl.DataFrame | None = None,
    min_incremental_time_loss_s: float = 0.05,
    min_positive_fuel_saved_l: float = 1e-6,
) -> pl.DataFrame:
    """Compute consecutive-segment fuel/time efficiency for zone model curves."""

    if zone_models.is_empty():
        return _empty_marginal_efficiency_frame()

    selected_distances = _selected_plan_distances(zone_plan)
    rows = []
    for zone_id in sorted(zone_models["zone_id"].unique().to_list()):
        model = zone_models.filter(pl.col("zone_id") == zone_id).sort("lico_distance_m")
        rows.extend(
            _zone_marginal_rows(
                model,
                selected_distance_m=selected_distances.get(str(zone_id)),
                min_incremental_time_loss_s=min_incremental_time_loss_s,
                min_positive_fuel_saved_l=min_positive_fuel_saved_l,
            )
        )

    if not rows:
        return _empty_marginal_efficiency_frame()
    return pl.DataFrame(rows, schema=_MARGINAL_SCHEMA, strict=False).select(_MARGINAL_COLUMNS)


def default_zone_plan_sensitivity_scenarios() -> tuple[ZonePlanSensitivityScenario, ...]:
    return (
        ZonePlanSensitivityScenario(name="base"),
        ZonePlanSensitivityScenario(name="best_ratio_caps", best_ratio_cap=True),
        ZonePlanSensitivityScenario(
            name="diagnostic_excluded",
            allowed_model_statuses=("model_ready",),
        ),
        ZonePlanSensitivityScenario(name="fuel_margin_0.01_l", target_fuel_margin_l=0.01),
    )


def summarize_zone_plan_sensitivity(
    zone_models: pl.DataFrame,
    *,
    base_config: ZoneOptimizerConfig,
    zone_priors: pl.DataFrame | None = None,
    scenarios: Sequence[ZonePlanSensitivityScenario] | None = None,
) -> pl.DataFrame:
    """Run optimizer variants and summarize plan-level sensitivity."""

    scenario_list = tuple(scenarios or default_zone_plan_sensitivity_scenarios())
    rows = []
    for scenario in scenario_list:
        scenario_models = _apply_scenario_model_filters(zone_models, scenario)
        scenario_config = replace(
            base_config,
            target_fuel_saved_per_lap_l=(
                base_config.target_fuel_saved_per_lap_l + scenario.target_fuel_margin_l
            ),
            allowed_model_statuses=(
                scenario.allowed_model_statuses
                if scenario.allowed_model_statuses is not None
                else base_config.allowed_model_statuses
            ),
            require_usable_ratio=(
                scenario.require_usable_ratio
                if scenario.require_usable_ratio is not None
                else base_config.require_usable_ratio
            ),
        )
        plan = optimize_zone_lico_plan(
            scenario_models,
            config=scenario_config,
            zone_priors=zone_priors,
        )
        rows.append(_sensitivity_row(scenario, scenario_config, scenario_models, plan))

    return pl.DataFrame(rows, schema=_SENSITIVITY_SCHEMA, strict=False).select(
        _SENSITIVITY_COLUMNS
    )


def _zone_marginal_rows(
    model: pl.DataFrame,
    *,
    selected_distance_m: float | None,
    min_incremental_time_loss_s: float,
    min_positive_fuel_saved_l: float,
) -> list[dict[str, Any]]:
    rows = list(model.iter_rows(named=True))
    if len(rows) < 2:
        return []

    best_ratio_distance_m = _best_cumulative_ratio_distance(model)
    output = []
    for left, right in zip(rows, rows[1:]):
        from_distance_m = float(left["lico_distance_m"])
        to_distance_m = float(right["lico_distance_m"])
        if to_distance_m <= from_distance_m:
            continue
        incremental_fuel_saved_l = (
            float(right["predicted_fuel_saved_l"]) - float(left["predicted_fuel_saved_l"])
        )
        incremental_time_lost_s = (
            float(right["predicted_time_lost_s"]) - float(left["predicted_time_lost_s"])
        )
        flags = _marginal_flags(
            incremental_fuel_saved_l,
            incremental_time_lost_s,
            min_incremental_time_loss_s=min_incremental_time_loss_s,
            min_positive_fuel_saved_l=min_positive_fuel_saved_l,
        )
        marginal_ratio = _marginal_ratio(
            incremental_fuel_saved_l,
            incremental_time_lost_s,
            min_incremental_time_loss_s=min_incremental_time_loss_s,
            min_positive_fuel_saved_l=min_positive_fuel_saved_l,
        )
        output.append(
            {
                "zone_id": str(right["zone_id"]),
                "display_label": str(right["display_label"]),
                "from_lico_distance_m": from_distance_m,
                "to_lico_distance_m": to_distance_m,
                "segment_distance_m": to_distance_m - from_distance_m,
                "incremental_fuel_saved_l": incremental_fuel_saved_l,
                "incremental_time_lost_s": incremental_time_lost_s,
                "marginal_fuel_saved_per_second_lps": marginal_ratio,
                "start_predicted_fuel_saved_l": float(left["predicted_fuel_saved_l"]),
                "end_predicted_fuel_saved_l": float(right["predicted_fuel_saved_l"]),
                "start_predicted_time_lost_s": float(left["predicted_time_lost_s"]),
                "end_predicted_time_lost_s": float(right["predicted_time_lost_s"]),
                "end_cumulative_fuel_saved_per_second_lps": right.get(
                    "predicted_fuel_saved_per_second_lps"
                ),
                "best_cumulative_ratio_distance_m": best_ratio_distance_m,
                "is_after_best_cumulative_ratio_distance": (
                    best_ratio_distance_m is not None and from_distance_m >= best_ratio_distance_m
                ),
                "selected_plan_distance_m": selected_distance_m,
                "contains_selected_plan_point": (
                    selected_distance_m is not None
                    and selected_distance_m > from_distance_m
                    and selected_distance_m <= to_distance_m
                ),
                "model_status": str(right["model_status"]),
                "quality_flags": _format_quality_flags(right.get("quality_flags")),
                "marginal_flags": "|".join(flags),
            }
        )
    return output


def _marginal_ratio(
    fuel_saved_l: float,
    time_lost_s: float,
    *,
    min_incremental_time_loss_s: float,
    min_positive_fuel_saved_l: float,
) -> float | None:
    if fuel_saved_l <= min_positive_fuel_saved_l:
        return None
    if time_lost_s < min_incremental_time_loss_s:
        return None
    return fuel_saved_l / time_lost_s


def _marginal_flags(
    fuel_saved_l: float,
    time_lost_s: float,
    *,
    min_incremental_time_loss_s: float,
    min_positive_fuel_saved_l: float,
) -> list[str]:
    flags = []
    if fuel_saved_l <= min_positive_fuel_saved_l:
        flags.append("nonpositive_incremental_fuel")
    if time_lost_s < 0.0:
        flags.append("negative_incremental_time")
    elif time_lost_s < min_incremental_time_loss_s:
        flags.append("low_incremental_time_ratio_suppressed")
    return flags


def _best_cumulative_ratio_distance(model: pl.DataFrame) -> float | None:
    usable = model.filter(pl.col("predicted_fuel_saved_per_second_lps").is_not_null())
    if usable.is_empty():
        return None
    max_ratio = float(usable["predicted_fuel_saved_per_second_lps"].max())
    best_rows = usable.filter(pl.col("predicted_fuel_saved_per_second_lps") == max_ratio)
    return float(best_rows["lico_distance_m"].min())


def _selected_plan_distances(zone_plan: pl.DataFrame | None) -> dict[str, float]:
    if zone_plan is None or zone_plan.is_empty():
        return {}
    return {
        str(row["zone_id"]): float(row["selected_lico_distance_m"])
        for row in zone_plan.iter_rows(named=True)
    }


def _apply_scenario_model_filters(
    zone_models: pl.DataFrame,
    scenario: ZonePlanSensitivityScenario,
) -> pl.DataFrame:
    filtered = zone_models
    caps: dict[str, float] = {}
    if scenario.best_ratio_cap:
        caps.update(_best_ratio_caps(filtered))
    if scenario.max_lico_distance_by_zone:
        caps.update(
            {
                str(zone_id): float(max_distance_m)
                for zone_id, max_distance_m in scenario.max_lico_distance_by_zone.items()
            }
        )
    if caps:
        filtered = _filter_model_by_distance_caps(filtered, caps)
    return filtered


def _best_ratio_caps(zone_models: pl.DataFrame) -> dict[str, float]:
    caps = {}
    for zone_id in sorted(zone_models["zone_id"].unique().to_list()):
        zone_model = zone_models.filter(pl.col("zone_id") == zone_id)
        caps[str(zone_id)] = _best_cumulative_ratio_distance(zone_model) or 0.0
    return caps


def _filter_model_by_distance_caps(
    zone_models: pl.DataFrame,
    caps: Mapping[str, float],
) -> pl.DataFrame:
    rows = [
        row
        for row in zone_models.iter_rows(named=True)
        if float(row["lico_distance_m"]) <= caps.get(str(row["zone_id"]), float("inf")) + 1e-9
    ]
    if not rows:
        return pl.DataFrame(schema=zone_models.schema)
    return pl.DataFrame(rows, schema=zone_models.schema, strict=False).select(zone_models.columns)


def _sensitivity_row(
    scenario: ZonePlanSensitivityScenario,
    config: ZoneOptimizerConfig,
    scenario_models: pl.DataFrame,
    plan: pl.DataFrame,
) -> dict[str, Any]:
    if plan.is_empty():
        return {
            "scenario_name": scenario.name,
            "scenario_notes": scenario.notes,
            "target_fuel_saved_per_lap_l": config.target_fuel_saved_per_lap_l,
            "plan_status": "no_candidates",
            "total_predicted_fuel_saved_l": None,
            "total_predicted_time_lost_s": None,
            "total_optimization_time_lost_s": None,
            "fuel_surplus_l": None,
            "selected_zone_count": 0,
            "selected_zone_ids": "",
            "selected_zone_distances": "",
            "diagnostic_selected_zone_count": 0,
            "considered_zone_count": _unique_zone_count(scenario_models),
            "considered_model_point_count": scenario_models.height,
            "best_ratio_cap_applied": scenario.best_ratio_cap,
            "target_fuel_margin_l": scenario.target_fuel_margin_l,
        }

    first = plan.row(0, named=True)
    selected = plan.filter(pl.col("is_selected_for_lico"))
    return {
        "scenario_name": scenario.name,
        "scenario_notes": scenario.notes,
        "target_fuel_saved_per_lap_l": config.target_fuel_saved_per_lap_l,
        "plan_status": str(first["plan_status"]),
        "total_predicted_fuel_saved_l": float(first["total_predicted_fuel_saved_l"]),
        "total_predicted_time_lost_s": float(first["total_predicted_time_lost_s"]),
        "total_optimization_time_lost_s": float(first["total_optimization_time_lost_s"]),
        "fuel_surplus_l": float(first["fuel_surplus_l"]),
        "selected_zone_count": selected.height,
        "selected_zone_ids": _selected_zone_ids(selected),
        "selected_zone_distances": _selected_zone_distances(selected),
        "diagnostic_selected_zone_count": selected.filter(
            pl.col("model_status") == "diagnostic_only"
        ).height,
        "considered_zone_count": _unique_zone_count(scenario_models),
        "considered_model_point_count": scenario_models.height,
        "best_ratio_cap_applied": scenario.best_ratio_cap,
        "target_fuel_margin_l": scenario.target_fuel_margin_l,
    }


def _selected_zone_ids(selected: pl.DataFrame) -> str:
    if selected.is_empty():
        return ""
    return "|".join(selected.sort("zone_id")["zone_id"].to_list())


def _selected_zone_distances(selected: pl.DataFrame) -> str:
    if selected.is_empty():
        return ""
    rows = selected.sort("zone_id").iter_rows(named=True)
    return "|".join(
        f"{row['zone_id']}={float(row['selected_lico_distance_m']):.3f}" for row in rows
    )


def _unique_zone_count(frame: pl.DataFrame) -> int:
    if frame.is_empty():
        return 0
    return len(frame["zone_id"].unique())


def _format_quality_flags(flags: Any) -> str:
    if flags is None:
        return ""
    if isinstance(flags, str):
        return flags
    return "|".join(str(flag) for flag in flags)


def _empty_marginal_efficiency_frame() -> pl.DataFrame:
    return pl.DataFrame(schema=_MARGINAL_SCHEMA)


_MARGINAL_COLUMNS = [
    "zone_id",
    "display_label",
    "from_lico_distance_m",
    "to_lico_distance_m",
    "segment_distance_m",
    "incremental_fuel_saved_l",
    "incremental_time_lost_s",
    "marginal_fuel_saved_per_second_lps",
    "start_predicted_fuel_saved_l",
    "end_predicted_fuel_saved_l",
    "start_predicted_time_lost_s",
    "end_predicted_time_lost_s",
    "end_cumulative_fuel_saved_per_second_lps",
    "best_cumulative_ratio_distance_m",
    "is_after_best_cumulative_ratio_distance",
    "selected_plan_distance_m",
    "contains_selected_plan_point",
    "model_status",
    "quality_flags",
    "marginal_flags",
]

_MARGINAL_SCHEMA = {
    "zone_id": pl.String,
    "display_label": pl.String,
    "from_lico_distance_m": pl.Float64,
    "to_lico_distance_m": pl.Float64,
    "segment_distance_m": pl.Float64,
    "incremental_fuel_saved_l": pl.Float64,
    "incremental_time_lost_s": pl.Float64,
    "marginal_fuel_saved_per_second_lps": pl.Float64,
    "start_predicted_fuel_saved_l": pl.Float64,
    "end_predicted_fuel_saved_l": pl.Float64,
    "start_predicted_time_lost_s": pl.Float64,
    "end_predicted_time_lost_s": pl.Float64,
    "end_cumulative_fuel_saved_per_second_lps": pl.Float64,
    "best_cumulative_ratio_distance_m": pl.Float64,
    "is_after_best_cumulative_ratio_distance": pl.Boolean,
    "selected_plan_distance_m": pl.Float64,
    "contains_selected_plan_point": pl.Boolean,
    "model_status": pl.String,
    "quality_flags": pl.String,
    "marginal_flags": pl.String,
}

_SENSITIVITY_COLUMNS = [
    "scenario_name",
    "scenario_notes",
    "target_fuel_saved_per_lap_l",
    "plan_status",
    "total_predicted_fuel_saved_l",
    "total_predicted_time_lost_s",
    "total_optimization_time_lost_s",
    "fuel_surplus_l",
    "selected_zone_count",
    "selected_zone_ids",
    "selected_zone_distances",
    "diagnostic_selected_zone_count",
    "considered_zone_count",
    "considered_model_point_count",
    "best_ratio_cap_applied",
    "target_fuel_margin_l",
]

_SENSITIVITY_SCHEMA = {
    "scenario_name": pl.String,
    "scenario_notes": pl.String,
    "target_fuel_saved_per_lap_l": pl.Float64,
    "plan_status": pl.String,
    "total_predicted_fuel_saved_l": pl.Float64,
    "total_predicted_time_lost_s": pl.Float64,
    "total_optimization_time_lost_s": pl.Float64,
    "fuel_surplus_l": pl.Float64,
    "selected_zone_count": pl.Int64,
    "selected_zone_ids": pl.String,
    "selected_zone_distances": pl.String,
    "diagnostic_selected_zone_count": pl.Int64,
    "considered_zone_count": pl.Int64,
    "considered_model_point_count": pl.Int64,
    "best_ratio_cap_applied": pl.Boolean,
    "target_fuel_margin_l": pl.Float64,
}
