from __future__ import annotations

import pytest
import polars as pl

from licor.analysis.experimental_lap_replanner import (
    ExperimentalAdaptiveHandoffGuardrailConfig,
    ExperimentalLapExecutionEvent,
    ExperimentalLapReplannerConfig,
    ExperimentalLapReplannerContext,
    ExperimentalLapReplanningScenario,
    build_experimental_guarded_adaptive_live_transition_preview,
    _apply_driver_execution_calibration_to_zone_models,
    _apply_fuel_load_conditioning_to_zone_models,
    build_experimental_shadow_adaptive_transition_comparison,
    build_experimental_lap_race_state_context,
    build_experimental_live_transition_preview,
    simulate_experimental_lap_replanning,
    simulate_experimental_lap_replanning_from_observed_executions,
    summarize_experimental_race_state_context_effects,
    summarize_experimental_shadow_adaptive_handoffs,
    summarize_experimental_shadow_adaptive_zones,
    summarize_experimental_zone_execution_calibration,
)


def test_adaptive_replanner_increases_next_lap_demand_after_opening_full_push() -> None:
    static_plan = pl.DataFrame(
        {
            "zone_id": ["spa_t01", "spa_t18"],
            "display_label": ["T01", "T18"],
            "selected_lico_distance_m": [60.0, 100.0],
            "is_selected_for_lico": [True, True],
            "predicted_fuel_saved_l": [0.03, 0.05],
            "predicted_time_lost_s": [0.06, 0.08],
            "plan_status": ["target_met", "target_met"],
            "model_status": ["model_ready", "model_ready"],
            "support_score": [0.96, 0.95],
            "recommended_range_start_m": [60.0, 100.0],
            "recommended_range_end_m": [70.0, 130.0],
        }
    )
    robust_zone_models = pl.DataFrame(
        {
            "zone_id": ["spa_t01", "spa_t01", "spa_t18", "spa_t18", "spa_t14"],
            "display_label": ["T01", "T01", "T18", "T18", "T14"],
            "lico_distance_m": [60.0, 70.0, 100.0, 130.0, 20.0],
            "robust_predicted_fuel_saved_l": [0.03, 0.04, 0.05, 0.07, 0.02],
            "robust_predicted_time_lost_s": [0.06, 0.08, 0.08, 0.12, 0.02],
            "robust_predicted_fuel_saved_per_second_lps": [0.5, 0.5, 0.625, 0.583, 1.0],
            "is_extrapolated": [False, False, False, False, False],
            "model_status": [
                "model_ready",
                "model_ready",
                "model_ready",
                "model_ready",
                "micro_lico_only",
            ],
            "quality_flags": ["", "", "", "", ""],
            "support_score": [0.96, 0.97, 0.95, 0.94, 0.90],
        }
    )
    robust_ranges = pl.DataFrame(
        {
            "zone_id": ["spa_t01", "spa_t18"],
            "display_label": ["T01", "T18"],
            "selected_lico_distance_m": [60.0, 100.0],
            "recommended_range_start_m": [60.0, 100.0],
            "recommended_range_end_m": [70.0, 130.0],
            "recommended_range_width_m": [10.0, 30.0],
        }
    )
    zone_priors = pl.DataFrame(
        {
            "zone_id": ["spa_t01", "spa_t18", "spa_t14"],
            "strategy_role": ["usable_now", "usable_now", "candidate_with_penalty"],
            "feasibility_score": [4, 5, 2],
            "max_lico_distance_m": [80.0, 140.0, 20.0],
        }
    )
    context = ExperimentalLapReplannerContext(
        variant_name="range_aware_all_eligible_zones",
        static_plan=static_plan,
        robust_zone_models=robust_zone_models,
        robust_ranges=robust_ranges,
        zone_priors=zone_priors,
        adaptive_scope="all_eligible_zones",
    )
    scenarios = (
        ExperimentalLapReplanningScenario(
            scenario_id="opening_full_push",
            total_laps=2,
            events=(
                ExperimentalLapExecutionEvent(
                    lap_number=1,
                    scenario_event="opening_full_push",
                    execution_quality="full_push_override",
                    force_zero_lico=True,
                ),
            ),
        ),
    )
    config = ExperimentalLapReplannerConfig(
        target_fuel_saved_per_lap_l=0.08,
        planning_modes=("static", "adaptive"),
    )

    lap_summary, lap_plan, scenario_summary = simulate_experimental_lap_replanning(
        context,
        scenarios,
        config=config,
    )

    static_lap1 = lap_summary.filter(
        (pl.col("planning_mode") == "static") & (pl.col("lap_number") == 1)
    ).row(0, named=True)
    adaptive_lap1 = lap_summary.filter(
        (pl.col("planning_mode") == "adaptive") & (pl.col("lap_number") == 1)
    ).row(0, named=True)
    assert static_lap1["fuel_saved_this_lap_l"] == 0.0
    assert adaptive_lap1["fuel_saved_this_lap_l"] == 0.0
    assert adaptive_lap1["next_lap_expected_fuel_saved_l"] > static_lap1["next_lap_expected_fuel_saved_l"]
    assert "spa_t14" in adaptive_lap1["next_lap_selected_zone_ids"]
    assert not lap_plan.is_empty()
    assert scenario_summary.filter(pl.col("planning_mode") == "adaptive")[
        "target_met"
    ].item() is False


