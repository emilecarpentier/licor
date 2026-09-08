"""Freeze the Paul static pilot and verify its scheduled cue path without audio."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile

import polars as pl

from licor.analysis import load_live_cue_plan
from licor.analysis.live_plan import LiveCuePlanConfig, build_live_cue_plan
from licor.analysis.track_zones import load_track_zone_table, track_zones_to_frame
from licor.live.audio import RecordingAudioCueAdapter
from licor.live.lmu_shared_memory import LmuLiveTelemetrySample
from licor.live.runtime import LiveStaticCueSessionConfig, run_static_live_cue_session


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_DIR = (
    PROJECT_ROOT / "data/processed/experimental/paul_ricard_pilot_2026_09"
)
ZONE_CONFIG = PROJECT_ROOT / "config/track_zones/paul_ricard_lmp2_zones.draft.json"
LAP_PATTERNS = {
    5: ("push", "lico", "push", "lico", "push"),
    6: ("push", "lico", "lico", "push", "push", "lico"),
    7: ("push", "lico", "lico", "push", "lico", "lico", "push"),
}


def lap_schedule(scored_laps: int, first_scored_lap: int) -> list[dict[str, object]]:
    if scored_laps not in LAP_PATTERNS or first_scored_lap < 0:
        raise ValueError(
            "require 5, 6 or 7 scored laps and a nonnegative absolute first lap"
        )
    return [
        {
            "scored_index": index + 1,
            "lap_number": first_scored_lap + index,
            "role": role,
            "cue_enabled": role == "lico",
        }
        for index, role in enumerate(LAP_PATTERNS[scored_laps])
    ]


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_pack(
    input_dir: Path, pack_dir: Path, zone_config: Path = ZONE_CONFIG
) -> dict:
    # A frozen pack must be given a new directory for any new generation.
    if pack_dir.exists():
        raise FileExistsError(f"refusing to replace frozen pack: {pack_dir}")
    from build_paul_ricard_intake import verify_intake_manifest

    intake = verify_intake_manifest(input_dir, PROJECT_ROOT)
    plan_manifest_path = input_dir / "plan_manifest.json"
    upstream = json.loads(plan_manifest_path.read_text(encoding="utf-8"))
    for section in ("inputs", "source_files", "outputs"):
        for record in upstream[section]:
            path = (PROJECT_ROOT / record["path"]).resolve()
            if (
                not path.is_relative_to(PROJECT_ROOT)
                or sha256_file(path) != record["sha256"]
            ):
                raise ValueError(f"stale upstream plan lineage: {record['path']}")
    plan_path = input_dir / "zone_plan.csv"
    passes_path = input_dir / "zone_passes_modeling.csv"
    zone_plan = pl.read_csv(plan_path)
    passes = pl.read_csv(passes_path)
    table = load_track_zone_table(zone_config)
    if table.validation_issues():
        raise ValueError(f"invalid track-zone definitions: {table.validation_issues()}")
    selected = zone_plan.filter(pl.col("is_selected_for_lico"))
    if selected.is_empty() or set(selected["plan_status"].to_list()) != {"target_met"}:
        raise ValueError("pilot requires a nonempty target_met plan")
    speeds = (
        passes.filter(
            (pl.col("lico_intensity").is_in(["baseline", "none"]))
            & (~pl.col("has_lico"))
            & (pl.col("validity_label") == "valid")
        )
        .group_by("zone_id")
        .agg(
            pl.col("brake_start_speed_kph")
            .median()
            .alias("cue_latency_reference_speed_kph")
        )
    )
    selected = selected.join(speeds, on="zone_id", how="left")
    if any(
        v is None or not math.isfinite(v) or v <= 0
        for v in selected["cue_latency_reference_speed_kph"].to_list()
    ):
        raise ValueError(
            "selected zones require a valid local push braking-speed reference"
        )
    live_plan = build_live_cue_plan(
        selected,
        track_zones_to_frame(table),
        config=LiveCuePlanConfig(
            plan_id="paul_ricard_pilot_static_2026_09",
            track_name=table.track_name,
            car_class=table.car_class,
            race_context_id="pilot_0.05_l_per_lap_not_race_strategy",
            minimum_confidence_label="pilot_unvalidated",
            cue_latency_compensation_s=0.35,
            notes="Frozen static pilot. Spa 0.35 s latency transferred provisionally; "
            "local push brake speed is a proxy. Fuel/time predictions are unvalidated.",
        ),
    )
    if any(
        not math.isfinite(v) or v < 0 for v in live_plan["cue_distance_m"].to_list()
    ):
        raise ValueError("pilot only supports non-wrapping positive cue positions")
    pack_dir.mkdir(parents=True)
    live_plan.write_csv(pack_dir / "plan.csv")
    selected.write_csv(pack_dir / "predictions.csv")
    pl.DataFrame(
        [
            {"scored_laps": count, **row}
            for count in LAP_PATTERNS
            for row in lap_schedule(count, 1)
        ]
    ).rename({"lap_number": "relative_lap_number"}).write_csv(
        pack_dir / "lap_patterns.csv"
    )
    live_plan.select(
        "zone_id",
        "display_label",
        "selected_lico_distance_m",
        "planned_lift_start_m",
        "cue_distance_m",
    ).with_columns(pl.lit("").alias("driver_notes")).write_csv(
        pack_dir / "zone_notes_template.csv"
    )
    metadata = {
        "status": "template_not_collected",
        "track": table.track_name,
        "car_class": table.car_class,
        "car": "",
        "driver": "",
        "setup": "",
        "tire_wear_multiplier": 0,
        "starting_fuel_l": None,
        "weather_and_track_conditions": "",
        "telemetry_duckdb": "",
        "valid_laps": [],
        "excluded_laps_with_reasons": {},
        "analysis_note": "Analyze enabled LICO cues separately from muted push crossings. "
        "Compare achieved zone fuel/time with same-run push laps; no adaptive authority.",
    }
    (pack_dir / "run_metadata_template.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )
    (pack_dir / "start_pilot.ps1").write_text(_launcher(pack_dir), encoding="utf-8")
    for name in ("intake_manifest.json", "plan_manifest.json", "selected_support.csv"):
        (pack_dir / name).write_bytes((input_dir / name).read_bytes())
    sources = [
        plan_path,
        passes_path,
        zone_config,
        Path(__file__),
        PROJECT_ROOT / "src/licor/live/runtime.py",
        PROJECT_ROOT / "src/licor/live/lmu_live_cli.py",
        PROJECT_ROOT / "src/licor/analysis/live_plan.py",
    ]
    for optional in (
        input_dir / "intake_manifest.json",
        input_dir / "plan_manifest.json",
    ):
        if optional.exists():
            sources.append(optional)
    manifest = {
        "schema_version": 1,
        "pack_status": "frozen_static_pilot_pending_empirical_validation",
        "plan_id": live_plan["plan_id"][0],
        "git_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, text=True
        ).strip(),
        "git_dirty": bool(
            subprocess.check_output(
                ["git", "status", "--porcelain"], cwd=PROJECT_ROOT, text=True
            ).strip()
        ),
        "source_paths_relative_to": "project_root",
        "sources": {
            **intake["source_sha256"],
            **{
                (input_dir / name)
                .resolve()
                .relative_to(PROJECT_ROOT)
                .as_posix(): digest
                for name, digest in intake["artifact_sha256"].items()
            },
            **{record["path"]: record["sha256"] for record in upstream["source_files"]},
            **{
                path.resolve().relative_to(PROJECT_ROOT).as_posix(): sha256_file(path)
                for path in sources
            },
        },
        "artifact_paths_relative_to": "pack_directory",
        "artifacts": {
            path.name: sha256_file(path)
            for path in sorted(pack_dir.iterdir())
            if path.is_file()
        },
        "latency": {
            "seconds": 0.35,
            "status": "provisional_transfer_from_spa",
            "speed_source": "median valid local push brake_start_speed_kph proxy",
        },
        "validation": "Synthetic silent runtime schedule preflight only; no simulator/audio/fuel validation.",
        "adaptive_mode": "offline_after_run_only",
        "target_fuel_saved_per_lap_l": 0.05,
        "predicted_fuel_saved_per_lap_l": live_plan["expected_fuel_saved_l"].sum(),
        "predicted_time_lost_per_lap_s": live_plan["expected_time_lost_s"].sum(),
    }
    (pack_dir / "pack_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    return verify_pack(pack_dir)


class _SyntheticSource:
    def __init__(self, samples: list[LmuLiveTelemetrySample]):
        self.samples = iter(samples)

    def read_next_sample(self, *, timeout_ms: int):
        del timeout_ms
        try:
            return next(self.samples)
        except StopIteration:
            raise AssertionError(
                "preflight runtime did not stop at the configured lap"
            ) from None

    def close(self):
        pass


def preflight_schedule(plan_path: Path, scored_laps: int) -> dict[str, int]:
    plan = load_live_cue_plan(plan_path)
    schedule = lap_schedule(scored_laps, 4)
    enabled = tuple(int(row["lap_number"]) for row in schedule if row["cue_enabled"])
    last_lap = int(schedule[-1]["lap_number"])
    positions = sorted(
        {
            0.0,
            *[
                position
                for cue in plan["cue_distance_m"].to_list()
                for position in (max(0.0, cue - 0.5), cue + 0.5)
            ],
        }
    )
    samples = [
        LmuLiveTelemetrySample(
            lap_number=lap,
            lap_distance_m=distance,
            ts=float(index),
            elapsed_s=float(index),
        )
        for index, (lap, distance) in enumerate(
            (lap, distance) for lap in range(3, last_lap + 2) for distance in positions
        )
    ]
    audio = RecordingAudioCueAdapter()
    with tempfile.TemporaryDirectory(prefix="licor-pilot-preflight-") as temporary:
        events = run_static_live_cue_session(
            plan_path=plan_path,
            event_log_path=Path(temporary) / "events.csv",
            sample_source=_SyntheticSource(samples),
            audio_adapter=audio,
            config=LiveStaticCueSessionConfig(
                cue_lap_numbers=enabled,
                stop_after_lap_number=last_lap,
            ),
        )
    expected = {(lap, zone) for lap in enabled for zone in plan["zone_id"].to_list()}
    actual = [(cue.lap_number, cue.zone_id) for cue in audio.cues]
    if set(actual) != expected or len(actual) != len(expected):
        raise AssertionError("pilot preflight audio gate/count mismatch")
    if events.height != (scored_laps + 1) * plan.height:
        raise AssertionError("pilot preflight must retain push/outlap crossing logs")
    if events.filter(pl.col("cue_enabled")).height != len(expected):
        raise AssertionError("pilot preflight enabled event log mismatch")
    return {
        "scored_laps": scored_laps,
        "cue_count": len(actual),
        "logged_crossings": events.height,
    }


def verify_pack(pack_dir: Path) -> dict:
    manifest = json.loads((pack_dir / "pack_manifest.json").read_text(encoding="utf-8"))
    for mapping, base in (("sources", PROJECT_ROOT), ("artifacts", pack_dir)):
        for relative, expected in manifest[mapping].items():
            path = (base / relative).resolve()
            if not path.is_relative_to(base.resolve()) or sha256_file(path) != expected:
                raise ValueError(f"frozen pack hash mismatch: {relative}")
    results = [
        preflight_schedule(pack_dir / "plan.csv", count) for count in LAP_PATTERNS
    ]
    return {
        "pack": str(pack_dir),
        "hashes_verified": True,
        "silent_synthetic_preflight": results,
    }


def _launcher(pack_dir: Path) -> str:
    relative_root = Path(os.path.relpath(PROJECT_ROOT, pack_dir)).as_posix()
    return """param(
    [Parameter(Mandatory=$true)][ValidateRange(0,9999)][int]$FirstScoredLap,
    [ValidateSet(5,6,7)][int]$ScoredLaps = 6,
    [ValidatePattern('^[A-Za-z0-9_-]+$')][string]$RunId = ('paul_pilot_' + (Get-Date -Format 'yyyyMMdd_HHmmss')),
    [switch]$EmitSystemBeep
)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '__ROOT__')).Path
$python = Join-Path $projectRoot '.venv/Scripts/python.exe'
Push-Location $projectRoot
try {
    & $python scripts/build_paul_ricard_pilot_pack.py --verify-only --pack-dir $PSScriptRoot
    if ($LASTEXITCODE -ne 0) { throw 'Pack preflight failed.' }
    $patterns = @{5=@('push','lico','push','lico','push');6=@('push','lico','lico','push','push','lico');7=@('push','lico','lico','push','lico','lico','push')}
    $schedule = @(for ($i = 0; $i -lt $ScoredLaps; $i++) {
        [pscustomobject]@{scored_index=$i+1;lap_number=$FirstScoredLap+$i;role=$patterns[$ScoredLaps][$i];cue_enabled=($patterns[$ScoredLaps][$i] -eq 'lico');fuel_start_l='';cue_missed='';traffic_or_error='';notes=''}
    })
    $cueLaps = @($schedule | Where-Object cue_enabled | ForEach-Object lap_number)
    $sessionDir = Join-Path (Split-Path $PSScriptRoot -Parent) ('sessions/' + $RunId)
    if (Test-Path -LiteralPath $sessionDir) { throw 'Run directory already exists; choose a new RunId.' }
    New-Item -ItemType Directory -Path $sessionDir | Out-Null
    $schedule | Export-Csv -LiteralPath (Join-Path $sessionDir 'lap_schedule.csv') -NoTypeInformation -Encoding UTF8
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'run_metadata_template.json') -Destination $sessionDir
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'pack_manifest.json') -Destination $sessionDir
    $resolvedConfig = @{run_id=$RunId;first_scored_lap=$FirstScoredLap;scored_laps=$ScoredLaps;cue_laps=$cueLaps;stop_after_lap=$FirstScoredLap+$ScoredLaps-1;emit_system_beep=[bool]$EmitSystemBeep;plan_sha256=(Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $PSScriptRoot 'plan.csv')).Hash;telemetry_log='telemetry.csv';operator_mode='static';adaptive_mode='offline_after_run_only'}
    $resolvedConfig | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $sessionDir 'session_config.json') -Encoding UTF8
    $schedule | Format-Table
    Write-Host 'Absolute shared-memory lap numbers: verify FirstScoredLap before driving. Ctrl+C aborts.'
    $liveArgs = @('scripts/run_lmu_live_cues.py','--plan',(Join-Path $PSScriptRoot 'plan.csv'),'--event-log',(Join-Path $sessionDir 'events.csv'),'--telemetry-log',(Join-Path $sessionDir 'telemetry.csv'),'--run-id',$RunId,'--stop-after-lap',($FirstScoredLap+$ScoredLaps-1),'--cue-laps') + $cueLaps
    if ($EmitSystemBeep) { $liveArgs += '--emit-system-beep' }
    & $python @liveArgs
    if ($LASTEXITCODE -ne 0) { throw 'Live session exited with an error; preserve logs.' }
} finally { Pop-Location }
""".replace("__ROOT__", relative_root)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument(
        "--pack-dir", type=Path, default=DEFAULT_INPUT_DIR / "pilot_pack"
    )
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    result = (
        verify_pack(args.pack_dir)
        if args.verify_only
        else build_pack(args.input_dir, args.pack_dir)
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
