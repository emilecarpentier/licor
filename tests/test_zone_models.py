import polars as pl
import pytest

from licor.analysis import (
    ZoneModelConfig,
    build_zone_piecewise_models,
)


def test_builds_piecewise_linear_predictions_from_bins():
    bins = pl.DataFrame(
        [
            _bin("spa_t18", "T18", 0.0, 0.0, 0.0, 5, 0),
            _bin("spa_t18", "T18", 50.0, 0.05, 0.20, 3, 3),
            _bin("spa_t18", "T18", 100.0, 0.12, 0.55, 3, 3),
        ]
    )

    model = build_zone_piecewise_models(
        bins,
        config=ZoneModelConfig(distance_step_m=25.0),
    )

    assert model["lico_distance_m"].to_list() == [0.0, 25.0, 50.0, 75.0, 100.0]
    assert model["predicted_fuel_saved_l"].to_list() == pytest.approx(
        [0.0, 0.025, 0.05, 0.085, 0.12]
    )
    assert model["predicted_time_lost_s"].to_list() == pytest.approx(
        [0.0, 0.1, 0.2, 0.375, 0.55]
    )
    assert model["model_status"].to_list() == ["model_ready"] * 5

    row = model.filter(pl.col("lico_distance_m") == 25.0).row(0, named=True)
    assert row["predicted_fuel_saved_per_second_lps"] == pytest.approx(0.25)
    assert row["is_extrapolated"] is False
    assert row["source_bin_count"] == 3
    assert row["nonzero_source_bin_count"] == 2


def test_applies_monotone_fuel_and_time_for_optimization_curve():
    bins = pl.DataFrame(
        [
            _bin("spa_t08", "T08", 0.0, 0.0, 0.0, 5, 0),
            _bin("spa_t08", "T08", 50.0, 0.06, 0.30, 2, 2),
            _bin("spa_t08", "T08", 100.0, 0.04, 0.10, 2, 2),
        ]
    )

    model = build_zone_piecewise_models(
        bins,
        config=ZoneModelConfig(distance_step_m=50.0),
    )

    assert model.select("lico_distance_m", "predicted_fuel_saved_l").rows() == [
        (0.0, 0.0),
        (50.0, 0.06),
        (100.0, 0.06),
    ]
    last = model.filter(pl.col("lico_distance_m") == 100.0).row(0, named=True)
    assert last["predicted_time_lost_s"] == pytest.approx(0.30)
    assert "fuel_monotone_adjusted" in last["quality_flags"]
    assert "time_not_monotone" in last["quality_flags"]


def test_suppresses_ratio_when_time_loss_is_too_small():
    bins = pl.DataFrame(
        [
            _bin("spa_t05_t06", "T05-T06", 0.0, 0.0, 0.0, 5, 0),
            _bin("spa_t05_t06", "T05-T06", 70.0, 0.04, -0.02, 1, 1),
            _bin("spa_t05_t06", "T05-T06", 100.0, 0.05, 0.04, 2, 2),
            _bin("spa_t05_t06", "T05-T06", 140.0, 0.08, 0.20, 2, 2),
        ]
    )

    model = build_zone_piecewise_models(
        bins,
        config=ZoneModelConfig(distance_step_m=35.0, min_ratio_time_loss_s=0.05),
    )

    early = model.filter(pl.col("lico_distance_m") == 70.0).row(0, named=True)
    assert early["predicted_time_lost_s"] == pytest.approx(0.0)
    assert early["predicted_fuel_saved_per_second_lps"] is None
    assert "negative_time_loss_observed" in early["quality_flags"]
    assert "low_time_loss_ratio_suppressed" in early["quality_flags"]

    later = model.filter(pl.col("lico_distance_m") == 140.0).row(0, named=True)
    assert later["predicted_fuel_saved_per_second_lps"] == pytest.approx(0.4)


def test_marks_review_excluded_zone_without_deleting_predictions():
    bins = pl.DataFrame(
        [
            _bin("spa_t09", "T09", 0.0, 0.0, 0.0, 5, 0),
            _bin("spa_t09", "T09", 30.0, 0.01, 0.02, 1, 1),
        ]
    )
    annotations = pl.DataFrame(
        [
            {
                "zone_id": "spa_t09",
                "signal_tags": ["no_credible_lico_signal"],
                "notes": "No useful signal.",
            }
        ]
    )

    model = build_zone_piecewise_models(
        bins,
        zone_annotations=annotations,
        config=ZoneModelConfig(distance_step_m=30.0),
    )

    assert set(model["model_status"].to_list()) == {"review_excluded"}
    assert "review_excluded_from_optimization" in model.row(0, named=True)["quality_flags"]


def test_marks_low_data_when_too_few_nonzero_bins():
    bins = pl.DataFrame(
        [
            _bin("spa_t01", "T01", 0.0, 0.0, 0.0, 5, 0),
            _bin("spa_t01", "T01", 40.0, 0.02, 0.15, 1, 1),
        ]
    )

    model = build_zone_piecewise_models(
        bins,
        config=ZoneModelConfig(distance_step_m=20.0, min_nonzero_bins=2),
    )

    assert set(model["model_status"].to_list()) == {"low_data"}
    assert "low_nonzero_bin_count" in model.row(0, named=True)["quality_flags"]


def test_returns_empty_for_empty_bins():
    assert build_zone_piecewise_models(pl.DataFrame()).is_empty()


def _bin(
    zone_id: str,
    display_label: str,
    distance_m: float,
    fuel_saved_l: float,
    time_lost_s: float,
    pass_count: int,
    lico_pass_count: int,
) -> dict[str, object]:
    return {
        "zone_id": zone_id,
        "display_label": display_label,
        "lico_distance_bin_start_m": max(0.0, distance_m - 12.5),
        "lico_distance_bin_end_m": distance_m + 12.5,
        "lico_distance_bin_mid_m": distance_m,
        "pass_count": pass_count,
        "detected_lico_passes": lico_pass_count,
        "detected_lico_rate": lico_pass_count / pass_count,
        "lico_intensities": ["low"] if lico_pass_count else ["none"],
        "mean_lico_distance_before_brake_m": distance_m,
        "mean_fuel_saved_l": fuel_saved_l,
        "mean_time_lost_s": time_lost_s,
        "fuel_saved_per_second_lps": None,
        "mean_observed_fuel_saved_per_second_lps": None,
        "mean_min_speed_kph": 120.0,
        "mean_exit_speed_kph": 180.0,
    }
