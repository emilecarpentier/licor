import polars as pl
import pytest

from licor.analysis import (
    ZoneCurveConfig,
    build_zone_curve_bins,
    build_zone_curve_points,
    summarize_zone_curve_bins,
)


def test_builds_zone_curve_points_against_zone_baseline():
    zone_passes = pl.DataFrame(
        [
            _zone_pass(1, "spa_t01", "T01", "none", 0.40, 5.00, False, None),
            _zone_pass(2, "spa_t01", "T01", "none", 0.38, 5.10, False, None),
            _zone_pass(3, "spa_t01", "T01", "low", 0.35, 5.25, True, 72.0),
            _zone_pass(4, "spa_t01", "T01", "high", 0.32, 5.60, True, 118.0),
        ]
    )

    points = build_zone_curve_points(zone_passes)

    assert points.height == 4

    low = points.filter(pl.col("lico_intensity") == "low").row(0, named=True)
    assert low["lico_distance_before_brake_m"] == pytest.approx(72.0)
    assert low["baseline_mean_fuel_used_l"] == pytest.approx(0.39)
    assert low["fuel_saved_vs_baseline_l"] == pytest.approx(0.04)
    assert low["baseline_mean_elapsed_time_s"] == pytest.approx(5.05)
    assert low["time_lost_vs_baseline_s"] == pytest.approx(0.20)
    assert low["fuel_saved_per_second_lps"] == pytest.approx(0.20)

    baseline_points = points.filter(pl.col("lico_intensity") == "none")
    assert baseline_points["lico_distance_before_brake_m"].to_list() == [0.0, 0.0]
    assert baseline_points["fuel_saved_per_second_lps"].to_list() == [None, None]


def test_bins_zone_curve_points_by_lico_distance():
    zone_passes = pl.DataFrame(
        [
            _zone_pass(1, "spa_t01", "T01", "none", 0.40, 5.00, False, None),
            _zone_pass(2, "spa_t01", "T01", "none", 0.38, 5.10, False, None),
            _zone_pass(3, "spa_t01", "T01", "low", 0.35, 5.25, True, 72.0),
            _zone_pass(4, "spa_t01", "T01", "medium", 0.34, 5.35, True, 87.0),
            _zone_pass(5, "spa_t01", "T01", "high", 0.32, 5.60, True, 118.0),
        ]
    )

    bins = build_zone_curve_bins(zone_passes, config=ZoneCurveConfig(bin_size_m=50.0))

    assert bins.select(
        "lico_distance_bin_start_m",
        "lico_distance_bin_end_m",
        "pass_count",
    ).rows() == [
        (0.0, 50.0, 2),
        (50.0, 100.0, 2),
        (100.0, 150.0, 1),
    ]

    middle_bin = bins.filter(pl.col("lico_distance_bin_start_m") == 50.0).row(0, named=True)
    assert middle_bin["detected_lico_passes"] == 2
    assert middle_bin["detected_lico_rate"] == pytest.approx(1.0)
    assert middle_bin["mean_lico_distance_before_brake_m"] == pytest.approx(79.5)
    assert middle_bin["mean_fuel_saved_l"] == pytest.approx(0.045)
    assert middle_bin["mean_time_lost_s"] == pytest.approx(0.25)
    assert middle_bin["fuel_saved_per_second_lps"] == pytest.approx(0.18)
    assert middle_bin["lico_intensities"] == ["low", "medium"]

    baseline_bin = bins.filter(pl.col("lico_distance_bin_start_m") == 0.0).row(0, named=True)
    assert baseline_bin["fuel_saved_per_second_lps"] is None


def test_filters_invalid_passes_and_sparse_bins():
    zone_passes = pl.DataFrame(
        [
            _zone_pass(1, "spa_t01", "T01", "none", 0.40, 5.00, False, None),
            _zone_pass(2, "spa_t01", "T01", "none", 0.38, 5.10, False, None),
            _zone_pass(3, "spa_t01", "T01", "low", 0.35, 5.25, True, 72.0),
            _zone_pass(
                4,
                "spa_t01",
                "T01",
                "high",
                0.32,
                5.60,
                True,
                118.0,
                validity_label="incomplete_zone_coverage",
            ),
        ]
    )

    points = build_zone_curve_points(zone_passes)
    bins = summarize_zone_curve_bins(
        points,
        config=ZoneCurveConfig(bin_size_m=50.0, min_bin_pass_count=2),
    )

    assert points.height == 3
    assert bins.select("lico_distance_bin_start_m", "pass_count").rows() == [
        (0.0, 2),
    ]


def test_returns_empty_when_no_baseline_is_available():
    zone_passes = pl.DataFrame(
        [
            _zone_pass(1, "spa_t01", "T01", "low", 0.35, 5.25, True, 72.0),
        ]
    )

    assert build_zone_curve_points(zone_passes).is_empty()
    assert build_zone_curve_bins(zone_passes).is_empty()


def test_excludes_detected_lico_from_baseline_points_by_default():
    zone_passes = pl.DataFrame(
        [
            _zone_pass(1, "spa_t18", "T18", "none", 0.40, 5.00, False, None),
            _zone_pass(2, "spa_t18", "T18", "none", 0.38, 5.10, True, 18.0),
            _zone_pass(3, "spa_t18", "T18", "low", 0.35, 5.25, True, 72.0),
        ]
    )

    points = build_zone_curve_points(zone_passes)

    assert points.height == 2
    assert points.filter(pl.col("lico_intensity") == "none").height == 1
    assert points["lap_number"].to_list() == [1, 3]


def test_nullable_collection_design_does_not_drop_nonbaseline_points():
    zone_passes = pl.DataFrame(
        [
            _zone_pass(1, "spa_t18", "T18", "none", 0.40, 5.00, False, None),
            _zone_pass(2, "spa_t18", "T18", "live", 0.35, 5.25, True, 72.0),
        ]
    ).with_columns(pl.lit(None, dtype=pl.String).alias("collection_design"))

    points = build_zone_curve_points(zone_passes)

    assert points["lap_number"].to_list() == [1, 2]


def _zone_pass(
    lap_number: int,
    zone_id: str,
    display_label: str,
    lico_intensity: str,
    fuel_used_l: float,
    elapsed_time_s: float,
    has_lico: bool,
    lico_distance_before_brake_m: float | None,
    *,
    validity_label: str = "valid",
) -> dict[str, object]:
    return {
        "file_name": "synthetic.duckdb",
        "run_id": f"synthetic_{lico_intensity}",
        "lap_number": lap_number,
        "zone_id": zone_id,
        "display_label": display_label,
        "lico_intensity": lico_intensity,
        "has_lico": has_lico,
        "lico_start_distance_before_brake_m": lico_distance_before_brake_m,
        "fuel_used_l": fuel_used_l,
        "elapsed_time_s": elapsed_time_s,
        "min_speed_kph": 120.0 - lap_number,
        "exit_speed_kph": 180.0 - lap_number,
        "validity_label": validity_label,
    }
