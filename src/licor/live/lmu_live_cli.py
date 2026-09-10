from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from licor.live.audio import AudioCue, NullAudioCueAdapter, SystemBeepAudioCueAdapter
from licor.live.lmu_shared_memory import (
    LMUSharedMemoryReader,
    LmuLiveEnvironment,
    inspect_default_lmu_live_environment,
    inspect_lmu_live_environment,
    probe_lmu_shared_memory_available,
)
from licor.live.runtime import (
    LiveStaticCueSessionConfig,
    run_lmu_static_live_cue_session,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.bench_beep_only:
        SystemBeepAudioCueAdapter(blocking=True).emit(
            AudioCue(
                plan_id="bench_beep",
                zone_id="bench",
                display_label="Bench",
                lap_number=0,
                trigger_status="fired_on_time",
                audio_cue_kind=args.audio_cue_kind,
            )
        )
        print("Bench beep emitted.")
        return 0

    environment = _environment_from_args(args)
    if args.doctor:
        _print_environment(environment)
        available, message = probe_lmu_shared_memory_available()
        print(f"shared_memory_probe={available} message={message}")
        return 0 if environment.is_ready_for_static_live_cues else 1

    if not environment.is_ready_for_static_live_cues:
        _print_environment(environment)
        raise SystemExit("LMU live environment is not ready. Run with --doctor first.")

    if args.show_current_lap:
        reader = LMUSharedMemoryReader()
        try:
            sample = reader.read_next_player_sample(timeout_ms=5000)
        finally:
            reader.close()
        if sample is None:
            print(
                "No player sample available. Enter the car and retry; no audio emitted."
            )
            return 1
        print(
            f"absolute_lap_number={sample.lap_number} lap_distance_m={sample.lap_distance_m:.3f}"
        )
        print(
            "If the next start/finish crossing starts your first scored lap, use current lap + 1."
        )
        return 0

    if not args.plan or not args.event_log:
        raise SystemExit(
            "--plan and --event-log are required unless --doctor or --bench-beep-only is used."
        )

    audio_adapter = (
        SystemBeepAudioCueAdapter() if args.emit_system_beep else NullAudioCueAdapter()
    )
    events = run_lmu_static_live_cue_session(
        plan_path=args.plan,
        event_log_path=args.event_log,
        accuracy_log_path=args.accuracy_log,
        telemetry_log_path=args.telemetry_log,
        audio_adapter=audio_adapter,
        config=LiveStaticCueSessionConfig(
            run_id=args.run_id,
            file_name=args.file_name or Path(args.event_log).name,
            audio_cue_kind=args.audio_cue_kind,
            track_length_m=args.track_length_m,
            default_cue_tolerance_m=args.default_cue_tolerance_m,
            max_initial_late_distance_m=args.max_initial_late_distance_m,
            overwrite_existing_logs=args.overwrite_existing_logs,
            write_accuracy_log=not args.no_accuracy_log,
            update_timeout_ms=args.update_timeout_ms,
            max_laps=args.max_laps,
            max_events=args.max_events,
            cue_lap_numbers=None if args.cue_laps is None else tuple(args.cue_laps),
            stop_after_lap_number=args.stop_after_lap,
        ),
    )
    print(f"Wrote {events.height} live cue events to {Path(args.event_log)}")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run LICOR static live cues against LMU shared memory."
    )
    parser.add_argument("--doctor", action="store_true")
    parser.add_argument(
        "--show-current-lap",
        action="store_true",
        help="Read one player sample (5 s maximum wait), report absolute lap/distance, then exit without audio.",
    )
    parser.add_argument("--bench-beep-only", action="store_true")
    parser.add_argument("--plan")
    parser.add_argument("--event-log")
    parser.add_argument("--accuracy-log")
    parser.add_argument(
        "--telemetry-log",
        help="Stream all live samples, including muted push laps, to CSV.",
    )
    parser.add_argument("--run-id", default="")
    parser.add_argument("--file-name", default="")
    parser.add_argument("--audio-cue-kind", default="beep")
    parser.add_argument("--track-length-m", type=float)
    parser.add_argument("--default-cue-tolerance-m", type=float, default=5.0)
    parser.add_argument("--max-initial-late-distance-m", type=float, default=30.0)
    parser.add_argument("--emit-system-beep", action="store_true")
    parser.add_argument("--overwrite-existing-logs", action="store_true")
    parser.add_argument("--no-accuracy-log", action="store_true")
    parser.add_argument("--update-timeout-ms", type=int, default=250)
    parser.add_argument("--max-laps", type=int)
    parser.add_argument("--max-events", type=int)
    parser.add_argument(
        "--cue-laps",
        type=int,
        nargs="+",
        help="Absolute LMU lap numbers with audio enabled; other laps remain logged silently.",
    )
    parser.add_argument(
        "--stop-after-lap",
        type=int,
        help="Stop on entering the lap after this absolute LMU lap number.",
    )
    parser.add_argument("--install-root")
    parser.add_argument("--settings-path")
    return parser


def _environment_from_args(args: argparse.Namespace) -> LmuLiveEnvironment:
    if args.install_root or args.settings_path:
        install_root = args.install_root or str(
            Path(r"C:\Program Files (x86)\Steam\steamapps\common\Le Mans Ultimate")
        )
        return inspect_lmu_live_environment(
            install_root=install_root,
            settings_path=args.settings_path,
        )
    return inspect_default_lmu_live_environment()


def _print_environment(environment: LmuLiveEnvironment) -> None:
    print(f"install_root={environment.install_root}")
    print(f"settings_path={environment.settings_path}")
    print(f"shared_memory_support_dir={environment.shared_memory_support_dir}")
    print(f"shared_memory_header_path={environment.shared_memory_header_path}")
    print(f"external_plugins_enabled={environment.external_plugins_enabled}")
    print(f"webui_bind={environment.webui_bind}")
    print(f"webui_port={environment.webui_port}")
    print(
        f"status_flags={','.join(environment.status_flags) if environment.status_flags else 'ok'}"
    )
