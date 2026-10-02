import importlib.util
from pathlib import Path

import numpy as np
import polars as pl

SPEC = importlib.util.spec_from_file_location(
    "sebring_push_intake",
    Path(__file__).resolve().parents[1] / "scripts/inspect_sebring_push_run.py",
)
intake = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(intake)


def test_profile_retains_nonfinite_count():
    result = intake.profile_values(np.array([1, 2, np.nan, np.inf]))
    assert result == {"samples": 4, "nonfinite": 2, "minimum": 1, "maximum": 2}


def test_secondary_braking_flag_is_not_training_action():
    brakes = pl.DataFrame(
        {
            "lap_number": [8],
            "start_ts": [10.0],
            "end_ts": [12.0],
            "start_lap_distance_m": [100.0],
            "end_lap_distance_m": [200.0],
        }
    )
    coasts = pl.DataFrame(
        {
            "has_lico": [True, True],
            "lap_number": [8, 9],
            "brake_start_ts": [12.5, 12.5],
            "lico_start_m": [150.0, 150.0],
        }
    )
    result = intake.classify_coast_context(coasts, brakes)
    assert result[0]["review_context"] == "release_within_prior_braking"
    assert result[1]["review_context"] == "review_approach_lift"
    assert not any(row["intentional_lico_training_eligible"] for row in result)
