from __future__ import annotations

import json
import subprocess
from pathlib import Path

import polars as pl

from licor.analysis.experimental_zone_dynamics import (
    ExperimentalZoneDynamicsConfig,
    build_experimental_zone_dynamics,
    build_labeled_experimental_lap_samples,
)
from licor.analysis.experimental_zone_dynamics_driver_review import (
    summarize_experimental_zone_dynamics_driver_review,
)
from licor.analysis.experimental_zone_dynamics_model import (
    ExperimentalZoneDynamicsModelConfig,
    compare_zone_dynamics_models,
    score_zone_dynamics_models,
)
from licor.analysis.experimental_robust_optimizer import (
    build_experimental_range_aware_plan,
    build_experimental_robust_zone_models,
    compare_experimental_plan_variants,
    compare_experimental_zone_plans,
    summarize_experimental_robust_recommended_ranges,
)
from licor.analysis.experimental_lap_replanner import (
    ExperimentalAdaptiveHandoffGuardrailConfig,
    ExperimentalLapExecutionEvent,
    ExperimentalLapReplannerConfig,
    ExperimentalLapReplannerContext,
    ExperimentalLapReplanningScenario,
    build_experimental_guarded_adaptive_live_transition_preview,
    build_experimental_lap_race_state_context,
    build_experimental_live_transition_preview,
    build_experimental_shadow_adaptive_transition_comparison,
    simulate_experimental_lap_replanning,
    simulate_experimental_lap_replanning_from_observed_executions,
    summarize_experimental_race_state_context_effects,
    summarize_experimental_shadow_adaptive_handoffs,
    summarize_experimental_shadow_adaptive_zones,
    summarize_experimental_zone_execution_calibration,
)
from licor.analysis.experimental_live_replay_validation import (
    ExperimentalLiveReplayValidationConfig,
    build_experimental_live_replay_plan,
    replay_experimental_live_replay_plan,
)
from licor.analysis.live_plan import (
    LiveCuePlanConfig,
    build_live_cue_executions_from_zone_passes,
    build_live_cue_plan,
)
from licor.analysis.experimental_zone_reclassification import (
    apply_experimental_strategy_prior_overrides,
    apply_experimental_zone_reclassification,
    build_experimental_status_frame,
    summarize_experimental_zone_reclassification,
)
from licor.analysis.processed_artifacts import build_labeled_zone_passes
from licor.analysis.strategy_priors import load_strategy_prior_table
from licor.analysis.track_zones import load_track_zone_table, track_zones_to_frame
from licor.analysis.zone_optimizer import ZoneOptimizerConfig, optimize_zone_lico_plan
from licor.analysis.zone_plan_diagnostics import (
    ZonePlanSensitivityScenario,
    build_zone_marginal_efficiency,
    summarize_zone_plan_sensitivity,
)
from licor.reports.experimental_zone_dynamics_report import (
    create_experimental_zone_dynamics_report_figure,
    write_experimental_zone_dynamics_report_html,
)
from licor.reports.experimental_zone_dynamics_driver_review_report import (
    write_experimental_zone_dynamics_driver_review_report_html,
)
from licor.reports.zone_model_report import (
    create_zone_model_report_figure,
    write_zone_model_report_html,
)
from licor.reports.experimental_lap_replanner_report import (
    create_experimental_lap_replanner_report_figure,
    create_experimental_shadow_adaptive_summary_figure,
    create_experimental_zone_execution_calibration_figure,
    write_experimental_guarded_adaptive_handoff_report_html,
    write_experimental_lap_replanner_report_html,
    write_experimental_lap_replanner_validation_report_html,
    write_experimental_shadow_adaptive_report_html,
)
from licor.reports.experimental_live_replay_validation_report import (
    create_experimental_live_replay_validation_figure,
    write_experimental_live_replay_validation_report_html,
)
from licor.reports.zone_plan_report import (
    create_zone_plan_report_figure,
    write_zone_plan_report_html,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATASET_LABEL_FILE = PROJECT_ROOT / "config/datasets/spa_lmp2_v2_2026-05-21.json"
TRACK_ZONE_FILE = PROJECT_ROOT / "config/track_zones/spa_lmp2_zones.draft.json"
DRIVER_REVIEW_FILE = (
    PROJECT_ROOT / "config/driver_reviews/spa_lmp2_v2_zone_review_2026-05-21.json"
)
PROTOCOL_FILE = PROJECT_ROOT / "config/collection_protocols/spa_lmp2_v2_protocol.json"
STRATEGY_PRIOR_FILE = (
    PROJECT_ROOT / "config/strategy_priors/spa_lmp2_driver_priors_2026-05-14.json"
)
CURRENT_PROCESSED_DIR = PROJECT_ROOT / "data/processed"
OUTPUT_DIR = PROJECT_ROOT / "data/processed/experimental/spa_dynamics_v1"

LIVE_CUE_LATENCY_COMPENSATION_S = 0.35
LIVE_CUE_LATENCY_REFERENCE_SPEED_KPH = 250.0


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    zone_passes = build_labeled_zone_passes(
        dataset_label_file=DATASET_LABEL_FILE,
        track_zone_file=TRACK_ZONE_FILE,
        project_root=PROJECT_ROOT,
        driver_review_file=DRIVER_REVIEW_FILE,
    )
    lap_samples = build_labeled_experimental_lap_samples(
        dataset_label_file=DATASET_LABEL_FILE,
        project_root=PROJECT_ROOT,
    )
    zone_dynamics = build_experimental_zone_dynamics(
        zone_passes,
        lap_samples,
        config=ExperimentalZoneDynamicsConfig(),
    )
    zone_dynamics_summary = _summarize_zone_dynamics(zone_dynamics)

    model_config = ExperimentalZoneDynamicsModelConfig()
    model_comparison = compare_zone_dynamics_models(zone_dynamics, config=model_config)
    model_scores = score_zone_dynamics_models(zone_dynamics, config=model_config)
    current_zone_status = _current_zone_status()
    driver_review = summarize_experimental_zone_dynamics_driver_review(
        zone_dynamics,
        model_comparison=model_comparison,
        current_zone_status=current_zone_status,
    )

    base_zone_models = pl.read_csv(CURRENT_PROCESSED_DIR / "spa_lmp2_zone_piecewise_models.csv")
    base_zone_priors = load_strategy_prior_table(STRATEGY_PRIOR_FILE).to_frame()
    target_fuel_saved_l = _current_target_fuel_saved_l()
    zone_reclassification = summarize_experimental_zone_reclassification(base_zone_models)
    reclassified_zone_models = apply_experimental_zone_reclassification(
        base_zone_models,
        zone_reclassification,
    )
    reclassified_zone_priors = apply_experimental_strategy_prior_overrides(
        base_zone_priors,
        zone_reclassification,
    )
    reclassified_status_frame = build_experimental_status_frame(reclassified_zone_models)
    reclassified_driver_review = summarize_experimental_zone_dynamics_driver_review(
        zone_dynamics,
        model_comparison=model_comparison,
        current_zone_status=reclassified_status_frame,
    )
    promoted_ready_config = ZoneOptimizerConfig(
        target_fuel_saved_per_lap_l=target_fuel_saved_l,
        allowed_model_statuses=("model_ready",),
    )
    promoted_ready_plus_micro_config = ZoneOptimizerConfig(
        target_fuel_saved_per_lap_l=target_fuel_saved_l,
        allowed_model_statuses=("model_ready", "micro_lico_only"),
    )
    reclassified_ready_plan = optimize_zone_lico_plan(
        reclassified_zone_models,
        config=promoted_ready_config,
        zone_priors=reclassified_zone_priors,
    )
    reclassified_ready_plus_micro_plan = optimize_zone_lico_plan(
        reclassified_zone_models,
        config=promoted_ready_plus_micro_config,
        zone_priors=reclassified_zone_priors,
    )
    reclassified_marginal_efficiency = build_zone_marginal_efficiency(
        reclassified_zone_models,
        zone_plan=reclassified_ready_plus_micro_plan,
    )
    reclassified_sensitivity = summarize_zone_plan_sensitivity(
        reclassified_zone_models,
        base_config=promoted_ready_plus_micro_config,
        zone_priors=reclassified_zone_priors,
        scenarios=_experimental_reclassified_scenarios(),
    )
    robust_zone_models = build_experimental_robust_zone_models(
        reclassified_zone_models,
        zone_dynamics,
        model_comparison=model_comparison,
    )
    robust_plan = optimize_zone_lico_plan(
        _optimizer_ready_frame(robust_zone_models),
        config=promoted_ready_plus_micro_config,
        zone_priors=reclassified_zone_priors,
    )
    robust_ranges = summarize_experimental_robust_recommended_ranges(
        robust_zone_models,
        robust_plan,
    )
    robust_plan_comparison = compare_experimental_zone_plans(
        reclassified_ready_plus_micro_plan,
        robust_plan,
        robust_ranges,
        robust_zone_models,
    )
    range_aware_selected_zones_plan = build_experimental_range_aware_plan(
        robust_zone_models,
        robust_ranges,
        target_fuel_saved_per_lap_l=target_fuel_saved_l,
        zone_priors=reclassified_zone_priors,
        allowed_model_statuses=promoted_ready_plus_micro_config.allowed_model_statuses,
        top_up_scope="selected_zones",
    )
    range_aware_selected_zones_plan_comparison = compare_experimental_plan_variants(
        robust_plan,
        range_aware_selected_zones_plan,
        robust_ranges,
        robust_zone_models,
        left_prefix="robust",
        right_prefix="range_aware_selected_zones",
    )
    range_aware_all_eligible_plan = build_experimental_range_aware_plan(
        robust_zone_models,
        robust_ranges,
        target_fuel_saved_per_lap_l=target_fuel_saved_l,
        zone_priors=reclassified_zone_priors,
        allowed_model_statuses=promoted_ready_plus_micro_config.allowed_model_statuses,
        top_up_scope="all_eligible_zones",
    )
    range_aware_all_eligible_plan_comparison = compare_experimental_plan_variants(
        robust_plan,
        range_aware_all_eligible_plan,
        robust_ranges,
        robust_zone_models,
        left_prefix="robust",
        right_prefix="range_aware_all_eligible",
    )
    range_aware_variant_summary = _plan_variant_summary_frame(
        {
            "robust": robust_plan,
            "range_aware_selected_zones": range_aware_selected_zones_plan,
            "range_aware_all_eligible_zones": range_aware_all_eligible_plan,
        }
    )
    replanner_contexts = [
        ExperimentalLapReplannerContext(
            variant_name="range_aware_selected_zones",
            static_plan=range_aware_selected_zones_plan,
            robust_zone_models=robust_zone_models,
            robust_ranges=robust_ranges,
            zone_priors=reclassified_zone_priors,
            adaptive_scope="selected_zones",
        ),
        ExperimentalLapReplannerContext(
            variant_name="range_aware_all_eligible_zones",
            static_plan=range_aware_all_eligible_plan,
            robust_zone_models=robust_zone_models,
            robust_ranges=robust_ranges,
            zone_priors=reclassified_zone_priors,
            adaptive_scope="all_eligible_zones",
        ),
    ]
    replanner_config = ExperimentalLapReplannerConfig(
        target_fuel_saved_per_lap_l=target_fuel_saved_l,
        planning_modes=("static", "adaptive"),
        allowed_model_statuses=promoted_ready_plus_micro_config.allowed_model_statuses,
    )
    replanning_scenarios = _experimental_replanning_scenarios()
    replanning_outputs = [
        simulate_experimental_lap_replanning(
            context,
            replanning_scenarios,
            config=replanner_config,
        )
        for context in replanner_contexts
    ]
    replanning_lap_summary = _concat_frames(
        [output[0] for output in replanning_outputs]
    )
    replanning_lap_plan = _concat_frames(
        [output[1] for output in replanning_outputs]
    )
    replanning_scenario_summary = _concat_frames(
        [output[2] for output in replanning_outputs]
    )
    track_zones = track_zones_to_frame(load_track_zone_table(TRACK_ZONE_FILE))
    candidate_track_length_m = _median_track_length_m(lap_samples)
    cue_latency_reference_speeds = _cue_latency_reference_speed_frame(zone_dynamics)
    range_aware_selected_zones_live_input = _attach_cue_latency_reference_speeds(
        range_aware_selected_zones_plan,
        cue_latency_reference_speeds,
    )
    range_aware_all_eligible_live_input = _attach_cue_latency_reference_speeds(
        range_aware_all_eligible_plan,
        cue_latency_reference_speeds,
    )
    live_candidate_selected_plan = build_live_cue_plan(
        range_aware_selected_zones_plan,
        track_zones,
        config=LiveCuePlanConfig(
            plan_id="experimental_live_candidate_range_aware_selected_zones_v1",
            track_name="Spa-Francorchamps",
            car_class="LMP2",
            race_context_id="spa_dynamics_v1_live_candidate",
            minimum_confidence_label="experimental_candidate",
            track_length_m=candidate_track_length_m,
            notes="First pilot live validation candidate from range_aware_selected_zones.",
        ),
    )
    live_candidate_selected_latency_compensated_plan = build_live_cue_plan(
        range_aware_selected_zones_plan,
        track_zones,
        config=LiveCuePlanConfig(
            plan_id="experimental_live_candidate_range_aware_selected_zones_latency_v1",
            track_name="Spa-Francorchamps",
            car_class="LMP2",
            race_context_id="spa_dynamics_v1_live_candidate",
            minimum_confidence_label="experimental_candidate",
            track_length_m=candidate_track_length_m,
            cue_latency_compensation_s=LIVE_CUE_LATENCY_COMPENSATION_S,
            cue_latency_reference_speed_kph=LIVE_CUE_LATENCY_REFERENCE_SPEED_KPH,
            notes=(
                "First pilot live validation candidate from "
                "range_aware_selected_zones with latency compensation v1."
            ),
        ),
    )
    live_candidate_selected_latency_speed_aware_plan = build_live_cue_plan(
        range_aware_selected_zones_live_input,
        track_zones,
        config=LiveCuePlanConfig(
            plan_id="experimental_live_candidate_range_aware_selected_zones_latency_v2",
            track_name="Spa-Francorchamps",
            car_class="LMP2",
            race_context_id="spa_dynamics_v1_live_candidate",
            minimum_confidence_label="experimental_candidate",
            track_length_m=candidate_track_length_m,
            cue_latency_compensation_s=LIVE_CUE_LATENCY_COMPENSATION_S,
            notes=(
                "Speed-aware pilot live validation candidate from "
                "range_aware_selected_zones with latency compensation v2."
            ),
        ),
    )
    live_candidate_all_eligible_plan = build_live_cue_plan(
        range_aware_all_eligible_plan,
        track_zones,
        config=LiveCuePlanConfig(
            plan_id="experimental_live_candidate_range_aware_all_eligible_zones_v1",
            track_name="Spa-Francorchamps",
            car_class="LMP2",
            race_context_id="spa_dynamics_v1_live_candidate",
            minimum_confidence_label="experimental_candidate",
            track_length_m=candidate_track_length_m,
            notes="First pilot live validation candidate from range_aware_all_eligible_zones.",
        ),
    )
    live_candidate_all_eligible_latency_compensated_plan = build_live_cue_plan(
        range_aware_all_eligible_plan,
        track_zones,
        config=LiveCuePlanConfig(
            plan_id=(
                "experimental_live_candidate_range_aware_all_eligible_zones_latency_v1"
            ),
            track_name="Spa-Francorchamps",
            car_class="LMP2",
            race_context_id="spa_dynamics_v1_live_candidate",
            minimum_confidence_label="experimental_candidate",
            track_length_m=candidate_track_length_m,
            cue_latency_compensation_s=LIVE_CUE_LATENCY_COMPENSATION_S,
            cue_latency_reference_speed_kph=LIVE_CUE_LATENCY_REFERENCE_SPEED_KPH,
            notes=(
                "First pilot live validation candidate from "
                "range_aware_all_eligible_zones with latency compensation v1."
            ),
        ),
    )
    live_candidate_all_eligible_latency_speed_aware_plan = build_live_cue_plan(
        range_aware_all_eligible_live_input,
        track_zones,
        config=LiveCuePlanConfig(
            plan_id=(
                "experimental_live_candidate_range_aware_all_eligible_zones_latency_v2"
            ),
            track_name="Spa-Francorchamps",
            car_class="LMP2",
            race_context_id="spa_dynamics_v1_live_candidate",
            minimum_confidence_label="experimental_candidate",
            track_length_m=candidate_track_length_m,
            cue_latency_compensation_s=LIVE_CUE_LATENCY_COMPENSATION_S,
            notes=(
                "Speed-aware pilot live validation candidate from "
                "range_aware_all_eligible_zones with latency compensation v2."
            ),
        ),
    )
    valid_zone_passes = zone_passes.filter(pl.col("validity_label") == "valid")
    observed_execution_source = valid_zone_passes.join(
        zone_dynamics.select(
            "run_id",
            "lap_number",
            "zone_id",
            "stint_index",
            "zone_start_m",
            "carcass_temp_zone_start_c",
            "carcass_temp_zone_start_delta_vs_baseline_c",
            "fuel_saved_vs_baseline_l",
            "time_lost_vs_baseline_s",
        ),
        on=["run_id", "lap_number", "zone_id"],
        how="left",
    )
    observed_lap_context = build_experimental_lap_race_state_context(
        observed_execution_source
    )
    observed_live_cue_plans: list[pl.DataFrame] = []
    observed_live_cue_executions: list[pl.DataFrame] = []
    observed_replanning_outputs = []
    for context in replanner_contexts:
        live_cue_plan = build_live_cue_plan(
            context.static_plan,
            track_zones,
            config=LiveCuePlanConfig(
                plan_id=f"experimental_{context.variant_name}",
                track_name="Spa-Francorchamps",
                car_class="LMP2",
                race_context_id="spa_dynamics_v1_observed_execution",
                minimum_confidence_label="experimental",
                notes="Observed offline replay scaffold from experimental plan.",
            ),
        ).with_columns(pl.lit(context.variant_name).alias("variant_name"))
        live_cue_executions = build_live_cue_executions_from_zone_passes(
            live_cue_plan,
            observed_execution_source,
        ).with_columns(pl.lit(context.variant_name).alias("variant_name"))
        observed_live_cue_plans.append(live_cue_plan)
        observed_live_cue_executions.append(live_cue_executions)
        observed_replanning_outputs.append(
            simulate_experimental_lap_replanning_from_observed_executions(
                context,
                live_cue_executions.drop("variant_name"),
                config=replanner_config,
                lap_context_frame=observed_lap_context,
            )
        )
    observed_live_cue_plan = _concat_frames(observed_live_cue_plans)
    observed_live_cue_execution = _concat_frames(observed_live_cue_executions)
    observed_replanning_lap_summary = _concat_frames(
        [output[0] for output in observed_replanning_outputs]
    )
    observed_replanning_lap_plan = _concat_frames(
        [output[1] for output in observed_replanning_outputs]
    )
    observed_replanning_scenario_summary = _concat_frames(
        [output[2] for output in observed_replanning_outputs]
    )
    observed_context_effect_summary = summarize_experimental_race_state_context_effects(
        observed_replanning_lap_summary
    )
    observed_zone_execution_calibration_summary = (
        summarize_experimental_zone_execution_calibration(
            observed_replanning_lap_summary,
            observed_replanning_lap_plan,
        )
    )
    observed_live_transition_preview = build_experimental_live_transition_preview(
        observed_replanning_lap_summary,
        observed_replanning_lap_plan,
    )
    observed_live_transition_preview = _attach_cue_latency_reference_speeds(
        observed_live_transition_preview,
        cue_latency_reference_speeds,
        zone_key="next_zone_id",
        output_column="next_cue_latency_reference_speed_kph",
    )
    observed_adaptive_live_replay_config = ExperimentalLiveReplayValidationConfig(
        planning_modes=("adaptive",),
        track_name="Spa-Francorchamps",
        car_class="LMP2",
        race_context_id="spa_dynamics_v1_observed_adaptive_replay",
        track_length_m=candidate_track_length_m,
        cue_latency_compensation_s=LIVE_CUE_LATENCY_COMPENSATION_S,
        cue_latency_reference_speed_kph=LIVE_CUE_LATENCY_REFERENCE_SPEED_KPH,
    )
    observed_adaptive_live_replay_plan = build_experimental_live_replay_plan(
        observed_live_transition_preview,
        track_zones,
        config=observed_adaptive_live_replay_config,
    )
    (
        observed_adaptive_live_replay_events,
        observed_adaptive_live_replay_accuracy,
        observed_adaptive_live_replay_validation_rows,
        observed_adaptive_live_replay_handoff_summary,
        observed_adaptive_live_replay_zone_summary,
    ) = replay_experimental_live_replay_plan(
        observed_adaptive_live_replay_plan,
        lap_samples,
        observed_execution_source,
        config=observed_adaptive_live_replay_config,
    )
    selected_latency_v2_shadow_context = ExperimentalLapReplannerContext(
        variant_name="selected_zones_latency_v2_baseline",
        static_plan=range_aware_selected_zones_plan,
        robust_zone_models=robust_zone_models,
        robust_ranges=robust_ranges,
        zone_priors=reclassified_zone_priors,
        adaptive_scope="selected_zones",
    )
    selected_latency_v2_shadow_zone_passes = observed_execution_source.filter(
        (pl.col("collection_design") == "recommendation_execution")
        & (
            pl.col("audio_cue_plan_id")
            == "experimental_live_candidate_range_aware_selected_zones_latency_v2"
        )
    )
    selected_latency_v2_shadow_lap_context = build_experimental_lap_race_state_context(
        selected_latency_v2_shadow_zone_passes
    )
    selected_latency_v2_shadow_live_cue_plan = (
        live_candidate_selected_latency_speed_aware_plan.with_columns(
            pl.lit(selected_latency_v2_shadow_context.variant_name).alias("variant_name")
        )
    )
    selected_latency_v2_shadow_live_cue_execution = (
        build_live_cue_executions_from_zone_passes(
            selected_latency_v2_shadow_live_cue_plan,
            selected_latency_v2_shadow_zone_passes,
        ).with_columns(pl.lit(selected_latency_v2_shadow_context.variant_name).alias("variant_name"))
    )
    (
        selected_latency_v2_shadow_replanning_lap_summary,
        selected_latency_v2_shadow_replanning_lap_plan,
        selected_latency_v2_shadow_replanning_scenario_summary,
    ) = simulate_experimental_lap_replanning_from_observed_executions(
        selected_latency_v2_shadow_context,
        selected_latency_v2_shadow_live_cue_execution.drop("variant_name"),
        config=replanner_config,
        lap_context_frame=selected_latency_v2_shadow_lap_context,
    )
    selected_latency_v2_shadow_live_transition_preview = (
        build_experimental_live_transition_preview(
            selected_latency_v2_shadow_replanning_lap_summary,
            selected_latency_v2_shadow_replanning_lap_plan,
        )
    )
    selected_latency_v2_shadow_live_transition_preview = _attach_cue_latency_reference_speeds(
        selected_latency_v2_shadow_live_transition_preview,
        cue_latency_reference_speeds,
        zone_key="next_zone_id",
        output_column="next_cue_latency_reference_speed_kph",
    )
    selected_latency_v2_shadow_transition_comparison = (
        build_experimental_shadow_adaptive_transition_comparison(
            selected_latency_v2_shadow_live_transition_preview
        )
    )
    selected_latency_v2_shadow_handoff_summary = (
        summarize_experimental_shadow_adaptive_handoffs(
            selected_latency_v2_shadow_transition_comparison
        )
    )
    selected_latency_v2_shadow_zone_summary = (
        summarize_experimental_shadow_adaptive_zones(
            selected_latency_v2_shadow_transition_comparison
        )
    )
    selected_latency_v2_shadow_adaptive_live_replay_config = (
        ExperimentalLiveReplayValidationConfig(
            planning_modes=("adaptive",),
            track_name="Spa-Francorchamps",
            car_class="LMP2",
            race_context_id="spa_dynamics_v1_shadow_selected_latency_v2",
            track_length_m=candidate_track_length_m,
            cue_latency_compensation_s=LIVE_CUE_LATENCY_COMPENSATION_S,
            plan_id_prefix="experimental_shadow_adaptive_replay",
        )
    )
    selected_latency_v2_shadow_adaptive_live_replay_plan = (
        build_experimental_live_replay_plan(
            selected_latency_v2_shadow_live_transition_preview,
            track_zones,
            config=selected_latency_v2_shadow_adaptive_live_replay_config,
        )
    )
    (
        selected_latency_v2_shadow_adaptive_live_replay_events,
        selected_latency_v2_shadow_adaptive_live_replay_accuracy,
        selected_latency_v2_shadow_adaptive_live_replay_validation_rows,
        selected_latency_v2_shadow_adaptive_live_replay_handoff_summary,
        selected_latency_v2_shadow_adaptive_live_replay_zone_summary,
    ) = replay_experimental_live_replay_plan(
        selected_latency_v2_shadow_adaptive_live_replay_plan,
        lap_samples,
        selected_latency_v2_shadow_zone_passes,
        config=selected_latency_v2_shadow_adaptive_live_replay_config,
    )
    selected_latency_v2_guarded_handoff_preview, selected_latency_v2_guarded_handoff_detail, (
        selected_latency_v2_guarded_handoff_summary
    ) = build_experimental_guarded_adaptive_live_transition_preview(
        selected_latency_v2_shadow_live_transition_preview,
        config=ExperimentalAdaptiveHandoffGuardrailConfig(
            max_abs_distance_delta_m=20.0,
            low_support_rows_threshold=2,
            low_support_max_abs_distance_delta_m=10.0,
            allow_added_zones=False,
            allow_removed_zones=False,
        ),
    )
    selected_latency_v2_guarded_live_replay_config = (
        ExperimentalLiveReplayValidationConfig(
            planning_modes=("adaptive_guarded",),
            track_name="Spa-Francorchamps",
            car_class="LMP2",
            race_context_id="spa_dynamics_v1_guarded_handoff_selected_latency_v2",
            track_length_m=candidate_track_length_m,
            cue_latency_compensation_s=LIVE_CUE_LATENCY_COMPENSATION_S,
            plan_id_prefix="experimental_guarded_adaptive_handoff",
        )
    )
    selected_latency_v2_guarded_live_replay_plan = build_experimental_live_replay_plan(
        selected_latency_v2_guarded_handoff_preview,
        track_zones,
        config=selected_latency_v2_guarded_live_replay_config,
    )
    (
        selected_latency_v2_guarded_live_replay_events,
        selected_latency_v2_guarded_live_replay_accuracy,
        selected_latency_v2_guarded_live_replay_validation_rows,
        selected_latency_v2_guarded_live_replay_handoff_summary,
        selected_latency_v2_guarded_live_replay_zone_summary,
    ) = replay_experimental_live_replay_plan(
        selected_latency_v2_guarded_live_replay_plan,
        lap_samples,
        selected_latency_v2_shadow_zone_passes,
        config=selected_latency_v2_guarded_live_replay_config,
    )

    figure = create_experimental_zone_dynamics_report_figure(
        zone_dynamics,
        title="Spa LMP2 experimental zone dynamics (v1)",
    )
    report_path = write_experimental_zone_dynamics_report_html(
        figure,
        OUTPUT_DIR / "spa_lmp2_experimental_zone_dynamics_report.html",
    )
    driver_review_report_path = write_experimental_zone_dynamics_driver_review_report_html(
        zone_dynamics,
        driver_review,
        OUTPUT_DIR / "spa_lmp2_experimental_zone_dynamics_driver_review_report.html",
    )
    reclassified_driver_review_report_path = write_experimental_zone_dynamics_driver_review_report_html(
        zone_dynamics,
        reclassified_driver_review,
        OUTPUT_DIR
        / "spa_lmp2_experimental_zone_dynamics_driver_review_reclassified_report.html",
    )
    reclassified_model_report_path = write_zone_model_report_html(
        create_zone_model_report_figure(
            reclassified_zone_models,
            title="Spa LMP2 experimental reclassified zone models",
        ),
        OUTPUT_DIR / "spa_lmp2_experimental_zone_model_reclassified_report.html",
    )
    reclassified_plan_report_path = write_zone_plan_report_html(
        create_zone_plan_report_figure(
            reclassified_zone_models,
            reclassified_ready_plus_micro_plan,
            title="Spa LMP2 experimental reclassified plan (ready + micro)",
        ),
        OUTPUT_DIR / "spa_lmp2_experimental_zone_plan_reclassified_report.html",
    )
    robust_plan_report_path = write_zone_plan_report_html(
        create_zone_plan_report_figure(
            _optimizer_ready_frame(robust_zone_models),
            robust_plan,
            title="Spa LMP2 experimental robust plan",
        ),
        OUTPUT_DIR / "spa_lmp2_experimental_zone_plan_robust_report.html",
    )
    range_aware_selected_zones_plan_report_path = write_zone_plan_report_html(
        create_zone_plan_report_figure(
            _optimizer_ready_frame(robust_zone_models),
            range_aware_selected_zones_plan,
            title="Spa LMP2 experimental range-aware plan (selected zones top-up)",
        ),
        OUTPUT_DIR / "spa_lmp2_experimental_zone_plan_range_aware_report.html",
    )
    range_aware_all_eligible_plan_report_path = write_zone_plan_report_html(
        create_zone_plan_report_figure(
            _optimizer_ready_frame(robust_zone_models),
            range_aware_all_eligible_plan,
            title="Spa LMP2 experimental range-aware plan (all eligible zones top-up)",
        ),
        OUTPUT_DIR / "spa_lmp2_experimental_zone_plan_range_aware_all_eligible_report.html",
    )
    replanner_report_path = write_experimental_lap_replanner_report_html(
        create_experimental_lap_replanner_report_figure(
            replanning_lap_summary,
            title="Spa LMP2 experimental lap-by-lap replanning simulator",
        ),
        OUTPUT_DIR / "spa_lmp2_experimental_lap_replanner_report.html",
    )
    observed_replanner_report_path = write_experimental_lap_replanner_report_html(
        create_experimental_lap_replanner_report_figure(
            observed_replanning_lap_summary,
            title="Spa LMP2 experimental replanning from observed executions",
        ),
        OUTPUT_DIR / "spa_lmp2_experimental_observed_replanner_report.html",
    )
    observed_replanner_validation_report_path = (
        write_experimental_lap_replanner_validation_report_html(
            title="Spa LMP2 experimental observed replanning validation",
            replanner_figure=create_experimental_lap_replanner_report_figure(
                observed_replanning_lap_summary,
                title="Spa LMP2 experimental replanning from observed executions",
            ),
            calibration_figure=create_experimental_zone_execution_calibration_figure(
                observed_zone_execution_calibration_summary,
                title="Spa LMP2 observed zone execution calibration",
            ),
            zone_summary=observed_zone_execution_calibration_summary,
            live_transition_preview=observed_live_transition_preview.filter(
                pl.col("planning_mode") == "adaptive"
            ),
            path=OUTPUT_DIR
            / "spa_lmp2_experimental_observed_replanner_validation_report.html",
        )
    )
    observed_adaptive_live_replay_report_path = (
        write_experimental_live_replay_validation_report_html(
            title="Spa LMP2 experimental adaptive live replay validation",
            figure=create_experimental_live_replay_validation_figure(
                observed_adaptive_live_replay_handoff_summary,
                title="Spa LMP2 experimental adaptive live replay validation",
            ),
            handoff_summary=observed_adaptive_live_replay_handoff_summary,
            zone_summary=observed_adaptive_live_replay_zone_summary,
            validation_rows=observed_adaptive_live_replay_validation_rows,
            path=OUTPUT_DIR
            / "spa_lmp2_experimental_observed_adaptive_live_replay_validation_report.html",
        )
    )
    selected_latency_v2_shadow_report_path = write_experimental_shadow_adaptive_report_html(
        title="Spa LMP2 shadow adaptive between-laps validation from live baseline v2",
        replanner_figure=create_experimental_lap_replanner_report_figure(
            selected_latency_v2_shadow_replanning_lap_summary,
            title="Spa LMP2 shadow adaptive replanning from live baseline v2",
        ),
        shadow_figure=create_experimental_shadow_adaptive_summary_figure(
            selected_latency_v2_shadow_handoff_summary,
            selected_latency_v2_shadow_zone_summary,
            title="Spa LMP2 static vs shadow adaptive delta from live baseline v2",
        ),
        handoff_summary=selected_latency_v2_shadow_handoff_summary,
        zone_summary=selected_latency_v2_shadow_zone_summary,
        transition_comparison=selected_latency_v2_shadow_transition_comparison,
        live_transition_preview=selected_latency_v2_shadow_live_transition_preview,
        replay_handoff_summary=selected_latency_v2_shadow_adaptive_live_replay_handoff_summary,
        replay_zone_summary=selected_latency_v2_shadow_adaptive_live_replay_zone_summary,
        path=OUTPUT_DIR
        / "spa_lmp2_experimental_selected_latency_v2_shadow_adaptive_report.html",
    )
    selected_latency_v2_guarded_handoff_report_path = (
        write_experimental_guarded_adaptive_handoff_report_html(
            title="Spa LMP2 guarded adaptive between-laps handoff from live baseline v2",
            summary=selected_latency_v2_guarded_handoff_summary,
            detail=selected_latency_v2_guarded_handoff_detail,
            guarded_live_transition_preview=selected_latency_v2_guarded_handoff_preview,
            guarded_live_plan=selected_latency_v2_guarded_live_replay_plan,
            guarded_replay_handoff_summary=selected_latency_v2_guarded_live_replay_handoff_summary,
            path=OUTPUT_DIR
            / "spa_lmp2_experimental_selected_latency_v2_guarded_adaptive_handoff_report.html",
        )
    )

    _write_csv(zone_dynamics, OUTPUT_DIR / "spa_lmp2_experimental_zone_dynamics.csv")
    _write_csv(
        zone_dynamics_summary,
        OUTPUT_DIR / "spa_lmp2_experimental_zone_dynamics_summary.csv",
    )
    _write_csv(
        model_comparison,
        OUTPUT_DIR / "spa_lmp2_experimental_zone_dynamics_model_comparison.csv",
    )
    _write_csv(
        model_scores,
        OUTPUT_DIR / "spa_lmp2_experimental_zone_dynamics_model_scores.csv",
    )
    _write_csv(
        driver_review,
        OUTPUT_DIR / "spa_lmp2_experimental_zone_dynamics_driver_review.csv",
    )
    _write_csv(
        zone_reclassification,
        OUTPUT_DIR / "spa_lmp2_experimental_zone_reclassification.csv",
    )
    _write_csv(
        reclassified_zone_models,
        OUTPUT_DIR / "spa_lmp2_experimental_zone_models_reclassified.csv",
    )
    _write_csv(
        reclassified_zone_priors,
        OUTPUT_DIR / "spa_lmp2_experimental_strategy_priors_reclassified.csv",
    )
    _write_csv(
        reclassified_driver_review,
        OUTPUT_DIR / "spa_lmp2_experimental_zone_dynamics_driver_review_reclassified.csv",
    )
    _write_csv(
        reclassified_ready_plan,
        OUTPUT_DIR / "spa_lmp2_experimental_zone_lico_plan_reclassified_ready.csv",
    )
    _write_csv(
        reclassified_ready_plus_micro_plan,
        OUTPUT_DIR / "spa_lmp2_experimental_zone_lico_plan_reclassified_ready_plus_micro.csv",
    )
    _write_csv(
        reclassified_marginal_efficiency,
        OUTPUT_DIR / "spa_lmp2_experimental_zone_marginal_efficiency_reclassified.csv",
    )
    _write_csv(
        reclassified_sensitivity,
        OUTPUT_DIR / "spa_lmp2_experimental_zone_plan_reclassified_sensitivity.csv",
    )
    _write_csv(
        robust_zone_models,
        OUTPUT_DIR / "spa_lmp2_experimental_zone_models_robust.csv",
    )
    _write_csv(
        robust_plan,
        OUTPUT_DIR / "spa_lmp2_experimental_zone_lico_plan_robust.csv",
    )
    _write_csv(
        robust_ranges,
        OUTPUT_DIR / "spa_lmp2_experimental_zone_lico_plan_robust_ranges.csv",
    )
    _write_csv(
        robust_plan_comparison,
        OUTPUT_DIR / "spa_lmp2_experimental_zone_plan_naive_vs_robust.csv",
    )
    _write_csv(
        range_aware_selected_zones_plan,
        OUTPUT_DIR / "spa_lmp2_experimental_zone_lico_plan_range_aware.csv",
    )
    _write_csv(
        range_aware_selected_zones_plan,
        OUTPUT_DIR / "spa_lmp2_experimental_zone_lico_plan_range_aware_selected_zones.csv",
    )
    _write_csv(
        range_aware_all_eligible_plan,
        OUTPUT_DIR / "spa_lmp2_experimental_zone_lico_plan_range_aware_all_eligible_zones.csv",
    )
    _write_csv(
        range_aware_selected_zones_plan_comparison,
        OUTPUT_DIR / "spa_lmp2_experimental_zone_plan_robust_vs_range_aware.csv",
    )
    _write_csv(
        range_aware_selected_zones_plan_comparison,
        OUTPUT_DIR
        / "spa_lmp2_experimental_zone_plan_robust_vs_range_aware_selected_zones.csv",
    )
    _write_csv(
        range_aware_all_eligible_plan_comparison,
        OUTPUT_DIR
        / "spa_lmp2_experimental_zone_plan_robust_vs_range_aware_all_eligible_zones.csv",
    )
    _write_csv(
        range_aware_variant_summary,
        OUTPUT_DIR / "spa_lmp2_experimental_range_aware_variant_summary.csv",
    )
    _write_csv(
        live_candidate_selected_plan,
        OUTPUT_DIR / "spa_lmp2_experimental_live_candidate_selected_zones_plan.csv",
    )
    _write_csv(
        live_candidate_selected_latency_compensated_plan,
        OUTPUT_DIR
        / "spa_lmp2_experimental_live_candidate_selected_zones_latency_compensated_plan.csv",
    )
    _write_csv(
        live_candidate_selected_latency_speed_aware_plan,
        OUTPUT_DIR
        / "spa_lmp2_experimental_live_candidate_selected_zones_latency_speed_aware_plan.csv",
    )
    _write_csv(
        live_candidate_all_eligible_plan,
        OUTPUT_DIR / "spa_lmp2_experimental_live_candidate_all_eligible_plan.csv",
    )
    _write_csv(
        live_candidate_all_eligible_latency_compensated_plan,
        OUTPUT_DIR
        / "spa_lmp2_experimental_live_candidate_all_eligible_latency_compensated_plan.csv",
    )
    _write_csv(
        live_candidate_all_eligible_latency_speed_aware_plan,
        OUTPUT_DIR
        / "spa_lmp2_experimental_live_candidate_all_eligible_latency_speed_aware_plan.csv",
    )
    _write_csv(
        observed_live_cue_plan,
        OUTPUT_DIR / "spa_lmp2_experimental_observed_live_cue_plan.csv",
    )
    _write_csv(
        observed_live_cue_execution,
        OUTPUT_DIR / "spa_lmp2_experimental_observed_live_cue_executions.csv",
    )
    _write_csv(
        observed_lap_context,
        OUTPUT_DIR / "spa_lmp2_experimental_observed_lap_race_state_context.csv",
    )
    _write_csv(
        replanning_lap_summary,
        OUTPUT_DIR / "spa_lmp2_experimental_replanning_lap_summary.csv",
    )
    _write_csv(
        replanning_lap_plan,
        OUTPUT_DIR / "spa_lmp2_experimental_replanning_lap_plan.csv",
    )
    _write_csv(
        replanning_scenario_summary,
        OUTPUT_DIR / "spa_lmp2_experimental_replanning_scenario_summary.csv",
    )
    _write_csv(
        observed_replanning_lap_summary,
        OUTPUT_DIR / "spa_lmp2_experimental_observed_replanning_lap_summary.csv",
    )
    _write_csv(
        observed_replanning_lap_plan,
        OUTPUT_DIR / "spa_lmp2_experimental_observed_replanning_lap_plan.csv",
    )
    _write_csv(
        observed_replanning_scenario_summary,
        OUTPUT_DIR / "spa_lmp2_experimental_observed_replanning_scenario_summary.csv",
    )
    _write_csv(
        observed_context_effect_summary,
        OUTPUT_DIR / "spa_lmp2_experimental_observed_race_state_context_effect_summary.csv",
    )
    _write_csv(
        observed_zone_execution_calibration_summary,
        OUTPUT_DIR
        / "spa_lmp2_experimental_observed_zone_execution_calibration_summary.csv",
    )
    _write_csv(
        observed_live_transition_preview,
        OUTPUT_DIR / "spa_lmp2_experimental_observed_live_transition_preview.csv",
    )
    _write_csv(
        observed_adaptive_live_replay_plan,
        OUTPUT_DIR / "spa_lmp2_experimental_observed_adaptive_live_replay_plan.csv",
    )
    _write_csv(
        observed_adaptive_live_replay_events,
        OUTPUT_DIR / "spa_lmp2_experimental_observed_adaptive_live_replay_events.csv",
    )
    _write_csv(
        observed_adaptive_live_replay_accuracy,
        OUTPUT_DIR / "spa_lmp2_experimental_observed_adaptive_live_replay_accuracy.csv",
    )
    _write_csv(
        observed_adaptive_live_replay_validation_rows,
        OUTPUT_DIR
        / "spa_lmp2_experimental_observed_adaptive_live_replay_validation_rows.csv",
    )
    _write_csv(
        observed_adaptive_live_replay_handoff_summary,
        OUTPUT_DIR
        / "spa_lmp2_experimental_observed_adaptive_live_replay_handoff_summary.csv",
    )
    _write_csv(
        observed_adaptive_live_replay_zone_summary,
        OUTPUT_DIR
        / "spa_lmp2_experimental_observed_adaptive_live_replay_zone_summary.csv",
    )
    _write_csv(
        selected_latency_v2_shadow_live_cue_execution,
        OUTPUT_DIR
        / "spa_lmp2_experimental_selected_latency_v2_shadow_live_cue_executions.csv",
    )
    _write_csv(
        selected_latency_v2_shadow_lap_context,
        OUTPUT_DIR
        / "spa_lmp2_experimental_selected_latency_v2_shadow_lap_race_state_context.csv",
    )
    _write_csv(
        selected_latency_v2_shadow_replanning_lap_summary,
        OUTPUT_DIR
        / "spa_lmp2_experimental_selected_latency_v2_shadow_replanning_lap_summary.csv",
    )
    _write_csv(
        selected_latency_v2_shadow_replanning_lap_plan,
        OUTPUT_DIR
        / "spa_lmp2_experimental_selected_latency_v2_shadow_replanning_lap_plan.csv",
    )
    _write_csv(
        selected_latency_v2_shadow_replanning_scenario_summary,
        OUTPUT_DIR
        / "spa_lmp2_experimental_selected_latency_v2_shadow_replanning_scenario_summary.csv",
    )
    _write_csv(
        selected_latency_v2_shadow_live_transition_preview,
        OUTPUT_DIR
        / "spa_lmp2_experimental_selected_latency_v2_shadow_live_transition_preview.csv",
    )
    _write_csv(
        selected_latency_v2_shadow_transition_comparison,
        OUTPUT_DIR
        / "spa_lmp2_experimental_selected_latency_v2_shadow_transition_comparison.csv",
    )
    _write_csv(
        selected_latency_v2_shadow_handoff_summary,
        OUTPUT_DIR
        / "spa_lmp2_experimental_selected_latency_v2_shadow_handoff_summary.csv",
    )
    _write_csv(
        selected_latency_v2_shadow_zone_summary,
        OUTPUT_DIR
        / "spa_lmp2_experimental_selected_latency_v2_shadow_zone_summary.csv",
    )
    _write_csv(
        selected_latency_v2_shadow_adaptive_live_replay_plan,
        OUTPUT_DIR
        / "spa_lmp2_experimental_selected_latency_v2_shadow_adaptive_live_replay_plan.csv",
    )
    _write_csv(
        selected_latency_v2_shadow_adaptive_live_replay_events,
        OUTPUT_DIR
        / "spa_lmp2_experimental_selected_latency_v2_shadow_adaptive_live_replay_events.csv",
    )
    _write_csv(
        selected_latency_v2_shadow_adaptive_live_replay_accuracy,
        OUTPUT_DIR
        / "spa_lmp2_experimental_selected_latency_v2_shadow_adaptive_live_replay_accuracy.csv",
    )
    _write_csv(
        selected_latency_v2_shadow_adaptive_live_replay_validation_rows,
        OUTPUT_DIR
        / "spa_lmp2_experimental_selected_latency_v2_shadow_adaptive_live_replay_validation_rows.csv",
    )
    _write_csv(
        selected_latency_v2_shadow_adaptive_live_replay_handoff_summary,
        OUTPUT_DIR
        / "spa_lmp2_experimental_selected_latency_v2_shadow_adaptive_live_replay_handoff_summary.csv",
    )
    _write_csv(
        selected_latency_v2_shadow_adaptive_live_replay_zone_summary,
        OUTPUT_DIR
        / "spa_lmp2_experimental_selected_latency_v2_shadow_adaptive_live_replay_zone_summary.csv",
    )
    _write_csv(
        selected_latency_v2_guarded_handoff_preview,
        OUTPUT_DIR
        / "spa_lmp2_experimental_selected_latency_v2_guarded_handoff_preview.csv",
    )
    _write_csv(
        selected_latency_v2_guarded_handoff_detail,
        OUTPUT_DIR
        / "spa_lmp2_experimental_selected_latency_v2_guarded_handoff_detail.csv",
    )
    _write_csv(
        selected_latency_v2_guarded_handoff_summary,
        OUTPUT_DIR
        / "spa_lmp2_experimental_selected_latency_v2_guarded_handoff_summary.csv",
    )
    _write_csv(
        selected_latency_v2_guarded_live_replay_plan,
        OUTPUT_DIR
        / "spa_lmp2_experimental_selected_latency_v2_guarded_live_replay_plan.csv",
    )
    _write_csv(
        selected_latency_v2_guarded_live_replay_events,
        OUTPUT_DIR
        / "spa_lmp2_experimental_selected_latency_v2_guarded_live_replay_events.csv",
    )
    _write_csv(
        selected_latency_v2_guarded_live_replay_accuracy,
        OUTPUT_DIR
        / "spa_lmp2_experimental_selected_latency_v2_guarded_live_replay_accuracy.csv",
    )
    _write_csv(
        selected_latency_v2_guarded_live_replay_validation_rows,
        OUTPUT_DIR
        / "spa_lmp2_experimental_selected_latency_v2_guarded_live_replay_validation_rows.csv",
    )
    _write_csv(
        selected_latency_v2_guarded_live_replay_handoff_summary,
        OUTPUT_DIR
        / "spa_lmp2_experimental_selected_latency_v2_guarded_live_replay_handoff_summary.csv",
    )
    _write_csv(
        selected_latency_v2_guarded_live_replay_zone_summary,
        OUTPUT_DIR
        / "spa_lmp2_experimental_selected_latency_v2_guarded_live_replay_zone_summary.csv",
    )

    manifest = _reference_manifest(
        report_path=report_path,
        driver_review_report_path=driver_review_report_path,
        reclassified_driver_review_report_path=reclassified_driver_review_report_path,
        reclassified_model_report_path=reclassified_model_report_path,
        reclassified_plan_report_path=reclassified_plan_report_path,
        robust_plan_report_path=robust_plan_report_path,
        range_aware_plan_report_path=range_aware_selected_zones_plan_report_path,
        range_aware_all_eligible_plan_report_path=range_aware_all_eligible_plan_report_path,
        replanner_report_path=replanner_report_path,
        observed_replanner_report_path=observed_replanner_report_path,
        observed_replanner_validation_report_path=observed_replanner_validation_report_path,
        observed_adaptive_live_replay_report_path=observed_adaptive_live_replay_report_path,
        selected_latency_v2_shadow_report_path=selected_latency_v2_shadow_report_path,
        selected_latency_v2_guarded_handoff_report_path=selected_latency_v2_guarded_handoff_report_path,
    )
    manifest_path = OUTPUT_DIR / "spa_lmp2_experimental_reference_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print("Experimental dynamics refit complete.")
    print(f"Output directory: {OUTPUT_DIR}")
    print(
        zone_dynamics_summary.select(
            "zone_id",
            "lico_intensity",
            "pass_count",
            "mean_time_lost_vs_baseline_s",
            "mean_brake_start_delta_vs_baseline_m",
            "mean_apex_speed_delta_vs_baseline_kph",
        )
        .to_pandas()
        .to_string(index=False)
    )
    print()
    print(
        model_comparison.select(
            "zone_id",
            "status",
            "recommendation",
            "direct_r2",
            "dynamics_r2",
            "r2_improvement",
        )
        .to_pandas()
        .to_string(index=False)
    )
    print()
    print(
        driver_review.select(
            "zone_id",
            "current_model_status",
            "primary_review_label",
            "secondary_review_label",
            "pilot_takeaway",
        )
        .to_pandas()
        .to_string(index=False)
    )
    print()
    print(
        zone_reclassification.select(
            "zone_id",
            "base_model_status",
            "experimental_model_status",
            "reclassification_action",
            "max_lico_distance_m_override",
        )
        .to_pandas()
        .to_string(index=False)
    )
    print()
    print("Reclassified ready-only plan:")
    print(
        reclassified_ready_plan.select(
            "zone_id",
            "selected_lico_distance_m",
            "predicted_fuel_saved_l",
            "predicted_time_lost_s",
            "model_status",
            "plan_status",
        )
        .to_pandas()
        .to_string(index=False)
    )
    print()
    print("Reclassified ready+micro plan:")
    print(
        reclassified_ready_plus_micro_plan.select(
            "zone_id",
            "selected_lico_distance_m",
            "predicted_fuel_saved_l",
            "predicted_time_lost_s",
            "model_status",
            "plan_status",
        )
        .to_pandas()
        .to_string(index=False)
    )
    print()
    print(
        reclassified_sensitivity.select(
            "scenario_name",
            "plan_status",
            "total_predicted_fuel_saved_l",
            "total_predicted_time_lost_s",
            "fuel_surplus_l",
            "selected_zone_count",
            "selected_zone_ids",
        )
        .to_pandas()
        .to_string(index=False)
    )
    print()
    print("Robust plan:")
    print(
        robust_plan.select(
            "zone_id",
            "selected_lico_distance_m",
            "predicted_fuel_saved_l",
            "predicted_time_lost_s",
            "model_status",
            "plan_status",
        )
        .to_pandas()
        .to_string(index=False)
    )
    print()
    print(
        robust_plan_comparison.select(
            "zone_id",
            "naive_selected_lico_distance_m",
            "robust_selected_lico_distance_m",
            "distance_shift_m",
            "robust_support_score",
            "recommended_range_start_m",
            "recommended_range_end_m",
        )
        .to_pandas()
        .to_string(index=False)
    )
    print()
    print("Range-aware plan (selected zones top-up):")
    print(
        range_aware_selected_zones_plan.select(
            "zone_id",
            "selected_lico_distance_m",
            "predicted_fuel_saved_l",
            "predicted_time_lost_s",
            "model_status",
            "plan_status",
        )
        .to_pandas()
        .to_string(index=False)
    )
    print()
    print(
        range_aware_selected_zones_plan_comparison.select(
            "zone_id",
            "robust_selected_lico_distance_m",
            "range_aware_selected_zones_selected_lico_distance_m",
            "distance_shift_m",
            "range_aware_selected_zones_support_score",
            "recommended_range_start_m",
            "recommended_range_end_m",
        )
        .to_pandas()
        .to_string(index=False)
    )
    print()
    print("Range-aware plan (all eligible zones top-up):")
    print(
        range_aware_all_eligible_plan.select(
            "zone_id",
            "selected_lico_distance_m",
            "predicted_fuel_saved_l",
            "predicted_time_lost_s",
            "model_status",
            "plan_status",
        )
        .to_pandas()
        .to_string(index=False)
    )
    print()
    print(
        range_aware_all_eligible_plan_comparison.select(
            "zone_id",
            "robust_selected_lico_distance_m",
            "range_aware_all_eligible_selected_lico_distance_m",
            "distance_shift_m",
            "range_aware_all_eligible_support_score",
        )
        .to_pandas()
        .to_string(index=False)
    )
    print()
    print(
        range_aware_variant_summary.to_pandas().to_string(index=False)
    )
    print()
    print("Lap-by-lap replanning scenario summary:")
    print(
        replanning_scenario_summary.to_pandas().to_string(index=False)
    )
    print()
    print("Observed execution replanning scenario summary:")
    print(
        observed_replanning_scenario_summary.to_pandas().to_string(index=False)
    )


def _summarize_zone_dynamics(zone_dynamics: pl.DataFrame) -> pl.DataFrame:
    if zone_dynamics.is_empty():
        return pl.DataFrame()
    return (
        zone_dynamics.group_by(["zone_id", "display_label", "lico_intensity"])
        .agg(
            pl.len().alias("pass_count"),
            pl.col("time_lost_vs_baseline_s").mean().alias("mean_time_lost_vs_baseline_s"),
            pl.col("fuel_saved_vs_baseline_l").mean().alias("mean_fuel_saved_vs_baseline_l"),
            pl.col("brake_start_delta_vs_baseline_m")
            .mean()
            .alias("mean_brake_start_delta_vs_baseline_m"),
            pl.col("brake_start_speed_delta_vs_baseline_kph")
            .mean()
            .alias("mean_brake_start_speed_delta_vs_baseline_kph"),
            pl.col("apex_speed_delta_vs_baseline_kph")
            .mean()
            .alias("mean_apex_speed_delta_vs_baseline_kph"),
            pl.col("exit_speed_delta_vs_baseline_kph")
            .mean()
            .alias("mean_exit_speed_delta_vs_baseline_kph"),
            pl.col("carcass_temp_zone_start_delta_vs_baseline_c")
            .mean()
            .alias("mean_carcass_temp_zone_start_delta_vs_baseline_c"),
        )
        .sort(["zone_id", "lico_intensity"])
    )


def _cue_latency_reference_speed_frame(zone_dynamics: pl.DataFrame) -> pl.DataFrame:
    if zone_dynamics.is_empty():
        return pl.DataFrame(
            schema={
                "zone_id": pl.String,
                "cue_latency_reference_speed_kph": pl.Float64,
            }
        )
    return (
        zone_dynamics.group_by("zone_id")
        .agg(
            pl.col("baseline_mean_brake_start_speed_kph")
            .drop_nulls()
            .mean()
            .alias("baseline_mean_brake_start_speed_kph"),
            pl.col("brake_start_speed_kph")
            .drop_nulls()
            .mean()
            .alias("mean_brake_start_speed_kph"),
        )
        .with_columns(
            pl.coalesce(
                "baseline_mean_brake_start_speed_kph",
                "mean_brake_start_speed_kph",
            ).alias("cue_latency_reference_speed_kph")
        )
        .select("zone_id", "cue_latency_reference_speed_kph")
        .sort("zone_id")
    )


def _attach_cue_latency_reference_speeds(
    frame: pl.DataFrame,
    cue_latency_reference_speeds: pl.DataFrame,
    *,
    zone_key: str = "zone_id",
    output_column: str = "cue_latency_reference_speed_kph",
) -> pl.DataFrame:
    if frame.is_empty() or cue_latency_reference_speeds.is_empty():
        return frame
    prepared_frame = (
        frame.drop(output_column)
        if output_column in frame.columns
        else frame
    )
    return prepared_frame.join(
        cue_latency_reference_speeds.rename(
            {
                "zone_id": zone_key,
                "cue_latency_reference_speed_kph": output_column,
            }
        ),
        on=zone_key,
        how="left",
    )


def _reference_manifest(
    *,
    report_path: Path,
    driver_review_report_path: Path,
    reclassified_driver_review_report_path: Path,
    reclassified_model_report_path: Path,
    reclassified_plan_report_path: Path,
    robust_plan_report_path: Path,
    range_aware_plan_report_path: Path,
    range_aware_all_eligible_plan_report_path: Path,
    replanner_report_path: Path,
    observed_replanner_report_path: Path,
    observed_replanner_validation_report_path: Path,
    observed_adaptive_live_replay_report_path: Path,
    selected_latency_v2_shadow_report_path: Path,
    selected_latency_v2_guarded_handoff_report_path: Path,
) -> dict[str, object]:
    piecewise_models = pl.read_csv(CURRENT_PROCESSED_DIR / "spa_lmp2_zone_piecewise_models.csv")
    sensitivity = pl.read_csv(CURRENT_PROCESSED_DIR / "spa_lmp2_zone_plan_sensitivity.csv")
    prudent_plan = pl.read_csv(
        CURRENT_PROCESSED_DIR / "spa_lmp2_zone_lico_plan_driver_priors_prudent.csv"
    )
    model_ready_plan = pl.read_csv(CURRENT_PROCESSED_DIR / "spa_lmp2_zone_lico_plan_model_ready.csv")
    readiness = pl.read_csv(CURRENT_PROCESSED_DIR / "spa_lmp2_v2_zone_data_readiness.csv")
    git_branch, git_rebase = _git_state()

    return {
        "experiment_id": "spa_dynamics_v1",
        "source_inputs": {
            "dataset_label_file": str(DATASET_LABEL_FILE.relative_to(PROJECT_ROOT)),
            "track_zone_file": str(TRACK_ZONE_FILE.relative_to(PROJECT_ROOT)),
            "driver_review_file": str(DRIVER_REVIEW_FILE.relative_to(PROJECT_ROOT)),
            "protocol_file": str(PROTOCOL_FILE.relative_to(PROJECT_ROOT)),
        },
        "git_state": {
            "branch": git_branch,
            "rebase_in_progress": git_rebase,
        },
        "baseline_artifact_paths": {
            "zone_passes": "data/processed/spa_lmp2_zone_passes.csv",
            "zone_readiness": "data/processed/spa_lmp2_v2_zone_data_readiness.csv",
            "protocol_readiness": "data/processed/spa_lmp2_v2_protocol_readiness.csv",
            "lap_quality": "data/processed/spa_lmp2_v2_lap_quality_manifest.csv",
            "zone_summary": "data/processed/spa_lmp2_zone_summary.csv",
            "zone_models": "data/processed/spa_lmp2_zone_piecewise_models.csv",
            "zone_sensitivity": "data/processed/spa_lmp2_zone_plan_sensitivity.csv",
            "prudent_plan": "data/processed/spa_lmp2_zone_lico_plan_driver_priors_prudent.csv",
            "model_ready_plan": "data/processed/spa_lmp2_zone_lico_plan_model_ready.csv",
        },
        "baseline_snapshot": {
            "model_status_by_zone": _model_status_snapshot(piecewise_models),
            "readiness_by_zone": _readiness_snapshot(readiness),
            "sensitivity": _sensitivity_snapshot(sensitivity),
            "prudent_plan": _plan_snapshot(prudent_plan),
            "model_ready_plan": _plan_snapshot(model_ready_plan),
        },
        "experimental_outputs": {
            "zone_dynamics_csv": "data/processed/experimental/spa_dynamics_v1/spa_lmp2_experimental_zone_dynamics.csv",
            "zone_dynamics_summary_csv": "data/processed/experimental/spa_dynamics_v1/spa_lmp2_experimental_zone_dynamics_summary.csv",
            "model_comparison_csv": "data/processed/experimental/spa_dynamics_v1/spa_lmp2_experimental_zone_dynamics_model_comparison.csv",
            "model_scores_csv": "data/processed/experimental/spa_dynamics_v1/spa_lmp2_experimental_zone_dynamics_model_scores.csv",
            "report_html": str(report_path.relative_to(PROJECT_ROOT)),
            "driver_review_csv": "data/processed/experimental/spa_dynamics_v1/spa_lmp2_experimental_zone_dynamics_driver_review.csv",
            "driver_review_report_html": str(driver_review_report_path.relative_to(PROJECT_ROOT)),
            "zone_reclassification_csv": "data/processed/experimental/spa_dynamics_v1/spa_lmp2_experimental_zone_reclassification.csv",
            "reclassified_zone_models_csv": "data/processed/experimental/spa_dynamics_v1/spa_lmp2_experimental_zone_models_reclassified.csv",
            "reclassified_strategy_priors_csv": "data/processed/experimental/spa_dynamics_v1/spa_lmp2_experimental_strategy_priors_reclassified.csv",
            "reclassified_driver_review_csv": "data/processed/experimental/spa_dynamics_v1/spa_lmp2_experimental_zone_dynamics_driver_review_reclassified.csv",
            "reclassified_driver_review_report_html": str(
                reclassified_driver_review_report_path.relative_to(PROJECT_ROOT)
            ),
            "reclassified_ready_plan_csv": "data/processed/experimental/spa_dynamics_v1/spa_lmp2_experimental_zone_lico_plan_reclassified_ready.csv",
            "reclassified_ready_plus_micro_plan_csv": "data/processed/experimental/spa_dynamics_v1/spa_lmp2_experimental_zone_lico_plan_reclassified_ready_plus_micro.csv",
            "reclassified_marginal_efficiency_csv": "data/processed/experimental/spa_dynamics_v1/spa_lmp2_experimental_zone_marginal_efficiency_reclassified.csv",
            "reclassified_sensitivity_csv": "data/processed/experimental/spa_dynamics_v1/spa_lmp2_experimental_zone_plan_reclassified_sensitivity.csv",
            "reclassified_model_report_html": str(
                reclassified_model_report_path.relative_to(PROJECT_ROOT)
            ),
            "reclassified_plan_report_html": str(
                reclassified_plan_report_path.relative_to(PROJECT_ROOT)
            ),
            "robust_zone_models_csv": "data/processed/experimental/spa_dynamics_v1/spa_lmp2_experimental_zone_models_robust.csv",
            "robust_plan_csv": "data/processed/experimental/spa_dynamics_v1/spa_lmp2_experimental_zone_lico_plan_robust.csv",
            "robust_ranges_csv": "data/processed/experimental/spa_dynamics_v1/spa_lmp2_experimental_zone_lico_plan_robust_ranges.csv",
            "naive_vs_robust_plan_csv": "data/processed/experimental/spa_dynamics_v1/spa_lmp2_experimental_zone_plan_naive_vs_robust.csv",
            "robust_plan_report_html": str(
                robust_plan_report_path.relative_to(PROJECT_ROOT)
            ),
            "range_aware_plan_csv": "data/processed/experimental/spa_dynamics_v1/spa_lmp2_experimental_zone_lico_plan_range_aware.csv",
            "robust_vs_range_aware_plan_csv": "data/processed/experimental/spa_dynamics_v1/spa_lmp2_experimental_zone_plan_robust_vs_range_aware.csv",
            "range_aware_plan_report_html": str(
                range_aware_plan_report_path.relative_to(PROJECT_ROOT)
            ),
            "range_aware_selected_zones_plan_csv": "data/processed/experimental/spa_dynamics_v1/spa_lmp2_experimental_zone_lico_plan_range_aware_selected_zones.csv",
            "range_aware_all_eligible_plan_csv": "data/processed/experimental/spa_dynamics_v1/spa_lmp2_experimental_zone_lico_plan_range_aware_all_eligible_zones.csv",
            "live_candidate_selected_zones_plan_csv": "data/processed/experimental/spa_dynamics_v1/spa_lmp2_experimental_live_candidate_selected_zones_plan.csv",
            "live_candidate_selected_zones_latency_compensated_plan_csv": "data/processed/experimental/spa_dynamics_v1/spa_lmp2_experimental_live_candidate_selected_zones_latency_compensated_plan.csv",
            "live_candidate_selected_zones_latency_speed_aware_plan_csv": "data/processed/experimental/spa_dynamics_v1/spa_lmp2_experimental_live_candidate_selected_zones_latency_speed_aware_plan.csv",
            "live_candidate_all_eligible_plan_csv": "data/processed/experimental/spa_dynamics_v1/spa_lmp2_experimental_live_candidate_all_eligible_plan.csv",
            "live_candidate_all_eligible_latency_compensated_plan_csv": "data/processed/experimental/spa_dynamics_v1/spa_lmp2_experimental_live_candidate_all_eligible_latency_compensated_plan.csv",
            "live_candidate_all_eligible_latency_speed_aware_plan_csv": "data/processed/experimental/spa_dynamics_v1/spa_lmp2_experimental_live_candidate_all_eligible_latency_speed_aware_plan.csv",
            "robust_vs_range_aware_selected_zones_plan_csv": "data/processed/experimental/spa_dynamics_v1/spa_lmp2_experimental_zone_plan_robust_vs_range_aware_selected_zones.csv",
            "robust_vs_range_aware_all_eligible_plan_csv": "data/processed/experimental/spa_dynamics_v1/spa_lmp2_experimental_zone_plan_robust_vs_range_aware_all_eligible_zones.csv",
            "range_aware_variant_summary_csv": "data/processed/experimental/spa_dynamics_v1/spa_lmp2_experimental_range_aware_variant_summary.csv",
            "range_aware_all_eligible_plan_report_html": str(
                range_aware_all_eligible_plan_report_path.relative_to(PROJECT_ROOT)
            ),
            "observed_live_cue_plan_csv": "data/processed/experimental/spa_dynamics_v1/spa_lmp2_experimental_observed_live_cue_plan.csv",
            "observed_live_cue_executions_csv": "data/processed/experimental/spa_dynamics_v1/spa_lmp2_experimental_observed_live_cue_executions.csv",
            "observed_lap_race_state_context_csv": "data/processed/experimental/spa_dynamics_v1/spa_lmp2_experimental_observed_lap_race_state_context.csv",
            "replanning_lap_summary_csv": "data/processed/experimental/spa_dynamics_v1/spa_lmp2_experimental_replanning_lap_summary.csv",
            "replanning_lap_plan_csv": "data/processed/experimental/spa_dynamics_v1/spa_lmp2_experimental_replanning_lap_plan.csv",
            "replanning_scenario_summary_csv": "data/processed/experimental/spa_dynamics_v1/spa_lmp2_experimental_replanning_scenario_summary.csv",
            "replanner_report_html": str(
                replanner_report_path.relative_to(PROJECT_ROOT)
            ),
            "observed_replanning_lap_summary_csv": "data/processed/experimental/spa_dynamics_v1/spa_lmp2_experimental_observed_replanning_lap_summary.csv",
            "observed_replanning_lap_plan_csv": "data/processed/experimental/spa_dynamics_v1/spa_lmp2_experimental_observed_replanning_lap_plan.csv",
            "observed_replanning_scenario_summary_csv": "data/processed/experimental/spa_dynamics_v1/spa_lmp2_experimental_observed_replanning_scenario_summary.csv",
            "observed_race_state_context_effect_summary_csv": "data/processed/experimental/spa_dynamics_v1/spa_lmp2_experimental_observed_race_state_context_effect_summary.csv",
            "observed_zone_execution_calibration_summary_csv": "data/processed/experimental/spa_dynamics_v1/spa_lmp2_experimental_observed_zone_execution_calibration_summary.csv",
            "observed_live_transition_preview_csv": "data/processed/experimental/spa_dynamics_v1/spa_lmp2_experimental_observed_live_transition_preview.csv",
            "observed_adaptive_live_replay_plan_csv": "data/processed/experimental/spa_dynamics_v1/spa_lmp2_experimental_observed_adaptive_live_replay_plan.csv",
            "observed_adaptive_live_replay_events_csv": "data/processed/experimental/spa_dynamics_v1/spa_lmp2_experimental_observed_adaptive_live_replay_events.csv",
            "observed_adaptive_live_replay_accuracy_csv": "data/processed/experimental/spa_dynamics_v1/spa_lmp2_experimental_observed_adaptive_live_replay_accuracy.csv",
            "observed_adaptive_live_replay_validation_rows_csv": "data/processed/experimental/spa_dynamics_v1/spa_lmp2_experimental_observed_adaptive_live_replay_validation_rows.csv",
            "observed_adaptive_live_replay_handoff_summary_csv": "data/processed/experimental/spa_dynamics_v1/spa_lmp2_experimental_observed_adaptive_live_replay_handoff_summary.csv",
            "observed_adaptive_live_replay_zone_summary_csv": "data/processed/experimental/spa_dynamics_v1/spa_lmp2_experimental_observed_adaptive_live_replay_zone_summary.csv",
            "observed_replanner_report_html": str(
                observed_replanner_report_path.relative_to(PROJECT_ROOT)
            ),
            "observed_replanner_validation_report_html": str(
                observed_replanner_validation_report_path.relative_to(PROJECT_ROOT)
            ),
            "observed_adaptive_live_replay_validation_report_html": str(
                observed_adaptive_live_replay_report_path.relative_to(PROJECT_ROOT)
            ),
            "selected_latency_v2_shadow_live_cue_executions_csv": "data/processed/experimental/spa_dynamics_v1/spa_lmp2_experimental_selected_latency_v2_shadow_live_cue_executions.csv",
            "selected_latency_v2_shadow_lap_race_state_context_csv": "data/processed/experimental/spa_dynamics_v1/spa_lmp2_experimental_selected_latency_v2_shadow_lap_race_state_context.csv",
            "selected_latency_v2_shadow_replanning_lap_summary_csv": "data/processed/experimental/spa_dynamics_v1/spa_lmp2_experimental_selected_latency_v2_shadow_replanning_lap_summary.csv",
            "selected_latency_v2_shadow_replanning_lap_plan_csv": "data/processed/experimental/spa_dynamics_v1/spa_lmp2_experimental_selected_latency_v2_shadow_replanning_lap_plan.csv",
            "selected_latency_v2_shadow_replanning_scenario_summary_csv": "data/processed/experimental/spa_dynamics_v1/spa_lmp2_experimental_selected_latency_v2_shadow_replanning_scenario_summary.csv",
            "selected_latency_v2_shadow_live_transition_preview_csv": "data/processed/experimental/spa_dynamics_v1/spa_lmp2_experimental_selected_latency_v2_shadow_live_transition_preview.csv",
            "selected_latency_v2_shadow_transition_comparison_csv": "data/processed/experimental/spa_dynamics_v1/spa_lmp2_experimental_selected_latency_v2_shadow_transition_comparison.csv",
            "selected_latency_v2_shadow_handoff_summary_csv": "data/processed/experimental/spa_dynamics_v1/spa_lmp2_experimental_selected_latency_v2_shadow_handoff_summary.csv",
            "selected_latency_v2_shadow_zone_summary_csv": "data/processed/experimental/spa_dynamics_v1/spa_lmp2_experimental_selected_latency_v2_shadow_zone_summary.csv",
            "selected_latency_v2_shadow_adaptive_live_replay_plan_csv": "data/processed/experimental/spa_dynamics_v1/spa_lmp2_experimental_selected_latency_v2_shadow_adaptive_live_replay_plan.csv",
            "selected_latency_v2_shadow_adaptive_live_replay_events_csv": "data/processed/experimental/spa_dynamics_v1/spa_lmp2_experimental_selected_latency_v2_shadow_adaptive_live_replay_events.csv",
            "selected_latency_v2_shadow_adaptive_live_replay_accuracy_csv": "data/processed/experimental/spa_dynamics_v1/spa_lmp2_experimental_selected_latency_v2_shadow_adaptive_live_replay_accuracy.csv",
            "selected_latency_v2_shadow_adaptive_live_replay_validation_rows_csv": "data/processed/experimental/spa_dynamics_v1/spa_lmp2_experimental_selected_latency_v2_shadow_adaptive_live_replay_validation_rows.csv",
            "selected_latency_v2_shadow_adaptive_live_replay_handoff_summary_csv": "data/processed/experimental/spa_dynamics_v1/spa_lmp2_experimental_selected_latency_v2_shadow_adaptive_live_replay_handoff_summary.csv",
            "selected_latency_v2_shadow_adaptive_live_replay_zone_summary_csv": "data/processed/experimental/spa_dynamics_v1/spa_lmp2_experimental_selected_latency_v2_shadow_adaptive_live_replay_zone_summary.csv",
            "selected_latency_v2_shadow_report_html": str(
                selected_latency_v2_shadow_report_path.relative_to(PROJECT_ROOT)
            ),
            "selected_latency_v2_guarded_handoff_preview_csv": "data/processed/experimental/spa_dynamics_v1/spa_lmp2_experimental_selected_latency_v2_guarded_handoff_preview.csv",
            "selected_latency_v2_guarded_handoff_detail_csv": "data/processed/experimental/spa_dynamics_v1/spa_lmp2_experimental_selected_latency_v2_guarded_handoff_detail.csv",
            "selected_latency_v2_guarded_handoff_summary_csv": "data/processed/experimental/spa_dynamics_v1/spa_lmp2_experimental_selected_latency_v2_guarded_handoff_summary.csv",
            "selected_latency_v2_guarded_live_replay_plan_csv": "data/processed/experimental/spa_dynamics_v1/spa_lmp2_experimental_selected_latency_v2_guarded_live_replay_plan.csv",
            "selected_latency_v2_guarded_live_replay_events_csv": "data/processed/experimental/spa_dynamics_v1/spa_lmp2_experimental_selected_latency_v2_guarded_live_replay_events.csv",
            "selected_latency_v2_guarded_live_replay_accuracy_csv": "data/processed/experimental/spa_dynamics_v1/spa_lmp2_experimental_selected_latency_v2_guarded_live_replay_accuracy.csv",
            "selected_latency_v2_guarded_live_replay_validation_rows_csv": "data/processed/experimental/spa_dynamics_v1/spa_lmp2_experimental_selected_latency_v2_guarded_live_replay_validation_rows.csv",
            "selected_latency_v2_guarded_live_replay_handoff_summary_csv": "data/processed/experimental/spa_dynamics_v1/spa_lmp2_experimental_selected_latency_v2_guarded_live_replay_handoff_summary.csv",
            "selected_latency_v2_guarded_live_replay_zone_summary_csv": "data/processed/experimental/spa_dynamics_v1/spa_lmp2_experimental_selected_latency_v2_guarded_live_replay_zone_summary.csv",
            "selected_latency_v2_guarded_handoff_report_html": str(
                selected_latency_v2_guarded_handoff_report_path.relative_to(PROJECT_ROOT)
            ),
        },
    }


def _current_zone_status() -> pl.DataFrame:
    piecewise_models = pl.read_csv(CURRENT_PROCESSED_DIR / "spa_lmp2_zone_piecewise_models.csv")
    return (
        piecewise_models.group_by("zone_id")
        .agg(
            pl.col("display_label").first().alias("display_label"),
            pl.col("model_status").first().alias("current_model_status"),
            pl.col("quality_flags").first().alias("current_quality_flags"),
        )
        .sort("zone_id")
    )


def _current_target_fuel_saved_l() -> float:
    fuel_targets = pl.read_csv(CURRENT_PROCESSED_DIR / "spa_lmp2_fuel_saving_targets.csv")
    candidates = fuel_targets.filter(pl.col("is_less_than_baseline_stop_count"))
    if candidates.is_empty():
        return 0.0
    preferred = candidates.sort("target_stop_count", descending=True).row(0, named=True)
    return float(preferred["required_fuel_saving_per_lap_l"])


def _experimental_reclassified_scenarios() -> tuple[ZonePlanSensitivityScenario, ...]:
    return (
        ZonePlanSensitivityScenario(
            name="base",
            notes="Promoted experimental branch with model_ready plus micro_lico_only.",
        ),
        ZonePlanSensitivityScenario(
            name="micro_excluded",
            allowed_model_statuses=("model_ready",),
            notes="Remove micro_lico_only zones to measure dependence on T14-style micro LICO.",
        ),
        ZonePlanSensitivityScenario(
            name="best_ratio_caps",
            best_ratio_cap=True,
            notes="Cap each zone at its best cumulative ratio point after reclassification.",
        ),
        ZonePlanSensitivityScenario(
            name="fuel_margin_0.01_l",
            target_fuel_margin_l=0.01,
            notes="Add a 0.01 L/lap safety margin on the reclassified branch.",
        ),
    )


def _experimental_replanning_scenarios() -> tuple[ExperimentalLapReplanningScenario, ...]:
    return (
        ExperimentalLapReplanningScenario(
            scenario_id="nominal_follow_plan",
            total_laps=48,
            notes="Nominal execution with no disturbances.",
        ),
        ExperimentalLapReplanningScenario(
            scenario_id="opening_full_push_3_laps",
            total_laps=48,
            events=tuple(
                ExperimentalLapExecutionEvent(
                    lap_number=lap_number,
                    scenario_event="opening_full_push",
                    execution_quality="full_push_override",
                    force_zero_lico=True,
                    notes="Opening fight for position; no LICO executed.",
                )
                for lap_number in range(1, 4)
            ),
            notes="Opening laps ignore LICO, then the controller must recover.",
        ),
        ExperimentalLapReplanningScenario(
            scenario_id="under_executed_mid_stint",
            total_laps=48,
            events=tuple(
                ExperimentalLapExecutionEvent(
                    lap_number=lap_number,
                    scenario_event="under_executed",
                    execution_quality="partial_execution",
                    fuel_saved_scale=0.7,
                    time_lost_scale=0.75,
                    notes="Driver misses some cues and does less lift than planned.",
                )
                for lap_number in range(18, 21)
            ),
            notes="Mid-stint under-execution forces a higher next-lap fuel demand.",
        ),
        ExperimentalLapReplanningScenario(
            scenario_id="over_executed_mid_stint",
            total_laps=48,
            events=tuple(
                ExperimentalLapExecutionEvent(
                    lap_number=lap_number,
                    scenario_event="over_executed",
                    execution_quality="heavy_execution",
                    fuel_saved_scale=1.15,
                    time_lost_scale=1.20,
                    notes="Driver lifts more than planned and pays extra time cost.",
                )
                for lap_number in range(18, 21)
            ),
            notes="Over-execution should reduce the next-lap fuel demand.",
        ),
        ExperimentalLapReplanningScenario(
            scenario_id="traffic_nonideal_lap",
            total_laps=48,
            events=(
                ExperimentalLapExecutionEvent(
                    lap_number=12,
                    scenario_event="traffic_nonideal",
                    execution_quality="traffic_nonideal",
                    extra_time_lost_s=0.35,
                    notes="Traffic disturbs the lap without changing the fuel objective directly.",
                ),
            ),
            notes="Traffic should show up in time while leaving fuel-state math intact.",
        ),
    )


def _optimizer_ready_frame(robust_zone_models: pl.DataFrame) -> pl.DataFrame:
    return robust_zone_models.with_columns(
        pl.col("robust_predicted_fuel_saved_l").alias("predicted_fuel_saved_l"),
        pl.col("robust_predicted_time_lost_s").alias("predicted_time_lost_s"),
        pl.col("robust_predicted_fuel_saved_per_second_lps").alias(
            "predicted_fuel_saved_per_second_lps"
        ),
    )


def _concat_frames(frames: list[pl.DataFrame]) -> pl.DataFrame:
    non_empty = [frame for frame in frames if not frame.is_empty()]
    if not non_empty:
        return pl.DataFrame()
    return pl.concat(non_empty, how="vertical_relaxed")


def _median_track_length_m(lap_samples: pl.DataFrame) -> float | None:
    if lap_samples.is_empty() or "lap_distance_m" not in lap_samples.columns:
        return None
    lap_maxima = (
        lap_samples.group_by(["run_id", "lap_number"])
        .agg(pl.col("lap_distance_m").max().alias("max_lap_distance_m"))
        .filter(pl.col("max_lap_distance_m") > 0.0)
    )
    if lap_maxima.is_empty():
        return None
    return float(lap_maxima["max_lap_distance_m"].median())


def _plan_variant_summary_frame(plan_map: dict[str, pl.DataFrame]) -> pl.DataFrame:
    rows = [_plan_variant_summary_row(name, plan) for name, plan in plan_map.items()]
    return pl.DataFrame(rows).sort("variant_name")


def _plan_variant_summary_row(variant_name: str, plan: pl.DataFrame) -> dict[str, object]:
    if plan.is_empty():
        return {
            "variant_name": variant_name,
            "plan_status": "empty",
            "selected_zone_count": 0,
            "selected_zone_ids": "",
            "total_predicted_fuel_saved_l": 0.0,
            "total_predicted_time_lost_s": 0.0,
            "fuel_surplus_l": None,
            "total_optimization_action_cost_m": None,
        }
    selected = plan.filter(pl.col("is_selected_for_lico")).sort("zone_id")
    first = plan.row(0, named=True)
    action_cost = first.get("total_optimization_action_cost_m")
    return {
        "variant_name": variant_name,
        "plan_status": str(first["plan_status"]),
        "selected_zone_count": int(selected.height),
        "selected_zone_ids": "|".join(str(zone_id) for zone_id in selected["zone_id"].to_list()),
        "total_predicted_fuel_saved_l": float(first["total_predicted_fuel_saved_l"]),
        "total_predicted_time_lost_s": float(first["total_predicted_time_lost_s"]),
        "fuel_surplus_l": float(first["fuel_surplus_l"]),
        "total_optimization_action_cost_m": (
            float(action_cost) if action_cost is not None else None
        ),
    }


def _git_state() -> tuple[str, bool]:
    try:
        branch = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        rebase = (PROJECT_ROOT / ".git" / "rebase-merge").exists()
        return branch, rebase
    except Exception:
        return "", False


def _model_status_snapshot(piecewise_models: pl.DataFrame) -> list[dict[str, object]]:
    grouped = piecewise_models.group_by(["zone_id", "model_status"]).agg(
        pl.len().alias("row_count"),
        pl.col("quality_flags").first().alias("quality_flags"),
        pl.col("source_bin_count").max().alias("source_bin_count"),
        pl.col("nonzero_source_bin_count").max().alias("nonzero_source_bin_count"),
    )
    return grouped.sort("zone_id").to_dicts()


def _readiness_snapshot(readiness: pl.DataFrame) -> list[dict[str, object]]:
    return readiness.select(
        "zone_id",
        "readiness_status",
        "valid_pass_count",
        "baseline_pass_count",
        "lico_pass_count",
        "lico_distance_bin_count",
        "invalid_pass_count",
        "readiness_flags",
    ).sort("zone_id").to_dicts()


def _sensitivity_snapshot(sensitivity: pl.DataFrame) -> list[dict[str, object]]:
    return sensitivity.select(
        "scenario_name",
        "plan_status",
        "total_predicted_fuel_saved_l",
        "total_predicted_time_lost_s",
        "fuel_surplus_l",
        "selected_zone_count",
        "diagnostic_selected_zone_count",
    ).to_dicts()


def _plan_snapshot(plan: pl.DataFrame) -> list[dict[str, object]]:
    return plan.select(
        "zone_id",
        "selected_lico_distance_m",
        "predicted_fuel_saved_l",
        "predicted_time_lost_s",
        "plan_status",
        "model_status",
    ).to_dicts()


def _write_csv(frame: pl.DataFrame, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    _csv_safe_frame(frame).write_csv(path)
    return path


def _csv_safe_frame(frame: pl.DataFrame) -> pl.DataFrame:
    list_columns = [
        column for column, dtype in frame.schema.items() if isinstance(dtype, pl.List)
    ]
    if not list_columns:
        return frame
    return frame.with_columns(
        [
            pl.col(column).list.eval(pl.element().cast(pl.String)).list.join("|").alias(column)
            for column in list_columns
        ]
    )


if __name__ == "__main__":
    main()
