from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from licor.live.audio import AudioCue, NullAudioCueAdapter, SystemBeepAudioCueAdapter
from licor.live.replay import ReplayLiveCueSessionConfig, run_replay_live_cue_session


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

    audio_adapter = (
        SystemBeepAudioCueAdapter() if args.emit_system_beep else NullAudioCueAdapter()
    )
    events = run_replay_live_cue_session(
        plan_path=args.plan,
        telemetry_path=args.telemetry,
        event_log_path=args.event_log,
        accuracy_log_path=args.accuracy_log,
        audio_adapter=audio_adapter,
        config=ReplayLiveCueSessionConfig(
            run_id=args.run_id,
            file_name=args.file_name,
            audio_cue_kind=args.audio_cue_kind,
            track_length_m=args.track_length_m,
            default_cue_tolerance_m=args.default_cue_tolerance_m,
            max_initial_late_distance_m=args.max_initial_late_distance_m,
            write_accuracy_log=not args.no_accuracy_log,
            overwrite_existing_logs=args.overwrite_existing_logs,
        ),
    )
    print(f"Wrote {events.height} cue events to {Path(args.event_log)}")
    if not args.no_accuracy_log:
        accuracy_path = (
            Path(args.accuracy_log)
            if args.accuracy_log
            else Path(args.event_log).with_name(
                f"{Path(args.event_log).stem}_accuracy{Path(args.event_log).suffix}"
            )
        )
        print(f"Wrote accuracy log to {accuracy_path}")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Replay a live cue plan against telemetry samples or emit a bench beep."
    )
    parser.add_argument("--bench-beep-only", action="store_true")
    parser.add_argument("--plan")
    parser.add_argument("--telemetry")
    parser.add_argument("--event-log")
    parser.add_argument("--accuracy-log")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--file-name", default="")
    parser.add_argument("--audio-cue-kind", default="beep")
    parser.add_argument("--track-length-m", type=float)
    parser.add_argument("--default-cue-tolerance-m", type=float, default=5.0)
    parser.add_argument("--max-initial-late-distance-m", type=float, default=30.0)
    parser.add_argument("--emit-system-beep", action="store_true")
    parser.add_argument("--overwrite-existing-logs", action="store_true")
    parser.add_argument("--no-accuracy-log", action="store_true")
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