def test_traffic_event_preserves_fuel_math_but_adds_time() -> None:
    static_plan = pl.DataFrame(
        {
            "zone_id": ["spa_t01"],
            "display_label": ["T01"],
            "selected_lico_distance_m": [60.0],
            "is_selected_for_lico": [True],
            "predicted_fuel_saved_l": [0.05],
            "predicted_time_lost_s": [0.10],
            "plan_status": ["target_met"],
            "model_status": ["model_ready"],
        }
    )
    robust_zone_models = pl.DataFrame(
        {
            "zone_id": ["spa_t01"],
            "display_label": ["T01"],
            "lico_distance_m": [60.0],
            "robust_predicted_fuel_saved_l": [0.05],
            "robust_predicted_time_lost_s": [0.10],
            "robust_predicted_fuel_saved_per_second_lps": [0.5],
            "is_extrapolated": [False],
            "model_status": ["model_ready"],
            "quality_flags": [""],
            "support_score": [0.95],
        }
    )
    robust_ranges = pl.DataFrame(
        {
            "zone_id": ["spa_t01"],
            "display_label": ["T01"],
            "selected_lico_distance_m": [60.0],
            "recommended_range_start_m": [60.0],
            "recommended_range_end_m": [60.0],
            "recommended_range_width_m": [0.0],
        }
    )
    context = ExperimentalLapReplannerContext(
        variant_name="range_aware_selected_zones",
        static_plan=static_plan,
        robust_zone_models=robust_zone_models,
        robust_ranges=robust_ranges,
        adaptive_scope="selected_zones",
    )
    scenarios = (
        ExperimentalLapReplanningScenario(
            scenario_id="traffic_nonideal",
            total_laps=2,
            events=(
                ExperimentalLapExecutionEvent(
                    lap_number=1,
                    scenario_event="traffic_nonideal",
                    execution_quality="traffic_nonideal",
                    extra_time_lost_s=0.35,
                ),
            ),
        ),
    )
    config = ExperimentalLapReplannerConfig(
        target_fuel_saved_per_lap_l=0.05,
        planning_modes=("adaptive",),
    )

    lap_summary, _, _ = simulate_experimental_lap_replanning(
        context,
        scenarios,
        config=config,
    )

    lap1 = lap_summary.row(0, named=True)
    assert lap1["fuel_saved_this_lap_l"] == 0.05
    assert lap1["time_lost_this_lap_s"] == pytest.approx(0.45)
    assert lap1["next_lap_target_fuel_saved_l"] == 0.05


def test_builds_lap_race_state_context_from_zone_observations() -> None:
    zone_observations = pl.DataFrame(
        {
            "run_id": ["run_01"] * 4,
            "file_name": ["run.duckdb"] * 4,
            "lap_number": [5, 5, 6, 6],
            "zone_id": ["spa_t01", "spa_t18", "spa_t01", "spa_t18"],
            "zone_start_m": [100.0, 6200.0, 100.0, 6200.0],
            "fuel_start_l": [55.0, 52.0, 48.0, 45.0],
            "fuel_end_l": [54.7, 51.7, 47.7, 44.7],
            "stint_index": [1, 1, 2, 2],
            "carcass_temp_zone_start_c": [32.0, 60.0, 91.0, 94.0],
            "carcass_temp_zone_start_delta_vs_baseline_c": [-10.0, -1.0, 3.5, 4.0],
        }
    )

    context = build_experimental_lap_race_state_context(zone_observations)

    lap5 = context.filter(pl.col("lap_number") == 5).row(0, named=True)
    lap6 = context.filter(pl.col("lap_number") == 6).row(0, named=True)

    assert lap5["scenario_id"] == "observed_execution:run_01"
    assert lap5["lap_fuel_start_l"] == pytest.approx(55.0)
    assert lap5["lap_fuel_end_l"] == pytest.approx(51.7)
    assert lap5["fuel_load_band"] == "heavy"
    assert lap5["tire_regime_label"] == "pit_out_cold"
    assert lap6["fuel_load_band"] == "light"
    assert lap6["tire_regime_label"] == "hotter_than_baseline"


