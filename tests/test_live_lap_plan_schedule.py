from types import SimpleNamespace

import polars as pl
import pytest

from licor.live.audio import RecordingAudioCueAdapter
from licor.live import lmu_live_cli
from licor.live.lmu_shared_memory import LmuLiveTelemetrySample
from licor.live.runtime import LiveStaticCueSessionConfig, run_static_live_cue_session


def _plan() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "schema_version": [1, 1],
            "plan_id": ["A", "B"],
            "zone_id": ["t01", "t01"],
            "display_label": ["T1", "T1"],
            "cue_distance_m": [100.0, 150.0],
            "planned_lift_start_m": [120.0, 170.0],
            "cue_tolerance_m": [5.0, 5.0],
            "track_length_m": [1000.0, 1000.0],
            "notes": ["", ""],
        }
    )


class _Source:
    def __init__(self):
        self.closed = False
        self.samples = iter(
            LmuLiveTelemetrySample(lap, distance, float(index), float(index))
            for index, (lap, distance) in enumerate(
                (lap, distance)
                for lap in range(9, 18)
                for distance in (0.0, 99.0, 101.0, 149.0, 151.0)
            )
        )

    def read_next_sample(self, *, timeout_ms):
        del timeout_ms
        return next(self.samples)

    def close(self):
        self.closed = True


def test_two_frozen_plans_execute_p_a_b_p_b_a_p_without_duplicate_beeps(tmp_path):
    plan_path = tmp_path / "plan.csv"
    _plan().write_csv(plan_path)
    audio = RecordingAudioCueAdapter()
    source = _Source()
    events = run_static_live_cue_session(
        plan_path=plan_path,
        event_log_path=tmp_path / "events.csv",
        telemetry_log_path=tmp_path / "telemetry.csv",
        sample_source=source,
        audio_adapter=audio,
        config=LiveStaticCueSessionConfig(
            cue_lap_numbers=(11, 12, 14, 15),
            stop_after_lap_number=16,
            lap_plan_schedule=((11, "A"), (12, "B"), (14, "B"), (15, "A")),
        ),
    )
    assert source.closed
    assert [(cue.lap_number, cue.plan_id) for cue in audio.cues] == [
        (11, "A"),
        (12, "B"),
        (14, "B"),
        (15, "A"),
    ]
    enabled = events.filter(pl.col("cue_enabled"))
    assert enabled.select("lap_number", "plan_id", "cue_trigger_m").rows() == [
        (11, "A", 100.0),
        (12, "B", 150.0),
        (14, "B", 150.0),
        (15, "A", 100.0),
    ]
    assert events.filter(~pl.col("cue_enabled"))[
        "lap_number"
    ].unique().sort().to_list() == [9, 10, 13, 16]
    assert events.height == 12
    assert pl.read_csv(tmp_path / "telemetry.csv")[
        "lap_number"
    ].unique().sort().to_list() == list(range(9, 18))
    assert pl.read_csv(tmp_path / "events_accuracy.csv").select(
        "plan_id", "cue_count"
    ).rows() == [("A", 2), ("B", 2)]


def test_schedule_without_global_gate_is_silent_on_unmapped_laps(tmp_path):
    path = tmp_path / "plan.csv"
    _plan().write_csv(path)
    audio = RecordingAudioCueAdapter()
    run_static_live_cue_session(
        plan_path=path,
        event_log_path=tmp_path / "events.csv",
        sample_source=_Source(),
        audio_adapter=audio,
        config=LiveStaticCueSessionConfig(
            stop_after_lap_number=16, lap_plan_schedule=((11, "A"),)
        ),
    )
    assert [(cue.lap_number, cue.plan_id) for cue in audio.cues] == [(11, "A")]


@pytest.mark.parametrize(
    ("schedule", "cue_laps", "message"),
    [
        (None, None, "multiple live plans require"),
        ((), None, "must not be empty"),
        (((11, "C"),), None, "unknown plan_id"),
        (((11, "A"), (11, "B")), None, "duplicate lap"),
        (((-1, "A"),), None, "non-negative integer"),
        (((1.5, "A"),), None, "non-negative integer"),
        (((11, "A"),), (11, 12), "enabled cue laps missing"),
    ],
)
def test_invalid_schedule_rejected_before_logs_or_audio(
    tmp_path, schedule, cue_laps, message
):
    path = tmp_path / "plan.csv"
    _plan().write_csv(path)
    audio = RecordingAudioCueAdapter()
    with pytest.raises(ValueError, match=message):
        run_static_live_cue_session(
            plan_path=path,
            event_log_path=tmp_path / "events.csv",
            sample_source=_Source(),
            audio_adapter=audio,
            config=LiveStaticCueSessionConfig(
                lap_plan_schedule=schedule, cue_lap_numbers=cue_laps
            ),
        )
    assert not audio.cues
    assert not (tmp_path / "events.csv").exists()


@pytest.mark.parametrize(
    ("contents", "message"),
    [
        ("lap,plan\n11,A\n", "requires lap_number and plan_id"),
        ("lap_number,plan_id\n11.5,A\n", "integer lap_number"),
        ("lap_number,plan_id\n11,\n", "non-empty plan_id"),
    ],
)
def test_cli_schedule_rejects_invalid_csv(tmp_path, contents, message):
    path = tmp_path / "schedule.csv"
    path.write_text(contents, encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        lmu_live_cli._load_lap_plan_schedule(path)


def test_cli_passes_bom_encoded_absolute_lap_schedule_to_runtime(tmp_path, monkeypatch):
    path = tmp_path / "schedule.csv"
    path.write_text(
        '"lap_number","plan_id"\n"11","A"\n"12","B"\n', encoding="utf-8-sig"
    )
    captured = {}
    monkeypatch.setattr(
        lmu_live_cli,
        "_environment_from_args",
        lambda args: SimpleNamespace(is_ready_for_static_live_cues=True),
    )

    def run(**kwargs):
        captured.update(kwargs)
        return pl.DataFrame()

    monkeypatch.setattr(lmu_live_cli, "run_lmu_static_live_cue_session", run)
    assert (
        lmu_live_cli.main(
            [
                "--plan",
                str(tmp_path / "plan.csv"),
                "--event-log",
                str(tmp_path / "events.csv"),
                "--lap-plan-schedule",
                str(path),
                "--cue-laps",
                "11",
                "12",
            ]
        )
        == 0
    )
    assert captured["config"].lap_plan_schedule == ((11, "A"), (12, "B"))
    assert captured["config"].cue_lap_numbers == (11, 12)
