from __future__ import annotations

from pathlib import Path

import polars as pl

from licor.reports.experimental_lap_replanner_report import (
    create_experimental_lap_replanner_report_figure,
    create_experimental_shadow_adaptive_summary_figure,
    create_experimental_zone_execution_calibration_figure,
    write_experimental_guarded_adaptive_handoff_report_html,
    write_experimental_lap_replanner_report_html,
    write_experimental_lap_replanner_validation_report_html,
    write_experimental_shadow_adaptive_report_html,
)


def test_creates_lap_replanner_report_html(tmp_path: Path) -> None:
    lap_summary = pl.DataFrame(
        {
            "scenario_id": ["nominal", "nominal", "nominal", "nominal"],
            "planning_mode": ["static", "static", "adaptive", "adaptive"],
            "lap_number": [1, 2, 1, 2],
            "fuel_target_remaining_after_l": [3.8, 3.6, 3.8, 3.55],
            "next_lap_target_fuel_saved_l": [0.08, 0.08, 0.08, 0.09],
            "cumulative_fuel_saved_l": [0.08, 0.16, 0.08, 0.17],
            "cumulative_time_lost_s": [0.30, 0.60, 0.28, 0.59],
            "scenario_event": ["nominal", "nominal", "nominal", "nominal"],
            "execution_quality": ["nominal", "nominal", "nominal", "nominal"],
            "next_lap_selected_zone_ids": ["spa_t01|spa_t18"] * 4,
        }
    )

    figure = create_experimental_lap_replanner_report_figure(
        lap_summary,
        title="Experimental replanner",
    )
    output_path = write_experimental_lap_replanner_report_html(
        figure,
        tmp_path / "replanner_report.html",
    )

    assert output_path.exists()
    assert len(figure.data) == 8


def test_creates_lap_replanner_validation_report_html(tmp_path: Path) -> None:
    lap_summary = pl.DataFrame(
        {
            "scenario_id": ["nominal", "nominal", "nominal", "nominal"],
            "planning_mode": ["static", "static", "adaptive", "adaptive"],
            "variant_name": ["robust", "robust", "robust", "robust"],
            "lap_number": [1, 2, 1, 2],
            "fuel_target_remaining_after_l": [3.8, 3.6, 3.8, 3.55],
            "next_lap_target_fuel_saved_l": [0.08, 0.08, 0.08, 0.09],
            "cumulative_fuel_saved_l": [0.08, 0.16, 0.08, 0.17],
            "cumulative_time_lost_s": [0.30, 0.60, 0.28, 0.59],
            "scenario_event": ["nominal", "nominal", "nominal", "nominal"],
            "execution_quality": ["nominal", "nominal", "nominal", "nominal"],
            "next_lap_selected_zone_ids": ["spa_t01|spa_t18"] * 4,
            "fuel_load_band": ["medium"] * 4,
            "tire_regime_label": ["baseline_like"] * 4,
            "lap_context_label": ["medium|baseline_like|stint_1"] * 4,
        }
    )
    zone_summary = pl.DataFrame(
        {
            "variant_name": ["robust"],
            "planning_mode": ["adaptive"],
            "zone_id": ["spa_t18"],
            "display_label": ["T18"],
            "source_model_status": ["model_ready"],
            "sample_count": [3],
            "zone_specific_usage_rate": [1.0],
            "execution_rate": [1.0],
            "mean_applied_fuel_scale": [0.9],
            "mean_global_fuel_scale": [0.8],
            "mean_fuel_scale_delta_vs_global": [0.1],
            "mean_applied_time_scale": [0.85],
            "mean_global_time_scale": [0.8],
            "mean_time_scale_delta_vs_global": [0.05],
            "penalized_fuel_count": [0],
            "relieved_fuel_count": [2],
            "penalized_time_count": [0],
            "relieved_time_count": [1],
            "mean_support_rows": [2.0],
        }
    )
    live_transition_preview = pl.DataFrame(
        {
            "scenario_id": ["nominal"],
            "variant_name": ["robust"],
            "planning_mode": ["adaptive"],
            "current_lap_number": [1],
            "next_lap_number": [2],
            "current_scenario_event": ["nominal"],
            "current_execution_quality": ["valid"],
            "current_notes": [""],
            "next_lap_target_fuel_saved_l": [0.09],
            "next_lap_expected_fuel_saved_l": [0.10],
            "next_lap_expected_time_lost_s": [0.21],
            "next_lap_selected_zone_count": [1],
            "next_lap_selected_zone_ids": ["spa_t18"],
            "next_lap_driver_fuel_execution_scale": [0.9],
            "next_lap_driver_time_execution_scale": [0.85],
            "next_lap_driver_zone_execution_scale_count": [1],
            "next_zone_id": ["spa_t18"],
            "next_display_label": ["T18"],
            "next_selected_lico_distance_m": [130.0],
            "next_expected_fuel_saved_by_zone_l": [0.10],
            "next_expected_time_lost_by_zone_s": [0.21],
            "next_source_model_status": ["model_ready"],
            "next_recommended_range_start_m": [100.0],
            "next_recommended_range_end_m": [140.0],
            "next_applied_driver_fuel_execution_scale": [0.9],
            "next_applied_driver_time_execution_scale": [0.85],
            "next_applied_zone_execution_support_rows": [2],
            "next_applied_zone_specific_execution_scale": [True],
        }
    )

    replanner_figure = create_experimental_lap_replanner_report_figure(
        lap_summary,
        title="Experimental replanner",
    )
    calibration_figure = create_experimental_zone_execution_calibration_figure(
        zone_summary,
        title="Zone execution calibration",
    )
    output_path = write_experimental_lap_replanner_validation_report_html(
        title="Experimental validation view",
        replanner_figure=replanner_figure,
        calibration_figure=calibration_figure,
        zone_summary=zone_summary,
        live_transition_preview=live_transition_preview,
        path=tmp_path / "replanner_validation_report.html",
    )

    assert output_path.exists()
    html = output_path.read_text(encoding="utf-8")
    assert "Zone Execution Calibration" in html
    assert "Next-Lap Live Handoff Preview" in html