def test_observed_execution_replanner_raises_next_lap_demand_after_under_execution() -> None:
    static_plan = pl.DataFrame(
        {
            "zone_id": ["spa_t01", "spa_t18"],
            "display_label": ["T01", "T18"],
            "selected_lico_distance_m": [60.0, 100.0],
            "is_selected_for_lico": [True, True],
            "predicted_fuel_saved_l": [0.04, 0.04],
            "predicted_time_lost_s": [0.06, 0.08],
            "plan_status": ["target_met", "target_met"],
            "model_status": ["model_ready", "model_ready"],
            "support_score": [0.96, 0.95],
            "recommended_range_start_m": [60.0, 100.0],
            "recommended_range_end_m": [70.0, 130.0],
        }
    )
    robust_zone_models = pl.DataFrame(
        {
            "zone_id": ["spa_t01", "spa_t18", "spa_t14"],
            "display_label": ["T01", "T18", "T14"],
            "lico_distance_m": [70.0, 130.0, 20.0],
            "robust_predicted_fuel_saved_l": [0.05, 0.05, 0.02],
            "robust_predicted_time_lost_s": [0.08, 0.10, 0.02],
            "robust_predicted_fuel_saved_per_second_lps": [0.625, 0.5, 1.0],
            "is_extrapolated": [False, False, False],
            "model_status": ["model_ready", "model_ready", "micro_lico_only"],
            "quality_flags": ["", "", ""],
            "support_score": [0.97, 0.94, 0.90],
        }
    )
    robust_ranges = pl.DataFrame(
        {
            "zone_id": ["spa_t01", "spa_t18", "spa_t14"],
            "display_label": ["T01", "T18", "T14"],
            "selected_lico_distance_m": [60.0, 100.0, 20.0],
            "recommended_range_start_m": [60.0, 100.0, 20.0],
            "recommended_range_end_m": [70.0, 130.0, 20.0],
            "recommended_range_width_m": [10.0, 30.0, 0.0],
        }
    )
    zone_priors = pl.DataFrame(
        {
            "zone_id": ["spa_t01", "spa_t18", "spa_t14"],
            "strategy_role": ["usable_now", "usable_now", "candidate_with_penalty"],
            "feasibility_score": [4, 5, 2],
            "max_lico_distance_m": [80.0, 140.0, 20.0],
        }
    )
    observed_executions = pl.DataFrame(
        {
            "schema_version": [1, 1, 1, 1],
            "plan_id": ["experimental", "experimental", "experimental", "experimental"],
            "file_name": ["run.duckdb", "run.duckdb", "run.duckdb", "run.duckdb"],
            "run_id": ["run_01", "run_01", "run_01", "run_01"],
            "lap_number": [22, 22, 23, 23],
            "zone_id": ["spa_t01", "spa_t18", "spa_t01", "spa_t18"],
            "cue_trigger_m": [350.0, 6000.0, 350.0, 6000.0],
            "planned_lift_start_m": [350.0, 6000.0, 350.0, 6000.0],
            "actual_lift_start_m": [349.0, None, 348.0, 5990.0],
            "actual_lift_distance_before_brake_m": [61.0, None, 62.0, 110.0],
            "actual_brake_start_m": [410.0, 6100.0, 410.0, 6100.0],
            "cue_error_m": [-1.0, None, -2.0, -10.0],
            "fuel_saved_vs_baseline_l": [0.04, 0.0, 0.05, 0.07],
            "time_lost_vs_baseline_s": [0.06, 0.0, 0.08, 0.12],
            "execution_quality": ["valid", "missed", "valid", "valid"],
            "notes": ["under-executed lap", "under-executed lap", "", ""],
        }
    )
    context = ExperimentalLapReplannerContext(
        variant_name="range_aware_all_eligible_zones",
        static_plan=static_plan,
        robust_zone_models=robust_zone_models,
        robust_ranges=robust_ranges,
        zone_priors=zone_priors,
        adaptive_scope="all_eligible_zones",
    )
    config = ExperimentalLapReplannerConfig(
        target_fuel_saved_per_lap_l=0.08,
        planning_modes=("static", "adaptive"),
    )
    lap_context = build_experimental_lap_race_state_context(
        pl.DataFrame(
            {
                "run_id": ["run_01"] * 4,
                "file_name": ["run.duckdb"] * 4,
                "lap_number": [22, 22, 23, 23],
                "zone_id": ["spa_t01", "spa_t18", "spa_t01", "spa_t18"],
                "zone_start_m": [100.0, 6200.0, 100.0, 6200.0],
                "fuel_start_l": [50.0, 47.0, 45.0, 42.0],
                "fuel_end_l": [49.6, 46.6, 44.6, 41.6],
                "stint_index": [1, 1, 2, 2],
                "carcass_temp_zone_start_c": [88.0, 92.0, 94.0, 96.0],
                "carcass_temp_zone_start_delta_vs_baseline_c": [-2.0, -1.0, 3.0, 4.0],
            }
        )
    )

    lap_summary, lap_plan, scenario_summary = (
        simulate_experimental_lap_replanning_from_observed_executions(
            context,
            observed_executions,
            config=config,
            lap_context_frame=lap_context,
        )
    )

    static_lap1 = lap_summary.filter(
        (pl.col("planning_mode") == "static") & (pl.col("lap_number") == 22)
    ).row(0, named=True)
    adaptive_lap1 = lap_summary.filter(
        (pl.col("planning_mode") == "adaptive") & (pl.col("lap_number") == 22)
    ).row(0, named=True)

    assert static_lap1["scenario_id"] == "observed_execution:run_01"
    assert static_lap1["fuel_saved_this_lap_l"] == pytest.approx(0.04)
    assert static_lap1["actual_zone_count"] == 1
    assert "spa_t18" not in static_lap1["actual_zone_ids"]
    assert static_lap1["fuel_load_band"] == "heavy"
    assert static_lap1["tire_regime_label"] == "baseline_like"
    assert adaptive_lap1["driver_fuel_execution_scale"] == pytest.approx(1.0)
    assert adaptive_lap1["next_lap_driver_fuel_execution_scale"] < 1.0
    assert adaptive_lap1["next_lap_driver_zone_execution_scale_count"] >= 2
    assert "spa_t14" in adaptive_lap1["next_lap_selected_zone_ids"]
    adaptive_lap2_plan = lap_plan.filter(
        (pl.col("planning_mode") == "adaptive") & (pl.col("lap_number") == 23)
    )
    adaptive_t01 = adaptive_lap2_plan.filter(pl.col("zone_id") == "spa_t01").row(0, named=True)
    adaptive_t18 = adaptive_lap2_plan.filter(pl.col("zone_id") == "spa_t18").row(0, named=True)
    assert adaptive_t01["applied_zone_specific_execution_scale"] is True
    assert adaptive_t18["applied_zone_specific_execution_scale"] is True
    assert adaptive_t01["applied_zone_execution_support_rows"] == 1
    assert adaptive_t18["applied_zone_execution_support_rows"] == 1
    assert (
        adaptive_t01["applied_driver_fuel_execution_scale"]
        > adaptive_t18["applied_driver_fuel_execution_scale"]
    )
    assert not lap_plan.is_empty()
    assert scenario_summary.filter(pl.col("planning_mode") == "adaptive")[
        "target_met"
    ].item() is True


