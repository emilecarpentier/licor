from pathlib import Path

import polars as pl

import licor.live.replay_cli as replay_cli


def test_replay_cli_runs_replay_session(tmp_path: Path):
    plan_path = tmp_path / "plan.csv"
    telemetry_path = tmp_path / "telemetry.csv"
    event_log_path = tmp_path / "events.csv"
    accuracy_log_path = tmp_path / "accuracy.csv"
    _plan().write_csv(plan_path)
    _telemetry().write_csv(telemetry_path)

    exit_code = replay_cli.main(
        [
            "--plan",
            str(plan_path),
            "--telemetry",
            str(telemetry_path),
            "--event-log",
            str(event_log_path),
            "--accuracy-log",
            str(accuracy_log_path),
            "--run-id",
            "run_01",
        ]
    )

    assert exit_code == 0
    assert pl.read_csv(event_log_path).height == 1
    assert pl.read_csv(accuracy_log_path).height == 1


def test_replay_cli_supports_bench_beep_only():
    class _RecordingBeepAdapter:
        def __init__(self):
            self.emitted = 0

        def emit(self, cue) -> None:
            del cue
            self.emitted += 1

    adapter = _RecordingBeepAdapter()
    original = replay_cli.SystemBeepAudioCueAdapter
    replay_cli.SystemBeepAudioCueAdapter = lambda **kwargs: adapter
    try:
        assert replay_cli.main(["--bench-beep-only"]) == 0
    finally:
        replay_cli.SystemBeepAudioCueAdapter = original
    assert adapter.emitted == 1


def _plan() -> pl.DataFrame:
    return pl.DataFrame(
        [
            {
                "schema_version": 1,
                "plan_id": "plan_v1",
                "track_name": "Spa-Francorchamps",
                "car_class": "LMP2",
                "race_context_id": "ctx",
                "zone_id": "spa_t01",
                "display_label": "T01",
                "brake_reference_m": 133.0,
                "selected_lico_distance_m": 70.0,
                "planned_lift_start_m": 63.0,
                "cue_distance_m": 63.0,
                "cue_tolerance_m": 5.0,
                "track_length_m": 7000.0,
                "minimum_confidence_label": "experimental_candidate",
                "expected_fuel_saved_l": 0.03,
                "expected_time_lost_s": 0.14,
                "plan_status": "target_met",
                "source_model_status": "model_ready",
                "source_quality_flags": "",
                "strategy_role": "",
                "notes": "",
            }
        ]
    )


def _telemetry() -> pl.DataFrame:
    return pl.DataFrame(
        [
            {"lap_number": 1, "lap_distance_m": 60.0, "ts": 10.0},
            {"lap_number": 1, "lap_distance_m": 64.0, "ts": 10.1},
        ]
    )
