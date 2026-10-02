"""Prepare four ABAB recovery laps without changing frozen Sebring cue doses."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import tempfile
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "sebring_original", ROOT / "scripts/build_sebring_lico_validation_pack.py"
)
original = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(original)
SOURCE = original.DEFAULT_PACK
DEFAULT = original.TRANSFER / "lico_abab_retry_pack_v1"
PATTERN = ("A", "B", "A", "B")


def launcher(pack_dir: Path) -> str:
    text = (SOURCE / "start_lico_validation.ps1").read_text(encoding="utf-8")
    old_root = Path(os.path.relpath(ROOT, SOURCE)).as_posix()
    new_root = Path(os.path.relpath(ROOT, pack_dir.resolve())).as_posix()
    text = text.replace(old_root, new_root)
    text = text.replace(
        "build_sebring_lico_validation_pack.py", "build_sebring_abab_retry_pack.py"
    )
    text = text.replace("'sebring_lico_'", "'sebring_abab_'")
    text = text.replace("@('push','A','B','push','B','A','push')", "@('A','B','A','B')")
    text = (
        text.replace("$i -lt 7", "$i -lt 4")
        .replace("$FirstScoredLap+6", "$FirstScoredLap+3")
        .replace("$FirstScoredLap + 6", "$FirstScoredLap + 3")
    )
    text = text.replace("scored_laps=7", "scored_laps=4").replace(
        "The 7 scored laps", "The 4 scored laps"
    )
    text = text.replace(
        "Pattern: push / A / B / push / B / A / push.",
        "Pattern: A / B / A / B. No scored push laps.",
    )
    text = text.replace(
        "    $telemetryStartedAt = Get-Date",
        "    Write-Host 'If you abandon the block, press Ctrl+C here to stop listening; preserve the partial run. Do not leave two cue listeners running.'\n    $telemetryStartedAt = Get-Date",
    )
    return text


def preflight(path: Path) -> dict:
    plan = pl.read_csv(path)
    positions = sorted(
        {0.0, *[cue + delta for cue in plan["cue_distance_m"] for delta in (-0.5, 0.5)]}
    )
    samples = [
        original.LmuLiveTelemetrySample(
            lap_number=lap, lap_distance_m=distance, ts=float(i)
        )
        for i, (lap, distance) in enumerate(
            (lap, d) for lap in range(9, 15) for d in positions
        )
    ]
    mapping = tuple((10 + i, original.plan_id(role)) for i, role in enumerate(PATTERN))
    audio = original.RecordingAudioCueAdapter()
    with tempfile.TemporaryDirectory(
        prefix="sebring_abab_", dir=original.TRANSFER
    ) as tmp:
        events = original.run_static_live_cue_session(
            plan_path=path,
            event_log_path=Path(tmp) / "events.csv",
            sample_source=original.SyntheticSource(samples),
            audio_adapter=audio,
            config=original.LiveStaticCueSessionConfig(
                cue_lap_numbers=(10, 11, 12, 13),
                lap_plan_schedule=mapping,
                stop_after_lap_number=13,
            ),
        )
    expected = {(lap, pid, zone) for lap, pid in mapping for zone in original.DOSES}
    if {
        (cue.lap_number, cue.plan_id, cue.zone_id) for cue in audio.cues
    } != expected or len(audio.cues) != 28:
        raise ValueError("ABAB cue schedule failed")
    if events.height != 42 or set(
        events.filter(~pl.col("cue_enabled"))["lap_number"]
    ) != {9}:
        raise ValueError("ABAB silent outlap or stop boundary failed")
    return {
        "scored_laps": 4,
        "pattern": list(PATTERN),
        "cue_count": 28,
        "logged_crossings": events.height,
        "system_audio_emitted": False,
    }


def verify(pack_dir: Path) -> dict:
    manifest = json.loads((pack_dir / "pack_manifest.json").read_text(encoding="utf-8"))
    for group, root in (("sources", ROOT), ("artifacts", pack_dir)):
        for name, digest in manifest[group].items():
            target = (root / name).resolve()
            if (
                not target.is_relative_to(root.resolve())
                or original.sha256(target) != digest
            ):
                raise ValueError(f"{group} hash mismatch: {name}")
    if original.sha256(pack_dir / "plan.csv") != original.sha256(SOURCE / "plan.csv"):
        raise ValueError("Retry must preserve the original frozen cue doses")
    return {
        "pack": str(pack_dir.resolve()),
        "hashes_verified": True,
        "silent_preflight": preflight(pack_dir / "plan.csv"),
    }


def build(pack_dir: Path) -> dict:
    if pack_dir.exists():
        raise FileExistsError(f"Refusing to replace retry pack: {pack_dir}")
    original.verify_pack(SOURCE)
    pack_dir.mkdir(parents=True)
    for path in SOURCE.iterdir():
        if path.is_file():
            (pack_dir / path.name).write_bytes(path.read_bytes())
    (pack_dir / "original_plan_manifest.json").write_bytes(
        (SOURCE / "plan_manifest.json").read_bytes()
    )
    (pack_dir / "original_pack_manifest.json").write_bytes(
        (SOURCE / "pack_manifest.json").read_bytes()
    )
    original_meta = json.loads(
        (SOURCE / "plan_manifest.json").read_text(encoding="utf-8")
    )
    manifest = {
        "protocol_id": "sebring_abab_retry_v1",
        "pattern": list(PATTERN),
        "expected_beeps": 28,
        "unchanged_source_plan_sha256": original.sha256(SOURCE / "plan.csv"),
        "previous_attempt": "sebring_lico_20260912_132042",
        "previous_attempt_driver_review": "LICO laps imperfect; last push abandoned after T1 error",
        "evaluation_role": "repeat_execution_and_driver_familiarisation; not the original held-out schedule",
        "same_session_push_controls": False,
        "refit_performed": False,
        "plan_totals": original_meta["plan_totals"],
        "limitations": "Use prior push references with session/fuel/driver-learning caveats. Keep partial first attempt and localized errors separate. No new local-budget split declared after seeing outcomes.",
    }
    (pack_dir / "plan_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    metadata = json.loads(
        (SOURCE / "run_metadata_template.json").read_text(encoding="utf-8")
    )
    metadata.update(
        collection_protocol_id="sebring_abab_retry_v1",
        collection_session_id="abab_retry_01",
        lap_pattern=list(PATTERN),
        run_id="",
        status="prepared_not_run",
        driver_notes="Four ABAB repeat-execution laps requested after imperfect first attempt; no scored push controls.",
    )
    (pack_dir / "run_metadata_template.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )
    pl.DataFrame(
        [
            {
                "relative_lap": i,
                "role": role,
                "driver_lap_label": "",
                "errors_by_turn_phase": "",
                "beeps_heard": "",
            }
            for i, role in enumerate(PATTERN, 1)
        ]
    ).write_csv(pack_dir / "lap_notes_template.csv")
    (pack_dir / "start_lico_validation.ps1").write_text(
        launcher(pack_dir), encoding="utf-8"
    )
    (pack_dir / "README.md").write_bytes(
        (ROOT / "docs/sebring_abab_retry_run_sheet.md").read_bytes()
    )
    (pack_dir / "retry_preflight.json").write_text(
        json.dumps(preflight(pack_dir / "plan.csv"), indent=2), encoding="utf-8"
    )
    sources = dict(
        json.loads((SOURCE / "pack_manifest.json").read_text(encoding="utf-8"))[
            "sources"
        ]
    )
    for path in (
        Path(__file__).resolve(),
        ROOT / "docs/sebring_abab_retry_run_sheet.md",
        SOURCE / "plan.csv",
        SOURCE / "pack_manifest.json",
    ):
        sources[path.relative_to(ROOT).as_posix()] = original.sha256(path)
    payload = {
        "sources": sources,
        "artifacts": {
            p.name: original.sha256(p)
            for p in pack_dir.iterdir()
            if p.is_file() and p.name != "pack_manifest.json"
        },
    }
    (pack_dir / "pack_manifest.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )
    return verify(pack_dir)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack-dir", type=Path, default=DEFAULT)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            verify(args.pack_dir) if args.verify_only else build(args.pack_dir),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
