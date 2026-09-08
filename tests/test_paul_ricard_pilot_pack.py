import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import polars as pl
import pytest

from licor.live.lmu_live_cli import _build_parser
from licor.live import lmu_live_cli
from licor.live.lmu_shared_memory import LmuLiveTelemetrySample


SPEC = importlib.util.spec_from_file_location(
    "paul_pilot_pack",
    Path(__file__).resolve().parents[1] / "scripts/build_paul_ricard_pilot_pack.py",
)
pack = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pack)


def _plan():
    return pl.DataFrame(
        {
            "schema_version": [1, 1],
            "plan_id": ["pilot", "pilot"],
            "zone_id": ["pr_t11", "pr_t14"],
            "display_label": ["T11", "T14"],
            "cue_distance_m": [3500.0, 5000.0],
            "planned_lift_start_m": [3520.0, 5020.0],
            "cue_tolerance_m": [5.0, 5.0],
            "notes": ["", ""],
        }
    )


@pytest.mark.parametrize(
    "count,enabled", [(5, [5, 7]), (6, [5, 6, 9]), (7, [5, 6, 8, 9])]
)
def test_absolute_lap_schedules_and_real_runtime_gate(tmp_path, count, enabled):
    schedule = pack.lap_schedule(count, 4)
    assert [row["lap_number"] for row in schedule if row["cue_enabled"]] == enabled
    plan_path = tmp_path / "plan.csv"
    _plan().write_csv(plan_path)
    result = pack.preflight_schedule(plan_path, count)
    assert result == {
        "scored_laps": count,
        "cue_count": len(enabled) * 2,
        "logged_crossings": (count + 1) * 2,
    }


def test_preflight_verifies_frozen_hashes(tmp_path):
    _plan().write_csv(tmp_path / "plan.csv")
    (tmp_path / "pack_manifest.json").write_text(
        json.dumps(
            {
                "sources": {},
                "artifacts": {"plan.csv": pack.sha256_file(tmp_path / "plan.csv")},
            }
        )
    )
    assert pack.verify_pack(tmp_path)["hashes_verified"]
    with (tmp_path / "plan.csv").open("a") as handle:
        handle.write("\n")
    with pytest.raises(ValueError, match="hash mismatch"):
        pack.verify_pack(tmp_path)


def test_cli_accepts_absolute_cue_and_stop_laps():
    args = _build_parser().parse_args(
        ["--cue-laps", "5", "6", "9", "--stop-after-lap", "9"]
    )
    assert args.cue_laps == [5, 6, 9]
    assert args.stop_after_lap == 9


def test_build_refuses_to_replace_frozen_pack(tmp_path):
    with pytest.raises(FileExistsError, match="refusing to replace"):
        pack.build_pack(tmp_path, tmp_path)


def test_current_lap_probe_closes_reader_without_starting_audio(monkeypatch, capsys):
    reader = SimpleNamespace(closed=False)
    reader.read_next_player_sample = lambda timeout_ms: LmuLiveTelemetrySample(
        lap_number=12, lap_distance_m=42.5, ts=0.0
    )
    reader.close = lambda: setattr(reader, "closed", True)
    monkeypatch.setattr(lmu_live_cli, "LMUSharedMemoryReader", lambda: reader)
    monkeypatch.setattr(
        lmu_live_cli,
        "_environment_from_args",
        lambda args: SimpleNamespace(is_ready_for_static_live_cues=True),
    )
    assert lmu_live_cli.main(["--show-current-lap"]) == 0
    assert reader.closed
    assert "absolute_lap_number=12 lap_distance_m=42.500" in capsys.readouterr().out


@pytest.mark.parametrize("count,first", [(4, 1), (8, 1), (6, -1)])
def test_rejects_unplanned_schedules(count, first):
    with pytest.raises(ValueError):
        pack.lap_schedule(count, first)
