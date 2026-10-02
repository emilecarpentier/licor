import importlib.util
from pathlib import Path

import polars as pl
import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "sebring_retry", ROOT / "scripts/build_sebring_abab_retry_pack.py"
)
retry = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(retry)


def test_retry_launcher_uses_four_laps_and_preserves_partial_run_guard(
    tmp_path, monkeypatch
):
    source = tmp_path / "source"
    source.mkdir()
    template = (ROOT / "scripts/templates/sebring_lico_validation.ps1").read_text()
    (source / "start_lico_validation.ps1").write_text(template)
    monkeypatch.setattr(retry, "SOURCE", source)
    script = retry.launcher(tmp_path / "retry")
    assert "@('A','B','A','B')" in script
    assert "$i -lt 4" in script
    assert "scored_laps=4" in script
    assert "--stop-after-lap',($FirstScoredLap+3)" in script
    assert "$lastLapNumber -gt ($FirstScoredLap + 3)" in script
    assert "session_incomplete_pending_lap_review" in script
    assert "'sebring_abab_'" in script
    assert "build_sebring_abab_retry_pack.py" in script
    assert "Remove-Item" not in script
    assert "$FirstScoredLap+6" not in script
    assert "The 7 scored laps" not in script


def test_retry_preflight_checks_all_four_laps_and_silent_outlap(tmp_path, monkeypatch):
    monkeypatch.setattr(retry.original, "TRANSFER", tmp_path)
    rows = []
    for index, zone in enumerate(retry.original.DOSES):
        for offset, role in enumerate(("A", "B")):
            cue = 100.0 + index * 100 + offset * 20
            rows.append(
                {
                    "schema_version": 1,
                    "plan_id": retry.original.plan_id(role),
                    "zone_id": zone,
                    "display_label": zone,
                    "cue_distance_m": cue,
                    "planned_lift_start_m": cue + 10,
                    "cue_tolerance_m": 5.0,
                    "track_length_m": 1000.0,
                    "notes": "",
                }
            )
    path = tmp_path / "plan.csv"
    pl.DataFrame(rows).write_csv(path)
    result = retry.preflight(path)
    assert result["pattern"] == ["A", "B", "A", "B"]
    assert result["cue_count"] == 28
    assert result["logged_crossings"] == 42
    assert result["system_audio_emitted"] is False


def test_retry_refuses_to_overwrite_an_existing_pack(tmp_path):
    with pytest.raises(FileExistsError, match="Refusing to replace"):
        retry.build(tmp_path)