def test_fuel_load_conditioning_changes_adaptive_expected_time_monotonically() -> None:
    static_plan = pl.DataFrame(
        {
            "zone_id": ["spa_t18"],
            "display_label": ["T18"],
            "selected_lico_distance_m": [100.0],
            "is_selected_for_lico": [True],
            "predicted_fuel_saved_l": [0.07],
            "predicted_time_lost_s": [0.12],
            "plan_status": ["target_met"],
            "model_status": ["model_ready"],
            "support_score": [0.95],
            "recommended_range_start_m": [100.0],
            "recommended_range_end_m": [130.0],
        }
    )
    robust_zone_models = pl.DataFrame(
        {
            "zone_id": ["spa_t18", "spa_t18"],
            "display_label": ["T18", "T18"],
            "lico_distance_m": [100.0, 130.0],
            "robust_predicted_fuel_saved_l": [0.05, 0.07],
            "robust_predicted_time_lost_s": [0.08, 0.12],
            "robust_predicted_fuel_saved_per_second_lps": [0.625, 0.5833333333333334],
            "is_extrapolated": [False, False],
            "model_status": ["model_ready", "model_ready"],
            "quality_flags": ["", ""],
            "support_score": [0.95, 0.94],
        }
    )
    robust_ranges = pl.DataFrame(
        {
            "zone_id": ["spa_t18"],
            "display_label": ["T18"],
            "selected_lico_distance_m": [100.0],
            "recommended_range_start_m": [100.0],
            "recommended_range_end_m": [130.0],
            "recommended_range_width_m": [30.0],
        }
    )
    observed_executions = pl.DataFrame(
        {
            "schema_version": [1, 1],
            "plan_id": ["experimental", "experimental"],
            "file_name": ["run.duckdb", "run.duckdb"],
            "run_id": ["run_01", "run_01"],
            "lap_number": [22, 23],
            "zone_id": ["spa_t18", "spa_t18"],
            "cue_trigger_m": [6000.0, 6000.0],
            "planned_lift_start_m": [6000.0, 6000.0],
            "actual_lift_start_m": [5985.0, 5985.0],
            "actual_lift_distance_before_brake_m": [110.0, 110.0],
            "actual_brake_start_m": [6100.0, 6100.0],
            "cue_error_m": [-15.0, -15.0],
            "fuel_saved_vs_baseline_l": [0.04, 0.07],
            "time_lost_vs_baseline_s": [0.08, 0.12],
            "execution_quality": ["valid", "valid"],
            "notes": ["", ""],
        }
    )
    context = ExperimentalLapReplannerContext(
        variant_name="range_aware_selected_zones",
        static_plan=static_plan,
        robust_zone_models=robust_zone_models,
        robust_ranges=robust_ranges,
        adaptive_scope="selected_zones",
    )
    config = ExperimentalLapReplannerConfig(
        target_fuel_saved_per_lap_l=0.07,
        planning_modes=("adaptive",),
        fuel_load_conditioning_enabled=True,
    )
    heavy_lap_context = pl.DataFrame(
        {
            "scenario_id": ["observed_execution:run_01", "observed_execution:run_01"],
            "run_id": ["run_01", "run_01"],
            "lap_number": [22, 23],
            "lap_index_in_run": [1, 2],
            "total_laps_in_run": [2, 2],
            "lap_fuel_start_l": [55.0, 52.0],
            "lap_fuel_end_l": [54.6, 51.6],
            "lap_fuel_used_total_l": [0.4, 0.4],
            "fuel_load_ratio": [0.9, 0.8],
            "fuel_load_band": ["heavy", "heavy"],
            "lap_stint_index": [1, 2],
            "lap_start_carcass_temp_c": [90.0, 92.0],
            "lap_start_carcass_temp_delta_vs_baseline_c": [0.0, 0.0],
            "lap_mean_carcass_temp_delta_vs_baseline_c": [0.0, 0.0],
            "tire_regime_label": ["baseline_like", "baseline_like"],
            "lap_context_label": ["heavy|baseline_like|stint_1", "heavy|baseline_like|stint_2"],
        }
    )
    light_lap_context = heavy_lap_context.with_columns(
        pl.lit("light").alias("fuel_load_band"),
        pl.lit(0.1).alias("fuel_load_ratio"),
        pl.when(pl.col("lap_number") == 22)
        .then(pl.lit("light|baseline_like|stint_1"))
        .otherwise(pl.lit("light|baseline_like|stint_2"))
        .alias("lap_context_label"),
    )

    heavy_summary, _, _ = simulate_experimental_lap_replanning_from_observed_executions(
        context,
        observed_executions,
        config=config,
        lap_context_frame=heavy_lap_context,
    )
    light_summary, _, _ = simulate_experimental_lap_replanning_from_observed_executions(
        context,
        observed_executions,
        config=config,
        lap_context_frame=light_lap_context,
    )

    heavy_lap1 = heavy_summary.row(0, named=True)
    light_lap1 = light_summary.row(0, named=True)

    assert heavy_lap1["lap_target_fuel_saved_l"] == pytest.approx(light_lap1["lap_target_fuel_saved_l"])
    assert heavy_lap1["fuel_saved_this_lap_l"] == pytest.approx(light_lap1["fuel_saved_this_lap_l"])
    assert heavy_lap1["planned_fuel_saved_l"] == pytest.approx(light_lap1["planned_fuel_saved_l"])
    assert heavy_lap1["planned_time_lost_s"] > light_lap1["planned_time_lost_s"]
    assert heavy_lap1["next_lap_expected_time_lost_s"] > light_lap1["next_lap_expected_time_lost_s"]


