from pathlib import Path

import polars as pl
import pytest

from licor.live import (
    RecordingAudioCueAdapter,
    ReplayLiveCueSessionConfig,
    run_replay_live_cue_session,
)


def test_replay_session_writes_event_and_accuracy_logs(tmp_path: Path):
    plan_path = tmp_path / "plan.csv"
    telemetry_path = tmp_path / "telemetry.csv"
    event_log_path = tmp_path / "logs" / "events.csv"
    accuracy_log_path = tmp_path / "logs" / "accuracy.csv"
    _plan().write_csv(plan_path)
    _telemetry().write_csv(telemetry_path)
    audio = RecordingAudioCueAdapter()

    events = run_replay_live_cue_session(
        plan_path=plan_path,
        telemetry_path=telemetry_path,
        event_log_path=event_log_path,
        accuracy_log_path=accuracy_log_path,
        audio_adapter=audio,
        config=ReplayLiveCueSessionConfig(
            run_id="run_01",
            file_name="telemetry.csv",
            audio_cue_kind="short_beep",
        ),
    )

    written_events = pl.read_csv(event_log_path)
    written_accuracy = pl.read_csv(accuracy_log_path)
    assert events.select("zone_id", "trigger_status").rows() == [
        ("t01", "fired_on_time"),
        ("start", "fired_late"),
    ]
    assert written_events.select("run_id", "file_name", "audio_cue_kind").rows() == [
        ("run_01", "telemetry.csv", "short_beep"),
        ("run_01", "telemetry.csv", "short_beep"),
    ]
    assert written_accuracy.select("zone_id", "cue_count").rows() == [
        ("start", 1),
        ("t01", 1),
    ]
    assert [(cue.zone_id, cue.audio_cue_kind) for cue in audio.cues] == [
        ("t01", "short_beep"),
        ("start", "short_beep"),
    ]


def test_replay_session_writes_logs_before_audio_emit(tmp_path: Path):
    plan_path = tmp_path / "plan.csv"
    telemetry_path = tmp_path / "telemetry.csv"
    event_log_path = tmp_path / "events.csv"
    accuracy_log_path = tmp_path / "accuracy.csv"
    _plan().filter(pl.col("zone_id") == "t01").write_csv(plan_path)
    _telemetry().write_csv(telemetry_path)
    audio = _FailingAudioCueAdapter()

    with pytest.raises(RuntimeError, match="audio failed"):
        run_replay_live_cue_session(
            plan_path=plan_path,
            telemetry_path=telemetry_path,
            event_log_path=event_log_path,
            accuracy_log_path=accuracy_log_path,
            audio_adapter=audio,
        )

    assert event_log_path.exists()
    assert accuracy_log_path.exists()
    assert pl.read_csv(event_log_path).height == 1


def test_replay_session_uses_default_accuracy_log_path(tmp_path: Path):
    plan_path = tmp_path / "plan.csv"
    telemetry_path = tmp_path / "telemetry.csv"
    event_log_path = tmp_path / "events.csv"
    _plan().filter(pl.col("zone_id") == "t01").write_csv(plan_path)
    _telemetry().write_csv(telemetry_path)

    run_replay_live_cue_session(
        plan_path=plan_path,
        telemetry_path=telemetry_path,
        event_log_path=event_log_path,
    )

    assert event_log_path.exists()
    assert (tmp_path / "events_accuracy.csv").exists()


def test_replay_session_writes_empty_logs_and_does_not_emit_audio(tmp_path: Path):
    plan_path = tmp_path / "plan.csv"
    telemetry_path = tmp_path / "telemetry.csv"
    event_log_path = tmp_path / "events.csv"
    accuracy_log_path = tmp_path / "accuracy.csv"
    _plan().write_csv(plan_path)
    pl.DataFrame(schema={"lap_number": pl.Int64, "lap_distance_m": pl.Float64, "ts": pl.Float64}).write_csv(
        telemetry_path
    )
    audio = RecordingAudioCueAdapter()

    events = run_replay_live_cue_session(
        plan_path=plan_path,
        telemetry_path=telemetry_path,
        event_log_path=event_log_path,
        accuracy_log_path=accuracy_log_path,
        audio_adapter=audio,
    )

    assert events.is_empty()
    assert pl.read_csv(event_log_path).is_empty()
    assert pl.read_csv(accuracy_log_path).is_empty()
    assert audio.cues == []