def test_creates_shadow_adaptive_report_html(tmp_path: Path) -> None:
    lap_summary = pl.DataFrame(
        {
            "scenario_id": ["observed_execution:run_01", "observed_execution:run_01"],
            "planning_mode": ["adaptive", "adaptive"],
            "variant_name": ["selected_zones_latency_v2_baseline"] * 2,
            "lap_number": [8, 9],
            "fuel_target_remaining_after_l": [0.31, 0.00],
            "next_lap_target_fuel_saved_l": [0.31, 0.00],
            "cumulative_fuel_saved_l": [0.24, 0.48],
            "cumulative_time_lost_s": [0.50, 1.02],
            "scenario_event": ["observed_execution", "observed_execution"],
            "execution_quality": ["valid", "valid"],
            "next_lap_selected_zone_ids": ["spa_t01|spa_t18", ""],
            "fuel_load_band": ["medium", "light"],
            "tire_regime_label": ["baseline_like", "baseline_like"],
            "lap_context_label": ["medium|baseline_like|stint_1", "light|baseline_like|stint_1"],
        }
    )
    handoff_summary = pl.DataFrame(
        {
            "run_id": ["run_01"],
            "variant_name": ["selected_zones_latency_v2_baseline"],
            "scenario_id": ["observed_execution:run_01"],
            "current_lap_number": [8],
            "next_lap_number": [9],
            "next_lap_target_fuel_saved_l": [0.31],
            "static_zone_count": [2],
            "adaptive_zone_count": [2],
            "changed_zone_count": [2],
            "added_zone_count": [0],
            "removed_zone_count": [0],
            "mean_abs_distance_delta_m": [9.0],
            "expected_fuel_saved_delta_l": [0.005],
            "expected_time_lost_delta_s": [0.02],
            "changed_zone_ids": ["spa_t01|spa_t18"],
            "adaptive_driver_fuel_execution_scale": [0.9],
            "adaptive_driver_time_execution_scale": [0.95],
            "adaptive_zone_execution_scale_count": [2],
        }
    )
    zone_summary = pl.DataFrame(
        {
            "variant_name": ["selected_zones_latency_v2_baseline"],
            "zone_id": ["spa_t18"],
            "display_label": ["T18"],
            "sample_count": [1],
            "changed_count": [1],
            "added_count": [0],
            "removed_count": [0],
            "unchanged_count": [0],
            "longer_distance_count": [1],
            "shorter_distance_count": [0],
            "mean_distance_delta_m": [8.0],
            "mean_abs_distance_delta_m": [8.0],
            "max_abs_distance_delta_m": [8.0],
            "mean_expected_fuel_saved_delta_l": [0.01],
            "mean_expected_time_lost_delta_s": [0.03],
        }
    )
    comparison = pl.DataFrame(
        {
            "run_id": ["run_01"],
            "scenario_id": ["observed_execution:run_01"],
            "variant_name": ["selected_zones_latency_v2_baseline"],
            "current_lap_number": [8],
            "next_lap_number": [9],
            "zone_id": ["spa_t18"],
            "display_label": ["T18"],
            "change_type": ["longer_distance"],
            "static_selected_lico_distance_m": [132.0],
            "adaptive_selected_lico_distance_m": [140.0],
            "distance_delta_m": [8.0],
            "static_expected_fuel_saved_l": [0.06],
            "adaptive_expected_fuel_saved_l": [0.07],
            "expected_fuel_saved_delta_l": [0.01],
            "static_expected_time_lost_s": [0.24],
            "adaptive_expected_time_lost_s": [0.27],
            "expected_time_lost_delta_s": [0.03],
        }
    )
    preview = pl.DataFrame(
        {
            "scenario_id": ["observed_execution:run_01"],
            "variant_name": ["selected_zones_latency_v2_baseline"],
            "planning_mode": ["adaptive"],
            "current_lap_number": [8],
            "next_lap_number": [9],
            "next_zone_id": ["spa_t18"],
            "next_selected_lico_distance_m": [140.0],
            "next_applied_driver_fuel_execution_scale": [0.92],
            "next_applied_driver_time_execution_scale": [0.96],
            "next_applied_zone_execution_support_rows": [2],
            "next_lap_target_fuel_saved_l": [0.31],
        }
    )
    replay_handoff_summary = pl.DataFrame(
        {
            "run_id": ["run_01"],
            "current_lap_number": [8],
            "next_lap_number": [9],
            "planned_zone_ids": ["spa_t01|spa_t18"],
            "cue_on_time_rate": [0.8],
            "median_abs_cue_error_m": [3.0],
            "expected_fuel_saved_total_l": [0.31],
            "actual_fuel_saved_total_l": [0.29],
            "fuel_saved_total_error_l": [-0.02],
            "expected_time_lost_total_s": [1.02],
            "actual_time_lost_total_s": [0.99],
            "time_lost_total_error_s": [-0.03],
        }
    )
    replay_zone_summary = pl.DataFrame(
        {
            "display_label": ["T18"],
            "sample_count": [1],
            "cue_on_time_rate": [1.0],
            "median_abs_cue_error_m": [2.0],
            "zone_execution_rate": [1.0],
            "mean_fuel_saved_error_l": [-0.01],
            "mean_time_lost_error_s": [-0.02],
        }
    )

    replanner_figure = create_experimental_lap_replanner_report_figure(
        lap_summary,
        title="Shadow replanner",
    )
    shadow_figure = create_experimental_shadow_adaptive_summary_figure(
        handoff_summary,
        zone_summary,
        title="Shadow comparison",
    )
    output_path = write_experimental_shadow_adaptive_report_html(
        title="Shadow adaptive report",
        replanner_figure=replanner_figure,
        shadow_figure=shadow_figure,
        handoff_summary=handoff_summary,
        zone_summary=zone_summary,
        transition_comparison=comparison,
        live_transition_preview=preview,
        replay_handoff_summary=replay_handoff_summary,
        replay_zone_summary=replay_zone_summary,
        path=tmp_path / "shadow_adaptive_report.html",
    )

    assert output_path.exists()
    html = output_path.read_text(encoding="utf-8")
    assert "Static vs Shadow Adaptive Delta" in html
    assert "Replay Check On The Actual Next Lap" in html


