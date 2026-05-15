import polars as pl
import pytest

from licor.analysis import summarize_full_lap_sanity


def test_compares_full_lap_delta_with_summed_zone_deltas():
    lap_summary = pl.DataFrame(
        [
            _lap("run_none", "none", 1, 100.0, 10.0),
            _lap("run_none", "none", 2, 102.0, 10.2),
            _lap("run_low", "low", 3, 102.5, 9.4),
        ]
    )
    zone_points = pl.DataFrame(
        [
            _zone_point("run_low", 3, "spa_t01", 0.20, 0.40, True, 60.0),
            _zone_point("run_low", 3, "spa_t18", 0.30, 0.50, True, 90.0),
        ]
    )

    sanity = summarize_full_lap_sanity(lap_summary, zone_points)

    low = sanity.filter(pl.col("collection_label") == "low").row(0, named=True)
    assert low["baseline_mean_fuel_used_l"] == pytest.approx(10.1)
    assert low["lap_fuel_saved_vs_baseline_l"] == pytest.approx(0.7)
    assert low["zone_observed_fuel_saved_l"] == pytest.approx(0.5)
    assert low["fuel_residual_l"] == pytest.approx(0.2)
    assert low["zone_to_lap_fuel_ratio"] == pytest.approx(0.5 / 0.7)

    assert low["baseline_mean_lap_time_s"] == pytest.approx(101.0)
    assert low["lap_time_lost_vs_baseline_s"] == pytest.approx(1.5)
    assert low["zone_observed_time_lost_s"] == pytest.approx(0.9)
    assert low["time_residual_s"] == pytest.approx(0.6)
    assert low["zone_to_lap_time_ratio"] == pytest.approx(0.9 / 1.5)
    assert low["included_zone_count"] == 2
    assert low["observed_lico_zone_count"] == 2
    assert low["observed_lico_distance_m"] == pytest.approx(150.0)


def test_missing_zone_points_are_treated_as_zero_zone_coverage():
    lap_summary = pl.DataFrame(
        [
            _lap("run_none", "none", 1, 100.0, 10.0),
            _lap("run_low", "low", 2, 101.0, 9.8),
        ]
    )

    sanity = summarize_full_lap_sanity(lap_summary, pl.DataFrame())

    low = sanity.filter(pl.col("collection_label") == "low").row(0, named=True)
    assert low["zone_observed_fuel_saved_l"] == pytest.approx(0.0)
    assert low["zone_observed_time_lost_s"] == pytest.approx(0.0)
    assert low["fuel_residual_l"] == pytest.approx(0.2)
    assert low["time_residual_s"] == pytest.approx(1.0)
    assert low["included_zone_count"] == 0


def test_filters_invalid_laps_when_validity_column_is_available():
    lap_summary = pl.DataFrame(
        [
            _lap("run_none", "none", 1, 100.0, 10.0, is_valid_lap=True),
            _lap("run_none", "none", 2, 90.0, 8.0, is_valid_lap=False),
            _lap("run_low", "low", 3, 101.0, 9.8, is_valid_lap=True),
        ]
    )

    sanity = summarize_full_lap_sanity(lap_summary, pl.DataFrame())

    assert sanity["lap_number"].to_list() == [3, 1]
    low = sanity.filter(pl.col("collection_label") == "low").row(0, named=True)
    assert low["baseline_mean_fuel_used_l"] == pytest.approx(10.0)
    assert low["baseline_mean_lap_time_s"] == pytest.approx(100.0)


def test_returns_empty_without_a_baseline_lap():
    lap_summary = pl.DataFrame(
        [
            _lap("run_low", "low", 3, 101.0, 9.8),
        ]
    )

    assert summarize_full_lap_sanity(lap_summary, pl.DataFrame()).is_empty()


def _lap(
    run_id: str,
    collection_label: str,
    lap_number: int,
    lap_time_s: float,
    fuel_used_l: float,
    *,
    is_valid_lap: bool | None = None,
) -> dict[str, object]:
    row = {
        "run_id": run_id,
        "file_name": f"{run_id}.duckdb",
        "collection_label": collection_label,
        "lap_number": lap_number,
        "lap_time_s": lap_time_s,
        "fuel_used_l": fuel_used_l,
    }
    if is_valid_lap is not None:
        row["is_valid_lap"] = is_valid_lap
    return row


def _zone_point(
    run_id: str,
    lap_number: int,
    zone_id: str,
    fuel_saved_l: float,
    time_lost_s: float,
    has_lico: bool,
    lico_distance_m: float,
) -> dict[str, object]:
    return {
        "run_id": run_id,
        "lap_number": lap_number,
        "zone_id": zone_id,
        "fuel_saved_vs_baseline_l": fuel_saved_l,
        "time_lost_vs_baseline_s": time_lost_s,
        "has_lico": has_lico,
        "lico_distance_before_brake_m": lico_distance_m,
    }
