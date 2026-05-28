import polars as pl
import pytest

from licor.analysis import (
    LiveCuePlanConfig,
    build_live_cue_executions_from_zone_passes,
    build_live_cue_plan,
)


def test_builds_versioned_live_cue_plan_from_selected_zone_plan():
    plan = pl.DataFrame(
        [
            _zone_plan_row("spa_t01", "T01", 60.0, True, 0.05, 0.10),
            _zone_plan_row("spa_t05_t06", "T05-T06", 0.0, False, 0.0, 0.0),
        ]
    )
    zones = pl.DataFrame(
        [
            {"zone_id": "spa_t01", "brake_reference_m": 410.0},
            {"zone_id": "spa_t05_t06", "brake_reference_m": 1850.0},
        ]
    )

    live_plan = build_live_cue_plan(
        plan,
        zones,
        config=LiveCuePlanConfig(
            plan_id="spa_prudent_v1",
            track_name="Spa-Francorchamps",
            car_class="LMP2",
            race_context_id="elms_100m_48_laps",
            minimum_confidence_label="driver_review",
            cue_tolerance_m=7.5,
            notes="synthetic",
        ),
    )

    assert live_plan.height == 1
    row = live_plan.row(0, named=True)
    assert row["schema_version"] == 1
    assert row["plan_id"] == "spa_prudent_v1"
    assert row["zone_id"] == "spa_t01"
    assert row["planned_lift_start_m"] == pytest.approx(350.0)
    assert row["cue_distance_m"] == pytest.approx(350.0)
    assert row["track_length_m"] is None
    assert row["expected_fuel_saved_l"] == pytest.approx(0.05)
    assert row["expected_time_lost_s"] == pytest.approx(0.10)
    assert row["source_model_status"] == "diagnostic_only"
    assert row["strategy_role"] == "usable"
    assert row["notes"] == "synthetic"


def test_wraps_planned_lift_start_when_track_length_is_provided():
    plan = pl.DataFrame([_zone_plan_row("final", "Final", 80.0, True, 0.04, 0.07)])
    zones = pl.DataFrame([{"zone_id": "final", "brake_reference_m": 50.0}])

    live_plan = build_live_cue_plan(
        plan,
        zones,
        config=LiveCuePlanConfig(
            plan_id="wrap",
            track_name="Synthetic",
            car_class="TEST",
            track_length_m=7000.0,
        ),
    )

    assert live_plan["planned_lift_start_m"].to_list() == [pytest.approx(6970.0)]
    assert live_plan["track_length_m"].to_list() == [pytest.approx(7000.0)]


def test_advances_cue_distance_for_latency_compensation():
    plan = pl.DataFrame([_zone_plan_row("spa_t01", "T01", 60.0, True, 0.05, 0.10)])
    zones = pl.DataFrame([{"zone_id": "spa_t01", "brake_reference_m": 410.0}])

    live_plan = build_live_cue_plan(
        plan,
        zones,
        config=LiveCuePlanConfig(
            plan_id="latency",
            track_name="Spa-Francorchamps",
            car_class="LMP2",
            cue_latency_compensation_s=0.35,
            cue_latency_reference_speed_kph=250.0,
        ),
    )

    row = live_plan.row(0, named=True)
    assert row["planned_lift_start_m"] == pytest.approx(350.0)
    assert row["cue_distance_m"] == pytest.approx(325.69444444444446)
    assert row["cue_latency_compensation_distance_m"] == pytest.approx(
        24.305555555555557
    )
    assert row["cue_latency_reference_speed_kph"] == pytest.approx(250.0)


def test_uses_plan_row_speed_for_latency_compensation_when_available():
    plan = pl.DataFrame(
        [
            {
                **_zone_plan_row("spa_t01", "T01", 60.0, True, 0.05, 0.10),
                "mean_brake_start_speed_kph": 180.0,
            }
        ]
    )
    zones = pl.DataFrame([{"zone_id": "spa_t01", "brake_reference_m": 410.0}])

    live_plan = build_live_cue_plan(
        plan,
        zones,
        config=LiveCuePlanConfig(
            plan_id="latency_row_speed",
            track_name="Spa-Francorchamps",
            car_class="LMP2",
            cue_latency_compensation_s=0.30,
        ),
    )

    row = live_plan.row(0, named=True)
    assert row["cue_latency_reference_speed_kph"] == pytest.approx(180.0)
    assert row["cue_latency_compensation_distance_m"] == pytest.approx(15.0)
    assert row["cue_distance_m"] == pytest.approx(335.0)


def test_reports_missing_speed_when_latency_compensation_cannot_be_computed():
    plan = pl.DataFrame([_zone_plan_row("spa_t01", "T01", 60.0, True, 0.05, 0.10)])
    zones = pl.DataFrame([{"zone_id": "spa_t01", "brake_reference_m": 410.0}])

    with pytest.raises(ValueError, match="cue latency compensation requires"):
        build_live_cue_plan(
            plan,
            zones,
            config=LiveCuePlanConfig(
                plan_id="latency_missing_speed",
                track_name="Spa-Francorchamps",
                car_class="LMP2",
                cue_latency_compensation_s=0.35,
            ),
        )


def test_reports_missing_brake_reference_for_selected_zone():
    plan = pl.DataFrame([_zone_plan_row("missing", "Missing", 40.0, True, 0.02, 0.06)])
    zones = pl.DataFrame([{"zone_id": "other", "brake_reference_m": 100.0}])

    with pytest.raises(ValueError, match="missing brake_reference_m"):
        build_live_cue_plan(
            plan,
            zones,
            config=LiveCuePlanConfig(
                plan_id="bad",
                track_name="Synthetic",
                car_class="TEST",
            ),
        )


