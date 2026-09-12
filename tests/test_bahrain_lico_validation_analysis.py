import importlib.util
import math
from pathlib import Path

import polars as pl


SPEC = importlib.util.spec_from_file_location(
    "bahrain_lico_validation_analysis",
    Path(__file__).resolve().parents[1]
    / "scripts/analyze_bahrain_lico_validation.py",
)
analysis = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(analysis)


def test_interpolation_discards_stale_pre_reset_live_samples():
    lap = pl.DataFrame(
        {
            "elapsed_s": [0.0, 0.1, 0.2, 1.2, 2.2],
            "lap_distance_m": [5378.0, 5384.0, 5.0, 100.0, 200.0],
            "fuel_level_l": [50.0, 49.99, 49.98, 49.8, 49.6],
        }
    )

    elapsed = analysis.interpolate_at_distance(lap, 150.0, "elapsed_s")
    fuel = analysis.interpolate_at_distance(lap, 150.0, "fuel_level_l")

    assert math.isclose(elapsed, 1.7)
    assert math.isclose(fuel, 49.7)


def test_scoring_keeps_frozen_and_recovery_outcomes_separate():
    passes = pl.DataFrame(
        {
            "lap_number": [23, 26, 29, 24],
            "role": ["push", "push", "push", "lico"],
            "zone_id": ["bhr_t10"] * 4,
            "start_distance_m": [2400.0] * 4,
            "frozen_elapsed_time_s": [10.0, 10.2, 10.1, 10.3],
            "frozen_fuel_used_l": [0.20, 0.22, 0.21, 0.18],
            "recovery_elapsed_time_s": [12.0, 12.2, 12.1, 12.5],
            "recovery_fuel_used_l": [0.25, 0.27, 0.26, 0.22],
        }
    )

    baselines = analysis._build_baselines(passes, [23, 26, 29])
    scored = analysis._score_live_passes(passes, baselines, [24]).row(0, named=True)

    assert math.isclose(scored["frozen_time_lost_s"], 0.2)
    assert math.isclose(scored["recovery_time_lost_s"], 0.4)
    assert math.isclose(scored["frozen_fuel_saved_l"], 0.03)
    assert math.isclose(scored["recovery_fuel_saved_l"], 0.04)
