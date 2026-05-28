from __future__ import annotations

from dataclasses import dataclass

import polars as pl

from licor.analysis.experimental_robust_optimizer import (
    build_experimental_range_aware_plan,
)


@dataclass(frozen=True)
class ExperimentalLapExecutionEvent:
    lap_number: int
    scenario_event: str
    execution_quality: str = "nominal"
    force_zero_lico: bool = False
    fuel_saved_scale: float = 1.0
    time_lost_scale: float = 1.0
    extra_time_lost_s: float = 0.0
    notes: str = ""


@dataclass(frozen=True)
class ExperimentalLapReplanningScenario:
    scenario_id: str
    total_laps: int
    events: tuple[ExperimentalLapExecutionEvent, ...] = ()
    notes: str = ""


@dataclass(frozen=True)
class ExperimentalLapReplannerConfig:
    target_fuel_saved_per_lap_l: float
    planning_modes: tuple[str, ...] = ("static", "adaptive")
    allowed_model_statuses: tuple[str, ...] = ("model_ready", "micro_lico_only")
    fuel_load_conditioning_enabled: bool = False
    heavy_fuel_load_time_slope: float = 0.04
    medium_fuel_load_time_slope: float = 0.0
    light_fuel_load_time_slope: float = -0.04
    min_time_conditioning_multiplier: float = 0.75
    max_time_conditioning_multiplier: float = 1.25
    execution_calibration_enabled: bool = True
    execution_calibration_window_laps: int = 3
    min_driver_fuel_execution_scale: float = 0.65
    max_driver_fuel_execution_scale: float = 1.10
    min_driver_time_execution_scale: float = 0.80
    max_driver_time_execution_scale: float = 1.35
    zone_execution_calibration_enabled: bool = True
    zone_execution_calibration_full_weight_rows: int = 3


@dataclass(frozen=True)
class ExperimentalLapReplannerContext:
    variant_name: str
    static_plan: pl.DataFrame
    robust_zone_models: pl.DataFrame
    robust_ranges: pl.DataFrame
    zone_priors: pl.DataFrame | None = None
    adaptive_scope: str = "all_eligible_zones"


@dataclass(frozen=True)
class ExperimentalAdaptiveHandoffGuardrailConfig:
    max_abs_distance_delta_m: float = 20.0
    low_support_rows_threshold: int = 2
    low_support_max_abs_distance_delta_m: float = 10.0
    allow_added_zones: bool = False
    allow_removed_zones: bool = False