def test_fuel_load_conditioning_stays_bounded_at_extremes() -> None:
    zone_models = pl.DataFrame(
        {
            "zone_id": ["spa_t18", "spa_t18"],
            "display_label": ["T18", "T18"],
            "lico_distance_m": [100.0, 130.0],
            "robust_predicted_fuel_saved_l": [0.05, 0.07],
            "robust_predicted_time_lost_s": [0.08, 0.12],
            "robust_predicted_fuel_saved_per_second_lps": [0.625, 0.5833333333333334],
            "is_extrapolated": [False, False],
            "model_status": ["model_ready", "model_ready"],
            "quality_flags": ["", ""],
            "support_score": [0.95, 0.94],
        }
    )
    config = ExperimentalLapReplannerConfig(
        target_fuel_saved_per_lap_l=0.07,
        fuel_load_conditioning_enabled=True,
        heavy_fuel_load_time_slope=0.8,
        light_fuel_load_time_slope=-0.8,
        min_time_conditioning_multiplier=0.75,
        max_time_conditioning_multiplier=1.25,
    )

    heavy_conditioned = _apply_fuel_load_conditioning_to_zone_models(
        zone_models,
        config=config,
        lap_context={"fuel_load_band": "heavy"},
    )
    light_conditioned = _apply_fuel_load_conditioning_to_zone_models(
        zone_models,
        config=config,
        lap_context={"fuel_load_band": "light"},
    )

    heavy_times = heavy_conditioned["robust_predicted_time_lost_s"].to_list()
    light_times = light_conditioned["robust_predicted_time_lost_s"].to_list()
    heavy_ratios = heavy_conditioned["robust_predicted_fuel_saved_per_second_lps"].to_list()
    light_ratios = light_conditioned["robust_predicted_fuel_saved_per_second_lps"].to_list()

    assert heavy_times == pytest.approx([0.08, 0.15])
    assert light_times == pytest.approx([0.08, 0.09])
    assert heavy_ratios == pytest.approx([0.625, 0.07 / 0.15])
    assert light_ratios == pytest.approx([0.625, 0.07 / 0.09])


def test_summarizes_race_state_context_effects() -> None:
    lap_summary = pl.DataFrame(
        {
            "variant_name": ["robust", "robust", "robust"],
            "planning_mode": ["adaptive", "adaptive", "adaptive"],
            "fuel_load_band": ["heavy", "heavy", "light"],
            "tire_regime_label": ["baseline_like", "baseline_like", "hotter_than_baseline"],
            "planned_time_lost_s": [0.20, 0.30, 0.10],
            "time_lost_this_lap_s": [0.22, 0.35, 0.08],
            "planned_fuel_saved_l": [0.05, 0.06, 0.03],
            "fuel_saved_this_lap_l": [0.04, 0.07, 0.03],
            "next_lap_expected_time_lost_s": [0.25, 0.28, 0.09],
            "next_lap_expected_fuel_saved_l": [0.06, 0.06, 0.03],
        }
    )

    summary = summarize_experimental_race_state_context_effects(lap_summary)

    heavy = summary.filter(
        (pl.col("fuel_load_band") == "heavy")
        & (pl.col("tire_regime_label") == "baseline_like")
    ).row(0, named=True)
    light = summary.filter(pl.col("fuel_load_band") == "light").row(0, named=True)

    assert heavy["lap_count"] == 2
    assert heavy["mean_planned_time_lost_s"] == pytest.approx(0.25)
    assert heavy["mean_actual_time_lost_s"] == pytest.approx(0.285)
    assert heavy["mean_time_residual_s"] == pytest.approx(0.035)
    assert heavy["mean_actual_fuel_saved_l"] == pytest.approx(0.055)
    assert light["mean_next_lap_expected_fuel_saved_l"] == pytest.approx(0.03)


def test_driver_execution_calibration_reduces_next_lap_expected_fuel_after_under_execution() -> None:
    static_plan = pl.DataFrame(
        {
            "zone_id": ["spa_t18"],
            "display_label": ["T18"],
            "selected_lico_distance_m": [100.0],
            "is_selected_for_lico": [True],
            "predicted_fuel_saved_l": [0.07],
            "predicted_time_lost_s": [0.12],
            "plan_status": ["target_met"],
            "model_status": ["model_ready"],
            "support_score": [0.95],
            "recommended_range_start_m": [100.0],
            "recommended_range_end_m": [130.0],
        }
    )
    robust_zone_models = pl.DataFrame(
        {
            "zone_id": ["spa_t18", "spa_t18"],
            "display_label": ["T18", "T18"],
            "lico_distance_m": [100.0, 130.0],
            "robust_predicted_fuel_saved_l": [0.05, 0.07],
            "robust_predicted_time_lost_s": [0.08, 0.12],
            "robust_predicted_fuel_saved_per_second_lps": [0.625, 0.5833333333333334],
            "is_extrapolated": [False, False],
            "model_status": ["model_ready", "model_ready"],
            "quality_flags": ["", ""],
            "support_score": [0.95, 0.94],
        }
    )
    robust_ranges = pl.DataFrame(
        {
            "zone_id": ["spa_t18"],
            "display_label": ["T18"],
            "selected_lico_distance_m": [100.0],
            "recommended_range_start_m": [100.0],
            "recommended_range_end_m": [130.0],
            "recommended_range_width_m": [30.0],
        }
    )
    context = ExperimentalLapReplannerContext(
        variant_name="range_aware_selected_zones",
        static_plan=static_plan,
        robust_zone_models=robust_zone_models,
        robust_ranges=robust_ranges,
        adaptive_scope="selected_zones",
    )
    scenarios = (
        ExperimentalLapReplanningScenario(
            scenario_id="under_execution",
            total_laps=2,
            events=(
                ExperimentalLapExecutionEvent(
                    lap_number=1,
                    scenario_event="under_execution",
                    execution_quality="partial",
                    fuel_saved_scale=0.5,
                    time_lost_scale=1.2,
                ),
            ),
        ),
    )
    config = ExperimentalLapReplannerConfig(
        target_fuel_saved_per_lap_l=0.07,
        planning_modes=("adaptive",),
        execution_calibration_enabled=True,
        execution_calibration_window_laps=3,
        max_driver_fuel_execution_scale=1.0,
    )

    lap_summary, _, _ = simulate_experimental_lap_replanning(
        context,
        scenarios,
        config=config,
    )

    lap1 = lap_summary.filter(pl.col("lap_number") == 1).row(0, named=True)
    assert lap1["driver_fuel_execution_scale"] == pytest.approx(1.0)
    assert lap1["next_lap_driver_fuel_execution_scale"] == pytest.approx(0.65)
    assert lap1["next_lap_driver_time_execution_scale"] > 1.0
    assert lap1["next_lap_expected_fuel_saved_l"] < lap1["planned_fuel_saved_l"]


