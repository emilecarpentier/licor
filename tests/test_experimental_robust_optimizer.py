from __future__ import annotations

import polars as pl

from licor.analysis.experimental_robust_optimizer import (
    build_experimental_range_aware_plan,
    build_experimental_robust_zone_models,
    compare_experimental_plan_variants,
    compare_experimental_zone_plans,
    summarize_experimental_robust_recommended_ranges,
)


def test_penalizes_tail_point_more_than_supported_interior_point() -> None:
    zone_models = pl.DataFrame(
        {
            "zone_id": ["spa_t12_t13", "spa_t12_t13", "spa_t12_t13"],
            "display_label": ["T12-T13", "T12-T13", "T12-T13"],
            "lico_distance_m": [80.0, 90.0, 150.0],
            "predicted_fuel_saved_l": [0.05, 0.055, 0.085],
            "predicted_time_lost_s": [0.07, 0.08, 0.18],
            "predicted_fuel_saved_per_second_lps": [0.714, 0.688, 0.472],
            "is_extrapolated": [False, False, False],
            "model_status": ["model_ready", "model_ready", "model_ready"],
            "quality_flags": [
                ["experimental_promoted_from_diagnostic_only"],
                ["experimental_promoted_from_diagnostic_only"],
                ["experimental_promoted_from_diagnostic_only"],
            ],
            "source_bin_count": [6, 6, 6],
            "nonzero_source_bin_count": [6, 6, 6],
            "observed_max_lico_distance_m": [153.0, 153.0, 153.0],
        }
    )
    zone_dynamics = pl.DataFrame(
        {
            "zone_id": ["spa_t12_t13"] * 8,
            "display_label": ["T12-T13"] * 8,
            "lico_intensity": ["medium"] * 8,
            "has_lico": [True] * 8,
            "lico_distance_before_brake_m": [72.0, 78.0, 82.0, 88.0, 92.0, 95.0, 149.0, 153.0],
            "fuel_saved_vs_baseline_l": [0.041, 0.046, 0.049, 0.053, 0.056, 0.058, 0.086, 0.088],
            "time_lost_vs_baseline_s": [0.061, 0.064, 0.066, 0.071, 0.079, 0.082, 0.180, 0.184],
        }
    )
    model_comparison = pl.DataFrame(
        {
            "zone_id": ["spa_t12_t13"],
            "r2_improvement": [0.18],
        }
    )

    robust = build_experimental_robust_zone_models(
        zone_models,
        zone_dynamics,
        model_comparison=model_comparison,
    )

    interior = robust.filter(pl.col("lico_distance_m") == 80.0).row(0, named=True)
    tail = robust.filter(pl.col("lico_distance_m") == 150.0).row(0, named=True)

    assert interior["support_score"] > tail["support_score"]
    assert interior["support_penalty_fraction"] < tail["support_penalty_fraction"]
    assert tail["robust_predicted_fuel_saved_l"] < tail["predicted_fuel_saved_l"]
    assert tail["robust_predicted_time_lost_s"] > tail["predicted_time_lost_s"]


def test_builds_contiguous_recommended_range_around_selected_point() -> None:
    robust_zone_models = pl.DataFrame(
        {
            "zone_id": ["spa_t08"] * 5,
            "display_label": ["T08"] * 5,
            "lico_distance_m": [40.0, 50.0, 60.0, 70.0, 90.0],
            "robust_predicted_fuel_saved_l": [0.03, 0.04, 0.045, 0.046, 0.048],
            "robust_predicted_time_lost_s": [0.05, 0.06, 0.07, 0.074, 0.11],
            "robust_predicted_fuel_saved_per_second_lps": [0.60, 0.67, 0.64, 0.62, 0.44],
            "support_score": [0.78, 0.84, 0.80, 0.73, 0.39],
        }
    )
    robust_plan = pl.DataFrame(
        {
            "zone_id": ["spa_t08"],
            "display_label": ["T08"],
            "selected_lico_distance_m": [60.0],
            "is_selected_for_lico": [True],
            "predicted_fuel_saved_l": [0.045],
            "predicted_time_lost_s": [0.07],
            "plan_status": ["target_met"],
        }
    )

    ranges = summarize_experimental_robust_recommended_ranges(
        robust_zone_models,
        robust_plan,
    )

    row = ranges.row(0, named=True)
    assert row["recommended_range_start_m"] == 40.0
    assert row["recommended_range_end_m"] == 70.0
    assert row["selected_lico_distance_m"] == 60.0