def test_builds_replay_execution_rows_from_zone_passes():
    live_plan = pl.DataFrame(
        [
            {
                "schema_version": 1,
                "plan_id": "spa_prudent_v1",
                "track_name": "Spa",
                "car_class": "LMP2",
                "race_context_id": "elms",
                "zone_id": "spa_t01",
                "display_label": "T01",
                "brake_reference_m": 410.0,
                "selected_lico_distance_m": 60.0,
                "planned_lift_start_m": 350.0,
                "cue_distance_m": 350.0,
                "cue_tolerance_m": 5.0,
                "track_length_m": None,
                "minimum_confidence_label": "review",
                "expected_fuel_saved_l": 0.05,
                "expected_time_lost_s": 0.10,
                "plan_status": "target_met",
                "source_model_status": "diagnostic_only",
                "source_quality_flags": "synthetic",
                "strategy_role": "usable",
                "notes": "",
            }
        ]
    )
    zone_passes = pl.DataFrame(
        [
            {
                "file_name": "run.duckdb",
                "run_id": "run_01",
                "lap_number": 4,
                "zone_id": "spa_t01",
                "lico_start_m": 346.0,
                "lico_start_distance_before_brake_m": 64.0,
                "brake_start_m": 410.0,
                "fuel_delta_l": 0.047,
                "time_delta_s": 0.11,
                "validity_label": "valid",
                "notes": "clean replay",
            }
        ]
    )

    executions = build_live_cue_executions_from_zone_passes(live_plan, zone_passes)

    assert executions.height == 1
    row = executions.row(0, named=True)
    assert row["schema_version"] == 1
    assert row["plan_id"] == "spa_prudent_v1"
    assert row["cue_trigger_m"] == pytest.approx(350.0)
    assert row["planned_lift_start_m"] == pytest.approx(350.0)
    assert row["actual_lift_start_m"] == pytest.approx(346.0)
    assert row["actual_lift_distance_before_brake_m"] == pytest.approx(64.0)
    assert row["cue_error_m"] == pytest.approx(-4.0)
    assert row["fuel_saved_vs_baseline_l"] == pytest.approx(0.047)
    assert row["time_lost_vs_baseline_s"] == pytest.approx(0.11)
    assert row["execution_quality"] == "valid"


def _zone_plan_row(
    zone_id: str,
    display_label: str,
    selected_lico_distance_m: float,
    is_selected_for_lico: bool,
    predicted_fuel_saved_l: float,
    predicted_time_lost_s: float,
) -> dict[str, object]:
    return {
        "zone_id": zone_id,
        "display_label": display_label,
        "selected_lico_distance_m": selected_lico_distance_m,
        "is_selected_for_lico": is_selected_for_lico,
        "predicted_fuel_saved_l": predicted_fuel_saved_l,
        "predicted_time_lost_s": predicted_time_lost_s,
        "plan_status": "target_met",
        "model_status": "diagnostic_only",
        "quality_flags": "synthetic",
        "strategy_role": "usable",
    }


def test_builds_replay_execution_rows_from_existing_baseline_delta_columns():
    live_plan = pl.DataFrame(
        [
            {
                "schema_version": 1,
                "plan_id": "spa_prudent_v1",
                "track_name": "Spa",
                "car_class": "LMP2",
                "race_context_id": "elms",
                "zone_id": "spa_t01",
                "display_label": "T01",
                "brake_reference_m": 410.0,
                "selected_lico_distance_m": 60.0,
                "planned_lift_start_m": 350.0,
                "cue_distance_m": 350.0,
                "cue_tolerance_m": 5.0,
                "track_length_m": None,
                "minimum_confidence_label": "review",
                "expected_fuel_saved_l": 0.05,
                "expected_time_lost_s": 0.10,
                "plan_status": "target_met",
                "source_model_status": "diagnostic_only",
                "source_quality_flags": "synthetic",
                "strategy_role": "usable",
                "notes": "",
            }
        ]
    )
    zone_passes = pl.DataFrame(
        [
            {
                "lap_number": 4,
                "zone_id": "spa_t01",
                "lico_start_m": 346.0,
                "fuel_saved_vs_baseline_l": 0.047,
                "time_lost_vs_baseline_s": 0.11,
            }
        ]
    )

    row = build_live_cue_executions_from_zone_passes(
        live_plan,
        zone_passes,
    ).row(0, named=True)

    assert row["fuel_saved_vs_baseline_l"] == pytest.approx(0.047)
    assert row["time_lost_vs_baseline_s"] == pytest.approx(0.11)


def test_builds_replay_execution_rows_with_circular_cue_error():
    live_plan = pl.DataFrame(
        [
            {
                "plan_id": "wrap",
                "zone_id": "final",
                "cue_distance_m": 6970.0,
                "planned_lift_start_m": 6970.0,
                "track_length_m": 7000.0,
            }
        ]
    )
    zone_passes = pl.DataFrame(
        [
            {
                "lap_number": 1,
                "zone_id": "final",
                "lico_start_m": 10.0,
            }
        ]
    )

    row = build_live_cue_executions_from_zone_passes(
        live_plan,
        zone_passes,
    ).row(0, named=True)

    assert row["cue_error_m"] == pytest.approx(40.0)
