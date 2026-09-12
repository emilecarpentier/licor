"""Build and verify the Bahrain circuit-C push-only collection pack."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PACK_DIR = (
    PROJECT_ROOT
    / "data/processed/experimental/bahrain_lmp2_transfer_2026_09"
    / "push_baseline_pack_v1"
)
PROTOCOL_FILE = Path("config/collection_protocols/bahrain_lmp2_circuit_c_v1.json")
DATASET_FILE = Path("config/datasets/bahrain_lmp2_circuit_c_2026-09.json")
RUN_SHEET_FILE = Path("docs/bahrain_circuit_c_push_run_sheet.md")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_pack(pack_dir: Path = DEFAULT_PACK_DIR) -> dict:
    if pack_dir.exists():
        raise FileExistsError(f"refusing to replace frozen pack: {pack_dir}")
    pack_dir.mkdir(parents=True)
    (pack_dir / "run_metadata_template.json").write_text(
        json.dumps(_metadata_template(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    _write_lap_notes(pack_dir / "lap_notes_template.csv")
    (pack_dir / "start_push_baseline.ps1").write_text(
        _powershell_launcher(pack_dir), encoding="utf-8"
    )
    (pack_dir / "start_push_baseline.cmd").write_text(_cmd_launcher(), encoding="utf-8")
    (pack_dir / "README.md").write_text(_pack_readme(), encoding="utf-8")

    source_paths = [PROTOCOL_FILE, DATASET_FILE, RUN_SHEET_FILE]
    artifact_names = [
        "README.md",
        "lap_notes_template.csv",
        "run_metadata_template.json",
        "start_push_baseline.cmd",
        "start_push_baseline.ps1",
    ]
    manifest = {
        "schema_version": 1,
        "pack_id": "bahrain_lmp2_circuit_c_push_baseline_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "Five clean push laps before frozen Bahrain LICO predictions.",
        "protocol_id": "bahrain_lmp2_circuit_c_v1",
        "minimum_clean_laps": 5,
        "maximum_scored_laps": 7,
        "lico_cues_enabled": False,
        "sources": {
            path.as_posix(): sha256_file(PROJECT_ROOT / path) for path in source_paths
        },
        "artifacts": {name: sha256_file(pack_dir / name) for name in artifact_names},
    }
    (pack_dir / "pack_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return verify_pack(pack_dir)


def verify_pack(pack_dir: Path = DEFAULT_PACK_DIR) -> dict:
    manifest_path = pack_dir / "pack_manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"pack manifest not found: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("lico_cues_enabled") is not False:
        raise ValueError("Bahrain push pack must keep all LICO cues disabled")
    for relative_path, expected_hash in manifest["sources"].items():
        path = (PROJECT_ROOT / relative_path).resolve()
        if not path.is_relative_to(PROJECT_ROOT) or sha256_file(path) != expected_hash:
            raise ValueError(f"source hash mismatch: {relative_path}")
    for name, expected_hash in manifest["artifacts"].items():
        path = pack_dir / name
        if not path.is_file() or sha256_file(path) != expected_hash:
            raise ValueError(f"artifact hash mismatch: {name}")
    return {
        "pack": str(pack_dir.resolve()),
        "pack_id": manifest["pack_id"],
        "hashes_verified": True,
        "minimum_clean_laps": manifest["minimum_clean_laps"],
        "maximum_scored_laps": manifest["maximum_scored_laps"],
        "lico_cues_enabled": manifest["lico_cues_enabled"],
    }


def _metadata_template() -> dict[str, object]:
    return {
        "schema_version": 1,
        "status": "prepared_not_run",
        "run_id": "",
        "telemetry_duckdb": "",
        "collection_protocol_id": "bahrain_lmp2_circuit_c_v1",
        "collection_session_id": "baseline_push_01",
        "collection_design": "baseline",
        "run_type": "push_baseline",
        "collection_label": "none",
        "target_zones": [],
        "execution_quality": "unknown",
        "labels_quality": "pending_driver_review",
        "track_name_expected": "Bahrain International Circuit",
        "track_layout_expected": "Grand Prix",
        "car_class_expected": "LMP2_ELMS",
        "car_expected": "Oreca 07 ELMS Custom Team 2025 #397",
        "starting_fuel_l": 55,
        "tire_wear_multiplier": 0,
        "weather_constant": True,
        "setup_id": "constant_not_recorded",
        "scored_laps_planned": 5,
        "replacement_laps_allowed": 2,
        "audio_cue_plan_id": "",
        "driver_notes": "",
    }


def _write_lap_notes(path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "relative_lap",
                "driver_lap_label",
                "execution_quality",
                "affected_turns",
                "traffic_or_error",
                "notes",
            ],
        )
        writer.writeheader()
        for relative_lap in range(1, 8):
            writer.writerow(
                {
                    "relative_lap": relative_lap,
                    "driver_lap_label": "",
                    "execution_quality": "",
                    "affected_turns": "",
                    "traffic_or_error": "",
                    "notes": "",
                }
            )


def _powershell_launcher(pack_dir: Path) -> str:
    try:
        relative_root = Path(os.path.relpath(PROJECT_ROOT, pack_dir)).as_posix()
        project_root_expression = (
            f"(Resolve-Path (Join-Path $PSScriptRoot '{relative_root}')).Path"
        )
    except ValueError:
        project_root_expression = (
            f"(Resolve-Path -LiteralPath '{PROJECT_ROOT.as_posix()}').Path"
        )
    return """param(
    [ValidatePattern('^[A-Za-z0-9_-]+$')][string]$RunId = ('bahrain_push_' + (Get-Date -Format 'yyyyMMdd_HHmmss')),
    [switch]$ConfirmTelemetryRecording,
    [string]$TelemetryDir = 'C:\\Program Files (x86)\\Steam\\steamapps\\common\\Le Mans Ultimate\\UserData\\Telemetry'
)
$ErrorActionPreference = 'Stop'
$projectRoot = __ROOT_EXPRESSION__
$python = Join-Path $projectRoot '.venv/Scripts/python.exe'
Push-Location $projectRoot
try {
    if (-not $ConfirmTelemetryRecording) {
        throw 'Telemetry confirmation missing. Start LMU telemetry recording, then relaunch with -ConfirmTelemetryRecording.'
    }
    if (-not (Test-Path -LiteralPath $TelemetryDir)) {
        throw "LMU telemetry directory not found: $TelemetryDir"
    }
    & $python scripts/build_bahrain_push_pack.py --verify-only --pack-dir $PSScriptRoot
    if ($LASTEXITCODE -ne 0) { throw 'Pack preflight failed.' }
    $sessionRoot = Join-Path (Split-Path $PSScriptRoot -Parent) 'sessions'
    $sessionDir = Join-Path $sessionRoot $RunId
    if (Test-Path -LiteralPath $sessionDir) { throw 'Run directory already exists; choose a new RunId.' }
    New-Item -ItemType Directory -Path $sessionDir -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'run_metadata_template.json') -Destination $sessionDir
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'lap_notes_template.csv') -Destination $sessionDir
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'pack_manifest.json') -Destination $sessionDir
    $metadataPath = Join-Path $sessionDir 'run_metadata_template.json'
    $metadata = Get-Content -LiteralPath $metadataPath | ConvertFrom-Json
    $metadata.run_id = $RunId
    $metadata.status = 'session_started'
    $metadata | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $metadataPath -Encoding UTF8
    $telemetryStartedAt = Get-Date
    Write-Host ''
    Write-Host 'Bahrain push baseline: outlap, then 5 clean push laps; maximum 2 replacements.'
    Write-Host 'No intentional LICO. No cue or beep is running.'
    Write-Host "Session files: $sessionDir"
    Read-Host 'After crossing the line at the end of the final lap and stopping/exporting LMU telemetry, press Enter'
    $newTelemetry = Get-ChildItem -LiteralPath $TelemetryDir -Filter '*.duckdb' |
        Where-Object LastWriteTime -ge $telemetryStartedAt.AddSeconds(-5) |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    $metadata = Get-Content -LiteralPath $metadataPath | ConvertFrom-Json
    if ($null -eq $newTelemetry) {
        $metadata.status = 'session_recorded_telemetry_not_found'
        Write-Warning 'No new LMU .duckdb was found. Preserve the notes and link the telemetry file manually.'
    } else {
        $metadata.telemetry_duckdb = $newTelemetry.FullName
        $metadata.status = 'session_recorded_pending_lap_review'
        Write-Host "Linked LMU telemetry: $($newTelemetry.FullName)"
    }
    $metadata | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $metadataPath -Encoding UTF8
    Write-Host 'Complete lap_notes_template.csv, then give Codex the RunId and any driving errors.'
} finally { Pop-Location }
""".replace("__ROOT_EXPRESSION__", project_root_expression)


def _cmd_launcher() -> str:
    return """@echo off
setlocal
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_push_baseline.ps1" %*
exit /b %errorlevel%
"""


def _pack_readme() -> str:
    return """# Bahrain circuit-C push baseline pack

Run from the LICOR project root in PowerShell:

```powershell
& .\\data\\processed\\experimental\\bahrain_lmp2_transfer_2026_09\\push_baseline_pack_v1\\start_push_baseline.cmd -ConfirmTelemetryRecording
```

This creates a session directory, runs no cues or audio, waits for the operator
to finish the push laps, and links the newest LMU DuckDB. See
`docs/bahrain_circuit_c_push_run_sheet.md` for the frozen protocol.
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack-dir", type=Path, default=DEFAULT_PACK_DIR)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    result = (
        verify_pack(args.pack_dir) if args.verify_only else build_pack(args.pack_dir)
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