def test_compares_naive_and_robust_plan_rows() -> None:
    naive_plan = pl.DataFrame(
        {
            "zone_id": ["spa_t12_t13"],
            "display_label": ["T12-T13"],
            "selected_lico_distance_m": [150.0],
            "is_selected_for_lico": [True],
            "predicted_fuel_saved_l": [0.085],
            "predicted_time_lost_s": [0.18],
            "model_status": ["model_ready"],
            "plan_status": ["target_met"],
        }
    )
    robust_plan = pl.DataFrame(
        {
            "zone_id": ["spa_t12_t13"],
            "display_label": ["T12-T13"],
            "selected_lico_distance_m": [80.0],
            "is_selected_for_lico": [True],
            "predicted_fuel_saved_l": [0.048],
            "predicted_time_lost_s": [0.066],
            "model_status": ["model_ready"],
            "plan_status": ["target_met"],
        }
    )
    robust_ranges = pl.DataFrame(
        {
            "zone_id": ["spa_t12_t13"],
            "display_label": ["T12-T13"],
            "selected_lico_distance_m": [80.0],
            "recommended_range_start_m": [70.0],
            "recommended_range_end_m": [90.0],
            "recommended_range_width_m": [20.0],
        }
    )
    robust_zone_models = pl.DataFrame(
        {
            "zone_id": ["spa_t12_t13"],
            "display_label": ["T12-T13"],
            "lico_distance_m": [80.0],
            "support_score": [0.81],
            "local_support_pass_count": [6],
            "nearest_observed_gap_m": [2.0],
            "tail_span_to_max_observed_m": [73.0],
        }
    )

    comparison = compare_experimental_zone_plans(
        naive_plan,
        robust_plan,
        robust_ranges,
        robust_zone_models,
    )

    row = comparison.row(0, named=True)
    assert row["distance_shift_m"] == -70.0
    assert row["recommended_range_start_m"] == 70.0
    assert row["robust_support_score"] == 0.81


def test_range_aware_plan_prefers_smallest_credible_action_that_hits_target() -> None:
    robust_zone_models = pl.DataFrame(
        {
            "zone_id": [
                "spa_t01",
                "spa_t01",
                "spa_t01",
                "spa_t18",
                "spa_t18",
                "spa_t18",
            ],
            "display_label": ["T01", "T01", "T01", "T18", "T18", "T18"],
            "lico_distance_m": [0.0, 60.0, 70.0, 0.0, 100.0, 130.0],
            "robust_predicted_fuel_saved_l": [0.0, 0.05, 0.06, 0.0, 0.08, 0.10],
            "robust_predicted_time_lost_s": [0.0, 0.08, 0.10, 0.0, 0.10, 0.13],
            "robust_predicted_fuel_saved_per_second_lps": [None, 0.625, 0.6, None, 0.8, 0.769],
            "model_status": ["model_ready"] * 6,
            "quality_flags": ["", "", "", "", "", ""],
            "support_score": [1.0, 0.95, 0.92, 1.0, 0.94, 0.90],
        }
    )
    robust_ranges = pl.DataFrame(
        {
            "zone_id": ["spa_t01", "spa_t18"],
            "display_label": ["T01", "T18"],
            "selected_lico_distance_m": [70.0, 130.0],
            "recommended_range_start_m": [60.0, 100.0],
            "recommended_range_end_m": [70.0, 130.0],
            "recommended_range_width_m": [10.0, 30.0],
        }
    )

    range_aware_plan = build_experimental_range_aware_plan(
        robust_zone_models,
        robust_ranges,
        target_fuel_saved_per_lap_l=0.14,
    )

    assert range_aware_plan.filter(pl.col("zone_id") == "spa_t01")[
        "selected_lico_distance_m"
    ].item() == 70.0
    assert range_aware_plan.filter(pl.col("zone_id") == "spa_t18")[
        "selected_lico_distance_m"
    ].item() == 100.0
    assert range_aware_plan["total_optimization_action_cost_m"][0] == 170.0
    assert range_aware_plan["total_predicted_fuel_saved_l"][0] == 0.14
    assert range_aware_plan["plan_status"][0] == "target_met"


