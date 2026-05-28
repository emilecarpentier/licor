from __future__ import annotations

import polars as pl
import pytest

from licor.analysis.experimental_live_replay_validation import (
    ExperimentalLiveReplayValidationConfig,
    build_experimental_live_replay_plan,
    replay_experimental_live_replay_plan,
)


def test_builds_live_replay_plan_from_transition_preview() -> None:
    plan = build_experimental_live_replay_plan(
        _transition_preview(),
        _track_zones(),
        config=ExperimentalLiveReplayValidationConfig(
            track_name="Spa",
            car_class="LMP2",
            race_context_id="ctx",
            track_length_m=7000.0,
        ),
    )

    assert plan.height == 1
    row = plan.row(0, named=True)
    assert row["planning_mode"] == "adaptive"
    assert row["plan_id"].startswith("experimental_adaptive_replay|")
    assert row["planned_lift_start_m"] == 300.0
    assert row["cue_distance_m"] == 300.0
    assert row["run_id"] == "run_01"


def test_builds_live_replay_plan_with_latency_compensation() -> None:
    plan = build_experimental_live_replay_plan(
        _transition_preview(),
        _track_zones(),
        config=ExperimentalLiveReplayValidationConfig(
            track_name="Spa",
            car_class="LMP2",
            race_context_id="ctx",
            track_length_m=7000.0,
            cue_latency_compensation_s=0.35,
            cue_latency_reference_speed_kph=250.0,
        ),
    )

    row = plan.row(0, named=True)
    assert row["planned_lift_start_m"] == 300.0
    assert row["cue_distance_m"] == pytest.approx(275.69444444444446)
    assert row["cue_latency_compensation_distance_m"] == pytest.approx(
        24.305555555555557
    )


def test_builds_live_replay_plan_with_row_level_latency_speed() -> None:
    plan = build_experimental_live_replay_plan(
        _transition_preview().with_columns(
            pl.lit(180.0).alias("next_cue_latency_reference_speed_kph")
        ),
        _track_zones(),
        config=ExperimentalLiveReplayValidationConfig(
            track_name="Spa",
            car_class="LMP2",
            race_context_id="ctx",
            track_length_m=7000.0,
            cue_latency_compensation_s=0.35,
            cue_latency_reference_speed_kph=250.0,
        ),
    )

    row = plan.row(0, named=True)
    assert row["cue_latency_reference_speed_kph"] == pytest.approx(180.0)
    assert row["cue_distance_m"] == pytest.approx(282.5)
    assert row["cue_latency_compensation_distance_m"] == pytest.approx(17.5)


def test_replays_live_replay_plan_and_compares_to_observed_outcomes() -> None:
    live_replay_plan = build_experimental_live_replay_plan(
        _transition_preview(),
        _track_zones(),
        config=ExperimentalLiveReplayValidationConfig(
            track_length_m=7000.0,
        ),
    )

    events, accuracy, validation_rows, handoff_summary, zone_summary = (
        replay_experimental_live_replay_plan(
            live_replay_plan,
            _lap_samples(),
            _observed_zone_outcomes(),
            config=ExperimentalLiveReplayValidationConfig(track_length_m=7000.0),
        )
    )

    assert events.height == 1
    assert events.select("zone_id", "trigger_status").rows() == [
        ("T01", "fired_on_time"),
    ]
    assert accuracy.select("zone_id", "cue_count").rows() == [("T01", 1)]

    validation = validation_rows.row(0, named=True)
    assert validation["telemetry_available"] is True
    assert validation["cue_fired"] is True
    assert validation["cue_fired_on_time"] is True
    assert validation["actual_lift_distance_before_brake_m"] == 50.0
    assert validation["actual_distance_before_brake_error_m"] == pytest.approx(0.0)
    assert validation["fuel_saved_error_l"] == pytest.approx(-0.005)
    assert validation["time_lost_error_s"] == pytest.approx(-0.01)

    handoff = handoff_summary.row(0, named=True)
    assert handoff["planned_zone_count"] == 1
    assert handoff["telemetry_available"] is True
    assert handoff["cue_on_time_rate"] == 1.0
    assert handoff["fuel_saved_total_error_l"] == pytest.approx(-0.005)

    zone = zone_summary.row(0, named=True)
    assert zone["zone_id"] == "T01"
    assert zone["telemetry_available_rate"] == 1.0
    assert zone["cue_on_time_rate"] == 1.0
    assert zone["mean_actual_fuel_saved_l"] == 0.025


def test_leaves_errors_null_when_no_lift_is_observed() -> None:
    live_replay_plan = build_experimental_live_replay_plan(
        _transition_preview(),
        _track_zones(),
    )

    _, _, validation_rows, handoff_summary, _ = replay_experimental_live_replay_plan(
        live_replay_plan,
        _lap_samples(),
        _observed_zone_outcomes().with_columns(pl.lit(None).alias("lico_start_m")),
    )

    validation = validation_rows.row(0, named=True)
    assert validation["actual_zone_executed"] is False
    assert validation["actual_fuel_saved_l"] is None
    assert validation["fuel_saved_error_l"] is None
    assert validation["time_lost_error_s"] is None
    assert handoff_summary.row(0, named=True)["executed_zone_count"] == 0


