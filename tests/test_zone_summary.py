import polars as pl
import pytest

from licor.analysis import (
    ZoneSummaryConfig,
    rank_zone_cost_benefit,
    summarize_zone_costs,
)


def test_summarizes_zone_costs_against_push_baseline():
    zone_passes = pl.DataFrame(
        [
            _zone_pass("spa_t01", "T01", "none", 0.40, 5.00, False, None, None),
            _zone_pass("spa_t01", "T01", "none", 0.38, 5.10, False, None, None),
            _zone_pass("spa_t01", "T01", "low", 0.34, 5.20, True, 80.0, 1.2),
            _zone_pass("spa_t01", "T01", "low", 0.36, 5.30, True, 70.0, 1.1),
            _zone_pass("spa_t05_t06", "T05-T06", "none", 0.50, 8.00, False, None, None),
            _zone_pass("spa_t05_t06", "T05-T06", "high", 0.44, 8.60, True, 130.0, 1.8),
        ]
    )

    summary = summarize_zone_costs(zone_passes)

    t01_low = summary.filter(
        (pl.col("zone_id") == "spa_t01") & (pl.col("lico_intensity") == "low")
    ).row(0, named=True)
    assert t01_low["pass_count"] == 2
    assert t01_low["detected_lico_passes"] == 2
    assert t01_low["detected_lico_rate"] == pytest.approx(1.0)
    assert t01_low["mean_fuel_used_l"] == pytest.approx(0.35)
    assert t01_low["baseline_mean_fuel_used_l"] == pytest.approx(0.39)
    assert t01_low["fuel_saved_vs_baseline_l"] == pytest.approx(0.04)
    assert t01_low["mean_elapsed_time_s"] == pytest.approx(5.25)
    assert t01_low["baseline_mean_elapsed_time_s"] == pytest.approx(5.05)
    assert t01_low["time_lost_vs_baseline_s"] == pytest.approx(0.20)
    assert t01_low["fuel_saved_per_second_lps"] == pytest.approx(0.20)
    assert t01_low["mean_lico_start_distance_before_brake_m"] == pytest.approx(75.0)
    assert t01_low["mean_lico_duration_s"] == pytest.approx(1.15)

    t01_none = summary.filter(
        (pl.col("zone_id") == "spa_t01") & (pl.col("lico_intensity") == "none")
    ).row(0, named=True)
    assert t01_none["fuel_saved_per_second_lps"] is None


def test_filters_invalid_zone_passes_before_summarizing():
    zone_passes = pl.DataFrame(
        [
            _zone_pass("spa_t01", "T01", "none", 0.40, 5.0, False, None, None),
            _zone_pass(
                "spa_t01",
                "T01",
                "low",
                0.35,
                5.2,
                True,
                80.0,
                1.2,
                validity_label="incomplete_zone_coverage",
            ),
        ]
    )

    summary = summarize_zone_costs(zone_passes)

    assert summary.height == 1
    assert summary["lico_intensity"].to_list() == ["none"]


def test_can_use_borderline_zone_passes_when_configured():
    zone_passes = pl.DataFrame(
        [
            _zone_pass("spa_t01", "T01", "none", 0.40, 5.0, False, None, None),
            _zone_pass(
                "spa_t01",
                "T01",
                "low",
                0.35,
                5.2,
                True,
                80.0,
                1.2,
                validity_label="borderline",
            ),
        ]
    )

    summary = summarize_zone_costs(
        zone_passes,
        config=ZoneSummaryConfig(valid_labels=("valid", "borderline")),
    )

    assert summary.height == 2


def test_ranks_positive_fuel_saved_per_second_lost():
    zone_passes = pl.DataFrame(
        [
            _zone_pass("spa_t01", "T01", "none", 0.40, 5.0, False, None, None),
            _zone_pass("spa_t01", "T01", "low", 0.35, 5.5, True, 80.0, 1.2),
            _zone_pass("spa_t05_t06", "T05-T06", "none", 0.50, 8.0, False, None, None),
            _zone_pass("spa_t05_t06", "T05-T06", "low", 0.46, 8.1, True, 90.0, 1.0),
            _zone_pass("spa_t08", "T08", "none", 0.20, 4.0, False, None, None),
            _zone_pass("spa_t08", "T08", "low", 0.21, 4.1, True, 50.0, 0.8),
        ]
    )

    ranked = rank_zone_cost_benefit(summarize_zone_costs(zone_passes))

    assert ranked.select("rank", "zone_id").rows() == [
        (1, "spa_t05_t06"),
        (2, "spa_t01"),
    ]


def _zone_pass(
    zone_id: str,
    display_label: str,
    lico_intensity: str,
    fuel_used_l: float,
    elapsed_time_s: float,
    has_lico: bool,
    lico_distance_before_brake_m: float | None,
    lico_duration_s: float | None,
    *,
    validity_label: str = "valid",
) -> dict[str, object]:
    return {
        "zone_id": zone_id,
        "display_label": display_label,
        "lico_intensity": lico_intensity,
        "fuel_used_l": fuel_used_l,
        "elapsed_time_s": elapsed_time_s,
        "has_lico": has_lico,
        "lico_start_distance_before_brake_m": lico_distance_before_brake_m,
        "lico_duration_s": lico_duration_s,
        "lico_distance_m": lico_distance_before_brake_m,
        "brake_start_m": 250.0,
        "brake_start_speed_kph": 240.0,
        "min_speed_kph": 120.0,
        "exit_speed_kph": 180.0,
        "validity_label": validity_label,
    }