def test_zone_specific_execution_calibration_overrides_global_scale_per_zone() -> None:
    zone_models = pl.DataFrame(
        {
            "zone_id": ["spa_t01", "spa_t18"],
            "display_label": ["T01", "T18"],
            "lico_distance_m": [70.0, 130.0],
            "robust_predicted_fuel_saved_l": [0.05, 0.05],
            "robust_predicted_time_lost_s": [0.08, 0.10],
            "robust_predicted_fuel_saved_per_second_lps": [0.625, 0.5],
            "is_extrapolated": [False, False],
            "model_status": ["model_ready", "model_ready"],
            "quality_flags": ["", ""],
            "support_score": [0.97, 0.94],
        }
    )

    conditioned = _apply_driver_execution_calibration_to_zone_models(
        zone_models,
        driver_execution_scales={"fuel_scale": 0.65, "time_scale": 0.8},
        driver_zone_execution_scales={
            "spa_t01": {"fuel_scale": 0.80, "time_scale": 0.90, "support_rows": 2.0},
            "spa_t18": {"fuel_scale": 0.65, "time_scale": 0.80, "support_rows": 1.0},
        },
    )

    t01 = conditioned.filter(pl.col("zone_id") == "spa_t01").row(0, named=True)
    t18 = conditioned.filter(pl.col("zone_id") == "spa_t18").row(0, named=True)

    assert t01["robust_predicted_fuel_saved_l"] == pytest.approx(0.04)
    assert t18["robust_predicted_fuel_saved_l"] == pytest.approx(0.0325)
    assert t01["robust_predicted_time_lost_s"] == pytest.approx(0.072)
    assert t18["robust_predicted_time_lost_s"] == pytest.approx(0.08)


def test_summarizes_zone_execution_calibration() -> None:
    lap_summary = pl.DataFrame(
        {
            "scenario_id": ["s1", "s1"],
            "variant_name": ["v1", "v1"],
            "planning_mode": ["adaptive", "adaptive"],
            "lap_number": [1, 2],
            "driver_fuel_execution_scale": [0.8, 0.9],
            "driver_time_execution_scale": [0.85, 0.95],
        }
    )
    lap_plan = pl.DataFrame(
        {
            "scenario_id": ["s1", "s1", "s1"],
            "variant_name": ["v1", "v1", "v1"],
            "planning_mode": ["adaptive", "adaptive", "adaptive"],
            "lap_number": [1, 1, 2],
            "zone_id": ["spa_t01", "spa_t18", "spa_t01"],
            "display_label": ["T01", "T18", "T01"],
            "source_model_status": ["model_ready", "model_ready", "model_ready"],
            "applied_driver_fuel_execution_scale": [0.9, 0.7, 1.0],
            "applied_driver_time_execution_scale": [0.9, 0.8, 1.05],
            "applied_zone_execution_support_rows": [1, 1, 2],
            "applied_zone_specific_execution_scale": [True, False, True],
            "actual_is_executed": [True, False, True],
        }
    )

    summary = summarize_experimental_zone_execution_calibration(lap_summary, lap_plan)
    t01 = summary.filter(pl.col("zone_id") == "spa_t01").row(0, named=True)
    t18 = summary.filter(pl.col("zone_id") == "spa_t18").row(0, named=True)

    assert t01["sample_count"] == 2
    assert t01["zone_specific_usage_rate"] == pytest.approx(1.0)
    assert t01["mean_fuel_scale_delta_vs_global"] == pytest.approx(0.1)
    assert t18["zone_specific_usage_rate"] == pytest.approx(0.0)
    assert t18["execution_rate"] == pytest.approx(0.0)