def test_compare_plan_variants_supports_custom_prefixes() -> None:
    robust_plan = pl.DataFrame(
        {
            "zone_id": ["spa_t18"],
            "display_label": ["T18"],
            "selected_lico_distance_m": [130.0],
            "is_selected_for_lico": [True],
            "predicted_fuel_saved_l": [0.100],
            "predicted_time_lost_s": [0.130],
            "model_status": ["model_ready"],
            "plan_status": ["target_met"],
        }
    )
    range_aware_plan = pl.DataFrame(
        {
            "zone_id": ["spa_t18"],
            "display_label": ["T18"],
            "selected_lico_distance_m": [100.0],
            "is_selected_for_lico": [True],
            "predicted_fuel_saved_l": [0.080],
            "predicted_time_lost_s": [0.100],
            "model_status": ["model_ready"],
            "plan_status": ["target_met"],
        }
    )
    robust_ranges = pl.DataFrame(
        {
            "zone_id": ["spa_t18"],
            "display_label": ["T18"],
            "selected_lico_distance_m": [130.0],
            "recommended_range_start_m": [100.0],
            "recommended_range_end_m": [130.0],
            "recommended_range_width_m": [30.0],
        }
    )
    robust_zone_models = pl.DataFrame(
        {
            "zone_id": ["spa_t18"],
            "display_label": ["T18"],
            "lico_distance_m": [100.0],
            "support_score": [0.93],
            "local_support_pass_count": [5],
            "nearest_observed_gap_m": [3.0],
            "tail_span_to_max_observed_m": [35.0],
        }
    )

    comparison = compare_experimental_plan_variants(
        robust_plan,
        range_aware_plan,
        robust_ranges,
        robust_zone_models,
        left_prefix="robust",
        right_prefix="range_aware",
    )

    row = comparison.row(0, named=True)
    assert row["robust_selected_lico_distance_m"] == 130.0
    assert row["range_aware_selected_lico_distance_m"] == 100.0
    assert row["distance_shift_m"] == -30.0
    assert row["range_aware_support_score"] == 0.93


def test_range_aware_all_eligible_can_activate_new_zone() -> None:
    robust_zone_models = pl.DataFrame(
        {
            "zone_id": [
                "spa_t01",
                "spa_t01",
                "spa_t01",
                "spa_t18",
                "spa_t18",
                "spa_t18",
                "spa_t14",
                "spa_t14",
            ],
            "display_label": ["T01", "T01", "T01", "T18", "T18", "T18", "T14", "T14"],
            "lico_distance_m": [0.0, 60.0, 70.0, 0.0, 100.0, 130.0, 0.0, 20.0],
            "robust_predicted_fuel_saved_l": [0.0, 0.05, 0.06, 0.0, 0.08, 0.10, 0.0, 0.025],
            "robust_predicted_time_lost_s": [0.0, 0.08, 0.10, 0.0, 0.10, 0.13, 0.0, 0.01],
            "robust_predicted_fuel_saved_per_second_lps": [None, 0.625, 0.6, None, 0.8, 0.769, None, 2.5],
            "is_extrapolated": [False] * 8,
            "model_status": ["model_ready"] * 8,
            "quality_flags": [""] * 8,
            "support_score": [1.0, 0.95, 0.92, 1.0, 0.94, 0.90, 1.0, 0.88],
        }
    )
    robust_ranges = pl.DataFrame(
        {
            "zone_id": ["spa_t01", "spa_t18"],
            "display_label": ["T01", "T18"],
            "selected_lico_distance_m": [70.0, 130.0],
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
            "max_lico_distance_m": [100.0, 150.0, 20.0],
        }
    )

    selected_only_plan = build_experimental_range_aware_plan(
        robust_zone_models,
        robust_ranges,
        target_fuel_saved_per_lap_l=0.155,
        zone_priors=zone_priors,
        allowed_model_statuses=("model_ready",),
        top_up_scope="selected_zones",
    )
    all_eligible_plan = build_experimental_range_aware_plan(
        robust_zone_models,
        robust_ranges,
        target_fuel_saved_per_lap_l=0.155,
        zone_priors=zone_priors,
        allowed_model_statuses=("model_ready",),
        top_up_scope="all_eligible_zones",
    )

    assert "spa_t14" not in selected_only_plan["zone_id"].to_list()
    assert "spa_t14" in all_eligible_plan["zone_id"].to_list()
    assert all_eligible_plan.filter(pl.col("zone_id") == "spa_t14")[
        "selected_lico_distance_m"
    ].item() == 20.0
    assert selected_only_plan["total_predicted_time_lost_s"][0] > all_eligible_plan[
        "total_predicted_time_lost_s"
    ][0]
