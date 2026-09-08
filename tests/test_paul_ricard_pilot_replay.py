import json
import importlib.util
from pathlib import Path

import polars as pl
import pytest

SPEC = importlib.util.spec_from_file_location(
    "paul_pilot_replay",
    Path(__file__).resolve().parents[1] / "scripts/verify_paul_ricard_pilot_replay.py",
)
replay = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(replay)


def test_recorded_source_fails_on_exhaustion_instead_of_hanging():
    source = replay.RecordedSampleSource([])
    with pytest.raises(AssertionError, match="exhausted recorded samples"):
        source.read_next_sample(timeout_ms=0)
    source.close()
    assert source.closed


@pytest.mark.skipif(
    not replay.RAW_FILE.is_file(), reason="requires local raw Paul telemetry"
)
def test_raw_replay_terminates_using_an_observed_lap8_sample():
    samples, summary = replay.load_raw_replay_samples(replay.RAW_FILE)
    assert samples[0].lap_number == 0
    assert samples[-2].lap_number == 7
    assert samples[-1].lap_number == 8
    assert samples[-1].ts == pytest.approx(954.875)
    assert summary["termination_lap_event_ts"] == pytest.approx(954.86)
    assert samples[-1].fuel_level_l is not None
    assert samples[-1].brake_pct is not None
    assert all(after.ts > before.ts for before, after in zip(samples, samples[1:]))


@pytest.mark.skipif(
    not replay.RAW_FILE.is_file(), reason="requires local raw Paul telemetry"
)
def test_real_samples_runtime_gate_logs_muted_laps_and_emits_only_lico(
    tmp_path, monkeypatch
):
    # Fixture plan tests the runtime adapter; final pack provenance is checked by
    # the separate unpatched replay command against the real frozen pilot pack.
    pack_dir = tmp_path / "fixture_pack"
    pack_dir.mkdir()
    pl.DataFrame(
        {
            "schema_version": [1, 1],
            "plan_id": ["test"] * 2,
            "zone_id": ["a", "b"],
            "display_label": ["A", "B"],
            "cue_distance_m": [1000.0, 2600.0],
            "planned_lift_start_m": [1020.0, 2620.0],
            "cue_tolerance_m": [10.0, 10.0],
        }
    ).write_csv(pack_dir / "plan.csv")
    (pack_dir / "pack_manifest.json").write_text(
        json.dumps({"fixture": True}), encoding="utf-8"
    )
    monkeypatch.setattr(replay, "verify_pack", lambda path: None)
    manifest = replay.verify_recorded_replay(
        pack_dir=pack_dir, output_dir=tmp_path / "checks"
    )
    assert manifest["recorded_audio_calls"] == 8
    assert manifest["logged_crossings"] == 16
    assert manifest["enabled_laps"] == [2, 3, 5, 6]
    assert manifest["muted_laps"] == [0, 1, 4, 7]
    events = pl.read_csv(tmp_path / "checks/real_replay_events.csv")
    assert events.filter(pl.col("cue_enabled")).height == 8
    with pytest.raises(FileExistsError, match="already exists"):
        replay.verify_recorded_replay(pack_dir=pack_dir, output_dir=tmp_path / "checks")