def test_replay_session_rejects_invalid_telemetry_csv(tmp_path: Path):
    plan_path = tmp_path / "plan.csv"
    telemetry_path = tmp_path / "telemetry.csv"
    event_log_path = tmp_path / "events.csv"
    _plan().write_csv(plan_path)
    pl.DataFrame([{"lap_number": 1, "ts": 1.0}]).write_csv(telemetry_path)

    with pytest.raises(ValueError, match="telemetry samples are missing required columns"):
        run_replay_live_cue_session(
            plan_path=plan_path,
            telemetry_path=telemetry_path,
            event_log_path=event_log_path,
        )

    assert not event_log_path.exists()


def test_replay_session_rejects_empty_invalid_telemetry_csv(tmp_path: Path):
    plan_path = tmp_path / "plan.csv"
    telemetry_path = tmp_path / "telemetry.csv"
    event_log_path = tmp_path / "events.csv"
    _plan().write_csv(plan_path)
    pl.DataFrame(schema={"lap_number": pl.Int64, "ts": pl.Float64}).write_csv(
        telemetry_path
    )

    with pytest.raises(ValueError, match="telemetry samples are missing required columns"):
        run_replay_live_cue_session(
            plan_path=plan_path,
            telemetry_path=telemetry_path,
            event_log_path=event_log_path,
        )

    assert not event_log_path.exists()


def test_replay_session_rejects_invalid_plan_csv(tmp_path: Path):
    plan_path = tmp_path / "plan.csv"
    telemetry_path = tmp_path / "telemetry.csv"
    event_log_path = tmp_path / "events.csv"
    _plan().with_columns(pl.lit(-1.0).alias("cue_tolerance_m")).write_csv(plan_path)
    _telemetry().write_csv(telemetry_path)

    with pytest.raises(ValueError, match="cue_tolerance_m values must be positive"):
        run_replay_live_cue_session(
            plan_path=plan_path,
            telemetry_path=telemetry_path,
            event_log_path=event_log_path,
        )

    assert not event_log_path.exists()


def test_replay_session_refuses_to_overwrite_existing_logs(tmp_path: Path):
    plan_path = tmp_path / "plan.csv"
    telemetry_path = tmp_path / "telemetry.csv"
    event_log_path = tmp_path / "events.csv"
    _plan().filter(pl.col("zone_id") == "t01").write_csv(plan_path)
    _telemetry().write_csv(telemetry_path)
    event_log_path.write_text("existing", encoding="utf-8")

    with pytest.raises(FileExistsError, match="refusing to overwrite existing log"):
        run_replay_live_cue_session(
            plan_path=plan_path,
            telemetry_path=telemetry_path,
            event_log_path=event_log_path,
            config=ReplayLiveCueSessionConfig(write_accuracy_log=False),
        )


def test_replay_session_can_overwrite_existing_logs_when_explicit(tmp_path: Path):
    plan_path = tmp_path / "plan.csv"
    telemetry_path = tmp_path / "telemetry.csv"
    event_log_path = tmp_path / "events.csv"
    _plan().filter(pl.col("zone_id") == "t01").write_csv(plan_path)
    _telemetry().write_csv(telemetry_path)
    event_log_path.write_text("existing", encoding="utf-8")

    run_replay_live_cue_session(
        plan_path=plan_path,
        telemetry_path=telemetry_path,
        event_log_path=event_log_path,
        config=ReplayLiveCueSessionConfig(
            write_accuracy_log=False,
            overwrite_existing_logs=True,
        ),
    )

    assert pl.read_csv(event_log_path).height == 1


def _plan() -> pl.DataFrame:
    return pl.DataFrame(
        [
            _cue("t01", "T01", cue_m=350.0, tolerance_m=5.0),
            _cue("start", "Start", cue_m=10.0, tolerance_m=5.0),
        ]
    )


def _cue(
    zone_id: str,
    display_label: str,
    *,
    cue_m: float,
    tolerance_m: float,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "plan_id": "plan_v1",
        "zone_id": zone_id,
        "display_label": display_label,
        "cue_distance_m": cue_m,
        "planned_lift_start_m": cue_m,
        "cue_tolerance_m": tolerance_m,
        "track_length_m": 7000.0,
        "notes": "",
    }


def _telemetry() -> pl.DataFrame:
    return pl.DataFrame(
        [
            {"lap_number": 1, "lap_distance_m": 345.0, "ts": 10.0},
            {"lap_number": 1, "lap_distance_m": 352.0, "ts": 10.2},
            {"lap_number": 1, "lap_distance_m": 6990.0, "ts": 120.0},
            {"lap_number": 1, "lap_distance_m": 20.0, "ts": 120.2},
        ]
    )


class _FailingAudioCueAdapter:
    def emit(self, cue) -> None:
        del cue
        raise RuntimeError("audio failed")
