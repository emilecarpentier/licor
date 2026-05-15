import polars as pl

from licor.reports import create_zone_curve_report_figure


def test_creates_zone_curve_report_with_points_and_bins():
    points = pl.DataFrame(
        [
            _point("spa_t01", "T01", "none", 1, 0.0, 0.0, 0.0),
            _point("spa_t01", "T01", "low", 2, 75.0, 0.04, 0.20),
            _point("spa_t05_t06", "T05-T06", "none", 3, 0.0, 0.0, 0.0),
            _point("spa_t05_t06", "T05-T06", "high", 4, 125.0, 0.08, 0.40),
        ]
    )
    bins = pl.DataFrame(
        [
            _bin("spa_t01", "T01", 0.0, 25.0, 12.5, 1, 0, 0.0, 0.0),
            _bin("spa_t01", "T01", 50.0, 100.0, 75.0, 1, 1, 0.04, 0.20),
            _bin("spa_t05_t06", "T05-T06", 0.0, 25.0, 12.5, 1, 0, 0.0, 0.0),
            _bin("spa_t05_t06", "T05-T06", 100.0, 150.0, 125.0, 1, 1, 0.08, 0.40),
        ]
    )

    figure = create_zone_curve_report_figure(
        points,
        bins,
        title="Synthetic zone curves",
    )

    assert figure.layout.title.text == "Synthetic zone curves"
    assert len(figure.data) == 12
    assert figure.layout.height == 520
    assert figure.layout.annotations[0].text == "T01 fuel"
    assert figure.layout.annotations[1].text == "T01 time"
    assert {trace.name for trace in figure.data} == {
        "none pass",
        "low pass",
        "high pass",
        "bin fuel mean",
        "bin time mean",
    }


def test_creates_empty_zone_curve_report_figure():
    figure = create_zone_curve_report_figure(
        pl.DataFrame(),
        pl.DataFrame(),
        title="Empty report",
    )

    assert figure.layout.title.text == "Empty report"
    assert len(figure.data) == 0


def _point(
    zone_id: str,
    display_label: str,
    intensity: str,
    lap_number: int,
    lico_distance_m: float,
    fuel_saved_l: float,
    time_lost_s: float,
) -> dict[str, object]:
    return {
        "file_name": "synthetic.duckdb",
        "run_id": f"run_{intensity}",
        "lap_number": lap_number,
        "zone_id": zone_id,
        "display_label": display_label,
        "lico_intensity": intensity,
        "has_lico": intensity != "none",
        "lico_distance_before_brake_m": lico_distance_m,
        "fuel_used_l": 1.0,
        "baseline_mean_fuel_used_l": 1.0,
        "fuel_saved_vs_baseline_l": fuel_saved_l,
        "elapsed_time_s": 5.0,
        "baseline_mean_elapsed_time_s": 5.0,
        "time_lost_vs_baseline_s": time_lost_s,
        "fuel_saved_per_second_lps": None,
        "min_speed_kph": 120.0,
        "exit_speed_kph": 180.0,
        "validity_label": "valid",
    }


def _bin(
    zone_id: str,
    display_label: str,
    start_m: float,
    end_m: float,
    mid_m: float,
    pass_count: int,
    lico_pass_count: int,
    fuel_saved_l: float,
    time_lost_s: float,
) -> dict[str, object]:
    return {
        "zone_id": zone_id,
        "display_label": display_label,
        "lico_distance_bin_start_m": start_m,
        "lico_distance_bin_end_m": end_m,
        "lico_distance_bin_mid_m": mid_m,
        "pass_count": pass_count,
        "detected_lico_passes": lico_pass_count,
        "detected_lico_rate": 1.0 if lico_pass_count else 0.0,
        "lico_intensities": ["low"] if lico_pass_count else ["none"],
        "mean_lico_distance_before_brake_m": mid_m,
        "mean_fuel_saved_l": fuel_saved_l,
        "mean_time_lost_s": time_lost_s,
        "fuel_saved_per_second_lps": None,
        "mean_observed_fuel_saved_per_second_lps": None,
        "mean_min_speed_kph": 120.0,
        "mean_exit_speed_kph": 180.0,
    }
