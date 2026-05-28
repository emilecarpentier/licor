from __future__ import annotations

from pathlib import Path

import polars as pl

from licor.reports.experimental_live_replay_validation_report import (
    create_experimental_live_replay_validation_figure,
    write_experimental_live_replay_validation_report_html,
)


def test_creates_live_replay_validation_report_html(tmp_path: Path) -> None:
    handoff_summary = pl.DataFrame(
        [
            {
                "variant_name": "range_aware_all_eligible_zones",
                "planning_mode": "adaptive",
                "scenario_id": "observed_execution:run_01",
                "run_id": "run_01",
                "current_lap_number": 1,
                "next_lap_number": 2,
                "planned_zone_count": 1,
                "planned_zone_ids": "T01",
                "telemetry_available": True,
                "cue_fire_rate": 1.0,
                "cue_on_time_rate": 1.0,
                "mean_cue_error_m": 1.0,
                "median_abs_cue_error_m": 1.0,
                "max_abs_cue_error_m": 1.0,
                "zone_execution_rate": 1.0,
                "executed_zone_count": 1,
                "expected_fuel_saved_total_l": 0.03,
                "actual_fuel_saved_total_l": 0.025,
                "fuel_saved_total_error_l": -0.005,
                "expected_time_lost_total_s": 0.10,
                "actual_time_lost_total_s": 0.09,
                "time_lost_total_error_s": -0.01,
                "next_lap_target_fuel_saved_l": 0.30,
                "next_lap_expected_fuel_saved_l": 0.03,
                "next_lap_expected_time_lost_s": 0.10,
                "next_lap_driver_fuel_execution_scale": 0.90,
                "next_lap_driver_time_execution_scale": 0.95,
                "next_lap_driver_zone_execution_scale_count": 1,
            }
        ]
    )
    zone_summary = pl.DataFrame(
        [
            {
                "variant_name": "range_aware_all_eligible_zones",
                "planning_mode": "adaptive",
                "zone_id": "T01",
                "display_label": "T01",
                "source_model_status": "model_ready",
                "sample_count": 1,
                "telemetry_available_rate": 1.0,
                "cue_fire_rate": 1.0,
                "cue_on_time_rate": 1.0,
                "mean_cue_error_m": 1.0,
                "median_abs_cue_error_m": 1.0,
                "zone_execution_rate": 1.0,
                "mean_expected_fuel_saved_l": 0.03,
                "mean_actual_fuel_saved_l": 0.025,
                "mean_fuel_saved_error_l": -0.005,
                "mean_expected_time_lost_s": 0.10,
                "mean_actual_time_lost_s": 0.09,
                "mean_time_lost_error_s": -0.01,
            }
        ]
    )
    validation_rows = pl.DataFrame(
        [
            {
                "variant_name": "range_aware_all_eligible_zones",
                "planning_mode": "adaptive",
                "scenario_id": "observed_execution:run_01",
                "current_lap_number": 1,
                "next_lap_number": 2,
                "zone_id": "T01",
                "display_label": "T01",
                "selected_lico_distance_m": 50.0,
                "next_recommended_range_start_m": 40.0,
                "next_recommended_range_end_m": 60.0,
                "telemetry_available": True,
                "trigger_status": "fired_on_time",
                "cue_error_m": 1.0,
                "actual_lift_distance_before_brake_m": 50.0,
                "actual_distance_before_brake_error_m": 0.0,
                "actual_fuel_saved_l": 0.025,
                "fuel_saved_error_l": -0.005,
                "actual_time_lost_s": 0.09,
                "time_lost_error_s": -0.01,
            }
        ]
    )

    figure = create_experimental_live_replay_validation_figure(
        handoff_summary,
        title="Adaptive replay validation",
    )
    output_path = write_experimental_live_replay_validation_report_html(
        title="Adaptive replay validation",
        figure=figure,
        handoff_summary=handoff_summary,
        zone_summary=zone_summary,
        validation_rows=validation_rows,
        path=tmp_path / "adaptive_replay_validation.html",
    )

    html = output_path.read_text(encoding="utf-8")
    assert "Adaptive replay validation" in html
    assert "Lap-to-Lap Handoff Summary" in html
    assert "Detailed Validation Rows" in html
