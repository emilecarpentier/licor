import polars as pl
import pytest

from licor.analysis.cross_circuit_ml import (
    BrakingEventConfig,
    attach_fold_push_references,
    build_split_assignments,
    evaluate_monotone_action_acceleration_baseline,
    evaluate_monotone_action_only_baseline,
    extract_physical_braking_events,
    fit_fold_push_references,
)


def test_physical_braking_event_ignores_manual_lico_window_and_brake_reference():
    samples = pl.DataFrame(
        {
            "run_id": ["push"] * 11,
            "lap_number": [1] * 11,
            "ts": [index * 0.1 for index in range(11)],
            "lap_distance_m": [100.0 + index * 10.0 for index in range(11)],
            "ground_speed_kph": [220, 219, 218, 215, 205, 185, 160, 140, 142, 150, 165],
            "throttle_pct": [100, 100, 100, 5, 0, 0, 0, 10, 50, 60, 70],
            "brake_pct": [0, 8, 0, 30, 70, 80, 60, 20, 0, 0, 0],
        }
    )
    base = {
        "run_id": "push",
        "lap_number": 1,
        "zone_id": "z1",
        "zone_start_m": 90.0,
        "zone_end_m": 220.0,
        "lico_window_start_m": 110.0,
        "brake_reference_m": 170.0,
    }
    changed = {
        **base,
        "lico_window_start_m": 20.0,
        "brake_reference_m": 999.0,
        "zone_end_m": 260.0,
    }
    config = BrakingEventConfig(
        min_recovery_duration_s=0.19,
        min_post_minimum_duration_s=0.09,
    )

    first = extract_physical_braking_events(
        pl.DataFrame([base]), samples, track_length_m=1000.0, config=config
    ).row(0, named=True)
    second = extract_physical_braking_events(
        pl.DataFrame([changed]), samples, track_length_m=1000.0, config=config
    ).row(0, named=True)

    assert first["braking_event_quality"] == "ready"
    assert first["main_brake_onset_m"] == pytest.approx(130.0)
    assert first["min_speed_point_m"] == pytest.approx(170.0)
    assert first["push_deceleration_distance_observed_m"] == pytest.approx(40.0)
    assert first == second


def test_acceleration_profile_uses_validated_mapped_lmu_axis():
    timestamps = [index * 0.1 for index in range(38)]
    speeds = [100.0 + 0.72 * index for index in range(30)] + [
        121.0,
        105.0,
        85.0,
        65.0,
        70.0,
        75.0,
        80.0,
        85.0,
    ]
    speed_acceleration = [2.0]
    speed_acceleration.extend(
        (current - previous) / 3.6 / 0.1
        for previous, current in zip(speeds, speeds[1:])
    )
    samples = pl.DataFrame(
        {
            "run_id": ["lico"] * 38,
            "lap_number": [1] * 38,
            "ts": timestamps,
            "lap_distance_m": [100.0 + 10.0 * index for index in range(38)],
            "ground_speed_kph": speeds,
            "throttle_pct": [100.0] * 30 + [0.0, 0.0, 0.0, 0.0, 50.0, 60.0, 70.0, 80.0],
            "brake_pct": [0.0] * 30 + [50.0, 70.0, 80.0, 60.0, 0.0, 0.0, 0.0, 0.0],
            "longitudinal_accel_sensor_mps2": speed_acceleration,
        }
    )
    zone_pass = pl.DataFrame(
        [
            {
                "run_id": "lico",
                "lap_number": 1,
                "zone_id": "z1",
                "zone_start_m": 250.0,
                "zone_end_m": 480.0,
                "lico_start_m": 370.0,
            }
        ]
    )
    config = BrakingEventConfig(
        min_recovery_duration_s=0.29,
        min_post_minimum_duration_s=0.19,
    )

    event = extract_physical_braking_events(
        zone_pass, samples, track_length_m=1000.0, config=config
    ).row(0, named=True)

    assert event["acceleration_measurement_source"] == "mapped_g_force_lat_sensor"
    assert event["acceleration_sensor_speed_correlation"] > 0.99
    assert event["approach_acceleration_ratio_1_0_mps2"] == pytest.approx(2.0)
    assert event["observed_pre_lift_acceleration_mps2"] == pytest.approx(2.0)

    fallback = extract_physical_braking_events(
        zone_pass,
        samples.with_columns(pl.lit(999.0).alias("longitudinal_accel_sensor_mps2")),
        track_length_m=1000.0,
        config=config,
    ).row(0, named=True)
    assert (
        fallback["acceleration_measurement_source"]
        == "ground_speed_regression_fallback"
    )
    assert fallback["approach_acceleration_ratio_1_0_mps2"] == pytest.approx(2.0)


