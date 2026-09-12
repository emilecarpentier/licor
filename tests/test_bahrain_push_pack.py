import importlib.util
import json
from pathlib import Path

import pytest


SPEC = importlib.util.spec_from_file_location(
    "bahrain_push_pack",
    Path(__file__).resolve().parents[1] / "scripts/build_bahrain_push_pack.py",
)
pack = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pack)


def test_builds_and_verifies_push_only_pack(tmp_path):
    pack_dir = tmp_path / "pack"

    result = pack.build_pack(pack_dir)

    assert result["hashes_verified"]
    assert result["minimum_clean_laps"] == 5
    assert result["maximum_scored_laps"] == 7
    assert result["lico_cues_enabled"] is False
    assert (pack_dir / "start_push_baseline.cmd").is_file()
    notes = (pack_dir / "lap_notes_template.csv").read_text(encoding="utf-8")
    assert "relative_lap" in notes
    assert notes.count("\n") == 8


def test_verify_rejects_modified_pack_artifact(tmp_path):
    pack_dir = tmp_path / "pack"
    pack.build_pack(pack_dir)
    with (pack_dir / "lap_notes_template.csv").open("a", encoding="utf-8") as file:
        file.write("changed\n")

    with pytest.raises(ValueError, match="artifact hash mismatch"):
        pack.verify_pack(pack_dir)


def test_launcher_requires_telemetry_and_never_starts_live_cues():
    launcher = pack._powershell_launcher(pack.DEFAULT_PACK_DIR)
    command = pack._cmd_launcher()

    assert "[switch]$ConfirmTelemetryRecording" in launcher
    assert "Telemetry confirmation missing" in launcher
    assert "Read-Host" in launcher
    assert "Linked LMU telemetry" in launcher
    assert "run_lmu_live_cues" not in launcher
    assert "emit-system-beep" not in launcher.lower()
    assert "console]::beep" not in launcher.lower()
    assert "-ExecutionPolicy Bypass" in command


def test_metadata_template_covers_protocol_required_fields():
    protocol = json.loads((pack.PROJECT_ROOT / pack.PROTOCOL_FILE).read_text())

    assert set(protocol["required_run_metadata"]).issubset(pack._metadata_template())


def test_build_refuses_to_replace_frozen_pack(tmp_path):
    pack.build_pack(tmp_path / "pack")

    with pytest.raises(FileExistsError, match="refusing to replace"):
        pack.build_pack(tmp_path / "pack")