def simulate_experimental_lap_replanning(
    context: ExperimentalLapReplannerContext,
    scenarios: tuple[ExperimentalLapReplanningScenario, ...],
    *,
    config: ExperimentalLapReplannerConfig,
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    """Simulate lap-by-lap static versus adaptive replanning outcomes."""

    lap_summary_rows: list[dict[str, object]] = []
    lap_plan_rows: list[dict[str, object]] = []
    scenario_summary_rows: list[dict[str, object]] = []

    for scenario in scenarios:
        event_map = {
            int(event.lap_number): event
            for event in scenario.events
        }
        for planning_mode in config.planning_modes:
            remaining_target_l = (
                config.target_fuel_saved_per_lap_l * float(scenario.total_laps)
            )
            cumulative_fuel_saved_l = 0.0
            cumulative_time_lost_s = 0.0
            last_next_lap_target_l = 0.0
            last_next_lap_plan = pl.DataFrame()
            execution_history: list[dict[str, float]] = []
            zone_execution_history: list[dict[str, object]] = []

            for lap_number in range(1, scenario.total_laps + 1):
                laps_remaining = scenario.total_laps - lap_number + 1
                lap_target_fuel_saved_l = max(0.0, remaining_target_l / laps_remaining)
                lap_context = _empty_lap_context()
                driver_execution_scales = _driver_execution_scales(
                    execution_history,
                    config=config,
                    planning_mode=planning_mode,
                )
                driver_zone_execution_scales = _driver_zone_execution_scales(
                    zone_execution_history,
                    driver_execution_scales=driver_execution_scales,
                    config=config,
                    planning_mode=planning_mode,
                )
                current_plan = _planned_lap_plan(
                    context,
                    planning_mode=planning_mode,
                    target_fuel_saved_per_lap_l=lap_target_fuel_saved_l,
                    config=config,
                    lap_context=lap_context,
                    driver_execution_scales=driver_execution_scales,
                    driver_zone_execution_scales=driver_zone_execution_scales,
                )
                current_plan_summary = _plan_summary(current_plan)
                event = event_map.get(
                    lap_number,
                    ExperimentalLapExecutionEvent(
                        lap_number=lap_number,
                        scenario_event="nominal",
                    ),
                )
                actual_zone_rows, actual_fuel_saved_l, actual_time_lost_s = _execute_lap_plan(
                    current_plan,
                    event=event,
                )
                cumulative_fuel_saved_l += actual_fuel_saved_l
                cumulative_time_lost_s += actual_time_lost_s
                execution_history.append(
                    {
                        "planned_fuel_saved_l": current_plan_summary["total_fuel_saved_l"],
                        "planned_time_lost_s": current_plan_summary["total_time_lost_s"],
                        "actual_fuel_saved_l": actual_fuel_saved_l,
                        "actual_time_lost_s": actual_time_lost_s,
                    }
                )
                zone_execution_history.extend(
                    _zone_execution_history_rows(
                        current_plan,
                        actual_zone_rows=actual_zone_rows,
                        lap_number=lap_number,
                    )
                )
                remaining_target_after_l = remaining_target_l - actual_fuel_saved_l
                laps_after = scenario.total_laps - lap_number
                next_lap_target_l = (
                    max(0.0, remaining_target_after_l / laps_after) if laps_after > 0 else 0.0
                )
                next_driver_execution_scales = _driver_execution_scales(
                    execution_history,
                    config=config,
                    planning_mode=planning_mode,
                )
                next_driver_zone_execution_scales = _driver_zone_execution_scales(
                    zone_execution_history,
                    driver_execution_scales=next_driver_execution_scales,
                    config=config,
                    planning_mode=planning_mode,
                )
                next_lap_plan = (
                    _planned_lap_plan(
                        context,
                        planning_mode=planning_mode,
                        target_fuel_saved_per_lap_l=next_lap_target_l,
                        config=config,
                        lap_context=lap_context,
                        driver_execution_scales=next_driver_execution_scales,
                        driver_zone_execution_scales=next_driver_zone_execution_scales,
                    )
                    if laps_after > 0
                    else pl.DataFrame()
                )
                next_plan_summary = _plan_summary(next_lap_plan)

                lap_summary_rows.append(
                    {
                        "scenario_id": scenario.scenario_id,
                        "variant_name": context.variant_name,
                        "planning_mode": planning_mode,
                        "lap_number": lap_number,
                        "total_laps": scenario.total_laps,
                        "laps_remaining": laps_remaining,
                        "fuel_target_remaining_l": remaining_target_l,
                        "lap_target_fuel_saved_l": lap_target_fuel_saved_l,
                        "planned_zone_count": current_plan_summary["selected_zone_count"],
                        "planned_zone_ids": current_plan_summary["selected_zone_ids"],
                        "planned_zone_distances": current_plan_summary["selected_zone_distances"],
                        "planned_fuel_saved_l": current_plan_summary["total_fuel_saved_l"],
                        "planned_time_lost_s": current_plan_summary["total_time_lost_s"],
                        "planned_plan_status": current_plan_summary["plan_status"],
                        "execution_quality": event.execution_quality,
                        "scenario_event": event.scenario_event,
                        "actual_zone_count": len(actual_zone_rows),
                        "actual_zone_ids": "|".join(
                            str(row["zone_id"]) for row in actual_zone_rows
                        ),
                        "fuel_saved_this_lap_l": actual_fuel_saved_l,
                        "time_lost_this_lap_s": actual_time_lost_s,
                        "cumulative_fuel_saved_l": cumulative_fuel_saved_l,
                        "cumulative_time_lost_s": cumulative_time_lost_s,
                        "fuel_target_remaining_after_l": remaining_target_after_l,
                        "next_lap_target_fuel_saved_l": next_lap_target_l,
                        "next_lap_selected_zone_count": next_plan_summary["selected_zone_count"],
                        "next_lap_selected_zone_ids": next_plan_summary["selected_zone_ids"],
                        "next_lap_selected_zone_distances": next_plan_summary[
                            "selected_zone_distances"
                        ],
                        "next_lap_expected_fuel_saved_l": next_plan_summary["total_fuel_saved_l"],
                        "next_lap_expected_time_lost_s": next_plan_summary["total_time_lost_s"],
                        "next_lap_plan_status": next_plan_summary["plan_status"],
                        "driver_fuel_execution_scale": driver_execution_scales["fuel_scale"],
                        "driver_time_execution_scale": driver_execution_scales["time_scale"],
                        "driver_zone_execution_scale_count": len(driver_zone_execution_scales),
                        "driver_zone_execution_scale_zone_ids": _joined_unique_strings(
                            driver_zone_execution_scales.keys(),
                            default="",
                        ),
                        "next_lap_driver_fuel_execution_scale": next_driver_execution_scales[
                            "fuel_scale"
                        ],
                        "next_lap_driver_time_execution_scale": next_driver_execution_scales[
                            "time_scale"
                        ],
                        "next_lap_driver_zone_execution_scale_count": len(
                            next_driver_zone_execution_scales
                        ),
                        "next_lap_driver_zone_execution_scale_zone_ids": _joined_unique_strings(
                            next_driver_zone_execution_scales.keys(),
                            default="",
                        ),
                        **_empty_lap_context(),
                        "notes": event.notes or scenario.notes,
                    }
                )
                lap_plan_rows.extend(
                    _lap_plan_rows(
                        current_plan,
                        actual_zone_rows=actual_zone_rows,
                        scenario_id=scenario.scenario_id,
                        variant_name=context.variant_name,
                        planning_mode=planning_mode,
                        lap_number=lap_number,
                        execution_quality=event.execution_quality,
                        scenario_event=event.scenario_event,
                        notes=event.notes or scenario.notes,
                        driver_execution_scales=driver_execution_scales,
                        driver_zone_execution_scales=driver_zone_execution_scales,
                    )
                )

                remaining_target_l = remaining_target_after_l
                last_next_lap_target_l = next_lap_target_l
                last_next_lap_plan = next_lap_plan

            scenario_summary_rows.append(
                {
                    "scenario_id": scenario.scenario_id,
                    "variant_name": context.variant_name,
                    "planning_mode": planning_mode,
                    "total_laps": scenario.total_laps,
                    "total_actual_fuel_saved_l": cumulative_fuel_saved_l,
                    "total_actual_time_lost_s": cumulative_time_lost_s,
                    "final_fuel_target_remaining_l": remaining_target_l,
                    "final_next_lap_target_fuel_saved_l": last_next_lap_target_l,
                    "target_met": remaining_target_l <= 1e-9,
                    "final_next_lap_selected_zone_count": _plan_summary(last_next_lap_plan)[
                        "selected_zone_count"
                    ],
                    "final_next_lap_selected_zone_ids": _plan_summary(last_next_lap_plan)[
                        "selected_zone_ids"
                    ],
                    "notes": scenario.notes,
                }
            )

    lap_summary = _frame_with_schema(lap_summary_rows, _LAP_SUMMARY_SCHEMA)
    lap_plan = _frame_with_schema(lap_plan_rows, _LAP_PLAN_SCHEMA)
    scenario_summary = _frame_with_schema(scenario_summary_rows, _SCENARIO_SUMMARY_SCHEMA)
    return lap_summary, lap_plan, scenario_summary


def simulate_experimental_lap_replanning_from_observed_executions(
    context: ExperimentalLapReplannerContext,
    live_cue_executions: pl.DataFrame,
    *,
    config: ExperimentalLapReplannerConfig,
    scenario_prefix: str = "observed_execution",
    lap_context_frame: pl.DataFrame | None = None,
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    """Replan lap by lap from observed planned-vs-executed logs."""

    if live_cue_executions.is_empty():
        return (
            pl.DataFrame(schema=_LAP_SUMMARY_SCHEMA),
            pl.DataFrame(schema=_LAP_PLAN_SCHEMA),
            pl.DataFrame(schema=_SCENARIO_SUMMARY_SCHEMA),
        )

    lap_summary_rows: list[dict[str, object]] = []
    lap_plan_rows: list[dict[str, object]] = []
    scenario_summary_rows: list[dict[str, object]] = []

    lap_context_map = _lap_context_map(lap_context_frame)
    for scenario_id, scenario_notes, scenario_frame in _observed_execution_scenarios(
        live_cue_executions,
        scenario_prefix=scenario_prefix,
    ):
        lap_numbers = (
            scenario_frame.select("lap_number")
            .unique()
            .sort("lap_number")["lap_number"]
            .to_list()
        )
        total_laps = len(lap_numbers)
        if total_laps == 0:
            continue

        for planning_mode in config.planning_modes:
            remaining_target_l = config.target_fuel_saved_per_lap_l * float(total_laps)
            cumulative_fuel_saved_l = 0.0
            cumulative_time_lost_s = 0.0
            last_next_lap_target_l = 0.0
            last_next_lap_plan = pl.DataFrame()
            execution_history: list[dict[str, float]] = []
            zone_execution_history: list[dict[str, object]] = []

            for lap_index, lap_number in enumerate(lap_numbers, start=1):
                laps_remaining = total_laps - lap_index + 1
                lap_target_fuel_saved_l = max(0.0, remaining_target_l / laps_remaining)
                lap_context = lap_context_map.get(
                    (scenario_id, int(lap_number)),
                    _empty_lap_context(),
                )
                driver_execution_scales = _driver_execution_scales(
                    execution_history,
                    config=config,
                    planning_mode=planning_mode,
                )
                driver_zone_execution_scales = _driver_zone_execution_scales(
                    zone_execution_history,
                    driver_execution_scales=driver_execution_scales,
                    config=config,
                    planning_mode=planning_mode,
                )
                current_plan = _planned_lap_plan(
                    context,
                    planning_mode=planning_mode,
                    target_fuel_saved_per_lap_l=lap_target_fuel_saved_l,
                    config=config,
                    lap_context=lap_context,
                    driver_execution_scales=driver_execution_scales,
                    driver_zone_execution_scales=driver_zone_execution_scales,
                )
                current_plan_summary = _plan_summary(current_plan)
                lap_execution_frame = scenario_frame.filter(pl.col("lap_number") == lap_number)
                actual_zone_rows, actual_fuel_saved_l, actual_time_lost_s = (
                    _observed_lap_actuals(current_plan, lap_execution_frame)
                )
                execution_quality = _joined_unique_strings(
                    lap_execution_frame["execution_quality"].to_list(),
                    default="observed_execution",
                )
                notes = _joined_unique_strings(
                    lap_execution_frame["notes"].to_list(),
                    default=scenario_notes,
                )
                cumulative_fuel_saved_l += actual_fuel_saved_l
                cumulative_time_lost_s += actual_time_lost_s
                execution_history.append(
                    {
                        "planned_fuel_saved_l": current_plan_summary["total_fuel_saved_l"],
                        "planned_time_lost_s": current_plan_summary["total_time_lost_s"],
                        "actual_fuel_saved_l": actual_fuel_saved_l,
                        "actual_time_lost_s": actual_time_lost_s,
                    }
                )
                zone_execution_history.extend(
                    _zone_execution_history_rows(
                        current_plan,
                        actual_zone_rows=actual_zone_rows,
                        lap_number=int(lap_number),
                    )
                )
                remaining_target_after_l = remaining_target_l - actual_fuel_saved_l
                laps_after = total_laps - lap_index
                next_lap_target_l = (
                    max(0.0, remaining_target_after_l / laps_after) if laps_after > 0 else 0.0
                )
                next_driver_execution_scales = _driver_execution_scales(
                    execution_history,
                    config=config,
                    planning_mode=planning_mode,
                )
                next_driver_zone_execution_scales = _driver_zone_execution_scales(
                    zone_execution_history,
                    driver_execution_scales=next_driver_execution_scales,
                    config=config,
                    planning_mode=planning_mode,
                )
                next_lap_plan = (
                    _planned_lap_plan(
                        context,
                        planning_mode=planning_mode,
                        target_fuel_saved_per_lap_l=next_lap_target_l,
                        config=config,
                        lap_context=lap_context,
                        driver_execution_scales=next_driver_execution_scales,
                        driver_zone_execution_scales=next_driver_zone_execution_scales,
                    )
                    if laps_after > 0
                    else pl.DataFrame()
                )
                next_plan_summary = _plan_summary(next_lap_plan)

                lap_summary_rows.append(
                    {
                        "scenario_id": scenario_id,
                        "variant_name": context.variant_name,
                        "planning_mode": planning_mode,
                        "lap_number": int(lap_number),
                        "total_laps": total_laps,
                        "laps_remaining": laps_remaining,
                        "fuel_target_remaining_l": remaining_target_l,
                        "lap_target_fuel_saved_l": lap_target_fuel_saved_l,
                        "planned_zone_count": current_plan_summary["selected_zone_count"],
                        "planned_zone_ids": current_plan_summary["selected_zone_ids"],
                        "planned_zone_distances": current_plan_summary["selected_zone_distances"],
                        "planned_fuel_saved_l": current_plan_summary["total_fuel_saved_l"],
                        "planned_time_lost_s": current_plan_summary["total_time_lost_s"],
                        "planned_plan_status": current_plan_summary["plan_status"],
                        "execution_quality": execution_quality,
                        "scenario_event": "observed_execution",
                        "actual_zone_count": len(actual_zone_rows),
                        "actual_zone_ids": "|".join(
                            str(row["zone_id"]) for row in actual_zone_rows
                        ),
                        "fuel_saved_this_lap_l": actual_fuel_saved_l,
                        "time_lost_this_lap_s": actual_time_lost_s,
                        "cumulative_fuel_saved_l": cumulative_fuel_saved_l,
                        "cumulative_time_lost_s": cumulative_time_lost_s,
                        "fuel_target_remaining_after_l": remaining_target_after_l,
                        "next_lap_target_fuel_saved_l": next_lap_target_l,
                        "next_lap_selected_zone_count": next_plan_summary["selected_zone_count"],
                        "next_lap_selected_zone_ids": next_plan_summary["selected_zone_ids"],
                        "next_lap_selected_zone_distances": next_plan_summary[
                            "selected_zone_distances"
                        ],
                        "next_lap_expected_fuel_saved_l": next_plan_summary["total_fuel_saved_l"],
                        "next_lap_expected_time_lost_s": next_plan_summary["total_time_lost_s"],
                        "next_lap_plan_status": next_plan_summary["plan_status"],
                        "driver_fuel_execution_scale": driver_execution_scales["fuel_scale"],
                        "driver_time_execution_scale": driver_execution_scales["time_scale"],
                        "driver_zone_execution_scale_count": len(driver_zone_execution_scales),
                        "driver_zone_execution_scale_zone_ids": _joined_unique_strings(
                            driver_zone_execution_scales.keys(),
                            default="",
                        ),
                        "next_lap_driver_fuel_execution_scale": next_driver_execution_scales[
                            "fuel_scale"
                        ],
                        "next_lap_driver_time_execution_scale": next_driver_execution_scales[
                            "time_scale"
                        ],
                        "next_lap_driver_zone_execution_scale_count": len(
                            next_driver_zone_execution_scales
                        ),
                        "next_lap_driver_zone_execution_scale_zone_ids": _joined_unique_strings(
                            next_driver_zone_execution_scales.keys(),
                            default="",
                        ),
                        **lap_context,
                        "notes": notes,
                    }
                )
                lap_plan_rows.extend(
                    _lap_plan_rows(
                        current_plan,
                        actual_zone_rows=actual_zone_rows,
                        scenario_id=scenario_id,
                        variant_name=context.variant_name,
                        planning_mode=planning_mode,
                        lap_number=int(lap_number),
                        execution_quality=execution_quality,
                        scenario_event="observed_execution",
                        notes=notes,
                        driver_execution_scales=driver_execution_scales,
                        driver_zone_execution_scales=driver_zone_execution_scales,
                    )
                )

                remaining_target_l = remaining_target_after_l
                last_next_lap_target_l = next_lap_target_l
                last_next_lap_plan = next_lap_plan

            scenario_summary_rows.append(
                {
                    "scenario_id": scenario_id,
                    "variant_name": context.variant_name,
                    "planning_mode": planning_mode,
                    "total_laps": total_laps,
                    "total_actual_fuel_saved_l": cumulative_fuel_saved_l,
                    "total_actual_time_lost_s": cumulative_time_lost_s,
                    "final_fuel_target_remaining_l": remaining_target_l,
                    "final_next_lap_target_fuel_saved_l": last_next_lap_target_l,
                    "target_met": remaining_target_l <= 1e-9,
                    "final_next_lap_selected_zone_count": _plan_summary(last_next_lap_plan)[
                        "selected_zone_count"
                    ],
                    "final_next_lap_selected_zone_ids": _plan_summary(last_next_lap_plan)[
                        "selected_zone_ids"
                    ],
                    "notes": scenario_notes,
                }
            )

    lap_summary = _frame_with_schema(lap_summary_rows, _LAP_SUMMARY_SCHEMA)
    lap_plan = _frame_with_schema(lap_plan_rows, _LAP_PLAN_SCHEMA)
    scenario_summary = _frame_with_schema(scenario_summary_rows, _SCENARIO_SUMMARY_SCHEMA)
    return lap_summary, lap_plan, scenario_summary


def build_experimental_lap_race_state_context(zone_observations: pl.DataFrame) -> pl.DataFrame:
    """Build a first lap-level race-state context from existing zone observations."""

    if zone_observations.is_empty():
        return pl.DataFrame(schema=_LAP_CONTEXT_SCHEMA)

    required = {
        "run_id",
        "lap_number",
        "fuel_start_l",
        "fuel_end_l",
        "zone_start_m",
    }
    _require_columns(zone_observations, required, "zone observations")
    scenario_key_expr = _scenario_run_key_expr()
    with_key = zone_observations.with_columns(scenario_key_expr)
    lap_context = (
        with_key.group_by(["__scenario_run_key", "run_id", "lap_number"])
        .agg(
            pl.col("fuel_start_l").max().alias("lap_fuel_start_l"),
            pl.col("fuel_end_l").min().alias("lap_fuel_end_l"),
            pl.col("stint_index").drop_nulls().first().alias("lap_stint_index"),
            pl.col("carcass_temp_zone_start_c")
            .sort_by("zone_start_m")
            .drop_nulls()
            .first()
            .alias("lap_start_carcass_temp_c"),
            pl.col("carcass_temp_zone_start_delta_vs_baseline_c")
            .sort_by("zone_start_m")
            .drop_nulls()
            .first()
            .alias("lap_start_carcass_temp_delta_vs_baseline_c"),
            pl.col("carcass_temp_zone_start_delta_vs_baseline_c")
            .drop_nulls()
            .mean()
            .alias("lap_mean_carcass_temp_delta_vs_baseline_c"),
        )
        .sort(["run_id", "lap_number"])
        .with_columns(
            (pl.col("lap_fuel_start_l") - pl.col("lap_fuel_end_l")).alias("lap_fuel_used_total_l"),
            pl.int_range(1, pl.len() + 1).over("run_id").alias("lap_index_in_run"),
            pl.len().over("run_id").alias("total_laps_in_run"),
        )
    )

    fuel_bounds = lap_context.group_by("run_id").agg(
        pl.col("lap_fuel_start_l").max().alias("__run_max_fuel_start_l"),
        pl.col("lap_fuel_start_l").min().alias("__run_min_fuel_start_l"),
    )
    enriched = lap_context.join(fuel_bounds, on="run_id", how="left").with_columns(
        pl.when(
            (pl.col("__run_max_fuel_start_l") - pl.col("__run_min_fuel_start_l")).abs() <= 1e-9
        )
        .then(None)
        .otherwise(
            (
                pl.col("lap_fuel_start_l") - pl.col("__run_min_fuel_start_l")
            ) / (pl.col("__run_max_fuel_start_l") - pl.col("__run_min_fuel_start_l"))
        )
        .alias("fuel_load_ratio"),
    )
    enriched = enriched.with_columns(
        _fuel_load_band_expr(),
        _tire_regime_label_expr(),
        (pl.lit("observed_execution:") + pl.col("__scenario_run_key")).alias("scenario_id"),
    )
    return (
        enriched.with_columns(
            (
                pl.col("fuel_load_band")
                + pl.lit("|")
                + pl.col("tire_regime_label")
                + pl.lit("|stint_")
                + pl.col("lap_stint_index").fill_null(-1).cast(pl.Int64).cast(pl.String)
            ).alias("lap_context_label")
        )
        .drop("__run_max_fuel_start_l", "__run_min_fuel_start_l", "__scenario_run_key")
        .select(list(_LAP_CONTEXT_SCHEMA.keys()))
        .sort(["scenario_id", "lap_number"])
    )


def _planned_lap_plan(
    context: ExperimentalLapReplannerContext,
    *,
    planning_mode: str,
    target_fuel_saved_per_lap_l: float,
    config: ExperimentalLapReplannerConfig,
    lap_context: dict[str, object] | None = None,
    driver_execution_scales: dict[str, float] | None = None,
    driver_zone_execution_scales: dict[str, dict[str, float]] | None = None,
) -> pl.DataFrame:
    if planning_mode == "static":
        conditioned_static_plan = _apply_fuel_load_conditioning_to_plan(
            context.static_plan,
            config=config,
            lap_context=lap_context,
        )
        return _static_plan_for_target(conditioned_static_plan, target_fuel_saved_per_lap_l)
    if planning_mode == "adaptive":
        conditioned_zone_models = _apply_fuel_load_conditioning_to_zone_models(
            context.robust_zone_models,
            config=config,
            lap_context=lap_context,
        )
        conditioned_zone_models = _apply_driver_execution_calibration_to_zone_models(
            conditioned_zone_models,
            driver_execution_scales=driver_execution_scales,
            driver_zone_execution_scales=driver_zone_execution_scales,
        )
        return build_experimental_range_aware_plan(
            conditioned_zone_models,
            context.robust_ranges,
            target_fuel_saved_per_lap_l=target_fuel_saved_per_lap_l,
            zone_priors=context.zone_priors,
            allowed_model_statuses=config.allowed_model_statuses,
            top_up_scope=context.adaptive_scope,
        )
    raise ValueError(f"Unsupported planning mode: {planning_mode}")


def _static_plan_for_target(
    static_plan: pl.DataFrame,
    target_fuel_saved_per_lap_l: float,
) -> pl.DataFrame:
    if static_plan.is_empty():
        return pl.DataFrame()
    total_fuel_saved_l = float(static_plan["predicted_fuel_saved_l"].sum())
    plan_status = "target_met" if total_fuel_saved_l + 1e-12 >= target_fuel_saved_per_lap_l else "target_unreachable"
    return static_plan.with_columns(
        pl.lit(target_fuel_saved_per_lap_l).alias("target_fuel_saved_per_lap_l"),
        pl.lit(total_fuel_saved_l).alias("total_predicted_fuel_saved_l"),
        pl.lit(float(static_plan["predicted_time_lost_s"].sum())).alias(
            "total_predicted_time_lost_s"
        ),
        pl.lit(float(static_plan["predicted_time_lost_s"].sum())).alias(
            "total_optimization_time_lost_s"
        ),
        pl.lit(total_fuel_saved_l - target_fuel_saved_per_lap_l).alias("fuel_surplus_l"),
        pl.lit(plan_status).alias("plan_status"),
    )


def _apply_fuel_load_conditioning_to_plan(
    plan: pl.DataFrame,
    *,
    config: ExperimentalLapReplannerConfig,
    lap_context: dict[str, object] | None,
) -> pl.DataFrame:
    return _apply_fuel_load_time_conditioning(
        plan,
        config=config,
        lap_context=lap_context,
        distance_column="selected_lico_distance_m",
        time_column="predicted_time_lost_s",
        fuel_column="predicted_fuel_saved_l",
        ratio_column=None,
        range_start_column="recommended_range_start_m",
        range_end_column="recommended_range_end_m",
    )


def _apply_fuel_load_conditioning_to_zone_models(
    zone_models: pl.DataFrame,
    *,
    config: ExperimentalLapReplannerConfig,
    lap_context: dict[str, object] | None,
) -> pl.DataFrame:
    return _apply_fuel_load_time_conditioning(
        zone_models,
        config=config,
        lap_context=lap_context,
        distance_column="lico_distance_m",
        time_column="robust_predicted_time_lost_s",
        fuel_column="robust_predicted_fuel_saved_l",
        ratio_column="robust_predicted_fuel_saved_per_second_lps",
    )


def _apply_driver_execution_calibration_to_zone_models(
    zone_models: pl.DataFrame,
    *,
    driver_execution_scales: dict[str, float] | None,
    driver_zone_execution_scales: dict[str, dict[str, float]] | None = None,
) -> pl.DataFrame:
    if zone_models.is_empty() or driver_execution_scales is None:
        return zone_models

    default_fuel_scale = float(driver_execution_scales.get("fuel_scale", 1.0))
    default_time_scale = float(driver_execution_scales.get("time_scale", 1.0))
    if (
        abs(default_fuel_scale - 1.0) <= 1e-12
        and abs(default_time_scale - 1.0) <= 1e-12
        and not driver_zone_execution_scales
    ):
        return zone_models

    conditioned_rows: list[dict[str, object]] = []
    for row in zone_models.iter_rows(named=True):
        zone_id = str(row.get("zone_id") or "")
        zone_scales = (driver_zone_execution_scales or {}).get(zone_id, {})
        fuel_scale = float(zone_scales.get("fuel_scale", default_fuel_scale))
        time_scale = float(zone_scales.get("time_scale", default_time_scale))
        conditioned_fuel_saved_l = (
            (_optional_float(row.get("robust_predicted_fuel_saved_l")) or 0.0) * fuel_scale
        )
        conditioned_time_lost_s = (
            (_optional_float(row.get("robust_predicted_time_lost_s")) or 0.0) * time_scale
        )
        conditioned_row = dict(row)
        conditioned_row["robust_predicted_fuel_saved_l"] = conditioned_fuel_saved_l
        conditioned_row["robust_predicted_time_lost_s"] = conditioned_time_lost_s
        conditioned_row["robust_predicted_fuel_saved_per_second_lps"] = (
            conditioned_fuel_saved_l / conditioned_time_lost_s
            if conditioned_time_lost_s > 1e-12
            else None
        )
        conditioned_rows.append(conditioned_row)

    return pl.DataFrame(
        conditioned_rows,
        schema=zone_models.schema,
        strict=False,
    ).select(zone_models.columns)


def _apply_fuel_load_time_conditioning(
    frame: pl.DataFrame,
    *,
    config: ExperimentalLapReplannerConfig,
    lap_context: dict[str, object] | None,
    distance_column: str,
    time_column: str,
    fuel_column: str,
    ratio_column: str | None,
    range_start_column: str | None = None,
    range_end_column: str | None = None,
) -> pl.DataFrame:
    if (
        frame.is_empty()
        or not config.fuel_load_conditioning_enabled
        or time_column not in frame.columns
        or fuel_column not in frame.columns
        or distance_column not in frame.columns
    ):
        return frame

    slope = _fuel_load_time_slope(config, lap_context)
    if abs(slope) <= 1e-12:
        return frame

    distance_bounds = _conditioning_distance_bounds(
        frame,
        distance_column=distance_column,
        range_start_column=range_start_column,
        range_end_column=range_end_column,
    )
    conditioned_rows: list[dict[str, object]] = []
    for row in frame.iter_rows(named=True):
        zone_id = str(row.get("zone_id") or "")
        distance_value = _optional_float(row.get(distance_column)) or 0.0
        start_m, end_m = distance_bounds.get(zone_id, (distance_value, distance_value))
        normalized_distance = _normalized_conditioning_distance(
            distance_value,
            start_m,
            end_m,
        )
        multiplier = min(
            config.max_time_conditioning_multiplier,
            max(
                config.min_time_conditioning_multiplier,
                1.0 + (slope * normalized_distance),
            ),
        )
        conditioned_time_lost_s = (
            (_optional_float(row.get(time_column)) or 0.0) * multiplier
        )
        conditioned_row = dict(row)
        conditioned_row[time_column] = conditioned_time_lost_s
        if ratio_column is not None and ratio_column in frame.columns:
            fuel_saved_l = _optional_float(row.get(fuel_column)) or 0.0
            conditioned_row[ratio_column] = (
                fuel_saved_l / conditioned_time_lost_s
                if conditioned_time_lost_s > 1e-12
                else None
            )
        conditioned_rows.append(conditioned_row)

    return pl.DataFrame(
        conditioned_rows,
        schema=frame.schema,
        strict=False,
    ).select(frame.columns)


def _conditioning_distance_bounds(
    frame: pl.DataFrame,
    *,
    distance_column: str,
    range_start_column: str | None,
    range_end_column: str | None,
) -> dict[str, tuple[float, float]]:
    bounds: dict[str, tuple[float, float]] = {}
    for row in frame.iter_rows(named=True):
        zone_id = str(row.get("zone_id") or "")
        distance_value = _optional_float(row.get(distance_column)) or 0.0
        start_m = (
            _optional_float(row.get(range_start_column))
            if range_start_column is not None and range_start_column in frame.columns
            else None
        )
        end_m = (
            _optional_float(row.get(range_end_column))
            if range_end_column is not None and range_end_column in frame.columns
            else None
        )
        if start_m is not None and end_m is not None:
            current_start_m, current_end_m = bounds.get(zone_id, (start_m, end_m))
            bounds[zone_id] = (min(current_start_m, start_m), max(current_end_m, end_m))
            continue

        current_start_m, current_end_m = bounds.get(zone_id, (distance_value, distance_value))
        bounds[zone_id] = (
            min(current_start_m, distance_value),
            max(current_end_m, distance_value),
        )
    return bounds


def _normalized_conditioning_distance(
    distance_value: float,
    start_m: float,
    end_m: float,
) -> float:
    width_m = end_m - start_m
    if width_m <= 1e-9:
        return 1.0 if distance_value > 0.0 else 0.0
    normalized = (distance_value - start_m) / width_m
    return max(0.0, min(1.0, normalized))


def _fuel_load_time_slope(
    config: ExperimentalLapReplannerConfig,
    lap_context: dict[str, object] | None,
) -> float:
    fuel_load_band = str((lap_context or {}).get("fuel_load_band") or "").strip().lower()
    if fuel_load_band == "heavy":
        return config.heavy_fuel_load_time_slope
    if fuel_load_band == "light":
        return config.light_fuel_load_time_slope
    return config.medium_fuel_load_time_slope


def _driver_execution_scales(
    execution_history: list[dict[str, float]],
    *,
    config: ExperimentalLapReplannerConfig,
    planning_mode: str,
) -> dict[str, float]:
    if not config.execution_calibration_enabled or planning_mode != "adaptive":
        return {"fuel_scale": 1.0, "time_scale": 1.0}
    if not execution_history:
        return {"fuel_scale": 1.0, "time_scale": 1.0}

    history_window = (
        execution_history[-config.execution_calibration_window_laps :]
        if config.execution_calibration_window_laps > 0
        else execution_history
    )
    planned_fuel_total = sum(max(0.0, row["planned_fuel_saved_l"]) for row in history_window)
    actual_fuel_total = sum(max(0.0, row["actual_fuel_saved_l"]) for row in history_window)
    planned_time_total = sum(max(0.0, row["planned_time_lost_s"]) for row in history_window)
    actual_time_total = sum(max(0.0, row["actual_time_lost_s"]) for row in history_window)

    fuel_scale = 1.0
    time_scale = 1.0
    if planned_fuel_total > 1e-12:
        fuel_scale = actual_fuel_total / planned_fuel_total
        fuel_scale = min(
            config.max_driver_fuel_execution_scale,
            max(config.min_driver_fuel_execution_scale, fuel_scale),
        )
    if planned_time_total > 1e-12:
        time_scale = actual_time_total / planned_time_total
        time_scale = min(
            config.max_driver_time_execution_scale,
            max(config.min_driver_time_execution_scale, time_scale),
        )
    return {
        "fuel_scale": fuel_scale,
        "time_scale": time_scale,
    }


def _driver_zone_execution_scales(
    zone_execution_history: list[dict[str, object]],
    *,
    driver_execution_scales: dict[str, float],
    config: ExperimentalLapReplannerConfig,
    planning_mode: str,
) -> dict[str, dict[str, float]]:
    if not config.zone_execution_calibration_enabled or planning_mode != "adaptive":
        return {}
    if not zone_execution_history:
        return {}

    latest_lap_number = max(int(row["lap_number"]) for row in zone_execution_history)
    if config.execution_calibration_window_laps > 0:
        min_lap_number = latest_lap_number - config.execution_calibration_window_laps + 1
        history_window = [
            row
            for row in zone_execution_history
            if int(row["lap_number"]) >= min_lap_number
        ]
    else:
        history_window = zone_execution_history

    global_fuel_scale = float(driver_execution_scales.get("fuel_scale", 1.0))
    global_time_scale = float(driver_execution_scales.get("time_scale", 1.0))
    full_weight_rows = max(1, int(config.zone_execution_calibration_full_weight_rows))
    zone_scales: dict[str, dict[str, float]] = {}

    history_frame = pl.DataFrame(history_window, strict=False)
    if history_frame.is_empty():
        return {}

    for row in (
        history_frame.group_by("zone_id")
        .agg(
            pl.len().alias("support_rows"),
            pl.col("planned_fuel_saved_l").sum().alias("planned_fuel_saved_l"),
            pl.col("planned_time_lost_s").sum().alias("planned_time_lost_s"),
            pl.col("actual_fuel_saved_l").sum().alias("actual_fuel_saved_l"),
            pl.col("actual_time_lost_s").sum().alias("actual_time_lost_s"),
        )
        .iter_rows(named=True)
    ):
        support_rows = int(row["support_rows"])
        blend_weight = min(1.0, support_rows / full_weight_rows)
        zone_fuel_scale = global_fuel_scale
        zone_time_scale = global_time_scale
        planned_fuel_saved_l = _optional_float(row.get("planned_fuel_saved_l")) or 0.0
        planned_time_lost_s = _optional_float(row.get("planned_time_lost_s")) or 0.0
        if planned_fuel_saved_l > 1e-12:
            raw_fuel_scale = (_optional_float(row.get("actual_fuel_saved_l")) or 0.0) / planned_fuel_saved_l
            raw_fuel_scale = min(
                config.max_driver_fuel_execution_scale,
                max(config.min_driver_fuel_execution_scale, raw_fuel_scale),
            )
            zone_fuel_scale = (
                (global_fuel_scale * (1.0 - blend_weight))
                + (raw_fuel_scale * blend_weight)
            )
        if planned_time_lost_s > 1e-12:
            raw_time_scale = (_optional_float(row.get("actual_time_lost_s")) or 0.0) / planned_time_lost_s
            raw_time_scale = min(
                config.max_driver_time_execution_scale,
                max(config.min_driver_time_execution_scale, raw_time_scale),
            )
            zone_time_scale = (
                (global_time_scale * (1.0 - blend_weight))
                + (raw_time_scale * blend_weight)
            )
        zone_scales[str(row["zone_id"])] = {
            "fuel_scale": zone_fuel_scale,
            "time_scale": zone_time_scale,
            "support_rows": float(support_rows),
        }
    return zone_scales


def _zone_execution_history_rows(
    current_plan: pl.DataFrame,
    *,
    actual_zone_rows: list[dict[str, object]],
    lap_number: int,
) -> list[dict[str, object]]:
    if current_plan.is_empty():
        return []
    actual_map = {str(row["zone_id"]): row for row in actual_zone_rows}
    rows: list[dict[str, object]] = []
    selected = current_plan.filter(pl.col("is_selected_for_lico"))
    for row in selected.iter_rows(named=True):
        zone_id = str(row["zone_id"])
        actual_row = actual_map.get(zone_id)
        rows.append(
            {
                "lap_number": int(lap_number),
                "zone_id": zone_id,
                "planned_fuel_saved_l": float(row["predicted_fuel_saved_l"]),
                "planned_time_lost_s": float(row["predicted_time_lost_s"]),
                "actual_fuel_saved_l": (
                    float(actual_row["actual_fuel_saved_l"]) if actual_row is not None else 0.0
                ),
                "actual_time_lost_s": (
                    float(actual_row["actual_time_lost_s"]) if actual_row is not None else 0.0
                ),
            }
        )
    return rows


def _execute_lap_plan(
    current_plan: pl.DataFrame,
    *,
    event: ExperimentalLapExecutionEvent,
) -> tuple[list[dict[str, object]], float, float]:
    if current_plan.is_empty() or event.force_zero_lico:
        return [], 0.0, max(0.0, event.extra_time_lost_s)

    actual_rows: list[dict[str, object]] = []
    total_fuel_saved_l = 0.0
    total_time_lost_s = float(event.extra_time_lost_s)
    selected = current_plan.filter(pl.col("is_selected_for_lico"))
    for row in selected.iter_rows(named=True):
        actual_fuel_saved_l = float(row["predicted_fuel_saved_l"]) * max(event.fuel_saved_scale, 0.0)
        actual_time_lost_s = float(row["predicted_time_lost_s"]) * max(event.time_lost_scale, 0.0)
        total_fuel_saved_l += actual_fuel_saved_l
        total_time_lost_s += actual_time_lost_s
        actual_rows.append(
            {
                "zone_id": str(row["zone_id"]),
                "display_label": str(row["display_label"]),
                "selected_lico_distance_m": float(row["selected_lico_distance_m"]),
                "expected_fuel_saved_l": float(row["predicted_fuel_saved_l"]),
                "expected_time_lost_s": float(row["predicted_time_lost_s"]),
                "actual_fuel_saved_l": actual_fuel_saved_l,
                "actual_time_lost_s": actual_time_lost_s,
                "support_score": _optional_float(row.get("support_score")),
                "recommended_range_start_m": _optional_float(row.get("recommended_range_start_m")),
                "recommended_range_end_m": _optional_float(row.get("recommended_range_end_m")),
                "source_model_status": str(row.get("model_status") or ""),
            }
        )
    return actual_rows, total_fuel_saved_l, total_time_lost_s


def _lap_plan_rows(
    current_plan: pl.DataFrame,
    *,
    actual_zone_rows: list[dict[str, object]],
    scenario_id: str,
    variant_name: str,
    planning_mode: str,
    lap_number: int,
    execution_quality: str,
    scenario_event: str,
    notes: str,
    driver_execution_scales: dict[str, float] | None = None,
    driver_zone_execution_scales: dict[str, dict[str, float]] | None = None,
) -> list[dict[str, object]]:
    if current_plan.is_empty():
        return []
    actual_map = {
        str(row["zone_id"]): row for row in actual_zone_rows
    }
    rows = []
    selected = current_plan.filter(pl.col("is_selected_for_lico"))
    for row in selected.iter_rows(named=True):
        actual_row = actual_map.get(str(row["zone_id"]))
        zone_id = str(row["zone_id"])
        zone_scales = (driver_zone_execution_scales or {}).get(zone_id, {})
        rows.append(
            {
                "scenario_id": scenario_id,
                "variant_name": variant_name,
                "planning_mode": planning_mode,
                "lap_number": lap_number,
                "zone_id": zone_id,
                "display_label": str(row["display_label"]),
                "selected_lico_distance_m": float(row["selected_lico_distance_m"]),
                "expected_fuel_saved_l": float(row["predicted_fuel_saved_l"]),
                "expected_time_lost_s": float(row["predicted_time_lost_s"]),
                "support_score": _optional_float(row.get("support_score")),
                "recommended_range_start_m": _optional_float(row.get("recommended_range_start_m")),
                "recommended_range_end_m": _optional_float(row.get("recommended_range_end_m")),
                "source_model_status": str(row.get("model_status") or ""),
                "applied_driver_fuel_execution_scale": float(
                    zone_scales.get(
                        "fuel_scale",
                        (driver_execution_scales or {}).get("fuel_scale", 1.0),
                    )
                ),
                "applied_driver_time_execution_scale": float(
                    zone_scales.get(
                        "time_scale",
                        (driver_execution_scales or {}).get("time_scale", 1.0),
                    )
                ),
                "applied_zone_execution_support_rows": int(
                    zone_scales.get("support_rows", 0.0)
                ),
                "applied_zone_specific_execution_scale": zone_id in (driver_zone_execution_scales or {}),
                "execution_quality": execution_quality,
                "scenario_event": scenario_event,
                "actual_is_executed": actual_row is not None,
                "actual_fuel_saved_l": (
                    float(actual_row["actual_fuel_saved_l"]) if actual_row is not None else 0.0
                ),
                "actual_time_lost_s": (
                    float(actual_row["actual_time_lost_s"]) if actual_row is not None else 0.0
                ),
                "notes": notes,
            }
        )
    return rows


def _plan_summary(plan: pl.DataFrame) -> dict[str, object]:
    if plan.is_empty():
        return {
            "selected_zone_count": 0,
            "selected_zone_ids": "",
            "selected_zone_distances": "",
            "total_fuel_saved_l": 0.0,
            "total_time_lost_s": 0.0,
            "plan_status": "target_met",
        }
    selected = plan.filter(pl.col("is_selected_for_lico")).sort("zone_id")
    if selected.is_empty():
        return {
            "selected_zone_count": 0,
            "selected_zone_ids": "",
            "selected_zone_distances": "",
            "total_fuel_saved_l": 0.0,
            "total_time_lost_s": 0.0,
            "plan_status": str(plan["plan_status"][0]),
        }
    return {
        "selected_zone_count": int(selected.height),
        "selected_zone_ids": "|".join(str(zone_id) for zone_id in selected["zone_id"].to_list()),
        "selected_zone_distances": "|".join(
            f"{str(row['zone_id'])}={float(row['selected_lico_distance_m']):.3f}"
            for row in selected.iter_rows(named=True)
        ),
        "total_fuel_saved_l": float(selected["predicted_fuel_saved_l"].sum()),
        "total_time_lost_s": float(selected["predicted_time_lost_s"].sum()),
        "plan_status": str(plan["plan_status"][0]),
    }


def _observed_execution_scenarios(
    live_cue_executions: pl.DataFrame,
    *,
    scenario_prefix: str,
) -> list[tuple[str, str, pl.DataFrame]]:
    run_key_expr = _scenario_run_key_expr()
    keyed = live_cue_executions.with_columns(run_key_expr)
    scenarios: list[tuple[str, str, pl.DataFrame]] = []
    for run_key in keyed.select("__scenario_run_key").unique().sort("__scenario_run_key")[
        "__scenario_run_key"
    ].to_list():
        scenario_frame = keyed.filter(pl.col("__scenario_run_key") == run_key).drop(
            "__scenario_run_key"
        )
        file_names = _joined_unique_strings(
            scenario_frame["file_name"].to_list(),
            default="",
        )
        notes = f"Observed execution log for {run_key}"
        if file_names and file_names != run_key:
            notes = f"{notes} ({file_names})"
        scenarios.append((f"{scenario_prefix}:{run_key}", notes, scenario_frame))
    return scenarios


def _observed_lap_actuals(
    current_plan: pl.DataFrame,
    lap_execution_frame: pl.DataFrame,
) -> tuple[list[dict[str, object]], float, float]:
    if lap_execution_frame.is_empty():
        return [], 0.0, 0.0

    plan_row_map = {
        str(row["zone_id"]): row
        for row in current_plan.filter(pl.col("is_selected_for_lico")).iter_rows(named=True)
    }
    actual_rows: list[dict[str, object]] = []
    total_fuel_saved_l = 0.0
    total_time_lost_s = 0.0

    for row in lap_execution_frame.iter_rows(named=True):
        actual_fuel_saved_l = _optional_float(row.get("fuel_saved_vs_baseline_l")) or 0.0
        actual_time_lost_s = _optional_float(row.get("time_lost_vs_baseline_s")) or 0.0
        total_fuel_saved_l += actual_fuel_saved_l
        total_time_lost_s += actual_time_lost_s
        actual_lift_start_m = row.get("actual_lift_start_m")
        zone_id = str(row["zone_id"])
        if actual_lift_start_m is None:
            continue
        plan_row = plan_row_map.get(zone_id, {})
        actual_rows.append(
            {
                "zone_id": zone_id,
                "display_label": str(plan_row.get("display_label") or zone_id),
                "selected_lico_distance_m": _optional_float(
                    plan_row.get("selected_lico_distance_m")
                    if plan_row
                    else row.get("actual_lift_distance_before_brake_m")
                )
                or 0.0,
                "expected_fuel_saved_l": _optional_float(
                    plan_row.get("predicted_fuel_saved_l")
                )
                or 0.0,
                "expected_time_lost_s": _optional_float(
                    plan_row.get("predicted_time_lost_s")
                )
                or 0.0,
                "actual_fuel_saved_l": actual_fuel_saved_l,
                "actual_time_lost_s": actual_time_lost_s,
                "support_score": _optional_float(plan_row.get("support_score")),
                "recommended_range_start_m": _optional_float(
                    plan_row.get("recommended_range_start_m")
                ),
                "recommended_range_end_m": _optional_float(
                    plan_row.get("recommended_range_end_m")
                ),
                "source_model_status": str(plan_row.get("model_status") or ""),
            }
        )
    return actual_rows, total_fuel_saved_l, total_time_lost_s


def _lap_context_map(
    lap_context_frame: pl.DataFrame | None,
) -> dict[tuple[str, int], dict[str, object]]:
    if lap_context_frame is None or lap_context_frame.is_empty():
        return {}
    return {
        (str(row["scenario_id"]), int(row["lap_number"])): {
            "lap_index_in_run": int(row["lap_index_in_run"]),
            "lap_fuel_start_l": _optional_float(row.get("lap_fuel_start_l")),
            "lap_fuel_end_l": _optional_float(row.get("lap_fuel_end_l")),
            "lap_fuel_used_total_l": _optional_float(row.get("lap_fuel_used_total_l")),
            "fuel_load_ratio": _optional_float(row.get("fuel_load_ratio")),
            "fuel_load_band": str(row.get("fuel_load_band") or ""),
            "lap_stint_index": (
                int(row["lap_stint_index"]) if row.get("lap_stint_index") is not None else None
            ),
            "tire_regime_label": str(row.get("tire_regime_label") or ""),
            "lap_start_carcass_temp_c": _optional_float(row.get("lap_start_carcass_temp_c")),
            "lap_mean_carcass_temp_delta_vs_baseline_c": _optional_float(
                row.get("lap_mean_carcass_temp_delta_vs_baseline_c")
            ),
            "lap_context_label": str(row.get("lap_context_label") or ""),
        }
        for row in lap_context_frame.iter_rows(named=True)
    }


def _empty_lap_context() -> dict[str, object]:
    return {
        "lap_index_in_run": None,
        "lap_fuel_start_l": None,
        "lap_fuel_end_l": None,
        "lap_fuel_used_total_l": None,
        "fuel_load_ratio": None,
        "fuel_load_band": "",
        "lap_stint_index": None,
        "tire_regime_label": "",
        "lap_start_carcass_temp_c": None,
        "lap_mean_carcass_temp_delta_vs_baseline_c": None,
        "lap_context_label": "",
    }


def _scenario_run_key_expr() -> pl.Expr:
    return (
        pl.when(pl.col("run_id").is_not_null() & (pl.col("run_id").str.len_chars() > 0))
        .then(pl.col("run_id"))
        .when(pl.col("file_name").is_not_null() & (pl.col("file_name").str.len_chars() > 0))
        .then(pl.col("file_name"))
        .otherwise(pl.lit("unknown_run"))
        .alias("__scenario_run_key")
    )


def _fuel_load_band_expr() -> pl.Expr:
    return (
        pl.when(pl.col("fuel_load_ratio").is_null())
        .then(pl.lit("unknown"))
        .when(pl.col("fuel_load_ratio") >= (2.0 / 3.0))
        .then(pl.lit("heavy"))
        .when(pl.col("fuel_load_ratio") >= (1.0 / 3.0))
        .then(pl.lit("medium"))
        .otherwise(pl.lit("light"))
        .alias("fuel_load_band")
    )


def _tire_regime_label_expr() -> pl.Expr:
    return (
        pl.when(
            pl.col("lap_start_carcass_temp_c").is_not_null()
            & (pl.col("lap_start_carcass_temp_c") < 35.0)
        )
        .then(pl.lit("pit_out_cold"))
        .when(
            pl.col("lap_mean_carcass_temp_delta_vs_baseline_c").is_not_null()
            & (pl.col("lap_mean_carcass_temp_delta_vs_baseline_c") <= -3.0)
        )
        .then(pl.lit("cooler_than_baseline"))
        .when(
            pl.col("lap_mean_carcass_temp_delta_vs_baseline_c").is_not_null()
            & (pl.col("lap_mean_carcass_temp_delta_vs_baseline_c") >= 3.0)
        )
        .then(pl.lit("hotter_than_baseline"))
        .otherwise(pl.lit("baseline_like"))
        .alias("tire_regime_label")
    )


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    return float(value)


def _joined_unique_strings(values: list[object], *, default: str) -> str:
    cleaned = sorted(
        {
            str(value).strip()
            for value in values
            if value is not None and str(value).strip()
        }
    )
    if not cleaned:
        return default
    return "|".join(cleaned)


def _frame_with_schema(
    rows: list[dict[str, object]],
    schema: dict[str, pl.DataType],
) -> pl.DataFrame:
    if not rows:
        return pl.DataFrame(schema=schema)
    columns = list(schema.keys())
    return pl.DataFrame(rows, schema=schema, strict=False).select(columns)


def summarize_experimental_race_state_context_effects(
    lap_summary: pl.DataFrame,
) -> pl.DataFrame:
    """Summarize observed replanning behavior by fuel-load and tire regime context."""

    if lap_summary.is_empty():
        return pl.DataFrame(schema=_RACE_STATE_CONTEXT_EFFECTS_SCHEMA)

    required = {
        "variant_name",
        "planning_mode",
        "fuel_load_band",
        "tire_regime_label",
        "planned_time_lost_s",
        "time_lost_this_lap_s",
        "planned_fuel_saved_l",
        "fuel_saved_this_lap_l",
        "next_lap_expected_time_lost_s",
        "next_lap_expected_fuel_saved_l",
    }
    _require_columns(lap_summary, required, "lap summary")
    return (
        lap_summary.group_by(
            [
                "variant_name",
                "planning_mode",
                "fuel_load_band",
                "tire_regime_label",
            ]
        )
        .agg(
            pl.len().alias("lap_count"),
            pl.col("planned_time_lost_s").mean().alias("mean_planned_time_lost_s"),
            pl.col("time_lost_this_lap_s").mean().alias("mean_actual_time_lost_s"),
            (
                pl.col("time_lost_this_lap_s") - pl.col("planned_time_lost_s")
            )
            .mean()
            .alias("mean_time_residual_s"),
            pl.col("planned_fuel_saved_l").mean().alias("mean_planned_fuel_saved_l"),
            pl.col("fuel_saved_this_lap_l").mean().alias("mean_actual_fuel_saved_l"),
            (
                pl.col("fuel_saved_this_lap_l") - pl.col("planned_fuel_saved_l")
            )
            .mean()
            .alias("mean_fuel_residual_l"),
            pl.col("next_lap_expected_time_lost_s")
            .mean()
            .alias("mean_next_lap_expected_time_lost_s"),
            pl.col("next_lap_expected_fuel_saved_l")
            .mean()
            .alias("mean_next_lap_expected_fuel_saved_l"),
        )
        .sort(
            [
                "variant_name",
                "planning_mode",
                "fuel_load_band",
                "tire_regime_label",
            ]
        )
        .select(list(_RACE_STATE_CONTEXT_EFFECTS_SCHEMA.keys()))
    )


def summarize_experimental_zone_execution_calibration(
    lap_summary: pl.DataFrame,
    lap_plan: pl.DataFrame,
) -> pl.DataFrame:
    """Summarize how zone-specific execution memory adjusts the adaptive plan."""

    if lap_summary.is_empty() or lap_plan.is_empty():
        return pl.DataFrame(schema=_ZONE_EXECUTION_CALIBRATION_SUMMARY_SCHEMA)

    _require_columns(
        lap_summary,
        {
            "scenario_id",
            "variant_name",
            "planning_mode",
            "lap_number",
            "driver_fuel_execution_scale",
            "driver_time_execution_scale",
        },
        "lap summary",
    )
    _require_columns(
        lap_plan,
        {
            "scenario_id",
            "variant_name",
            "planning_mode",
            "lap_number",
            "zone_id",
            "display_label",
            "source_model_status",
            "applied_driver_fuel_execution_scale",
            "applied_driver_time_execution_scale",
            "applied_zone_execution_support_rows",
            "applied_zone_specific_execution_scale",
            "actual_is_executed",
        },
        "lap plan",
    )

    joined = lap_plan.join(
        lap_summary.select(
            [
                "scenario_id",
                "variant_name",
                "planning_mode",
                "lap_number",
                "driver_fuel_execution_scale",
                "driver_time_execution_scale",
            ]
        ),
        on=["scenario_id", "variant_name", "planning_mode", "lap_number"],
        how="left",
    ).with_columns(
        (
            pl.col("applied_driver_fuel_execution_scale")
            - pl.col("driver_fuel_execution_scale")
        ).alias("fuel_scale_delta_vs_global"),
        (
            pl.col("applied_driver_time_execution_scale")
            - pl.col("driver_time_execution_scale")
        ).alias("time_scale_delta_vs_global"),
        pl.col("applied_zone_specific_execution_scale")
        .cast(pl.Float64)
        .alias("zone_specific_usage_rate"),
        pl.col("actual_is_executed").cast(pl.Float64).alias("execution_rate"),
    )

    return (
        joined.group_by(
            [
                "variant_name",
                "planning_mode",
                "zone_id",
                "display_label",
                "source_model_status",
            ]
        )
        .agg(
            pl.len().alias("sample_count"),
            pl.col("zone_specific_usage_rate").mean().alias("zone_specific_usage_rate"),
            pl.col("execution_rate").mean().alias("execution_rate"),
            pl.col("applied_driver_fuel_execution_scale")
            .mean()
            .alias("mean_applied_fuel_scale"),
            pl.col("driver_fuel_execution_scale").mean().alias("mean_global_fuel_scale"),
            pl.col("fuel_scale_delta_vs_global")
            .mean()
            .alias("mean_fuel_scale_delta_vs_global"),
            pl.col("applied_driver_time_execution_scale")
            .mean()
            .alias("mean_applied_time_scale"),
            pl.col("driver_time_execution_scale").mean().alias("mean_global_time_scale"),
            pl.col("time_scale_delta_vs_global")
            .mean()
            .alias("mean_time_scale_delta_vs_global"),
            (pl.col("fuel_scale_delta_vs_global") < -0.02)
            .cast(pl.Int64)
            .sum()
            .alias("penalized_fuel_count"),
            (pl.col("fuel_scale_delta_vs_global") > 0.02)
            .cast(pl.Int64)
            .sum()
            .alias("relieved_fuel_count"),
            (pl.col("time_scale_delta_vs_global") < -0.02)
            .cast(pl.Int64)
            .sum()
            .alias("penalized_time_count"),
            (pl.col("time_scale_delta_vs_global") > 0.02)
            .cast(pl.Int64)
            .sum()
            .alias("relieved_time_count"),
            pl.col("applied_zone_execution_support_rows")
            .mean()
            .alias("mean_support_rows"),
        )
        .sort(["variant_name", "planning_mode", "zone_id"])
        .select(list(_ZONE_EXECUTION_CALIBRATION_SUMMARY_SCHEMA.keys()))
    )


def build_experimental_live_transition_preview(
    lap_summary: pl.DataFrame,
    lap_plan: pl.DataFrame,
) -> pl.DataFrame:
    """Build a next-lap handoff preview from observed or simulated replanning logs."""

    if lap_summary.is_empty() or lap_plan.is_empty():
        return pl.DataFrame(schema=_LIVE_TRANSITION_PREVIEW_SCHEMA)

    _require_columns(
        lap_summary,
        {
            "scenario_id",
            "variant_name",
            "planning_mode",
            "lap_number",
            "total_laps",
            "scenario_event",
            "execution_quality",
            "notes",
            "next_lap_target_fuel_saved_l",
            "next_lap_expected_fuel_saved_l",
            "next_lap_expected_time_lost_s",
            "next_lap_selected_zone_count",
            "next_lap_selected_zone_ids",
            "next_lap_driver_fuel_execution_scale",
            "next_lap_driver_time_execution_scale",
            "next_lap_driver_zone_execution_scale_count",
        },
        "lap summary",
    )
    _require_columns(
        lap_plan,
        {
            "scenario_id",
            "variant_name",
            "planning_mode",
            "lap_number",
            "zone_id",
            "display_label",
            "selected_lico_distance_m",
            "expected_fuel_saved_l",
            "expected_time_lost_s",
            "source_model_status",
            "recommended_range_start_m",
            "recommended_range_end_m",
            "applied_driver_fuel_execution_scale",
            "applied_driver_time_execution_scale",
            "applied_zone_execution_support_rows",
            "applied_zone_specific_execution_scale",
        },
        "lap plan",
    )

    next_plan = lap_plan.rename(
        {
            "lap_number": "next_lap_number",
            "zone_id": "next_zone_id",
            "display_label": "next_display_label",
            "selected_lico_distance_m": "next_selected_lico_distance_m",
            "expected_fuel_saved_l": "next_expected_fuel_saved_by_zone_l",
            "expected_time_lost_s": "next_expected_time_lost_by_zone_s",
            "source_model_status": "next_source_model_status",
            "recommended_range_start_m": "next_recommended_range_start_m",
            "recommended_range_end_m": "next_recommended_range_end_m",
            "applied_driver_fuel_execution_scale": "next_applied_driver_fuel_execution_scale",
            "applied_driver_time_execution_scale": "next_applied_driver_time_execution_scale",
            "applied_zone_execution_support_rows": "next_applied_zone_execution_support_rows",
            "applied_zone_specific_execution_scale": "next_applied_zone_specific_execution_scale",
        }
    )
    current_summary = (
        lap_summary.sort(
            ["scenario_id", "variant_name", "planning_mode", "lap_number"]
        )
        .with_columns(
            pl.col("lap_number")
            .shift(-1)
            .over(["scenario_id", "variant_name", "planning_mode"])
            .alias("next_lap_number")
        )
        .filter(pl.col("next_lap_number").is_not_null())
        .rename(
            {
                "lap_number": "current_lap_number",
                "scenario_event": "current_scenario_event",
                "execution_quality": "current_execution_quality",
                "notes": "current_notes",
            }
        )
    )
    preview = current_summary.join(
        next_plan,
        on=["scenario_id", "variant_name", "planning_mode", "next_lap_number"],
        how="left",
    )
    if preview.is_empty():
        return pl.DataFrame(schema=_LIVE_TRANSITION_PREVIEW_SCHEMA)
    missing_columns = [
        column_name
        for column_name in _LIVE_TRANSITION_PREVIEW_SCHEMA
        if column_name not in preview.columns
    ]
    if missing_columns:
        preview = preview.with_columns(
            [pl.lit(None).alias(column_name) for column_name in missing_columns]
        )
    return preview.select(list(_LIVE_TRANSITION_PREVIEW_SCHEMA.keys())).sort(
        ["variant_name", "scenario_id", "current_lap_number", "next_zone_id"]
    )


def build_experimental_shadow_adaptive_transition_comparison(
    live_transition_preview: pl.DataFrame,
) -> pl.DataFrame:
    """Compare static next-lap handoffs against adaptive shadow handoffs."""

    if live_transition_preview.is_empty():
        return pl.DataFrame(schema=_SHADOW_TRANSITION_COMPARISON_SCHEMA)

    _require_columns(
        live_transition_preview,
        {
            "scenario_id",
            "variant_name",
            "planning_mode",
            "current_lap_number",
            "next_lap_number",
            "next_lap_target_fuel_saved_l",
            "next_zone_id",
            "next_display_label",
            "next_selected_lico_distance_m",
            "next_expected_fuel_saved_by_zone_l",
            "next_expected_time_lost_by_zone_s",
            "next_applied_driver_fuel_execution_scale",
            "next_applied_driver_time_execution_scale",
            "next_applied_zone_execution_support_rows",
            "next_applied_zone_specific_execution_scale",
        },
        "live transition preview",
    )

    static_rows = _shadow_transition_side(
        live_transition_preview,
        planning_mode="static",
        prefix="static",
    )
    adaptive_rows = _shadow_transition_side(
        live_transition_preview,
        planning_mode="adaptive",
        prefix="adaptive",
    )
    if static_rows.is_empty() and adaptive_rows.is_empty():
        return pl.DataFrame(schema=_SHADOW_TRANSITION_COMPARISON_SCHEMA)

    join_keys = [
        "scenario_id",
        "variant_name",
        "current_lap_number",
        "next_lap_number",
        "zone_id",
    ]
    comparison_keys = (
        pl.concat(
            [static_rows.select(join_keys), adaptive_rows.select(join_keys)],
            how="vertical_relaxed",
        )
        .unique()
        .sort(join_keys)
    )
    joined = (
        comparison_keys.join(static_rows, on=join_keys, how="left")
        .join(adaptive_rows, on=join_keys, how="left")
        .with_columns(
            pl.coalesce(
                pl.col("static_display_label"),
                pl.col("adaptive_display_label"),
            ).alias("display_label"),
            pl.coalesce(
                pl.col("adaptive_next_lap_target_fuel_saved_l"),
                pl.col("static_next_lap_target_fuel_saved_l"),
            ).alias("next_lap_target_fuel_saved_l"),
            (
                pl.col("adaptive_selected_lico_distance_m")
                - pl.col("static_selected_lico_distance_m")
            ).alias("distance_delta_m"),
            (
                pl.col("adaptive_expected_fuel_saved_l")
                - pl.col("static_expected_fuel_saved_l")
            ).alias("expected_fuel_saved_delta_l"),
            (
                pl.col("adaptive_expected_time_lost_s")
                - pl.col("static_expected_time_lost_s")
            ).alias("expected_time_lost_delta_s"),
            pl.when(
                pl.col("static_selected_lico_distance_m").is_null()
                & pl.col("adaptive_selected_lico_distance_m").is_not_null()
            )
            .then(pl.lit("added"))
            .when(
                pl.col("static_selected_lico_distance_m").is_not_null()
                & pl.col("adaptive_selected_lico_distance_m").is_null()
            )
            .then(pl.lit("removed"))
            .when(
                (
                    pl.col("adaptive_selected_lico_distance_m")
                    - pl.col("static_selected_lico_distance_m")
                )
                .abs()
                <= 1e-9
            )
            .then(pl.lit("unchanged"))
            .when(
                pl.col("adaptive_selected_lico_distance_m")
                > pl.col("static_selected_lico_distance_m")
            )
            .then(pl.lit("longer_distance"))
            .otherwise(pl.lit("shorter_distance"))
            .alias("change_type"),
        )
        .with_columns(
            pl.col("distance_delta_m").abs().alias("abs_distance_delta_m"),
            (pl.col("change_type") != "unchanged").alias("is_changed"),
            pl.lit(True).alias("shadow_mode"),
            pl.col("scenario_id").map_elements(
                _run_id_from_scenario_id,
                return_dtype=pl.String,
            ).alias("run_id"),
        )
    )
    return joined.select(list(_SHADOW_TRANSITION_COMPARISON_SCHEMA.keys())).sort(
        ["variant_name", "scenario_id", "current_lap_number", "next_lap_number", "zone_id"]
    )


def summarize_experimental_shadow_adaptive_handoffs(
    shadow_transition_comparison: pl.DataFrame,
) -> pl.DataFrame:
    """Summarize how far shadow adaptive handoffs diverge from the static baseline."""

    if shadow_transition_comparison.is_empty():
        return pl.DataFrame(schema=_SHADOW_HANDOFF_SUMMARY_SCHEMA)

    _require_columns(
        shadow_transition_comparison,
        set(_SHADOW_TRANSITION_COMPARISON_SCHEMA.keys()),
        "shadow transition comparison",
    )

    rows: list[dict[str, object]] = []
    for keys, frame in _shadow_handoff_groups(shadow_transition_comparison):
        static_zone_count = int(
            frame.filter(pl.col("static_selected_lico_distance_m").is_not_null()).height
        )
        adaptive_zone_count = int(
            frame.filter(pl.col("adaptive_selected_lico_distance_m").is_not_null()).height
        )
        changed = frame.filter(pl.col("change_type") != "unchanged")
        rows.append(
            {
                **keys,
                "shadow_mode": True,
                "next_lap_target_fuel_saved_l": _first_float(
                    frame["next_lap_target_fuel_saved_l"].to_list(),
                    default=0.0,
                ),
                "static_zone_count": static_zone_count,
                "adaptive_zone_count": adaptive_zone_count,
                "changed_zone_count": int(changed.height),
                "added_zone_count": int(frame.filter(pl.col("change_type") == "added").height),
                "removed_zone_count": int(frame.filter(pl.col("change_type") == "removed").height),
                "longer_distance_zone_count": int(
                    frame.filter(pl.col("change_type") == "longer_distance").height
                ),
                "shorter_distance_zone_count": int(
                    frame.filter(pl.col("change_type") == "shorter_distance").height
                ),
                "changed_zone_ids": _joined_unique_strings(
                    changed["zone_id"].to_list(),
                    default="",
                ),
                "mean_abs_distance_delta_m": _mean_or_none(
                    changed,
                    "abs_distance_delta_m",
                ),
                "max_abs_distance_delta_m": _max_or_none(
                    changed,
                    "abs_distance_delta_m",
                ),
                "static_expected_fuel_saved_total_l": float(
                    frame["static_expected_fuel_saved_l"].fill_null(0.0).sum()
                ),
                "adaptive_expected_fuel_saved_total_l": float(
                    frame["adaptive_expected_fuel_saved_l"].fill_null(0.0).sum()
                ),
                "expected_fuel_saved_delta_l": float(
                    frame["expected_fuel_saved_delta_l"].fill_null(0.0).sum()
                ),
                "static_expected_time_lost_total_s": float(
                    frame["static_expected_time_lost_s"].fill_null(0.0).sum()
                ),
                "adaptive_expected_time_lost_total_s": float(
                    frame["adaptive_expected_time_lost_s"].fill_null(0.0).sum()
                ),
                "expected_time_lost_delta_s": float(
                    frame["expected_time_lost_delta_s"].fill_null(0.0).sum()
                ),
                "adaptive_driver_fuel_execution_scale": _first_float(
                    frame["adaptive_applied_driver_fuel_execution_scale"].to_list(),
                    default=1.0,
                ),
                "adaptive_driver_time_execution_scale": _first_float(
                    frame["adaptive_applied_driver_time_execution_scale"].to_list(),
                    default=1.0,
                ),
                "adaptive_zone_execution_scale_count": int(
                    frame.filter(
                        pl.col("adaptive_applied_zone_specific_execution_scale").fill_null(False)
                    ).height
                ),
            }
        )

    return _frame_with_schema(rows, _SHADOW_HANDOFF_SUMMARY_SCHEMA).sort(
        ["variant_name", "scenario_id", "current_lap_number", "next_lap_number"]
    )


def summarize_experimental_shadow_adaptive_zones(
    shadow_transition_comparison: pl.DataFrame,
) -> pl.DataFrame:
    """Summarize shadow adaptive changes at the zone level."""

    if shadow_transition_comparison.is_empty():
        return pl.DataFrame(schema=_SHADOW_ZONE_SUMMARY_SCHEMA)

    _require_columns(
        shadow_transition_comparison,
        set(_SHADOW_TRANSITION_COMPARISON_SCHEMA.keys()),
        "shadow transition comparison",
    )

    rows: list[dict[str, object]] = []
    for zone_keys, frame in _shadow_zone_groups(shadow_transition_comparison):
        changed = frame.filter(pl.col("change_type") != "unchanged")
        rows.append(
            {
                **zone_keys,
                "sample_count": int(frame.height),
                "changed_count": int(changed.height),
                "added_count": int(frame.filter(pl.col("change_type") == "added").height),
                "removed_count": int(frame.filter(pl.col("change_type") == "removed").height),
                "unchanged_count": int(frame.filter(pl.col("change_type") == "unchanged").height),
                "longer_distance_count": int(
                    frame.filter(pl.col("change_type") == "longer_distance").height
                ),
                "shorter_distance_count": int(
                    frame.filter(pl.col("change_type") == "shorter_distance").height
                ),
                "mean_distance_delta_m": _mean_or_none(changed, "distance_delta_m"),
                "mean_abs_distance_delta_m": _mean_or_none(changed, "abs_distance_delta_m"),
                "max_abs_distance_delta_m": _max_or_none(changed, "abs_distance_delta_m"),
                "mean_expected_fuel_saved_delta_l": _mean_or_none(
                    frame,
                    "expected_fuel_saved_delta_l",
                ),
                "mean_expected_time_lost_delta_s": _mean_or_none(
                    frame,
                    "expected_time_lost_delta_s",
                ),
            }
        )

    return _frame_with_schema(rows, _SHADOW_ZONE_SUMMARY_SCHEMA).sort(
        ["variant_name", "zone_id"]
    )


def build_experimental_guarded_adaptive_live_transition_preview(
    live_transition_preview: pl.DataFrame,
    *,
    config: ExperimentalAdaptiveHandoffGuardrailConfig | None = None,
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    """Build a bounded operator-facing adaptive handoff preview from shadow rows."""

    guardrails = config or ExperimentalAdaptiveHandoffGuardrailConfig()
    if live_transition_preview.is_empty():
        return (
            pl.DataFrame(schema=_LIVE_TRANSITION_PREVIEW_SCHEMA),
            pl.DataFrame(schema=_GUARDED_ADAPTIVE_HANDOFF_DETAIL_SCHEMA),
            pl.DataFrame(schema=_GUARDED_ADAPTIVE_HANDOFF_SUMMARY_SCHEMA),
        )

    comparison = build_experimental_shadow_adaptive_transition_comparison(
        live_transition_preview
    )
    if comparison.is_empty():
        return (
            pl.DataFrame(schema=_LIVE_TRANSITION_PREVIEW_SCHEMA),
            pl.DataFrame(schema=_GUARDED_ADAPTIVE_HANDOFF_DETAIL_SCHEMA),
            pl.DataFrame(schema=_GUARDED_ADAPTIVE_HANDOFF_SUMMARY_SCHEMA),
        )

    static_map = _transition_preview_row_map(live_transition_preview, planning_mode="static")
    adaptive_map = _transition_preview_row_map(live_transition_preview, planning_mode="adaptive")

    detail_rows: list[dict[str, object]] = []
    preview_rows: list[dict[str, object]] = []
    summary_rows: list[dict[str, object]] = []
    for handoff_keys, handoff_frame in _shadow_handoff_groups(comparison):
        handoff_preview_rows: list[dict[str, object]] = []
        handoff_detail_rows: list[dict[str, object]] = []
        for row in handoff_frame.iter_rows(named=True):
            join_key = (
                str(row["scenario_id"]),
                str(row["variant_name"]),
                int(row["current_lap_number"]),
                int(row["next_lap_number"]),
                str(row["zone_id"]),
            )
            static_row = static_map.get(join_key)
            adaptive_row = adaptive_map.get(join_key)
            detail_row = _guarded_handoff_detail_row(
                row,
                static_row=static_row,
                adaptive_row=adaptive_row,
                config=guardrails,
            )
            handoff_detail_rows.append(detail_row)
            if not detail_row["keep_in_guarded_plan"]:
                continue
            handoff_preview_rows.append(
                _guarded_preview_row(
                    detail_row,
                    static_row=static_row,
                    adaptive_row=adaptive_row,
                )
            )

        preview_rows.extend(_finalize_guarded_preview_rows(handoff_preview_rows))
        detail_rows.extend(handoff_detail_rows)
        summary_rows.append(
            _guarded_handoff_summary_row(
                handoff_keys,
                handoff_detail_rows,
                handoff_preview_rows,
            )
        )

    preview = _frame_with_schema(preview_rows, _LIVE_TRANSITION_PREVIEW_SCHEMA).sort(
        ["variant_name", "scenario_id", "current_lap_number", "next_lap_number", "next_zone_id"]
    )
    detail = _frame_with_schema(
        detail_rows,
        _GUARDED_ADAPTIVE_HANDOFF_DETAIL_SCHEMA,
    ).sort(["variant_name", "scenario_id", "current_lap_number", "next_lap_number", "zone_id"])
    summary = _frame_with_schema(
        summary_rows,
        _GUARDED_ADAPTIVE_HANDOFF_SUMMARY_SCHEMA,
    ).sort(["variant_name", "scenario_id", "current_lap_number", "next_lap_number"])
    return preview, detail, summary


_LAP_SUMMARY_SCHEMA = {
    "scenario_id": pl.String,
    "variant_name": pl.String,
    "planning_mode": pl.String,
    "lap_number": pl.Int64,
    "total_laps": pl.Int64,
    "laps_remaining": pl.Int64,
    "fuel_target_remaining_l": pl.Float64,
    "lap_target_fuel_saved_l": pl.Float64,
    "planned_zone_count": pl.Int64,
    "planned_zone_ids": pl.String,
    "planned_zone_distances": pl.String,
    "planned_fuel_saved_l": pl.Float64,
    "planned_time_lost_s": pl.Float64,
    "planned_plan_status": pl.String,
    "execution_quality": pl.String,
    "scenario_event": pl.String,
    "actual_zone_count": pl.Int64,
    "actual_zone_ids": pl.String,
    "fuel_saved_this_lap_l": pl.Float64,
    "time_lost_this_lap_s": pl.Float64,
    "cumulative_fuel_saved_l": pl.Float64,
    "cumulative_time_lost_s": pl.Float64,
    "fuel_target_remaining_after_l": pl.Float64,
    "next_lap_target_fuel_saved_l": pl.Float64,
    "next_lap_selected_zone_count": pl.Int64,
    "next_lap_selected_zone_ids": pl.String,
    "next_lap_selected_zone_distances": pl.String,
    "next_lap_expected_fuel_saved_l": pl.Float64,
    "next_lap_expected_time_lost_s": pl.Float64,
    "next_lap_plan_status": pl.String,
    "driver_fuel_execution_scale": pl.Float64,
    "driver_time_execution_scale": pl.Float64,
    "driver_zone_execution_scale_count": pl.Int64,
    "driver_zone_execution_scale_zone_ids": pl.String,
    "next_lap_driver_fuel_execution_scale": pl.Float64,
    "next_lap_driver_time_execution_scale": pl.Float64,
    "next_lap_driver_zone_execution_scale_count": pl.Int64,
    "next_lap_driver_zone_execution_scale_zone_ids": pl.String,
    "lap_index_in_run": pl.Int64,
    "lap_fuel_start_l": pl.Float64,
    "lap_fuel_end_l": pl.Float64,
    "lap_fuel_used_total_l": pl.Float64,
    "fuel_load_ratio": pl.Float64,
    "fuel_load_band": pl.String,
    "lap_stint_index": pl.Int64,
    "tire_regime_label": pl.String,
    "lap_start_carcass_temp_c": pl.Float64,
    "lap_mean_carcass_temp_delta_vs_baseline_c": pl.Float64,
    "lap_context_label": pl.String,
    "notes": pl.String,
}

_LAP_PLAN_SCHEMA = {
    "scenario_id": pl.String,
    "variant_name": pl.String,
    "planning_mode": pl.String,
    "lap_number": pl.Int64,
    "zone_id": pl.String,
    "display_label": pl.String,
    "selected_lico_distance_m": pl.Float64,
    "expected_fuel_saved_l": pl.Float64,
    "expected_time_lost_s": pl.Float64,
    "support_score": pl.Float64,
    "recommended_range_start_m": pl.Float64,
    "recommended_range_end_m": pl.Float64,
    "source_model_status": pl.String,
    "applied_driver_fuel_execution_scale": pl.Float64,
    "applied_driver_time_execution_scale": pl.Float64,
    "applied_zone_execution_support_rows": pl.Int64,
    "applied_zone_specific_execution_scale": pl.Boolean,
    "execution_quality": pl.String,
    "scenario_event": pl.String,
    "actual_is_executed": pl.Boolean,
    "actual_fuel_saved_l": pl.Float64,
    "actual_time_lost_s": pl.Float64,
    "notes": pl.String,
}

_SCENARIO_SUMMARY_SCHEMA = {
    "scenario_id": pl.String,
    "variant_name": pl.String,
    "planning_mode": pl.String,
    "total_laps": pl.Int64,
    "total_actual_fuel_saved_l": pl.Float64,
    "total_actual_time_lost_s": pl.Float64,
    "final_fuel_target_remaining_l": pl.Float64,
    "final_next_lap_target_fuel_saved_l": pl.Float64,
    "target_met": pl.Boolean,
    "final_next_lap_selected_zone_count": pl.Int64,
    "final_next_lap_selected_zone_ids": pl.String,
    "notes": pl.String,
}

_LAP_CONTEXT_SCHEMA = {
    "scenario_id": pl.String,
    "run_id": pl.String,
    "lap_number": pl.Int64,
    "lap_index_in_run": pl.Int64,
    "total_laps_in_run": pl.Int64,
    "lap_fuel_start_l": pl.Float64,
    "lap_fuel_end_l": pl.Float64,
    "lap_fuel_used_total_l": pl.Float64,
    "fuel_load_ratio": pl.Float64,
    "fuel_load_band": pl.String,
    "lap_stint_index": pl.Int64,
    "lap_start_carcass_temp_c": pl.Float64,
    "lap_start_carcass_temp_delta_vs_baseline_c": pl.Float64,
    "lap_mean_carcass_temp_delta_vs_baseline_c": pl.Float64,
    "tire_regime_label": pl.String,
    "lap_context_label": pl.String,
}

_RACE_STATE_CONTEXT_EFFECTS_SCHEMA = {
    "variant_name": pl.String,
    "planning_mode": pl.String,
    "fuel_load_band": pl.String,
    "tire_regime_label": pl.String,
    "lap_count": pl.Int64,
    "mean_planned_time_lost_s": pl.Float64,
    "mean_actual_time_lost_s": pl.Float64,
    "mean_time_residual_s": pl.Float64,
    "mean_planned_fuel_saved_l": pl.Float64,
    "mean_actual_fuel_saved_l": pl.Float64,
    "mean_fuel_residual_l": pl.Float64,
    "mean_next_lap_expected_time_lost_s": pl.Float64,
    "mean_next_lap_expected_fuel_saved_l": pl.Float64,
}

_ZONE_EXECUTION_CALIBRATION_SUMMARY_SCHEMA = {
    "variant_name": pl.String,
    "planning_mode": pl.String,
    "zone_id": pl.String,
    "display_label": pl.String,
    "source_model_status": pl.String,
    "sample_count": pl.Int64,
    "zone_specific_usage_rate": pl.Float64,
    "execution_rate": pl.Float64,
    "mean_applied_fuel_scale": pl.Float64,
    "mean_global_fuel_scale": pl.Float64,
    "mean_fuel_scale_delta_vs_global": pl.Float64,
    "mean_applied_time_scale": pl.Float64,
    "mean_global_time_scale": pl.Float64,
    "mean_time_scale_delta_vs_global": pl.Float64,
    "penalized_fuel_count": pl.Int64,
    "relieved_fuel_count": pl.Int64,
    "penalized_time_count": pl.Int64,
    "relieved_time_count": pl.Int64,
    "mean_support_rows": pl.Float64,
}

_LIVE_TRANSITION_PREVIEW_SCHEMA = {
    "scenario_id": pl.String,
    "variant_name": pl.String,
    "planning_mode": pl.String,
    "current_lap_number": pl.Int64,
    "next_lap_number": pl.Int64,
    "current_scenario_event": pl.String,
    "current_execution_quality": pl.String,
    "current_notes": pl.String,
    "next_lap_target_fuel_saved_l": pl.Float64,
    "next_lap_expected_fuel_saved_l": pl.Float64,
    "next_lap_expected_time_lost_s": pl.Float64,
    "next_lap_selected_zone_count": pl.Int64,
    "next_lap_selected_zone_ids": pl.String,
    "next_lap_driver_fuel_execution_scale": pl.Float64,
    "next_lap_driver_time_execution_scale": pl.Float64,
    "next_lap_driver_zone_execution_scale_count": pl.Int64,
    "next_zone_id": pl.String,
    "next_display_label": pl.String,
    "next_selected_lico_distance_m": pl.Float64,
    "next_expected_fuel_saved_by_zone_l": pl.Float64,
    "next_expected_time_lost_by_zone_s": pl.Float64,
    "next_source_model_status": pl.String,
    "next_recommended_range_start_m": pl.Float64,
    "next_recommended_range_end_m": pl.Float64,
    "next_applied_driver_fuel_execution_scale": pl.Float64,
    "next_applied_driver_time_execution_scale": pl.Float64,
    "next_applied_zone_execution_support_rows": pl.Int64,
    "next_applied_zone_specific_execution_scale": pl.Boolean,
    "next_cue_latency_reference_speed_kph": pl.Float64,
}

_SHADOW_TRANSITION_COMPARISON_SCHEMA = {
    "scenario_id": pl.String,
    "run_id": pl.String,
    "variant_name": pl.String,
    "current_lap_number": pl.Int64,
    "next_lap_number": pl.Int64,
    "zone_id": pl.String,
    "display_label": pl.String,
    "shadow_mode": pl.Boolean,
    "next_lap_target_fuel_saved_l": pl.Float64,
    "static_display_label": pl.String,
    "static_selected_lico_distance_m": pl.Float64,
    "static_expected_fuel_saved_l": pl.Float64,
    "static_expected_time_lost_s": pl.Float64,
    "adaptive_display_label": pl.String,
    "adaptive_selected_lico_distance_m": pl.Float64,
    "adaptive_expected_fuel_saved_l": pl.Float64,
    "adaptive_expected_time_lost_s": pl.Float64,
    "adaptive_applied_driver_fuel_execution_scale": pl.Float64,
    "adaptive_applied_driver_time_execution_scale": pl.Float64,
    "adaptive_applied_zone_execution_support_rows": pl.Int64,
    "adaptive_applied_zone_specific_execution_scale": pl.Boolean,
    "distance_delta_m": pl.Float64,
    "abs_distance_delta_m": pl.Float64,
    "expected_fuel_saved_delta_l": pl.Float64,
    "expected_time_lost_delta_s": pl.Float64,
    "change_type": pl.String,
    "is_changed": pl.Boolean,
}

_SHADOW_HANDOFF_SUMMARY_SCHEMA = {
    "scenario_id": pl.String,
    "run_id": pl.String,
    "variant_name": pl.String,
    "current_lap_number": pl.Int64,
    "next_lap_number": pl.Int64,
    "shadow_mode": pl.Boolean,
    "next_lap_target_fuel_saved_l": pl.Float64,
    "static_zone_count": pl.Int64,
    "adaptive_zone_count": pl.Int64,
    "changed_zone_count": pl.Int64,
    "added_zone_count": pl.Int64,
    "removed_zone_count": pl.Int64,
    "longer_distance_zone_count": pl.Int64,
    "shorter_distance_zone_count": pl.Int64,
    "changed_zone_ids": pl.String,
    "mean_abs_distance_delta_m": pl.Float64,
    "max_abs_distance_delta_m": pl.Float64,
    "static_expected_fuel_saved_total_l": pl.Float64,
    "adaptive_expected_fuel_saved_total_l": pl.Float64,
    "expected_fuel_saved_delta_l": pl.Float64,
    "static_expected_time_lost_total_s": pl.Float64,
    "adaptive_expected_time_lost_total_s": pl.Float64,
    "expected_time_lost_delta_s": pl.Float64,
    "adaptive_driver_fuel_execution_scale": pl.Float64,
    "adaptive_driver_time_execution_scale": pl.Float64,
    "adaptive_zone_execution_scale_count": pl.Int64,
}

_SHADOW_ZONE_SUMMARY_SCHEMA = {
    "variant_name": pl.String,
    "zone_id": pl.String,
    "display_label": pl.String,
    "sample_count": pl.Int64,
    "changed_count": pl.Int64,
    "added_count": pl.Int64,
    "removed_count": pl.Int64,
    "unchanged_count": pl.Int64,
    "longer_distance_count": pl.Int64,
    "shorter_distance_count": pl.Int64,
    "mean_distance_delta_m": pl.Float64,
    "mean_abs_distance_delta_m": pl.Float64,
    "max_abs_distance_delta_m": pl.Float64,
    "mean_expected_fuel_saved_delta_l": pl.Float64,
    "mean_expected_time_lost_delta_s": pl.Float64,
}

_GUARDED_ADAPTIVE_HANDOFF_DETAIL_SCHEMA = {
    "scenario_id": pl.String,
    "run_id": pl.String,
    "variant_name": pl.String,
    "current_lap_number": pl.Int64,
    "next_lap_number": pl.Int64,
    "zone_id": pl.String,
    "display_label": pl.String,
    "next_lap_target_fuel_saved_l": pl.Float64,
    "support_rows": pl.Int64,
    "max_allowed_abs_distance_delta_m": pl.Float64,
    "static_selected_lico_distance_m": pl.Float64,
    "raw_adaptive_selected_lico_distance_m": pl.Float64,
    "guarded_selected_lico_distance_m": pl.Float64,
    "raw_distance_delta_m": pl.Float64,
    "guarded_distance_delta_m": pl.Float64,
    "raw_change_type": pl.String,
    "guardrail_reason": pl.String,
    "keep_in_guarded_plan": pl.Boolean,
    "is_guarded_change": pl.Boolean,
    "static_expected_fuel_saved_l": pl.Float64,
    "raw_adaptive_expected_fuel_saved_l": pl.Float64,
    "guarded_expected_fuel_saved_l": pl.Float64,
    "static_expected_time_lost_s": pl.Float64,
    "raw_adaptive_expected_time_lost_s": pl.Float64,
    "guarded_expected_time_lost_s": pl.Float64,
}

_GUARDED_ADAPTIVE_HANDOFF_SUMMARY_SCHEMA = {
    "scenario_id": pl.String,
    "run_id": pl.String,
    "variant_name": pl.String,
    "current_lap_number": pl.Int64,
    "next_lap_number": pl.Int64,
    "next_lap_target_fuel_saved_l": pl.Float64,
    "raw_changed_zone_count": pl.Int64,
    "guarded_changed_zone_count": pl.Int64,
    "clamped_zone_count": pl.Int64,
    "blocked_zone_count": pl.Int64,
    "guarded_zone_count": pl.Int64,
    "mean_guarded_abs_distance_delta_m": pl.Float64,
    "max_guarded_abs_distance_delta_m": pl.Float64,
    "raw_expected_fuel_saved_total_l": pl.Float64,
    "guarded_expected_fuel_saved_total_l": pl.Float64,
    "raw_expected_fuel_saved_delta_l_vs_static": pl.Float64,
    "guarded_expected_fuel_saved_delta_l_vs_static": pl.Float64,
    "raw_expected_time_lost_total_s": pl.Float64,
    "guarded_expected_time_lost_total_s": pl.Float64,
    "raw_expected_time_lost_delta_s_vs_static": pl.Float64,
    "guarded_expected_time_lost_delta_s_vs_static": pl.Float64,
    "target_met_after_guardrails": pl.Boolean,
    "guardrail_reasons": pl.String,
}


def _require_columns(frame: pl.DataFrame, required: set[str], label: str) -> None:
    missing = sorted(required - set(frame.columns))
    if missing:
        missing_text = ", ".join(missing)
        raise ValueError(f"{label} are missing required columns: {missing_text}")


def _shadow_transition_side(
    live_transition_preview: pl.DataFrame,
    *,
    planning_mode: str,
    prefix: str,
) -> pl.DataFrame:
    frame = live_transition_preview.filter(pl.col("planning_mode") == planning_mode)
    if frame.is_empty():
        return pl.DataFrame()
    return frame.select(
        [
            "scenario_id",
            "variant_name",
            "current_lap_number",
            "next_lap_number",
            pl.col("next_zone_id").alias("zone_id"),
            pl.col("next_display_label").alias(f"{prefix}_display_label"),
            pl.col("next_lap_target_fuel_saved_l").alias(
                f"{prefix}_next_lap_target_fuel_saved_l"
            ),
            pl.col("next_selected_lico_distance_m").alias(
                f"{prefix}_selected_lico_distance_m"
            ),
            pl.col("next_expected_fuel_saved_by_zone_l").alias(
                f"{prefix}_expected_fuel_saved_l"
            ),
            pl.col("next_expected_time_lost_by_zone_s").alias(
                f"{prefix}_expected_time_lost_s"
            ),
            pl.col("next_applied_driver_fuel_execution_scale").alias(
                f"{prefix}_applied_driver_fuel_execution_scale"
            ),
            pl.col("next_applied_driver_time_execution_scale").alias(
                f"{prefix}_applied_driver_time_execution_scale"
            ),
            pl.col("next_applied_zone_execution_support_rows").alias(
                f"{prefix}_applied_zone_execution_support_rows"
            ),
            pl.col("next_applied_zone_specific_execution_scale").alias(
                f"{prefix}_applied_zone_specific_execution_scale"
            ),
        ]
    )


def _transition_preview_row_map(
    live_transition_preview: pl.DataFrame,
    *,
    planning_mode: str,
) -> dict[tuple[str, str, int, int, str], dict[str, object]]:
    rows: dict[tuple[str, str, int, int, str], dict[str, object]] = {}
    for row in (
        live_transition_preview.filter(pl.col("planning_mode") == planning_mode)
        .sort(["variant_name", "scenario_id", "current_lap_number", "next_lap_number", "next_zone_id"])
        .iter_rows(named=True)
    ):
        rows[
            (
                str(row["scenario_id"]),
                str(row["variant_name"]),
                int(row["current_lap_number"]),
                int(row["next_lap_number"]),
                str(row["next_zone_id"]),
            )
        ] = row
    return rows


def _guarded_handoff_detail_row(
    comparison_row: dict[str, object],
    *,
    static_row: dict[str, object] | None,
    adaptive_row: dict[str, object] | None,
    config: ExperimentalAdaptiveHandoffGuardrailConfig,
) -> dict[str, object]:
    static_distance = _optional_float(comparison_row.get("static_selected_lico_distance_m"))
    adaptive_distance = _optional_float(
        comparison_row.get("adaptive_selected_lico_distance_m")
    )
    raw_delta = _optional_float(comparison_row.get("distance_delta_m"))
    support_rows = int(comparison_row.get("adaptive_applied_zone_execution_support_rows") or 0)
    max_allowed_abs_distance_delta_m = (
        config.max_abs_distance_delta_m
        if support_rows >= config.low_support_rows_threshold
        else config.low_support_max_abs_distance_delta_m
    )
    guardrail_reason = "accepted_raw_adaptive"
    guarded_distance = adaptive_distance
    keep_in_guarded_plan = True

    if static_distance is None and adaptive_distance is not None and not config.allow_added_zones:
        keep_in_guarded_plan = False
        guarded_distance = None
        guardrail_reason = "blocked_added_zone"
    elif static_distance is not None and adaptive_distance is None and not config.allow_removed_zones:
        guarded_distance = static_distance
        guardrail_reason = "blocked_removed_zone"
    elif static_distance is not None and adaptive_distance is None:
        keep_in_guarded_plan = False
        guarded_distance = None
        guardrail_reason = "accepted_removed_zone"
    elif static_distance is None and adaptive_distance is not None:
        guardrail_reason = "accepted_added_zone"
    elif static_distance is not None and adaptive_distance is not None:
        delta = adaptive_distance - static_distance
        if abs(delta) <= 1e-9:
            guardrail_reason = "unchanged"
        elif abs(delta) > max_allowed_abs_distance_delta_m:
            clamped_delta = max_allowed_abs_distance_delta_m if delta > 0.0 else -max_allowed_abs_distance_delta_m
            guarded_distance = static_distance + clamped_delta
            guardrail_reason = (
                "clamped_low_support"
                if support_rows < config.low_support_rows_threshold
                else "clamped_max_delta"
            )

    guarded_expected_fuel_saved_l = _guarded_expected_value(
        static_distance=static_distance,
        static_value=_optional_float(comparison_row.get("static_expected_fuel_saved_l")),
        adaptive_distance=adaptive_distance,
        adaptive_value=_optional_float(comparison_row.get("adaptive_expected_fuel_saved_l")),
        guarded_distance=guarded_distance,
    )
    guarded_expected_time_lost_s = _guarded_expected_value(
        static_distance=static_distance,
        static_value=_optional_float(comparison_row.get("static_expected_time_lost_s")),
        adaptive_distance=adaptive_distance,
        adaptive_value=_optional_float(comparison_row.get("adaptive_expected_time_lost_s")),
        guarded_distance=guarded_distance,
    )
    guarded_distance_delta_m = (
        None
        if static_distance is None or guarded_distance is None
        else float(guarded_distance - static_distance)
    )
    return {
        "scenario_id": str(comparison_row["scenario_id"]),
        "run_id": str(comparison_row["run_id"]),
        "variant_name": str(comparison_row["variant_name"]),
        "current_lap_number": int(comparison_row["current_lap_number"]),
        "next_lap_number": int(comparison_row["next_lap_number"]),
        "zone_id": str(comparison_row["zone_id"]),
        "display_label": str(comparison_row["display_label"]),
        "next_lap_target_fuel_saved_l": float(
            comparison_row.get("next_lap_target_fuel_saved_l") or 0.0
        ),
        "support_rows": support_rows,
        "max_allowed_abs_distance_delta_m": float(max_allowed_abs_distance_delta_m),
        "static_selected_lico_distance_m": static_distance,
        "raw_adaptive_selected_lico_distance_m": adaptive_distance,
        "guarded_selected_lico_distance_m": guarded_distance,
        "raw_distance_delta_m": raw_delta,
        "guarded_distance_delta_m": guarded_distance_delta_m,
        "raw_change_type": str(comparison_row.get("change_type") or ""),
        "guardrail_reason": guardrail_reason,
        "keep_in_guarded_plan": keep_in_guarded_plan,
        "is_guarded_change": bool(guardrail_reason.startswith("clamped") or guardrail_reason.startswith("blocked")),
        "static_expected_fuel_saved_l": _optional_float(
            comparison_row.get("static_expected_fuel_saved_l")
        ),
        "raw_adaptive_expected_fuel_saved_l": _optional_float(
            comparison_row.get("adaptive_expected_fuel_saved_l")
        ),
        "guarded_expected_fuel_saved_l": guarded_expected_fuel_saved_l,
        "static_expected_time_lost_s": _optional_float(
            comparison_row.get("static_expected_time_lost_s")
        ),
        "raw_adaptive_expected_time_lost_s": _optional_float(
            comparison_row.get("adaptive_expected_time_lost_s")
        ),
        "guarded_expected_time_lost_s": guarded_expected_time_lost_s,
    }


def _guarded_preview_row(
    detail_row: dict[str, object],
    *,
    static_row: dict[str, object] | None,
    adaptive_row: dict[str, object] | None,
) -> dict[str, object]:
    source_row = dict(adaptive_row or static_row or {})
    source_row["planning_mode"] = "adaptive_guarded"
    source_row["next_zone_id"] = str(detail_row["zone_id"])
    source_row["next_display_label"] = str(detail_row["display_label"])
    source_row["next_selected_lico_distance_m"] = detail_row["guarded_selected_lico_distance_m"]
    source_row["next_expected_fuel_saved_by_zone_l"] = detail_row["guarded_expected_fuel_saved_l"]
    source_row["next_expected_time_lost_by_zone_s"] = detail_row["guarded_expected_time_lost_s"]
    return source_row


def _finalize_guarded_preview_rows(
    handoff_preview_rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    if not handoff_preview_rows:
        return []
    next_zone_ids = [str(row["next_zone_id"]) for row in handoff_preview_rows]
    total_fuel_saved_l = sum(
        float(row["next_expected_fuel_saved_by_zone_l"] or 0.0)
        for row in handoff_preview_rows
    )
    total_time_lost_s = sum(
        float(row["next_expected_time_lost_by_zone_s"] or 0.0)
        for row in handoff_preview_rows
    )
    zone_count = len(handoff_preview_rows)
    zone_ids_joined = _joined_unique_strings(next_zone_ids, default="")
    zone_scale_count = sum(
        1
        for row in handoff_preview_rows
        if bool(row.get("next_applied_zone_specific_execution_scale"))
    )
    finalized_rows: list[dict[str, object]] = []
    for row in handoff_preview_rows:
        updated = dict(row)
        updated["next_lap_expected_fuel_saved_l"] = total_fuel_saved_l
        updated["next_lap_expected_time_lost_s"] = total_time_lost_s
        updated["next_lap_selected_zone_count"] = zone_count
        updated["next_lap_selected_zone_ids"] = zone_ids_joined
        updated["next_lap_driver_zone_execution_scale_count"] = zone_scale_count
        finalized_rows.append(updated)
    return finalized_rows


def _guarded_handoff_summary_row(
    handoff_keys: dict[str, object],
    detail_rows: list[dict[str, object]],
    preview_rows: list[dict[str, object]],
) -> dict[str, object]:
    static_expected_fuel_saved_total_l = sum(
        float(row.get("static_expected_fuel_saved_l") or 0.0) for row in detail_rows
    )
    raw_expected_fuel_saved_total_l = sum(
        float(row.get("raw_adaptive_expected_fuel_saved_l") or 0.0)
        for row in detail_rows
        if row.get("raw_adaptive_expected_fuel_saved_l") is not None
    )
    guarded_expected_fuel_saved_total_l = sum(
        float(row.get("guarded_expected_fuel_saved_l") or 0.0)
        for row in detail_rows
        if row.get("keep_in_guarded_plan")
    )
    static_expected_time_lost_total_s = sum(
        float(row.get("static_expected_time_lost_s") or 0.0) for row in detail_rows
    )
    raw_expected_time_lost_total_s = sum(
        float(row.get("raw_adaptive_expected_time_lost_s") or 0.0)
        for row in detail_rows
        if row.get("raw_adaptive_expected_time_lost_s") is not None
    )
    guarded_expected_time_lost_total_s = sum(
        float(row.get("guarded_expected_time_lost_s") or 0.0)
        for row in detail_rows
        if row.get("keep_in_guarded_plan")
    )
    guarded_abs_distance_deltas = [
        abs(float(row["guarded_distance_delta_m"]))
        for row in detail_rows
        if row.get("guarded_distance_delta_m") is not None
        and abs(float(row["guarded_distance_delta_m"])) > 1e-9
    ]
    next_lap_target_fuel_saved_l = _first_float(
        [row.get("next_lap_target_fuel_saved_l") for row in detail_rows],
        default=0.0,
    )
    return {
        **handoff_keys,
        "next_lap_target_fuel_saved_l": next_lap_target_fuel_saved_l,
        "raw_changed_zone_count": sum(
            1
            for row in detail_rows
            if row.get("raw_distance_delta_m") is not None
            and abs(float(row["raw_distance_delta_m"])) > 1e-9
        ),
        "guarded_changed_zone_count": sum(
            1
            for row in detail_rows
            if row.get("guarded_distance_delta_m") is not None
            and abs(float(row["guarded_distance_delta_m"])) > 1e-9
            and row.get("keep_in_guarded_plan")
        ),
        "clamped_zone_count": sum(
            1
            for row in detail_rows
            if str(row.get("guardrail_reason", "")).startswith("clamped")
        ),
        "blocked_zone_count": sum(
            1
            for row in detail_rows
            if str(row.get("guardrail_reason", "")).startswith("blocked")
        ),
        "guarded_zone_count": len(preview_rows),
        "mean_guarded_abs_distance_delta_m": (
            sum(guarded_abs_distance_deltas) / len(guarded_abs_distance_deltas)
            if guarded_abs_distance_deltas
            else None
        ),
        "max_guarded_abs_distance_delta_m": (
            max(guarded_abs_distance_deltas) if guarded_abs_distance_deltas else None
        ),
        "raw_expected_fuel_saved_total_l": raw_expected_fuel_saved_total_l,
        "guarded_expected_fuel_saved_total_l": guarded_expected_fuel_saved_total_l,
        "raw_expected_fuel_saved_delta_l_vs_static": (
            raw_expected_fuel_saved_total_l - static_expected_fuel_saved_total_l
        ),
        "guarded_expected_fuel_saved_delta_l_vs_static": (
            guarded_expected_fuel_saved_total_l - static_expected_fuel_saved_total_l
        ),
        "raw_expected_time_lost_total_s": raw_expected_time_lost_total_s,
        "guarded_expected_time_lost_total_s": guarded_expected_time_lost_total_s,
        "raw_expected_time_lost_delta_s_vs_static": (
            raw_expected_time_lost_total_s - static_expected_time_lost_total_s
        ),
        "guarded_expected_time_lost_delta_s_vs_static": (
            guarded_expected_time_lost_total_s - static_expected_time_lost_total_s
        ),
        "target_met_after_guardrails": guarded_expected_fuel_saved_total_l
        >= next_lap_target_fuel_saved_l - 1e-9,
        "guardrail_reasons": _joined_unique_strings(
            [row.get("guardrail_reason") for row in detail_rows],
            default="",
        ),
    }


def _guarded_expected_value(
    *,
    static_distance: float | None,
    static_value: float | None,
    adaptive_distance: float | None,
    adaptive_value: float | None,
    guarded_distance: float | None,
) -> float | None:
    if guarded_distance is None:
        return None
    if adaptive_distance is not None and abs(guarded_distance - adaptive_distance) <= 1e-9:
        return adaptive_value
    if static_distance is not None and abs(guarded_distance - static_distance) <= 1e-9:
        return static_value
    if (
        static_distance is not None
        and adaptive_distance is not None
        and static_value is not None
        and adaptive_value is not None
        and abs(adaptive_distance - static_distance) > 1e-9
    ):
        interpolation_ratio = (guarded_distance - static_distance) / (
            adaptive_distance - static_distance
        )
        return float(static_value + interpolation_ratio * (adaptive_value - static_value))
    if adaptive_value is not None:
        return adaptive_value
    return static_value


def _shadow_handoff_groups(
    shadow_transition_comparison: pl.DataFrame,
) -> list[tuple[dict[str, object], pl.DataFrame]]:
    rows: list[tuple[dict[str, object], pl.DataFrame]] = []
    keys = (
        shadow_transition_comparison.select(
            "scenario_id",
            "run_id",
            "variant_name",
            "current_lap_number",
            "next_lap_number",
        )
        .unique()
        .sort(["variant_name", "scenario_id", "current_lap_number", "next_lap_number"])
        .to_dicts()
    )
    for key in keys:
        frame = shadow_transition_comparison.filter(
            (pl.col("scenario_id") == key["scenario_id"])
            & (pl.col("variant_name") == key["variant_name"])
            & (pl.col("current_lap_number") == key["current_lap_number"])
            & (pl.col("next_lap_number") == key["next_lap_number"])
        )
        rows.append((key, frame))
    return rows


def _shadow_zone_groups(
    shadow_transition_comparison: pl.DataFrame,
) -> list[tuple[dict[str, object], pl.DataFrame]]:
    rows: list[tuple[dict[str, object], pl.DataFrame]] = []
    keys = (
        shadow_transition_comparison.select(
            "variant_name",
            "zone_id",
            "display_label",
        )
        .unique()
        .sort(["variant_name", "zone_id"])
        .to_dicts()
    )
    for key in keys:
        frame = shadow_transition_comparison.filter(
            (pl.col("variant_name") == key["variant_name"])
            & (pl.col("zone_id") == key["zone_id"])
        )
        rows.append((key, frame))
    return rows


def _mean_or_none(frame: pl.DataFrame, column_name: str) -> float | None:
    if frame.is_empty() or column_name not in frame.columns:
        return None
    value = frame[column_name].drop_nulls().mean()
    return float(value) if value is not None else None


def _max_or_none(frame: pl.DataFrame, column_name: str) -> float | None:
    if frame.is_empty() or column_name not in frame.columns:
        return None
    value = frame[column_name].drop_nulls().max()
    return float(value) if value is not None else None


def _first_float(values: list[object], *, default: float) -> float:
    for value in values:
        if value is not None:
            return float(value)
    return default


def _run_id_from_scenario_id(scenario_id: str) -> str:
    prefix = "observed_execution:"
    if scenario_id.startswith(prefix):
        return scenario_id[len(prefix) :]
    return scenario_id
