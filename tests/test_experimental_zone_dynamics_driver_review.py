from __future__ import annotations

import polars as pl

from licor.analysis.experimental_zone_dynamics_driver_review import (
    summarize_experimental_zone_dynamics_driver_review,
)


def test_driver_review_marks_structurally_favorable_zone() -> None:
    zone_dynamics = pl.DataFrame(
        {
            "zone_id": ["spa_t05_t06"] * 4,
            "display_label": ["T05-T06"] * 4,
            "lico_intensity": ["low", "medium", "high", "high"],
            "lico_distance_before_brake_m": [60.0, 100.0, 140.0, 180.0],
            "fuel_saved_vs_baseline_l": [0.02, 0.04, 0.06, 0.08],
            "time_lost_vs_baseline_s": [0.02, 0.04, 0.05, 0.07],
            "brake_start_delta_vs_baseline_m": [4.0, 7.0, 10.0, 13.0],
            "brake_start_speed_delta_vs_baseline_kph": [-8.0, -12.0, -16.0, -20.0],
            "apex_speed_delta_vs_baseline_kph": [0.6, 0.9, 1.1, 1.3],
            "exit_speed_delta_vs_baseline_kph": [0.2, 0.4, 0.5, 0.7],
            "carcass_temp_zone_start_delta_vs_baseline_c": [-2.0, -3.0, -4.0, -5.0],
        }
    )
    model_comparison = pl.DataFrame(
        {
            "zone_id": ["spa_t05_t06"],
            "direct_r2": [0.40],
            "dynamics_r2": [0.72],
            "r2_improvement": [0.32],
            "recommendation": ["dynamics_explains_more_variance"],
        }
    )
    current_status = pl.DataFrame(
        {
            "zone_id": ["spa_t05_t06"],
            "current_model_status": ["diagnostic_only"],
            "current_quality_flags": ["time_signal_unclear"],
        }
    )

    review = summarize_experimental_zone_dynamics_driver_review(
        zone_dynamics,
        model_comparison=model_comparison,
        current_zone_status=current_status,
    )

    row = review.row(0, named=True)
    assert row["primary_review_label"] == "structurally_favorable"
    assert row["secondary_review_label"] == "dynamics_matter_materially"
    assert "moves braking later" in row["driver_summary"]


def test_driver_review_marks_apex_penalized_zone() -> None:
    zone_dynamics = pl.DataFrame(
        {
            "zone_id": ["spa_t10_t11"] * 4,
            "display_label": ["T10-T11"] * 4,
            "lico_intensity": ["low", "medium", "high", "high"],
            "lico_distance_before_brake_m": [25.0, 40.0, 55.0, 70.0],
            "fuel_saved_vs_baseline_l": [0.01, 0.02, 0.03, 0.04],
            "time_lost_vs_baseline_s": [0.03, 0.06, 0.09, 0.12],
            "brake_start_delta_vs_baseline_m": [1.0, 2.0, 3.0, 4.0],
            "brake_start_speed_delta_vs_baseline_kph": [-6.0, -8.0, -10.0, -12.0],
            "apex_speed_delta_vs_baseline_kph": [-0.7, -1.3, -2.0, -2.8],
            "exit_speed_delta_vs_baseline_kph": [0.1, 0.0, -0.1, -0.3],
            "carcass_temp_zone_start_delta_vs_baseline_c": [-1.0, -1.5, -2.0, -2.5],
        }
    )

    review = summarize_experimental_zone_dynamics_driver_review(zone_dynamics)

    row = review.row(0, named=True)
    assert row["primary_review_label"] == "apex_penalized"
    assert "Apex speed drops" in row["driver_summary"]
