import importlib.util
from pathlib import Path

import polars as pl
import pytest


SPEC = importlib.util.spec_from_file_location(
    "paul_live_validation",
    Path(__file__).resolve().parents[1]
    / "scripts/analyze_paul_ricard_live_validation.py",
)
validation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validation)


def test_lap_validation_compares_lico_against_same_run_push_mean():
    telemetry = pl.DataFrame(
        {
            "lap_number": [1, 1, 2, 2, 3, 3],
            "lap_distance_m": [0.0, 5800.0] * 3,
            "ts": [0.0, 100.0, 101.0, 202.0, 203.0, 303.0],
            "fuel_level_l": [50.0, 47.0, 47.0, 44.2, 44.2, 41.2],
        }
    )
    schedule = pl.DataFrame(
        {
            "lap_number": [1, 2, 3],
            "role": ["push", "lico", "push"],
            "cue_enabled": [False, True, False],
        }
    )

    laps = validation.build_lap_validation(
        telemetry,
        schedule,
        predicted_fuel_saved_l=0.15,
        predicted_time_lost_s=0.4,
    )

    lico = laps.filter(pl.col("role") == "lico").row(0, named=True)
    assert lico["fuel_saved_vs_push_reference_l"] == pytest.approx(0.2)
    assert lico["time_lost_vs_push_reference_s"] == pytest.approx(1.0)
    assert lico["reference_method"] == "bracketing_linear_interpolation"
    assert laps["complete_distance_coverage"].all()


def test_read_json_accepts_powershell_utf8_bom(tmp_path):
    path = tmp_path / "metadata.json"
    path.write_text('{"status": "ready"}', encoding="utf-8-sig")

    assert validation.read_json(path) == {"status": "ready"}


def test_lap_validation_rejects_pre_reset_high_sample_as_completion():
    telemetry = pl.DataFrame(
        {
            "lap_number": [1, 1, 2, 2, 2],
            "lap_distance_m": [0.0, 5800.0, 5800.0, 0.0, 1000.0],
            "ts": [0.0, 100.0, 101.0, 102.0, 120.0],
            "fuel_level_l": [50.0, 47.0, 47.0, 46.99, 46.5],
        }
    )
    schedule = pl.DataFrame(
        {
            "lap_number": [1, 2],
            "role": ["push", "lico"],
            "cue_enabled": [False, True],
        }
    )

    laps = validation.build_lap_validation(
        telemetry,
        schedule,
        predicted_fuel_saved_l=0.15,
        predicted_time_lost_s=0.4,
    )

    assert not laps.filter(pl.col("lap_number") == 2)["complete_distance_coverage"][0]


def test_sampling_gap_table_marks_blocking_audio_gap():
    telemetry = pl.DataFrame({"ts": [1.0, 1.02, 1.14, 1.16]})
    events = pl.DataFrame({"lap_number": [1], "zone_id": ["z1"], "sample_ts": [1.02]})

    gaps = validation.build_sampling_gap_table(telemetry, events)

    assert gaps["sampling_gap_after_cue"][0]
    assert gaps["sampling_gap_after_cue_s"][0] == pytest.approx(0.12)


def test_project_telemetry_distance_reuses_live_runtime_projection():
    telemetry = pl.DataFrame(
        {
            "lap_number": [1, 1],
            "lap_distance_m": [340.0, 340.0],
            "ts": [10.0, 10.2],
            "elapsed_s": [10.0, 10.2],
            "fuel_level_l": [50.0, 49.99],
            "speed_kph": [180.0, 180.0],
            "throttle_pct": [100.0, 100.0],
            "brake_pct": [0.0, 0.0],
            "gear": [5, 5],
        }
    )

    projected = validation.project_telemetry_distance(telemetry, track_length_m=None)

    assert projected["raw_lap_distance_m"].to_list() == [340.0, 340.0]
    assert projected["lap_distance_m"].to_list() == pytest.approx([340.0, 350.0])
    assert projected["distance_projection_method"].to_list() == [
        "raw_scoring",
        "speed_projected",
    ]


def test_event_coverage_rejects_missing_zone():
    schedule = pl.DataFrame(
        {"lap_number": [1], "role": ["lico"], "cue_enabled": [True]}
    )
    plan = pl.DataFrame({"zone_id": ["z1", "z2"]})
    events = pl.DataFrame(
        {
            "lap_number": [1],
            "zone_id": ["z1"],
            "cue_enabled": [True],
            "cue_error_m": [0.5],
            "cue_tolerance_m": [5.0],
        }
    )

    with pytest.raises(ValueError, match="missing or duplicate"):
        validation.validate_event_coverage(events, schedule, plan)


def test_observation_coverage_keeps_failed_lico_execution():
    observations = pl.DataFrame(
        {"zone_id": ["z1", "z2"], "has_lico": [True, False]}
    )

    detected = validation.validate_observation_coverage(
        observations, expected_observations=2
    )

    assert detected == 1


def test_driver_review_excludes_only_named_zone_observation():
    laps = pl.DataFrame({"lap_number": [23, 25], "role": ["lico", "lico"]})
    observations = pl.DataFrame(
        {
            "lap_number": [23, 23, 25, 25],
            "zone_id": ["z1", "z2", "z1", "z2"],
        }
    )
    metadata = {
        "valid_laps": [25],
        "excluded_laps_with_reasons": {"23": "driver error"},
        "zone_exclusions": [
            {"lap_number": 23, "zone_id": "z1", "reason": "corner error"}
        ],
    }

    reviewed_laps, reviewed_observations = validation.apply_driver_review(
        laps, observations, metadata
    )

    assert reviewed_laps["driver_included"].to_list() == [False, True]
    assert reviewed_observations["driver_included"].to_list() == [
        False,
        True,
        True,
        True,
    ]


def test_refit_blockers_only_include_audio_gap_when_observed():
    without_gap = validation.build_refit_blockers(
        metadata_complete=True,
        lap_quality_resolved=True,
        telemetry_duckdb_linked=True,
        audible_gap_count=0,
    )
    with_gap = validation.build_refit_blockers(
        metadata_complete=True,
        lap_quality_resolved=True,
        telemetry_duckdb_linked=True,
        audible_gap_count=24,
    )

    assert all("system beep" not in blocker for blocker in without_gap)
    assert any("system beep" in blocker for blocker in with_gap)


def test_refit_blockers_preserve_unknown_unclean_laps():
    blockers = validation.build_refit_blockers(
        metadata_complete=True,
        lap_quality_resolved=False,
        telemetry_duckdb_linked=False,
        audible_gap_count=0,
    )

    assert any("lap numbers are unknown" in blocker for blocker in blockers)
    assert any("DuckDB" in blocker for blocker in blockers)