def test_cross_circuit_split_separates_train_calibration_and_test():
    observations = _observations()
    manifest = {
        "locked_external_holdout_run_ids": ["locked_confirmation"],
        "folds": [
            {
                "fold_id": "a_to_b",
                "evaluation_regime": "cross_circuit_zero_lico_shot_calibrated",
                "train_run_ids": ["a_push", "a_lico"],
                "calibration_run_ids": ["b_push"],
                "test_run_ids": ["b_lico"],
            }
        ],
    }

    assignments = build_split_assignments(observations, manifest)
    roles = dict(assignments.select("run_id", "split_role").unique().iter_rows())

    assert roles == {
        "a_push": "train",
        "a_lico": "train",
        "b_push": "calibration",
        "b_lico": "test",
    }
    assert assignments.filter(pl.col("score_eligible"))["run_id"].to_list() == [
        "b_lico"
    ]


def test_fold_reference_uses_only_allowed_push_rows_and_survives_test_poisoning():
    observations = _observations()
    manifest = {
        "folds": [
            {
                "fold_id": "a_to_b",
                "evaluation_regime": "cross_circuit_zero_lico_shot_calibrated",
                "train_run_ids": ["a_push", "a_lico"],
                "calibration_run_ids": ["b_push"],
                "test_run_ids": ["b_lico"],
            }
        ]
    }
    assignments = build_split_assignments(observations, manifest)

    references = fit_fold_push_references(
        observations, assignments, fold_id="a_to_b", minimum_support=1
    )
    poisoned = observations.with_columns(
        pl.when(pl.col("run_id") == "b_lico")
        .then(pl.lit(9999.0))
        .otherwise(pl.col("fuel_used_l"))
        .alias("fuel_used_l"),
        pl.when(pl.col("run_id") == "b_lico")
        .then(pl.lit(9999.0))
        .otherwise(pl.col("push_deceleration_distance_observed_m"))
        .alias("push_deceleration_distance_observed_m"),
        pl.when(pl.col("run_id") == "b_lico")
        .then(pl.lit(9999.0))
        .otherwise(pl.col("approach_acceleration_ratio_0_25_mps2"))
        .alias("approach_acceleration_ratio_0_25_mps2"),
    )
    poisoned_references = fit_fold_push_references(
        poisoned, assignments, fold_id="a_to_b", minimum_support=1
    )

    assert references.equals(poisoned_references)
    b_reference = references.filter(pl.col("circuit_id") == "b").row(0, named=True)
    assert b_reference["push_deceleration_distance_reference_m"] == pytest.approx(100.0)

    view = attach_fold_push_references(
        observations,
        assignments,
        references,
        fold_id="a_to_b",
    )
    test_row = view.filter(pl.col("run_id") == "b_lico").row(0, named=True)
    assert test_row["executed_lift_lead_vs_push_brake_m"] == pytest.approx(50.0)
    assert test_row["executed_lift_lead_to_push_deceleration_ratio"] == pytest.approx(
        0.5
    )
    assert test_row["target_fuel_saved_vs_fold_push_l"] == pytest.approx(0.1)
    assert test_row["push_acceleration_at_executed_lift_mps2"] == pytest.approx(2.0)
    assert test_row["executed_acceleration_weighted_action"] == pytest.approx(1.0)
    assert test_row["executed_acceleration_lookup_status"] == "in_range"


def test_fold_reference_rejects_unstable_denominator():
    observations = pl.concat(
        [
            _observations()
            .filter(pl.col("run_id") == "a_push")
            .with_columns(
                pl.lit(f"push_{index}").alias("observation_id"),
                pl.lit(f"push_{index}").alias("run_id"),
                pl.lit(distance).alias("push_deceleration_distance_observed_m"),
            )
            for index, distance in enumerate([50.0, 100.0, 150.0], start=1)
        ]
    )
    manifest = {
        "folds": [
            {
                "fold_id": "f",
                "evaluation_regime": "within_circuit_leave_one_run_out",
                "train_run_ids": ["push_1", "push_2", "push_3"],
            }
        ]
    }
    assignments = build_split_assignments(observations, manifest)

    references = fit_fold_push_references(observations, assignments, fold_id="f")

    assert references["push_reference_status"][0] == "unstable_push_denominator"


