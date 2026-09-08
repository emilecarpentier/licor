"""Replay recorded Paul telemetry through the live runtime, with audio recorded silently."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

import polars as pl

from licor.analysis.zone_detection import build_lap_telemetry
from licor.ingestion import LmuTelemetryDatabase
from licor.live.audio import RecordingAudioCueAdapter
from licor.live.lmu_shared_memory import LmuLiveTelemetrySample
from licor.live.runtime import LiveStaticCueSessionConfig, run_static_live_cue_session


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).with_name(name + ".py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_intake = _load_script("build_paul_ricard_intake")
_pack = _load_script("build_paul_ricard_pilot_pack")
PROJECT_ROOT = _intake.PROJECT_ROOT
_sha256 = _intake._sha256
DEFAULT_INPUT_DIR = _pack.DEFAULT_INPUT_DIR
lap_schedule = _pack.lap_schedule
verify_pack = _pack.verify_pack

RAW_FILE = (
    PROJECT_ROOT
    / "data/Paul Ricard Circuit_P_2026-06-01T23_09_07Z_controlled_random_01.duckdb"
)


def load_raw_replay_samples(
    raw_file: Path,
) -> tuple[list[LmuLiveTelemetrySample], dict]:
    """Use normalized completed laps plus a real sample after the last Lap event."""
    with LmuTelemetryDatabase(raw_file) as telemetry:
        samples = build_lap_telemetry(telemetry, lap_numbers=set(range(8)))
        if set(samples["lap_number"].to_list()) != set(range(8)):
            raise ValueError("Replay requires raw completed laps 0 through 7")
        lap_event = telemetry.event_series("Lap").tail(1).row(0, named=True)
        if lap_event["value"] != 8:
            raise ValueError(
                "Replay requires the recorded lap8 transition for termination"
            )
        terminal = (
            telemetry.fixed_channel("Brake Pos")
            .filter(pl.col("ts") >= lap_event["ts"])
            .head(1)
            .select("ts", pl.col("value").alias("brake_pct"))
        )
        for channel, column in (
            ("Lap Dist", "lap_distance_m"),
            ("Ground Speed", "ground_speed_kph"),
            ("Throttle Pos", "throttle_pct"),
            ("Fuel Level", "fuel_level_l"),
        ):
            terminal = terminal.join_asof(
                telemetry.fixed_channel(channel).select(
                    "ts", pl.col("value").alias(column)
                ),
                on="ts",
                strategy="backward",
            )
        if terminal.is_empty() or terminal.null_count().sum_horizontal()[0]:
            raise ValueError(
                "No real complete telemetry sample after the lap8 transition"
            )
        terminal = terminal.with_columns(pl.lit(8).alias("lap_number"))
        normalized = pl.concat(
            [
                samples.select(*terminal.columns),
                terminal,
            ]
        ).sort("ts")
        session_start = telemetry.session_start_ts()
    result = [
        LmuLiveTelemetrySample(
            lap_number=int(row["lap_number"]),
            lap_distance_m=float(row["lap_distance_m"]),
            ts=float(row["ts"]),
            elapsed_s=float(row["ts"]) - session_start,
            fuel_level_l=float(row["fuel_level_l"]),
            speed_kph=float(row["ground_speed_kph"]),
            throttle_pct=float(row["throttle_pct"]),
            brake_pct=float(row["brake_pct"]),
        )
        for row in normalized.iter_rows(named=True)
    ]
    return result, {
        "sample_count": len(result),
        "complete_laps": list(range(8)),
        "termination_lap_event_ts": lap_event["ts"],
        "termination_actual_sample_ts": result[-1].ts,
        "termination_actual_sample_distance_m": result[-1].lap_distance_m,
        "alignment": "Existing Brake Pos timeline, backward as-of alignment; no synthetic crossing or termination sample.",
    }


class RecordedSampleSource:
    def __init__(self, samples: list[LmuLiveTelemetrySample]):
        self.samples = iter(samples)
        self.closed = False

    def read_next_sample(self, *, timeout_ms: int) -> LmuLiveTelemetrySample:
        del timeout_ms
        try:
            return next(self.samples)
        except StopIteration:
            raise AssertionError(
                "Runtime exhausted recorded samples without stopping at real lap8"
            ) from None

    def close(self) -> None:
        self.closed = True


def verify_recorded_replay(
    *,
    pack_dir: Path = DEFAULT_INPUT_DIR / "pilot_pack",
    output_dir: Path = DEFAULT_INPUT_DIR / "replay_checks",
) -> dict:
    verify_pack(pack_dir)
    if output_dir.exists():
        raise FileExistsError(f"Replay check directory already exists: {output_dir}")
    samples, raw_summary = load_raw_replay_samples(RAW_FILE)
    plan = pl.read_csv(pack_dir / "plan.csv")
    enabled_laps = tuple(
        int(row["lap_number"]) for row in lap_schedule(7, 1) if row["cue_enabled"]
    )
    source = RecordedSampleSource(samples)
    audio = RecordingAudioCueAdapter()
    output_dir.mkdir(parents=True)
    event_path = output_dir / "real_replay_events.csv"
    events = run_static_live_cue_session(
        plan_path=pack_dir / "plan.csv",
        event_log_path=event_path,
        accuracy_log_path=output_dir / "real_replay_accuracy.csv",
        sample_source=source,
        audio_adapter=audio,
        config=LiveStaticCueSessionConfig(
            cue_lap_numbers=enabled_laps,
            stop_after_lap_number=7,
            run_id="paul_ricard_recorded_runtime_replay_check",
            file_name=RAW_FILE.name,
        ),
    )
    expected_crossings = {(lap, zone) for lap in range(8) for zone in plan["zone_id"]}
    expected_audio = {(lap, zone) for lap in enabled_laps for zone in plan["zone_id"]}
    actual_crossings = events.select("lap_number", "zone_id").rows()
    actual_audio = [(cue.lap_number, cue.zone_id) for cue in audio.cues]
    if (
        len(actual_crossings) != len(expected_crossings)
        or set(actual_crossings) != expected_crossings
    ):
        raise AssertionError("Recorded replay has missing or duplicate crossings")
    if len(actual_audio) != len(expected_audio) or set(actual_audio) != expected_audio:
        raise AssertionError(
            "Recorded replay audio gate emitted wrong or duplicate cues"
        )
    if (
        set(events.filter(pl.col("cue_enabled")).select("lap_number", "zone_id").rows())
        != expected_audio
    ):
        raise AssertionError("Enabled event log differs from recorded audio calls")
    if not source.closed:
        raise AssertionError("Recorded sample source was not closed")
    manifest = {
        "schema_version": 1,
        "check_status": "passed",
        "validation_scope": "Software distance-crossing, lap gating, deduplication and termination on recorded telemetry. Historical driving did not execute this plan; no fuel/time efficacy or audible human-response validation.",
        "raw_source": {
            "path": RAW_FILE.relative_to(PROJECT_ROOT).as_posix(),
            "sha256": _sha256(RAW_FILE),
        },
        "pack_manifest_sha256": _sha256(pack_dir / "pack_manifest.json"),
        "pack_plan_sha256": _sha256(pack_dir / "plan.csv"),
        "runtime_sha256": _sha256(PROJECT_ROOT / "src/licor/live/runtime.py"),
        "replay_script_sha256": _sha256(Path(__file__)),
        "raw_sample_summary": raw_summary,
        "enabled_laps": list(enabled_laps),
        "muted_laps": [0, 1, 4, 7],
        "zone_count": plan.height,
        "logged_crossings": events.height,
        "recorded_audio_calls": len(actual_audio),
        "enabled_cue_max_abs_error_m": events.filter(pl.col("cue_enabled"))[
            "cue_error_m"
        ]
        .abs()
        .max(),
        "artifacts": {
            path.name: _sha256(path) for path in output_dir.iterdir() if path.is_file()
        },
    }
    (output_dir / "replay_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pack-dir", type=Path, default=DEFAULT_INPUT_DIR / "pilot_pack"
    )
    parser.add_argument(
        "--output-dir", type=Path, default=DEFAULT_INPUT_DIR / "replay_checks"
    )
    args = parser.parse_args()
    print(
        json.dumps(
            verify_recorded_replay(pack_dir=args.pack_dir, output_dir=args.output_dir),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
