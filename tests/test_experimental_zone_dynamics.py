import polars as pl
import pytest

from licor.analysis.experimental_zone_dynamics import summarize_experimental_zone_dynamics


def test_summarizes_zone_dynamics_and_baseline_deltas():
    zone_passes = pl.DataFrame(
        [
            _zone_pass(
                lap_number=1,
                intensity="none",
                has_lico=False,
                elapsed_time_s=5.0,
                fuel_used_l=0.120,
                brake_start_m=40.0,
                brake_start_speed_kph=210.0,
                exit_speed_kph=150.0,
                lico_distance_before_brake=None,
            ),
            _zone_pass(
                lap_number=2,
                intensity="controlled_random",
                collection_design="controlled_random",
                has_lico=True,
                elapsed_time_s=5.2,
                fuel_used_l=0.110,
                brake_start_m=45.0,
                brake_start_speed_kph=205.0,
                exit_speed_kph=154.0,
                lico_distance_before_brake=55.0,
            ),
        ]
    )
    lap_samples = pl.DataFrame(
        _samples_for_lap(1, speeds=[260.0, 235.0, 210.0, 170.0, 150.0, 165.0], brakes=[0.0, 0.0, 20.0, 95.0, 35.0, 0.0], carcass=90.0)
        + _samples_for_lap(2, speeds=[245.0, 220.0, 205.0, 175.0, 155.0, 170.0], brakes=[0.0, 0.0, 0.0, 90.0, 30.0, 0.0], carcass=84.0)
    )

    dynamics = summarize_experimental_zone_dynamics(zone_passes, lap_samples)

    assert dynamics.height == 2
    lico_row = dynamics.filter(pl.col("lap_number") == 2).row(0, named=True)
    assert lico_row["stint_index"] == 2
    assert lico_row["zone_start_speed_kph"] == pytest.approx(245.0)
    assert lico_row["apex_distance_m"] == pytest.approx(40.0)
    assert lico_row["apex_speed_kph"] == pytest.approx(155.0)
    assert lico_row["time_start_to_brake_s"] == pytest.approx(3.0)
    assert lico_row["time_brake_to_apex_s"] == pytest.approx(1.0)
    assert lico_row["time_apex_to_end_s"] == pytest.approx(1.0)
    assert lico_row["brake_peak_pct"] == pytest.approx(90.0)
    assert lico_row["brake_duration_s"] == pytest.approx(2.0)
    assert lico_row["brake_area_pct_s"] == pytest.approx(1.2)
    assert lico_row["time_above_80pct_brake_s"] == pytest.approx(1.0)
    assert lico_row["brake_release_rate_pct_per_s"] == pytest.approx(60.0)
    assert lico_row["fuel_saved_vs_baseline_l"] == pytest.approx(0.010)
    assert lico_row["time_lost_vs_baseline_s"] == pytest.approx(0.2)
    assert lico_row["brake_start_delta_vs_baseline_m"] == pytest.approx(5.0)
    assert lico_row["brake_start_speed_delta_vs_baseline_kph"] == pytest.approx(-5.0)
    assert lico_row["apex_speed_delta_vs_baseline_kph"] == pytest.approx(5.0)
    assert lico_row["exit_speed_delta_vs_baseline_kph"] == pytest.approx(4.0)
    assert lico_row["carcass_temp_zone_start_delta_vs_baseline_c"] == pytest.approx(-6.0)


def test_builds_stint_index_from_sorted_laps_per_run():
    zone_passes = pl.DataFrame(
        [
            _zone_pass(lap_number=5, intensity="none", has_lico=False),
            _zone_pass(lap_number=7, intensity="controlled_random", collection_design="controlled_random", has_lico=True, lico_distance_before_brake=40.0),
        ]
    )
    lap_samples = pl.DataFrame(_samples_for_lap(5) + _samples_for_lap(7))

    dynamics = summarize_experimental_zone_dynamics(zone_passes, lap_samples)

    assert dynamics.filter(pl.col("lap_number") == 5).row(0, named=True)["stint_index"] == 1
    assert dynamics.filter(pl.col("lap_number") == 7).row(0, named=True)["stint_index"] == 2


def _zone_pass(
    *,
    lap_number: int,
    intensity: str,
    collection_design: str = "baseline",
    has_lico: bool,
    elapsed_time_s: float = 5.0,
    fuel_used_l: float = 0.120,
    brake_start_m: float = 40.0,
    brake_start_speed_kph: float = 210.0,
    exit_speed_kph: float = 150.0,
    lico_distance_before_brake: float | None = None,
) -> dict[str, object]:
    return {
        "run_id": "synthetic_run",
        "lap_number": lap_number,
        "zone_id": "spa_t18",
        "display_label": "T18",
        "lico_intensity": intensity,
        "collection_design": collection_design,
        "has_lico": has_lico,
        "validity_label": "valid",
        "zone_start_m": 0.0,
        "zone_end_m": 50.0,
        "fuel_used_l": fuel_used_l,
        "elapsed_time_s": elapsed_time_s,
        "brake_start_m": brake_start_m,
        "brake_start_speed_kph": brake_start_speed_kph,
        "exit_speed_kph": exit_speed_kph,
        "lico_start_distance_before_brake_m": lico_distance_before_brake,
    }


def _samples_for_lap(
    lap_number: int,
    *,
    speeds: list[float] | None = None,
    brakes: list[float] | None = None,
    carcass: float = 90.0,
) -> list[dict[str, object]]:
    speed_values = speeds or [260.0, 235.0, 210.0, 170.0, 150.0, 165.0]
    brake_values = brakes or [0.0, 0.0, 20.0, 95.0, 35.0, 0.0]
    rows = []
    for index, (speed, brake) in enumerate(zip(speed_values, brake_values)):
        rows.append(
            {
                "run_id": "synthetic_run",
                "lap_number": lap_number,
                "ts": float(index),
                "lap_distance_m": float(index * 10),
                "ground_speed_kph": speed,
                "brake_pct": brake,
                "carcass_temp_c": carcass,
                "rubber_temp_c": carcass - 5.0,
                "centre_temp_c": carcass - 8.0,
                "rim_temp_c": carcass - 3.0,
            }
        )
    return rows
