from pathlib import Path

import polars as pl
import pytest

from licor.live import RecordingAudioCueAdapter
from licor.live.lmu_shared_memory import LmuLiveTelemetrySample
from licor.live.runtime import LiveStaticCueSessionConfig, run_static_live_cue_session


def test_static_live_session_writes_logs_and_emits_audio(tmp_path: Path):
    plan_path = tmp_path / "plan.csv"
    event_log_path = tmp_path / "events.csv"
    accuracy_log_path = tmp_path / "accuracy.csv"
    _plan().write_csv(plan_path)
    audio = RecordingAudioCueAdapter()

    events = run_static_live_cue_session(
        plan_path=plan_path,
        event_log_path=event_log_path,
        accuracy_log_path=accuracy_log_path,
        sample_source=_ListSampleSource(
            [
                _sample(lap=1, lap_dist=345.0, ts=10.0),
                _sample(lap=1, lap_dist=352.0, ts=10.2),
                _sample(lap=1, lap_dist=6990.0, ts=120.0),
                _sample(lap=1, lap_dist=20.0, ts=120.2),
            ]
        ),
        audio_adapter=audio,
        config=LiveStaticCueSessionConfig(
            run_id="run_01",
            file_name="live_session",
            audio_cue_kind="short_beep",
            max_laps=1,
        ),
    )

    assert events.select("zone_id", "trigger_status").rows() == [
        ("t01", "fired_on_time"),
        ("start", "fired_late"),
    ]
    assert pl.read_csv(event_log_path).height == 2
    assert pl.read_csv(accuracy_log_path).select("zone_id", "cue_count").rows() == [
        ("start", 1),
        ("t01", 1),
    ]
    assert [(cue.zone_id, cue.audio_cue_kind) for cue in audio.cues] == [
        ("t01", "short_beep"),
        ("start", "short_beep"),
    ]


def test_static_live_session_writes_logs_before_audio_failure(tmp_path: Path):
    plan_path = tmp_path / "plan.csv"
    event_log_path = tmp_path / "events.csv"
    _plan().filter(pl.col("zone_id") == "t01").write_csv(plan_path)

    with pytest.raises(RuntimeError, match="audio failed"):
        run_static_live_cue_session(
            plan_path=plan_path,
            event_log_path=event_log_path,
            sample_source=_ListSampleSource(
                [
                    _sample(lap=1, lap_dist=345.0, ts=10.0),
                    _sample(lap=1, lap_dist=352.0, ts=10.2),
                ]
            ),
            audio_adapter=_FailingAudioCueAdapter(),
            config=LiveStaticCueSessionConfig(max_laps=1, write_accuracy_log=False),
        )

    assert pl.read_csv(event_log_path).height == 1


def test_static_live_session_refuses_to_overwrite_existing_logs(tmp_path: Path):
    plan_path = tmp_path / "plan.csv"
    event_log_path = tmp_path / "events.csv"
    _plan().filter(pl.col("zone_id") == "t01").write_csv(plan_path)
    event_log_path.write_text("existing", encoding="utf-8")

    with pytest.raises(FileExistsError, match="refusing to overwrite existing log"):
        run_static_live_cue_session(
            plan_path=plan_path,
            event_log_path=event_log_path,
            sample_source=_ListSampleSource([_sample(lap=1, lap_dist=351.0, ts=10.0)]),
            config=LiveStaticCueSessionConfig(write_accuracy_log=False),
        )


def _plan() -> pl.DataFrame:
    return pl.DataFrame(
        [
            {
                "schema_version": 1,
                "plan_id": "plan_v1",
                "zone_id": "t01",
                "display_label": "T01",
                "cue_distance_m": 350.0,
                "planned_lift_start_m": 350.0,
                "cue_tolerance_m": 5.0,
                "track_length_m": 7000.0,
                "notes": "",
            },
            {
                "schema_version": 1,
                "plan_id": "plan_v1",
                "zone_id": "start",
                "display_label": "Start",
                "cue_distance_m": 10.0,
                "planned_lift_start_m": 10.0,
                "cue_tolerance_m": 5.0,
                "track_length_m": 7000.0,
                "notes": "",
            },
        ]
    )


def _sample(*, lap: int, lap_dist: float, ts: float) -> LmuLiveTelemetrySample:
    return LmuLiveTelemetrySample(
        lap_number=lap,
        lap_distance_m=lap_dist,
        ts=ts,
        elapsed_s=ts,
    )


class _ListSampleSource:
    def __init__(self, samples: list[LmuLiveTelemetrySample]) -> None:
        self._samples = list(samples)
        self.closed = False

    def read_next_sample(self, *, timeout_ms: int) -> LmuLiveTelemetrySample | None:
        del timeout_ms
        if not self._samples:
            raise KeyboardInterrupt
        return self._samples.pop(0)

    def close(self) -> None:
        self.closed = True


class _FailingAudioCueAdapter:
    def emit(self, cue) -> None:
        del cue
        raise RuntimeError("audio failed")
