from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import polars as pl

from licor.analysis import (
    LiveCueRunnerConfig,
    load_live_cue_plan,
    simulate_live_cue_events,
    summarize_live_cue_event_accuracy,
)
from licor.live.audio import AudioCue, AudioCueAdapter, NullAudioCueAdapter


@dataclass(frozen=True)
class ReplayLiveCueSessionConfig:
    run_id: str = ""
    file_name: str = ""
    audio_cue_kind: str = "beep"
    track_length_m: float | None = None
    default_cue_tolerance_m: float = 5.0
    max_initial_late_distance_m: float = 30.0
    write_accuracy_log: bool = True
    overwrite_existing_logs: bool = False


def run_replay_live_cue_session(
    *,
    plan_path: str | Path,
    telemetry_path: str | Path,
    event_log_path: str | Path,
    accuracy_log_path: str | Path | None = None,
    audio_adapter: AudioCueAdapter | None = None,
    config: ReplayLiveCueSessionConfig | None = None,
) -> pl.DataFrame:
    """Replay telemetry samples through the live cue runner and write event logs."""

    replay_config = config or ReplayLiveCueSessionConfig()
    plan = load_live_cue_plan(plan_path)
    telemetry = pl.read_csv(telemetry_path)
    events = simulate_live_cue_events(
        plan,
        telemetry,
        config=LiveCueRunnerConfig(
            run_id=replay_config.run_id,
            file_name=replay_config.file_name or Path(telemetry_path).name,
            audio_cue_kind=replay_config.audio_cue_kind,
            track_length_m=replay_config.track_length_m,
            default_cue_tolerance_m=replay_config.default_cue_tolerance_m,
            max_initial_late_distance_m=replay_config.max_initial_late_distance_m,
        ),
    )
    _write_csv(
        events,
        event_log_path,
        overwrite_existing=replay_config.overwrite_existing_logs,
    )
    if replay_config.write_accuracy_log:
        accuracy_path = accuracy_log_path or _default_accuracy_log_path(event_log_path)
        _write_csv(
            summarize_live_cue_event_accuracy(events),
            accuracy_path,
            overwrite_existing=replay_config.overwrite_existing_logs,
        )
    _emit_audio_events(events, audio_adapter or NullAudioCueAdapter())
    return events


def _emit_audio_events(events: pl.DataFrame, audio_adapter: AudioCueAdapter) -> None:
    for row in events.iter_rows(named=True):
        audio_adapter.emit(
            AudioCue(
                plan_id=str(row["plan_id"]),
                zone_id=str(row["zone_id"]),
                display_label=str(row["display_label"]),
                lap_number=int(row["lap_number"]),
                trigger_status=str(row["trigger_status"]),
                audio_cue_kind=str(row["audio_cue_kind"]),
            )
        )


def _write_csv(
    frame: pl.DataFrame,
    path: str | Path,
    *,
    overwrite_existing: bool,
) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists() and not overwrite_existing:
        raise FileExistsError(f"refusing to overwrite existing log: {output_path}")
    frame.write_csv(output_path)
    return output_path


def _default_accuracy_log_path(event_log_path: str | Path) -> Path:
    path = Path(event_log_path)
    return path.with_name(f"{path.stem}_accuracy{path.suffix}")