def test_creates_guarded_adaptive_handoff_report_html(tmp_path: Path) -> None:
    summary = pl.DataFrame(
        {
            "run_id": ["run_01"],
            "current_lap_number": [8],
            "next_lap_number": [9],
            "next_lap_target_fuel_saved_l": [0.26],
            "raw_changed_zone_count": [4],
            "guarded_changed_zone_count": [3],
            "clamped_zone_count": [2],
            "blocked_zone_count": [0],
            "guarded_zone_count": [6],
            "mean_guarded_abs_distance_delta_m": [9.0],
            "guarded_expected_fuel_saved_total_l": [0.27],
            "guarded_expected_time_lost_total_s": [0.71],
            "target_met_after_guardrails": [True],
            "guardrail_reasons": ["accepted_raw_adaptive|clamped_low_support"],
        }
    )
    detail = pl.DataFrame(
        {
            "run_id": ["run_01"],
            "current_lap_number": [8],
            "next_lap_number": [9],
            "zone_id": ["spa_t18"],
            "display_label": ["T18"],
            "support_rows": [1],
            "static_selected_lico_distance_m": [140.0],
            "raw_adaptive_selected_lico_distance_m": [120.0],
            "guarded_selected_lico_distance_m": [130.0],
            "raw_distance_delta_m": [-20.0],
            "guarded_distance_delta_m": [-10.0],
            "guardrail_reason": ["clamped_low_support"],
            "keep_in_guarded_plan": [True],
            "static_expected_fuel_saved_l": [0.06],
            "raw_adaptive_expected_fuel_saved_l": [0.05],
            "guarded_expected_fuel_saved_l": [0.055],
            "static_expected_time_lost_s": [0.24],
            "raw_adaptive_expected_time_lost_s": [0.18],
            "guarded_expected_time_lost_s": [0.21],
        }
    )
    preview = pl.DataFrame(
        {
            "scenario_id": ["observed_execution:run_01"],
            "variant_name": ["selected_zones_latency_v2_baseline"],
            "planning_mode": ["adaptive_guarded"],
            "current_lap_number": [8],
            "next_lap_number": [9],
            "next_zone_id": ["spa_t18"],
            "next_selected_lico_distance_m": [130.0],
            "next_expected_fuel_saved_by_zone_l": [0.055],
            "next_expected_time_lost_by_zone_s": [0.21],
            "next_lap_target_fuel_saved_l": [0.26],
            "next_lap_expected_fuel_saved_l": [0.27],
            "next_lap_expected_time_lost_s": [0.71],
        }
    )
    live_plan = pl.DataFrame(
        {
            "plan_id": ["handoff_plan"],
            "run_id": ["run_01"],
            "current_lap_number": [8],
            "next_lap_number": [9],
            "zone_id": ["spa_t18"],
            "display_label": ["T18"],
            "selected_lico_distance_m": [130.0],
            "planned_lift_start_m": [6300.0],
            "cue_distance_m": [6270.0],
            "expected_fuel_saved_l": [0.055],
            "expected_time_lost_s": [0.21],
            "cue_latency_compensation_distance_m": [27.0],
        }
    )
    replay = pl.DataFrame(
        {
            "run_id": ["run_01"],
            "current_lap_number": [8],
            "next_lap_number": [9],
            "planned_zone_ids": ["spa_t18"],
            "cue_on_time_rate": [1.0],
            "median_abs_cue_error_m": [2.0],
            "expected_fuel_saved_total_l": [0.27],
            "actual_fuel_saved_total_l": [0.28],
            "fuel_saved_total_error_l": [0.01],
            "expected_time_lost_total_s": [0.71],
            "actual_time_lost_total_s": [0.69],
            "time_lost_total_error_s": [-0.02],
        }
    )

    output_path = write_experimental_guarded_adaptive_handoff_report_html(
        title="Guarded adaptive handoff",
        summary=summary,
        detail=detail,
        guarded_live_transition_preview=preview,
        guarded_live_plan=live_plan,
        guarded_replay_handoff_summary=replay,
        path=tmp_path / "guarded_adaptive_handoff_report.html",
    )

    assert output_path.exists()
    html = output_path.read_text(encoding="utf-8")
    assert "Guarded Handoff Summary" in html
    assert "Guarded Live Plan Export" in html
