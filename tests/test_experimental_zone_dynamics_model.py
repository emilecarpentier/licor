import polars as pl

from licor.analysis.experimental_zone_dynamics_model import (
    ExperimentalZoneDynamicsModelConfig,
    compare_zone_dynamics_models,
    score_zone_dynamics_models,
)


def test_dynamics_model_can_explain_more_variance_than_direct_model():
    frame = pl.DataFrame(
        [
            _row(
                "spa_t18",
                "T18",
                lap_number=index,
                lico_distance=distance,
                brake_delta=brake_delta,
                apex_delta=apex_delta,
                time_lost=(0.12 + 0.0002 * distance - 0.004 * brake_delta - 0.006 * apex_delta),
            )
            for index, (distance, brake_delta, apex_delta) in enumerate(
                [
                    (20.0, -5.0, -4.0),
                    (40.0, -2.0, -1.0),
                    (60.0, 0.0, 0.0),
                    (80.0, 1.0, 1.0),
                    (100.0, 4.0, 3.0),
                    (120.0, 7.0, 5.0),
                    (140.0, 9.0, 6.0),
                    (160.0, 11.0, 7.0),
                    (180.0, 12.0, 8.0),
                    (200.0, 14.0, 9.0),
                    (220.0, 15.0, 10.0),
                    (240.0, 17.0, 11.0),
                ],
                start=1,
            )
        ]
    )

    comparison = compare_zone_dynamics_models(
        frame,
        config=ExperimentalZoneDynamicsModelConfig(improvement_threshold_r2=0.001),
    )
    row = comparison.row(0, named=True)

    assert row["status"] == "comparable"
    assert row["dynamics_r2"] is not None
    assert row["direct_r2"] is not None
    assert row["dynamics_r2"] > row["direct_r2"]
    assert row["recommendation"] == "dynamics_explains_more_variance"


def test_reports_insufficient_data_when_zone_is_too_small():
    frame = pl.DataFrame(
        [
            _row("spa_t01", "T01", lap_number=index, lico_distance=20.0 * index, time_lost=0.1 * index)
            for index in range(1, 4)
        ]
    )

    comparison = compare_zone_dynamics_models(
        frame,
        config=ExperimentalZoneDynamicsModelConfig(min_training_rows=6),
    )

    row = comparison.row(0, named=True)
    assert row["status"] == "insufficient_data"
    assert row["recommendation"] == "collect_more_data"


def test_scores_zone_predictions_with_both_models():
    frame = pl.DataFrame(
        [
            _row(
                "spa_t05_t06",
                "T05-T06",
                lap_number=index,
                lico_distance=25.0 * index,
                brake_delta=float(index),
                apex_delta=float(index) * 0.5,
                time_lost=0.03 * index,
            )
            for index in range(1, 11)
        ]
    )

    scored = score_zone_dynamics_models(frame)

    assert scored.height == 10
    assert "direct_predicted_time_lost_vs_baseline_s" in scored.columns
    assert "dynamics_predicted_time_lost_vs_baseline_s" in scored.columns
    assert scored["direct_predicted_time_lost_vs_baseline_s"].null_count() == 0
    assert scored["dynamics_predicted_time_lost_vs_baseline_s"].null_count() == 0


def _row(
    zone_id: str,
    display_label: str,
    *,
    lap_number: int,
    lico_distance: float,
    time_lost: float,
    brake_delta: float = 0.0,
    apex_delta: float = 0.0,
) -> dict[str, object]:
    return {
        "zone_id": zone_id,
        "display_label": display_label,
        "run_id": "synthetic",
        "lap_number": lap_number,
        "lico_distance_before_brake_m": lico_distance,
        "brake_start_delta_vs_baseline_m": brake_delta,
        "brake_start_speed_delta_vs_baseline_kph": brake_delta * 0.5,
        "apex_speed_delta_vs_baseline_kph": apex_delta,
        "exit_speed_delta_vs_baseline_kph": apex_delta * 0.4,
        "carcass_temp_zone_start_delta_vs_baseline_c": 0.25 * lap_number,
        "stint_index": lap_number,
        "time_lost_vs_baseline_s": time_lost,
    }