def test_builds_live_transition_preview() -> None:
    lap_summary = pl.DataFrame(
        {
            "scenario_id": ["s1", "s1"],
            "variant_name": ["v1", "v1"],
            "planning_mode": ["adaptive", "adaptive"],
            "lap_number": [1, 2],
            "total_laps": [2, 2],
            "scenario_event": ["nominal", "nominal"],
            "execution_quality": ["valid", "valid"],
            "notes": ["", ""],
            "next_lap_target_fuel_saved_l": [0.10, 0.0],
            "next_lap_expected_fuel_saved_l": [0.09, 0.0],
            "next_lap_expected_time_lost_s": [0.20, 0.0],
            "next_lap_selected_zone_count": [1, 0],
            "next_lap_selected_zone_ids": ["spa_t18", ""],
            "next_lap_driver_fuel_execution_scale": [0.8, 1.0],
            "next_lap_driver_time_execution_scale": [0.9, 1.0],
            "next_lap_driver_zone_execution_scale_count": [1, 0],
        }
    )
    lap_plan = pl.DataFrame(
        {
            "scenario_id": ["s1"],
            "variant_name": ["v1"],
            "planning_mode": ["adaptive"],
            "lap_number": [2],
            "zone_id": ["spa_t18"],
            "display_label": ["T18"],
            "selected_lico_distance_m": [130.0],
            "expected_fuel_saved_l": [0.09],
            "expected_time_lost_s": [0.20],
            "source_model_status": ["model_ready"],
            "recommended_range_start_m": [100.0],
            "recommended_range_end_m": [140.0],
            "applied_driver_fuel_execution_scale": [0.8],
            "applied_driver_time_execution_scale": [0.9],
            "applied_zone_execution_support_rows": [2],
            "applied_zone_specific_execution_scale": [True],
        }
    )

    preview = build_experimental_live_transition_preview(lap_summary, lap_plan)
    row = preview.row(0, named=True)

    assert preview.height == 1
    assert row["current_lap_number"] == 1
    assert row["next_lap_number"] == 2
    assert row["next_zone_id"] == "spa_t18"
    assert row["next_applied_zone_specific_execution_scale"] is True


def test_builds_live_transition_preview_with_nonconsecutive_lap_numbers() -> None:
    lap_summary = pl.DataFrame(
        {
            "scenario_id": ["s1", "s1"],
            "variant_name": ["v1", "v1"],
            "planning_mode": ["adaptive", "adaptive"],
            "lap_number": [13, 15],
            "total_laps": [2, 2],
            "scenario_event": ["observed_execution", "observed_execution"],
            "execution_quality": ["valid", "valid"],
            "notes": ["", ""],
            "next_lap_target_fuel_saved_l": [0.10, 0.0],
            "next_lap_expected_fuel_saved_l": [0.09, 0.0],
            "next_lap_expected_time_lost_s": [0.20, 0.0],
            "next_lap_selected_zone_count": [1, 0],
            "next_lap_selected_zone_ids": ["spa_t18", ""],
            "next_lap_driver_fuel_execution_scale": [0.8, 1.0],
            "next_lap_driver_time_execution_scale": [0.9, 1.0],
            "next_lap_driver_zone_execution_scale_count": [1, 0],
        }
    )
    lap_plan = pl.DataFrame(
        {
            "scenario_id": ["s1"],
            "variant_name": ["v1"],
            "planning_mode": ["adaptive"],
            "lap_number": [15],
            "zone_id": ["spa_t18"],
            "display_label": ["T18"],
            "selected_lico_distance_m": [130.0],
            "expected_fuel_saved_l": [0.09],
            "expected_time_lost_s": [0.20],
            "source_model_status": ["model_ready"],
            "recommended_range_start_m": [100.0],
            "recommended_range_end_m": [140.0],
            "applied_driver_fuel_execution_scale": [0.8],
            "applied_driver_time_execution_scale": [0.9],
            "applied_zone_execution_support_rows": [2],
            "applied_zone_specific_execution_scale": [True],
        }
    )

    preview = build_experimental_live_transition_preview(lap_summary, lap_plan)

    assert preview.height == 1
    assert preview.row(0, named=True)["next_lap_number"] == 15


def test_builds_shadow_adaptive_transition_comparison_and_summaries() -> None:
    live_transition_preview = pl.DataFrame(
        {
            "scenario_id": ["observed_execution:run_01"] * 4,
            "variant_name": ["selected_zones_latency_v2_baseline"] * 4,
            "planning_mode": ["static", "static", "adaptive", "adaptive"],
            "current_lap_number": [8, 8, 8, 8],
            "next_lap_number": [9, 9, 9, 9],
            "current_scenario_event": ["observed_execution"] * 4,
            "current_execution_quality": ["valid"] * 4,
            "current_notes": [""] * 4,
            "next_lap_target_fuel_saved_l": [0.30, 0.30, 0.31, 0.31],
            "next_lap_expected_fuel_saved_l": [0.30, 0.30, 0.31, 0.31],
            "next_lap_expected_time_lost_s": [1.00, 1.00, 1.04, 1.04],
            "next_lap_selected_zone_count": [2, 2, 2, 2],
            "next_lap_selected_zone_ids": ["spa_t01|spa_t18"] * 4,
            "next_lap_driver_fuel_execution_scale": [1.0, 1.0, 0.9, 0.9],
            "next_lap_driver_time_execution_scale": [1.0, 1.0, 0.95, 0.95],
            "next_lap_driver_zone_execution_scale_count": [0, 0, 1, 1],
            "next_zone_id": ["spa_t01", "spa_t18", "spa_t01", "spa_t18"],
            "next_display_label": ["T01", "T18", "T01", "T18"],
            "next_selected_lico_distance_m": [70.0, 132.0, 60.0, 140.0],
            "next_expected_fuel_saved_by_zone_l": [0.04, 0.06, 0.035, 0.07],
            "next_expected_time_lost_by_zone_s": [0.14, 0.24, 0.13, 0.27],
            "next_source_model_status": ["model_ready"] * 4,
            "next_recommended_range_start_m": [60.0, 120.0, 60.0, 120.0],
            "next_recommended_range_end_m": [80.0, 145.0, 80.0, 145.0],
            "next_applied_driver_fuel_execution_scale": [1.0, 1.0, 0.9, 0.92],
            "next_applied_driver_time_execution_scale": [1.0, 1.0, 0.95, 0.96],
            "next_applied_zone_execution_support_rows": [0, 0, 1, 2],
            "next_applied_zone_specific_execution_scale": [False, False, True, True],
        }
    )

    comparison = build_experimental_shadow_adaptive_transition_comparison(
        live_transition_preview
    )
    handoff_summary = summarize_experimental_shadow_adaptive_handoffs(comparison)
    zone_summary = summarize_experimental_shadow_adaptive_zones(comparison)

    assert comparison.height == 2
    t01 = comparison.filter(pl.col("zone_id") == "spa_t01").row(0, named=True)
    t18 = comparison.filter(pl.col("zone_id") == "spa_t18").row(0, named=True)
    assert t01["change_type"] == "shorter_distance"
    assert t01["distance_delta_m"] == pytest.approx(-10.0)
    assert t18["change_type"] == "longer_distance"
    assert t18["distance_delta_m"] == pytest.approx(8.0)

    handoff = handoff_summary.row(0, named=True)
    assert handoff["run_id"] == "run_01"
    assert handoff["changed_zone_count"] == 2
    assert handoff["mean_abs_distance_delta_m"] == pytest.approx(9.0)
    assert handoff["expected_fuel_saved_delta_l"] == pytest.approx(0.005)

    t18_summary = zone_summary.filter(pl.col("zone_id") == "spa_t18").row(0, named=True)
    assert t18_summary["changed_count"] == 1
    assert t18_summary["mean_distance_delta_m"] == pytest.approx(8.0)


