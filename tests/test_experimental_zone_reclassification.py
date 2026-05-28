from __future__ import annotations

import polars as pl

from licor.analysis.experimental_zone_reclassification import (
    apply_experimental_strategy_prior_overrides,
    apply_experimental_zone_reclassification,
    build_experimental_status_frame,
    summarize_experimental_zone_reclassification,
)


def test_summarizes_zone_reclassification_policy() -> None:
    zone_models = pl.DataFrame(
        {
            "zone_id": ["spa_t01", "spa_t14", "spa_t18"],
            "display_label": ["T01", "T14", "T18"],
            "model_status": ["diagnostic_only", "diagnostic_only", "model_ready"],
            "quality_flags": [
                ["time_signal_unclear"],
                ["noisy_time_signal"],
                ["clean_signal"],
            ],
        }
    )

    review = summarize_experimental_zone_reclassification(zone_models)

    assert review.filter(pl.col("zone_id") == "spa_t01").row(0, named=True)[
        "experimental_model_status"
    ] == "model_ready"
    assert review.filter(pl.col("zone_id") == "spa_t14").row(0, named=True)[
        "experimental_model_status"
    ] == "micro_lico_only"
    assert review.filter(pl.col("zone_id") == "spa_t18").row(0, named=True)[
        "reclassification_action"
    ] == "unchanged"


def test_applies_zone_and_prior_overrides() -> None:
    zone_models = pl.DataFrame(
        {
            "zone_id": ["spa_t14", "spa_t14", "spa_t01"],
            "display_label": ["T14", "T14", "T01"],
            "lico_distance_m": [0.0, 20.0, 30.0],
            "predicted_fuel_saved_l": [0.0, 0.01, 0.03],
            "predicted_time_lost_s": [0.0, 0.03, 0.08],
            "predicted_fuel_saved_per_second_lps": [None, None, 0.375],
            "is_extrapolated": [False, False, False],
            "model_status": ["diagnostic_only", "diagnostic_only", "diagnostic_only"],
            "quality_flags": [["noisy_time_signal"], ["noisy_time_signal"], ["time_signal_unclear"]],
            "source_bin_count": [2, 2, 3],
            "nonzero_source_bin_count": [1, 1, 2],
            "observed_max_lico_distance_m": [20.0, 20.0, 30.0],
        }
    )
    priors = pl.DataFrame(
        {
            "zone_id": ["spa_t14", "spa_t01"],
            "display_label": ["T14", "T01"],
            "feasibility_score": [2, 4],
            "strategy_role": ["limited", "usable"],
            "allow_diagnostic_model": [True, True],
            "max_lico_distance_m": [40.0, None],
            "notes": ["old note", "base note"],
        }
    )

    review = summarize_experimental_zone_reclassification(zone_models)
    updated_models = apply_experimental_zone_reclassification(zone_models, review)
    updated_priors = apply_experimental_strategy_prior_overrides(priors, review)
    status_frame = build_experimental_status_frame(updated_models)

    t14_model = updated_models.filter(pl.col("zone_id") == "spa_t14").row(0, named=True)
    assert t14_model["model_status"] == "micro_lico_only"
    assert "experimental_micro_lico_only" in t14_model["quality_flags"]

    t01_model = updated_models.filter(pl.col("zone_id") == "spa_t01").row(0, named=True)
    assert t01_model["model_status"] == "model_ready"
    assert "experimental_promoted_from_diagnostic_only" in t01_model["quality_flags"]

    t14_prior = updated_priors.filter(pl.col("zone_id") == "spa_t14").row(0, named=True)
    assert t14_prior["max_lico_distance_m"] == 20.0
    assert "Experimental reclassification" in t14_prior["notes"]

    t14_status = status_frame.filter(pl.col("zone_id") == "spa_t14").row(0, named=True)
    assert t14_status["current_model_status"] == "micro_lico_only"
