from pathlib import Path

import polars as pl
import pytest

from licor.analysis import (
    LiveCueRunnerConfig,
    load_live_cue_plan,
    simulate_live_cue_events,
    summarize_live_cue_event_accuracy,
    validate_live_cue_plan,
)


def test_loads_live_cue_plan_csv(tmp_path: Path):
    path = tmp_path / "plan.csv"
    _plan().write_csv(path)

    loaded = load_live_cue_plan(path)

    assert loaded.select("plan_id", "zone_id", "cue_distance_m").rows() == [
        ("plan_v1", "t01", 350.0),
        ("plan_v1", "final", 6970.0),
        ("plan_v1", "start", 10.0),
    ]


def test_triggers_cue_when_distance_crosses_without_exact_sample():
    events = simulate_live_cue_events(
        _plan().filter(pl.col("zone_id") == "t01"),
        pl.DataFrame(
            [
                {"lap_number": 1, "lap_distance_m": 345.0, "ts": 10.0},
                {"lap_number": 1, "lap_distance_m": 352.0, "ts": 10.2},
            ]
        ),
        config=LiveCueRunnerConfig(run_id="run_01", file_name="synthetic.duckdb"),
    )

    assert events.height == 1
    row = events.row(0, named=True)
    assert row["plan_id"] == "plan_v1"
    assert row["file_name"] == "synthetic.duckdb"
    assert row["run_id"] == "run_01"
    assert row["zone_id"] == "t01"
    assert row["cue_trigger_m"] == pytest.approx(350.0)
    assert row["planned_lift_start_m"] == pytest.approx(350.0)
    assert row["actual_cue_distance_m"] == pytest.approx(352.0)
    assert row["cue_error_m"] == pytest.approx(2.0)
    assert row["trigger_status"] == "fired_on_time"
    assert row["audio_cue_kind"] == "beep"


def test_suppresses_duplicate_triggers_within_same_lap():
    events = simulate_live_cue_events(
        _plan().filter(pl.col("zone_id") == "t01"),
        pl.DataFrame(
            [
                {"lap_number": 1, "lap_distance_m": 346.0, "ts": 10.0},
                {"lap_number": 1, "lap_distance_m": 351.0, "ts": 10.1},
                {"lap_number": 1, "lap_distance_m": 354.0, "ts": 10.2},
            ]
        ),
    )

    assert events.height == 1
    assert events["actual_cue_distance_m"].to_list() == [pytest.approx(351.0)]


def test_rearms_cues_for_each_lap():
    events = simulate_live_cue_events(
        _plan().filter(pl.col("zone_id") == "t01"),
        pl.DataFrame(
            [
                {"lap_number": 1, "lap_distance_m": 345.0, "ts": 10.0},
                {"lap_number": 1, "lap_distance_m": 351.0, "ts": 10.1},
                {"lap_number": 2, "lap_distance_m": 346.0, "ts": 130.0},
                {"lap_number": 2, "lap_distance_m": 352.0, "ts": 130.1},
            ]
        ),
    )

    assert events.select("lap_number", "zone_id").rows() == [(1, "t01"), (2, "t01")]


def test_handles_track_wrap_for_cue_near_lap_start():
    events = simulate_live_cue_events(
        _plan().filter(pl.col("zone_id") == "start"),
        pl.DataFrame(
            [
                {"lap_number": 1, "lap_distance_m": 6990.0, "ts": 123.0},
                {"lap_number": 1, "lap_distance_m": 20.0, "ts": 123.2},
                {"lap_number": 1, "lap_distance_m": 30.0, "ts": 123.4},
            ]
        ),
    )

    assert events.height == 1
    row = events.row(0, named=True)
    assert row["zone_id"] == "start"
    assert row["cue_error_m"] == pytest.approx(10.0)
    assert row["trigger_status"] == "fired_late"


def test_handles_track_wrap_for_cue_near_lap_end_without_retrigger():
    events = simulate_live_cue_events(
        _plan().filter(pl.col("zone_id") == "final"),
        pl.DataFrame(
            [
                {"lap_number": 1, "lap_distance_m": 6950.0, "ts": 120.0},
                {"lap_number": 1, "lap_distance_m": 6980.0, "ts": 120.2},
                {"lap_number": 1, "lap_distance_m": 5.0, "ts": 120.4},
            ]
        ),
    )

    assert events.height == 1
    row = events.row(0, named=True)
    assert row["zone_id"] == "final"
    assert row["actual_cue_distance_m"] == pytest.approx(6980.0)
    assert row["cue_error_m"] == pytest.approx(10.0)