def test_builds_guarded_adaptive_live_transition_preview() -> None:
    live_transition_preview = pl.DataFrame(
        {
            "scenario_id": ["observed_execution:run_01"] * 4,
            "variant_name": ["selected_zones_latency_v2_baseline"] * 4,
            "planning_mode": ["static", "static", "adaptive", "adaptive"],
            "current_lap_number": [8, 8, 8, 8],
            "next_lap_number": [9, 9, 9, 9],
            "current_scenario_event": ["observed_execution"] * 4,
            "current_execution_quality": ["valid"] * 4,
            "current_notes": [""] * 4,
            "next_lap_target_fuel_saved_l": [0.30, 0.30, 0.30, 0.30],
            "next_lap_expected_fuel_saved_l": [0.10, 0.10, 0.10, 0.10],
            "next_lap_expected_time_lost_s": [0.30, 0.30, 0.30, 0.30],
            "next_lap_selected_zone_count": [2, 2, 2, 2],
            "next_lap_selected_zone_ids": ["spa_t01|spa_t18"] * 4,
            "next_lap_driver_fuel_execution_scale": [1.0, 1.0, 1.1, 1.1],
            "next_lap_driver_time_execution_scale": [1.0, 1.0, 0.8, 0.8],
            "next_lap_driver_zone_execution_scale_count": [0, 0, 2, 2],
            "next_zone_id": ["spa_t01", "spa_t18", "spa_t01", "spa_t18"],
            "next_display_label": ["T01", "T18", "T01", "T18"],
            "next_selected_lico_distance_m": [70.0, 140.0, 40.0, 132.0],
            "next_expected_fuel_saved_by_zone_l": [0.04, 0.06, 0.02, 0.055],
            "next_expected_time_lost_by_zone_s": [0.14, 0.24, 0.05, 0.19],
            "next_source_model_status": ["model_ready"] * 4,
            "next_recommended_range_start_m": [60.0, 120.0, 60.0, 120.0],
            "next_recommended_range_end_m": [80.0, 145.0, 80.0, 145.0],
            "next_applied_driver_fuel_execution_scale": [1.0, 1.0, 1.1, 1.1],
            "next_applied_driver_time_execution_scale": [1.0, 1.0, 0.8, 0.8],
            "next_applied_zone_execution_support_rows": [0, 0, 1, 3],
            "next_applied_zone_specific_execution_scale": [False, False, True, True],
        }
    )

    guarded_preview, detail, summary = build_experimental_guarded_adaptive_live_transition_preview(
        live_transition_preview,
        config=ExperimentalAdaptiveHandoffGuardrailConfig(
            max_abs_distance_delta_m=20.0,
            low_support_rows_threshold=2,
            low_support_max_abs_distance_delta_m=10.0,
        ),
    )

    assert guarded_preview.height == 2
    t01 = guarded_preview.filter(pl.col("next_zone_id") == "spa_t01").row(0, named=True)
    t18 = guarded_preview.filter(pl.col("next_zone_id") == "spa_t18").row(0, named=True)
    assert t01["planning_mode"] == "adaptive_guarded"
    assert t01["next_selected_lico_distance_m"] == pytest.approx(60.0)
    assert t18["next_selected_lico_distance_m"] == pytest.approx(132.0)

    detail_t01 = detail.filter(pl.col("zone_id") == "spa_t01").row(0, named=True)
    assert detail_t01["guardrail_reason"] == "clamped_low_support"
    assert detail_t01["guarded_distance_delta_m"] == pytest.approx(-10.0)

    handoff = summary.row(0, named=True)
    assert handoff["clamped_zone_count"] == 1
    assert handoff["guarded_zone_count"] == 2
    assert handoff["target_met_after_guardrails"] is False