def test_marks_missing_telemetry_as_not_replayed_instead_of_cue_miss() -> None:
    live_replay_plan = build_experimental_live_replay_plan(
        _transition_preview(),
        _track_zones(),
    )

    _, _, validation_rows, handoff_summary, zone_summary = replay_experimental_live_replay_plan(
        live_replay_plan,
        pl.DataFrame(schema=_lap_samples().schema),
        _observed_zone_outcomes(),
    )

    validation = validation_rows.row(0, named=True)
    assert validation["telemetry_available"] is False
    assert validation["cue_fired"] is None
    assert validation["cue_fired_on_time"] is None
    assert handoff_summary.row(0, named=True)["telemetry_available"] is False
    assert zone_summary.row(0, named=True)["telemetry_available_rate"] == 0.0


def _transition_preview() -> pl.DataFrame:
    return pl.DataFrame(
        [
            {
                "scenario_id": "observed_execution:run_01",
                "variant_name": "range_aware_all_eligible_zones",
                "planning_mode": "adaptive",
                "current_lap_number": 1,
                "next_lap_number": 2,
                "current_scenario_event": "observed_execution",
                "current_execution_quality": "nominal",
                "current_notes": "note",
                "next_lap_target_fuel_saved_l": 0.30,
                "next_lap_expected_fuel_saved_l": 0.03,
                "next_lap_expected_time_lost_s": 0.10,
                "next_lap_selected_zone_count": 1,
                "next_lap_selected_zone_ids": "T01",
                "next_lap_driver_fuel_execution_scale": 0.90,
                "next_lap_driver_time_execution_scale": 0.95,
                "next_lap_driver_zone_execution_scale_count": 1,
                "next_zone_id": "T01",
                "next_display_label": "T01",
                "next_selected_lico_distance_m": 50.0,
                "next_expected_fuel_saved_by_zone_l": 0.03,
                "next_expected_time_lost_by_zone_s": 0.10,
                "next_source_model_status": "model_ready",
                "next_recommended_range_start_m": 40.0,
                "next_recommended_range_end_m": 60.0,
                "next_applied_driver_fuel_execution_scale": 0.90,
                "next_applied_driver_time_execution_scale": 0.95,
                "next_applied_zone_execution_support_rows": 2,
                "next_applied_zone_specific_execution_scale": True,
            },
            {
                "scenario_id": "observed_execution:run_01",
                "variant_name": "range_aware_all_eligible_zones",
                "planning_mode": "static",
                "current_lap_number": 1,
                "next_lap_number": 2,
                "current_scenario_event": "observed_execution",
                "current_execution_quality": "nominal",
                "current_notes": "note",
                "next_lap_target_fuel_saved_l": 0.30,
                "next_lap_expected_fuel_saved_l": 0.03,
                "next_lap_expected_time_lost_s": 0.10,
                "next_lap_selected_zone_count": 1,
                "next_lap_selected_zone_ids": "T01",
                "next_lap_driver_fuel_execution_scale": 1.00,
                "next_lap_driver_time_execution_scale": 1.00,
                "next_lap_driver_zone_execution_scale_count": 0,
                "next_zone_id": "T01",
                "next_display_label": "T01",
                "next_selected_lico_distance_m": 50.0,
                "next_expected_fuel_saved_by_zone_l": 0.03,
                "next_expected_time_lost_by_zone_s": 0.10,
                "next_source_model_status": "model_ready",
                "next_recommended_range_start_m": 40.0,
                "next_recommended_range_end_m": 60.0,
                "next_applied_driver_fuel_execution_scale": 1.00,
                "next_applied_driver_time_execution_scale": 1.00,
                "next_applied_zone_execution_support_rows": 0,
                "next_applied_zone_specific_execution_scale": False,
            },
        ]
    )


def _track_zones() -> pl.DataFrame:
    return pl.DataFrame(
        [
            {
                "zone_id": "T01",
                "display_label": "T01",
                "brake_reference_m": 350.0,
            }
        ]
    )


def _lap_samples() -> pl.DataFrame:
    return pl.DataFrame(
        [
            {
                "run_id": "run_01",
                "file_name": "run_01.duckdb",
                "lap_number": 2,
                "ts": 10.0,
                "lap_elapsed_s": 0.0,
                "lap_distance_m": 280.0,
            },
            {
                "run_id": "run_01",
                "file_name": "run_01.duckdb",
                "lap_number": 2,
                "ts": 10.2,
                "lap_elapsed_s": 0.2,
                "lap_distance_m": 301.0,
            },
        ]
    )


def _observed_zone_outcomes() -> pl.DataFrame:
    return pl.DataFrame(
        [
            {
                "run_id": "run_01",
                "lap_number": 2,
                "zone_id": "T01",
                "lico_start_m": 298.0,
                "lico_start_distance_before_brake_m": 50.0,
                "brake_start_m": 348.0,
                "fuel_saved_vs_baseline_l": 0.025,
                "time_lost_vs_baseline_s": 0.09,
                "validity_label": "valid",
                "notes": "observed",
            }
        ]
    )