def test_marks_late_trigger_when_sample_gap_exceeds_tolerance():
    events = simulate_live_cue_events(
        _plan().filter(pl.col("zone_id") == "t01"),
        pl.DataFrame(
            [
                {"lap_number": 1, "lap_distance_m": 340.0, "ts": 10.0},
                {"lap_number": 1, "lap_distance_m": 370.0, "ts": 10.5},
            ]
        ),
    )

    assert events["trigger_status"].to_list() == ["fired_late"]
    assert events["cue_error_m"].to_list() == [pytest.approx(20.0)]


def test_summarizes_live_cue_event_accuracy():
    events = simulate_live_cue_events(
        _plan().filter(pl.col("zone_id") == "t01"),
        pl.DataFrame(
            [
                {"lap_number": 1, "lap_distance_m": 345.0, "ts": 10.0},
                {"lap_number": 1, "lap_distance_m": 352.0, "ts": 10.2},
                {"lap_number": 2, "lap_distance_m": 340.0, "ts": 130.0},
                {"lap_number": 2, "lap_distance_m": 370.0, "ts": 130.4},
            ]
        ),
    )

    summary = summarize_live_cue_event_accuracy(events)

    assert summary.select("zone_id", "cue_count", "on_time_rate").rows() == [
        ("t01", 2, 0.5),
    ]
    assert summary["max_abs_cue_error_m"].to_list() == [pytest.approx(20.0)]


def test_rejects_invalid_live_cue_plan():
    with pytest.raises(ValueError, match="cue_tolerance_m values must be positive"):
        validate_live_cue_plan(_plan().with_columns(pl.lit(-1.0).alias("cue_tolerance_m")))


def test_rejects_null_required_live_cue_plan_values():
    with pytest.raises(ValueError, match="null required values: cue_distance_m"):
        validate_live_cue_plan(_plan().with_columns(pl.lit(None).alias("cue_distance_m")))

    with pytest.raises(ValueError, match="null required values: planned_lift_start_m"):
        validate_live_cue_plan(
            _plan().with_columns(pl.lit(None).alias("planned_lift_start_m"))
        )


def test_rejects_inconsistent_track_lengths():
    plan = _plan().with_columns(
        pl.when(pl.col("zone_id") == "t01")
        .then(7001.0)
        .otherwise(7000.0)
        .alias("track_length_m")
    )

    with pytest.raises(ValueError, match="track_length_m values must be consistent"):
        validate_live_cue_plan(plan)


def test_rejects_config_track_length_that_makes_plan_distance_invalid():
    plan = _plan().drop("track_length_m")

    with pytest.raises(ValueError, match="distances must be below track_length_m"):
        simulate_live_cue_events(
            plan,
            pl.DataFrame([{"lap_number": 1, "lap_distance_m": 1.0, "ts": 1.0}]),
            config=LiveCueRunnerConfig(track_length_m=100.0),
        )


def test_rejects_duplicate_plan_zone_rows():
    duplicate = pl.concat(
        [
            _plan().filter(pl.col("zone_id") == "t01"),
            _plan().filter(pl.col("zone_id") == "t01"),
        ]
    )

    with pytest.raises(ValueError, match="duplicate plan_id/zone_id"):
        validate_live_cue_plan(duplicate)


def test_allows_same_zone_in_different_plans_without_suppressing_cues():
    base = _plan().filter(pl.col("zone_id") == "t01")
    second_plan = base.with_columns(pl.lit("plan_v2").alias("plan_id"))
    events = simulate_live_cue_events(
        pl.concat([base, second_plan]),
        pl.DataFrame(
            [
                {"lap_number": 1, "lap_distance_m": 345.0, "ts": 10.0},
                {"lap_number": 1, "lap_distance_m": 352.0, "ts": 10.2},
            ]
        ),
    )

    assert events.select("plan_id", "zone_id").rows() == [
        ("plan_v1", "t01"),
        ("plan_v2", "t01"),
    ]


def test_does_not_infer_wrap_without_track_length():
    events = simulate_live_cue_events(
        _plan().filter(pl.col("zone_id") == "start").drop("track_length_m"),
        pl.DataFrame(
            [
                {"lap_number": 1, "lap_distance_m": 6990.0, "ts": 123.0},
                {"lap_number": 1, "lap_distance_m": 20.0, "ts": 123.2},
            ]
        ),
    )

    assert events.is_empty()


def _plan() -> pl.DataFrame:
    return pl.DataFrame(
        [
            _cue("t01", "T01", cue_m=350.0, tolerance_m=5.0),
            _cue("final", "Final", cue_m=6970.0, tolerance_m=15.0),
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