def test_lift_after_push_brake_does_not_wrap_into_full_lap_lead():
    observations = _observations().with_columns(
        pl.when(pl.col("run_id") == "b_lico")
        .then(pl.lit(320.0))
        .otherwise(pl.col("lico_start_m"))
        .alias("lico_start_m")
    )
    manifest = {
        "folds": [
            {
                "fold_id": "a_to_b",
                "evaluation_regime": "cross_circuit_zero_lico_shot_calibrated",
                "train_run_ids": ["a_push", "a_lico"],
                "calibration_run_ids": ["b_push"],
                "test_run_ids": ["b_lico"],
            }
        ]
    }
    assignments = build_split_assignments(observations, manifest)
    references = fit_fold_push_references(
        observations, assignments, fold_id="a_to_b", minimum_support=1
    )

    view = attach_fold_push_references(
        observations, assignments, references, fold_id="a_to_b"
    )

    test_row = view.filter(pl.col("run_id") == "b_lico").row(0, named=True)
    assert test_row["executed_lift_lead_vs_push_brake_m"] is None
    assert test_row["executed_lift_lead_to_push_deceleration_ratio"] is None


def test_acceleration_lookup_flags_out_of_profile_range():
    observations = _observations().with_columns(
        pl.when(pl.col("run_id") == "b_lico")
        .then(pl.lit(100.0))
        .otherwise(pl.col("lico_start_m"))
        .alias("lico_start_m")
    )
    manifest = {
        "folds": [
            {
                "fold_id": "a_to_b",
                "evaluation_regime": "cross_circuit_zero_lico_shot_calibrated",
                "train_run_ids": ["a_push", "a_lico"],
                "calibration_run_ids": ["b_push"],
                "test_run_ids": ["b_lico"],
            }
        ]
    }
    assignments = build_split_assignments(observations, manifest)
    references = fit_fold_push_references(
        observations, assignments, fold_id="a_to_b", minimum_support=1
    )

    view = attach_fold_push_references(
        observations, assignments, references, fold_id="a_to_b"
    )

    test_row = view.filter(pl.col("run_id") == "b_lico").row(0, named=True)
    assert test_row["executed_lift_lead_to_push_deceleration_ratio"] == pytest.approx(
        2.0
    )
    assert test_row["executed_acceleration_lookup_status"] == "clipped_high"
    assert test_row["push_acceleration_at_executed_lift_mps2"] == pytest.approx(0.0)


def test_locked_external_holdout_cannot_enter_observations():
    observations = _observations().with_columns(
        pl.when(pl.col("run_id") == "b_lico")
        .then(pl.lit("locked_confirmation"))
        .otherwise(pl.col("run_id"))
        .alias("run_id")
    )
    manifest = {
        "locked_external_holdout_run_ids": ["locked_confirmation"],
        "folds": [
            {
                "fold_id": "f",
                "evaluation_regime": "within_circuit_leave_one_run_out",
                "train_run_ids": ["a_push"],
                "test_run_ids": ["a_lico"],
            }
        ],
    }

    with pytest.raises(ValueError, match="locked external holdout leaked"):
        build_split_assignments(observations, manifest)


def test_split_rejects_same_raw_hash_across_roles():
    observations = _observations().with_columns(
        pl.when(pl.col("run_id").is_in(["a_push", "b_lico"]))
        .then(pl.lit("duplicate"))
        .otherwise(pl.col("source_raw_sha256"))
        .alias("source_raw_sha256")
    )
    manifest = {
        "folds": [
            {
                "fold_id": "f",
                "evaluation_regime": "within_circuit_leave_one_run_out",
                "train_run_ids": ["a_push"],
                "test_run_ids": ["b_lico"],
                "excluded_run_ids": ["a_lico", "b_push"],
            }
        ]
    }

    with pytest.raises(ValueError, match="raw telemetry hash"):
        build_split_assignments(observations, manifest)


