import importlib.util
from pathlib import Path

import polars as pl
import pytest

from licor.analysis.cross_circuit_ml import build_split_assignments


SPEC = importlib.util.spec_from_file_location(
    "cross_circuit_ml_v2_builder",
    Path(__file__).resolve().parents[1] / "scripts/build_cross_circuit_ml_table_v2.py",
)
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


def test_frozen_schedule_overrides_false_positive_coasts_and_silent_zones():
    frame = pl.DataFrame(
        {
            "run_id": [builder.BAHRAIN_LICO] * 3,
            "lap_number": [26, 27, 27],
            "zone_id": ["bhr_t04", "bhr_t04", "bhr_t13"],
            "has_lico": [True, True, True],
            "lico_start_m": [1000.0, 900.0, 4000.0],
            "planned_lift_start_m": [None] * 3,
        }
    )
    plan = pl.DataFrame({"zone_id": ["bhr_t04"], "planned_lift_start_m": [900.0]})

    result = builder.apply_bahrain_schedule(frame, plan).sort("lap_number", "zone_id")

    assert result["observed_has_lico"].to_list() == [True] * 3
    assert result["has_lico"].to_list() == [False, True, False]
    assert result["lico_start_m"].to_list() == [None, 900.0, None]
    assert result["is_push_reference_candidate"].to_list() == [True, False, False]
    assert result["planned_lift_start_m"].to_list() == [None, 900.0, None]


def test_phase_masks_keep_prebrake_but_remove_contaminated_apex_denominator():
    frame = pl.DataFrame(
        {
            "run_id": [builder.BAHRAIN_PUSH] * 2,
            "lap_number": [18, 19],
            "zone_id": ["bhr_t04"] * 2,
            "validity_label": ["borderline"] * 2,
            "elapsed_time_s": [10.0, 11.0],
            "fuel_used_l": [0.3, 0.4],
            "exit_speed_kph": [160.0, 150.0],
            "min_speed_point_kph": [80.0, 85.0],
            "min_speed_point_m": [500.0, 510.0],
            "push_deceleration_distance_observed_m": [200.0, 210.0],
            "main_brake_onset_m": [300.0] * 2,
            "approach_acceleration_ratio_0_0_mps2": [1.0] * 2,
            "approach_acceleration_ratio_0_5_mps2": [1.0] * 2,
        }
    )
    review = {
        "phase_metric_masks": [
            {
                "run_id": builder.BAHRAIN_PUSH,
                "lap_number": 19,
                "zone_id": "bhr_t04",
                "excluded_metrics": [
                    "zone_elapsed_time",
                    "zone_fuel_used",
                    "exit_speed",
                    "apex_speed",
                ],
                "reason": "T4 mid/exit error",
            }
        ]
    }

    result = builder.apply_phase_masks(frame, review)

    assert result["model_eligible"].to_list() == [True, True]
    assert result["fuel_used_l"].to_list() == [0.3, None]
    assert result["push_deceleration_distance_observed_m"].to_list() == [200.0, None]
    assert result["main_brake_onset_m"].to_list() == [300.0] * 2
    assert result["approach_acceleration_ratio_0_0_mps2"].to_list() == [1.0] * 2
    assert result["approach_acceleration_ratio_0_5_mps2"].to_list() == [1.0, None]


def test_reference_support_is_per_metric_and_test_push_cannot_enter():
    frame = _references_fixture()
    manifest = {
        "folds": [
            {
                "fold_id": "f",
                "evaluation_regime": "within_circuit_leave_one_run_out",
                "train_run_ids": ["train_push"],
                "test_run_ids": ["test_run"],
            }
        ]
    }
    assignments = build_split_assignments(frame, manifest)
    references = builder.fit_supported_references(frame, assignments, fold_id="f")

    assert references["push_fuel_support"][0] == 2
    assert references["push_time_support"][0] == 3
    assert references["push_deceleration_support"][0] == 2
    assert references["push_fuel_used_reference_l"][0] is None
    assert references["push_elapsed_time_reference_s"][0] == pytest.approx(10.0)
    assert (
        references["push_reference_status"][0]
        == "insufficient_push_denominator_support"
    )


def test_existing_pack_cannot_be_overwritten():
    with pytest.raises(FileExistsError, match="refusing to replace"):
        builder.build_pack(builder.PROJECT_ROOT, builder.PROJECT_ROOT)


def _references_fixture():
    rows = []
    for index in range(4):
        rows.append(
            {
                "observation_id": str(index),
                "run_id": "train_push" if index < 3 else "test_run",
                "source_raw_sha256": "a" if index < 3 else "b",
                "circuit_id": "a",
                "lap_number": index + 1,
                "zone_id": "z",
                "has_lico": False,
                "model_eligible": True,
                "is_push_reference_candidate": True,
                "braking_event_quality": "ready",
                "main_brake_onset_m": 200.0,
                "push_deceleration_distance_observed_m": None if index == 2 else 100.0,
                "zone_start_speed_kph": 280.0,
                "main_brake_onset_speed_kph": 280.0,
                "fuel_used_l": None if index == 2 else 0.3,
                "elapsed_time_s": 10.0 if index < 3 else 999.0,
                "min_speed_point_kph": 80.0,
                "exit_speed_kph": 140.0,
                **{
                    f"approach_acceleration_ratio_{ratio}_mps2": 1.0
                    for ratio in ("0_0", "0_25", "0_5", "1_0", "1_5")
                },
            }
        )
    return pl.DataFrame(rows)
