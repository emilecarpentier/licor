import importlib.util
from pathlib import Path

import polars as pl
import pytest

SPEC = importlib.util.spec_from_file_location(
    "sebring_analysis",
    Path(__file__).resolve().parents[1] / "scripts/analyze_sebring_lico_sessions.py",
)
analysis = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(analysis)


def test_onset_ignores_short_pedal_cut():
    frame = pl.DataFrame(
        {
            "ts": [0.0, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3],
            "value": [100.0, 0.0, 100.0, 0.0, 0.0, 0.0, 0.0],
        }
    )
    assert analysis.sustained_onset(frame, 0, 0.3, above=False) == 0.15
    assert analysis.sustained_onset(frame, 0, 0.1, above=False) is None


def test_reference_cohorts_do_not_pool_and_quality_flags_survive():
    rows = []
    for cohort, role, time, fuel, good, impact in [
        ("prior_push", "push", 10.0, 1.0, True, 0),
        ("first_attempt", "push", 11.0, 1.1, True, 1),
        ("first_attempt", "A", 12.0, 0.8, True, 0),
        ("retry", "B", 99.0, 99.0, False, 0),
    ]:
        rows.append(
            dict(
                cohort=cohort,
                role=role,
                zone_id="t1",
                elapsed_time_s=time,
                fuel_used_l=fuel,
                quality_ok=good,
                impact_event_count=impact,
                exit_speed_kph=200.0,
                entry_speed_kph=250.0,
                driver_review_pending=True,
            )
        )
    result = analysis.contrasts(pl.DataFrame(rows)).sort("baseline")
    assert result.height == 2
    assert result["time_lost_s"].to_list() == [1.0, 2.0]
    assert result["fuel_saved_l"].to_list() == pytest.approx([0.3, 0.2])
    assert result["baseline_impact_pass_count"].to_list() == [1, 0]
    assert result["driver_review_pending"].all()


def test_analysis_never_overwrites_existing_outputs(tmp_path):
    with pytest.raises(FileExistsError):
        analysis.build(tmp_path)


def test_sampling_rejects_extrapolation():
    frame = pl.DataFrame({"ts": [1.0, 2.0], "value": [2.0, 4.0]})
    assert analysis.sample(frame, 1.5) == 3.0
    with pytest.raises(ValueError):
        analysis.sample(frame, 0.0)