def test_monotone_action_baseline_fits_train_only():
    views = pl.DataFrame(
        {
            "fold_id": ["f", "f", "f"],
            "evaluation_regime": ["diagnostic"] * 3,
            "observation_id": ["train1", "train2", "test"],
            "run_id": ["train", "train", "test"],
            "split_role": ["train", "train", "test"],
            "score_eligible": [False, False, True],
            "model_eligible": [True, True, True],
            "executed_lift_lead_to_push_deceleration_ratio": [0.5, 1.0, 2.0],
            "target_fuel_saved_vs_fold_push_l": [0.1, 0.2, 999.0],
            "target_time_lost_vs_fold_push_s": [0.2, 0.4, 999.0],
        }
    )

    predictions, metrics = evaluate_monotone_action_only_baseline(views)

    fuel_prediction = predictions.filter(pl.col("target_name") == "fuel_saved_l").row(
        0, named=True
    )
    assert fuel_prediction["predicted"] == pytest.approx(0.4)
    fuel_metric = metrics.filter(pl.col("target_name") == "fuel_saved_l").row(
        0, named=True
    )
    assert fuel_metric["fitted_slope"] == pytest.approx(0.2)


def test_monotone_action_acceleration_baseline_learns_interaction():
    views = pl.DataFrame(
        {
            "fold_id": ["f"] * 5,
            "evaluation_regime": ["diagnostic"] * 5,
            "observation_id": ["train1", "train2", "train3", "train4", "test"],
            "run_id": ["train"] * 4 + ["test"],
            "split_role": ["train"] * 4 + ["test"],
            "score_eligible": [False] * 4 + [True],
            "model_eligible": [True] * 5,
            "executed_lift_lead_to_push_deceleration_ratio": [
                1.0,
                1.0,
                2.0,
                2.0,
                1.5,
            ],
            "push_acceleration_at_executed_lift_mps2": [0.0, 2.0, 0.0, 2.0, 1.0],
            "executed_acceleration_weighted_action": [0.0, 2.0, 0.0, 4.0, 1.5],
            "executed_acceleration_lookup_status": ["in_range"] * 5,
            "target_fuel_saved_vs_fold_push_l": [0.1, 0.5, 0.2, 1.0, 0.45],
            "target_time_lost_vs_fold_push_s": [0.1, 0.5, 0.2, 1.0, 0.45],
        }
    )

    predictions, metrics = evaluate_monotone_action_acceleration_baseline(views)

    fuel_prediction = predictions.filter(pl.col("target_name") == "fuel_saved_l").row(
        0, named=True
    )
    assert fuel_prediction["predicted"] == pytest.approx(0.45)
    fuel_metric = metrics.filter(pl.col("target_name") == "fuel_saved_l").row(
        0, named=True
    )
    assert fuel_metric["fitted_slope"] == pytest.approx(0.1)
    assert fuel_metric["fitted_interaction_slope"] == pytest.approx(0.2)


def _observations() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "observation_id": ["a_push", "a_lico", "b_push", "b_lico"],
            "circuit_id": ["a", "a", "b", "b"],
            "run_id": ["a_push", "a_lico", "b_push", "b_lico"],
            "source_raw_sha256": ["hash1", "hash2", "hash3", "hash4"],
            "lap_number": [1, 1, 1, 1],
            "zone_id": ["z", "z", "z", "z"],
            "has_lico": [False, True, False, True],
            "model_eligible": [True, True, True, True],
            "is_push_reference_candidate": [True, False, True, False],
            "braking_event_quality": ["ready"] * 4,
            "main_brake_onset_m": [200.0, 220.0, 300.0, 330.0],
            "main_brake_onset_speed_kph": [250.0, 230.0, 240.0, 220.0],
            "push_deceleration_distance_observed_m": [80.0, 70.0, 100.0, 90.0],
            "approach_acceleration_ratio_0_0_mps2": [4.0, 4.0, 3.0, 3.0],
            "approach_acceleration_ratio_0_25_mps2": [3.5, 3.5, 2.5, 2.5],
            "approach_acceleration_ratio_0_5_mps2": [3.0, 3.0, 2.0, 2.0],
            "approach_acceleration_ratio_1_0_mps2": [2.0, 2.0, 1.0, 1.0],
            "approach_acceleration_ratio_1_5_mps2": [1.0, 1.0, 0.0, 0.0],
            "zone_start_speed_kph": [260.0, 250.0, 250.0, 240.0],
            "fuel_used_l": [0.3, 0.2, 0.4, 0.3],
            "elapsed_time_s": [8.0, 8.2, 9.0, 9.3],
            "min_speed_point_kph": [100.0, 102.0, 90.0, 91.0],
            "exit_speed_kph": [150.0, 151.0, 140.0, 142.0],
            "lico_start_m": [None, 150.0, None, 250.0],
            "planned_lift_start_m": [None, None, None, None],
            "track_length_m": [1000.0] * 4,
        }
    )
