import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import polars as pl
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
try:
    SPEC = importlib.util.spec_from_file_location(
        "sebring_phases", ROOT / "scripts/qualify_sebring_phases.py"
    )
    phases = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(phases)
finally:
    sys.path.pop(0)


def test_quality_policy_never_certifies_unlocalized_errors_or_coupled_windows():
    assert (
        phases.quality_tier("first_attempt", "sbr_t07", 100, True) == "exploratory_only"
    )
    assert phases.quality_tier("retry", "sbr_t03", 100, True) == "exploratory_only"
    assert phases.quality_tier("retry", "sbr_t07", 100, True) == "strict_retry"
    assert phases.quality_tier("retry", "sbr_t07", 54, True) == "exploratory_only"
    assert phases.quality_tier("retry", "sbr_t07", 100, False) == "exploratory_only"


def test_cross_line_uses_next_lap_not_held_previous_distance_or_pit_teleport():
    trace = SimpleNamespace(
        intervals={},
        distance=pl.DataFrame(
            {
                "ts": [0.0, 0.2, 0.4, 0.6, 0.8],
                "lap_distance_m": [5800.0, 0.0, 50.0, 150.0, -1500.0],
            }
        ),
    )
    assert phases.after_line_time(trace, 10, 0, 100) == pytest.approx(0.5)


def test_incomplete_next_lap_cannot_be_extrapolated():
    trace = SimpleNamespace(
        intervals={},
        distance=pl.DataFrame(
            {"ts": [0.0, 0.2, 0.4, 0.6], "lap_distance_m": [5800.0, 0.0, 67.0, -1500.0]}
        ),
    )
    with pytest.raises(ValueError, match="does not reach"):
        phases.after_line_time(trace, 10, 0, 100)


def test_acceleration_uses_only_push_grid_and_rejects_out_of_range():
    grid = pl.DataFrame(
        {
            "zone_id": ["z"] * 4,
            "lead_m": [0.0, 0.0, 100.0, 100.0],
            "acceleration_mps2": [0.0, 2.0, 2.0, 4.0],
        }
    )
    assert phases.interpolate_acceleration(grid, "z", 50) == 2.0
    with pytest.raises(ValueError, match="no clipping"):
        phases.interpolate_acceleration(grid, "z", 101)


def test_phase_builder_refuses_overwrite(tmp_path):
    with pytest.raises(FileExistsError):
        phases.build(tmp_path)
