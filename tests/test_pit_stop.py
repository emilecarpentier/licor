from pathlib import Path

import duckdb
import pytest

from licor.analysis import PitStopConfig, RunLapLabels, extract_pit_stop_observations
from licor.ingestion import LmuTelemetryDatabase


def test_extracts_pit_stop_refill_and_limiter_observation(tmp_path):
    db_path = tmp_path / "pitstop.duckdb"
    _create_synthetic_pitstop_duckdb(db_path)
    labels = _run_labels(file_name="pitstop.duckdb")

    with LmuTelemetryDatabase(db_path) as telemetry:
        observations = extract_pit_stop_observations(
            telemetry,
            run_labels=labels,
            config=PitStopConfig(reference_refill_rate_lps=2.0),
        )

    assert observations.height == 1
    row = observations.row(0, named=True)
    assert row["run_id"] == "synthetic_pitstop"
    assert row["pit_stop_index"] == 1
    assert row["pit_entry_elapsed_s"] == pytest.approx(100.0)
    assert row["pit_exit_elapsed_s"] == pytest.approx(160.0)
    assert row["in_pits_duration_s"] == pytest.approx(60.0)
    assert row["speed_limiter_on_elapsed_s"] == pytest.approx(98.0)
    assert row["speed_limiter_off_elapsed_s"] == pytest.approx(162.0)
    assert row["speed_limiter_duration_s"] == pytest.approx(64.0)
    assert row["stationary_start_elapsed_s"] == pytest.approx(110.0)
    assert row["stationary_end_elapsed_s"] == pytest.approx(150.0)
    assert row["stationary_duration_s"] == pytest.approx(40.0)
    assert row["refill_start_elapsed_s"] == pytest.approx(112.0)
    assert row["refill_end_elapsed_s"] == pytest.approx(148.0)
    assert row["refill_duration_s"] == pytest.approx(36.0)
    assert row["fuel_added_l"] == pytest.approx(72.0)
    assert row["observed_refill_rate_lps"] == pytest.approx(2.0)
    assert row["refill_rate_delta_lps"] == pytest.approx(0.0)
    assert row["refill_rate_ratio_to_reference"] == pytest.approx(1.0)
    assert row["pit_lane_commitment_time_s"] == pytest.approx(64.0)
    assert row["tire_change_included"] is False
    assert row["validity_label"] == "valid"


def test_can_keep_initial_active_interval_when_configured(tmp_path):
    db_path = tmp_path / "pitstop.duckdb"
    _create_synthetic_pitstop_duckdb(db_path)

    with LmuTelemetryDatabase(db_path) as telemetry:
        observations = extract_pit_stop_observations(
            telemetry,
            config=PitStopConfig(ignore_initial_active_interval=False),
        )

    assert observations["pit_entry_elapsed_s"].to_list() == [0.0, 100.0]
    assert observations["validity_label"].to_list()[0].startswith("missing_")


def test_marks_observation_when_refill_is_missing(tmp_path):
    db_path = tmp_path / "pitstop.duckdb"
    _create_synthetic_pitstop_duckdb(db_path, include_refill=False)

    with LmuTelemetryDatabase(db_path) as telemetry:
        observations = extract_pit_stop_observations(telemetry)

    row = observations.row(0, named=True)
    assert row["validity_label"] == "missing_refill"
    assert row["fuel_added_l"] is None
    assert row["observed_refill_rate_lps"] is None


def _create_synthetic_pitstop_duckdb(
    path: Path,
    *,
    include_refill: bool = True,
) -> None:
    con = duckdb.connect(str(path))
    con.execute("create table metadata(key varchar primary key, value varchar)")
    con.execute(
        """
        insert into metadata values
        ('TrackName', 'Synthetic Spa'),
        ('CarClass', 'LMP2_TEST')
        """
    )
    con.execute(
        """
        create table channelsList(
            channelName varchar primary key,
            frequency integer,
            unit varchar
        )
        """
    )
    con.execute(
        """
        insert into channelsList values
        ('Fuel Level', 10, 'L'),
        ('Ground Speed', 10, 'km/h')
        """
    )
    con.execute("create table eventsList(eventName varchar primary key, unit varchar)")
    con.execute("insert into eventsList values ('Lap', ''), ('In Pits', ''), ('Speed Limiter', '')")
    con.execute('create table "Lap"(ts double, value usmallint)')
    con.execute('insert into "Lap" values (1000, 1), (1180, 2), (1360, 3)')
    con.execute('create table "In Pits"(ts double, value utinyint)')
    con.execute('insert into "In Pits" values (1000, 1), (1020, 0), (1100, 1), (1160, 0)')
    con.execute('create table "Speed Limiter"(ts double, value boolean)')
    con.execute('insert into "Speed Limiter" values (1000, true), (1020, false), (1098, true), (1162, false)')
    con.execute('create table "Fuel Level"(value float)')
    con.execute('create table "Ground Speed"(value float)')

    for sample_index in range(1801):
        elapsed_s = sample_index * 0.1
        fuel_level = _fuel_level(elapsed_s, include_refill=include_refill)
        speed = 0.0 if 110.0 <= elapsed_s <= 150.0 else 50.0
        con.execute('insert into "Fuel Level" values (?)', [fuel_level])
        con.execute('insert into "Ground Speed" values (?)', [speed])
    con.close()


def _fuel_level(elapsed_s: float, *, include_refill: bool) -> float:
    if not include_refill:
        return 5.0
    if elapsed_s < 112.0:
        return 5.0
    if elapsed_s <= 148.0:
        return 5.0 + (elapsed_s - 112.0) * 2.0
    return 77.0


def _run_labels(*, file_name: str) -> RunLapLabels:
    return RunLapLabels.from_dict(
        {
            "run_id": "synthetic_pitstop",
            "file": file_name,
            "track": "Synthetic Spa",
            "car_class": "LMP2_TEST",
            "car": "Synthetic LMP2",
            "session_type": "Practice",
            "run_type": "pit stop observation",
            "collection_label": "pitstop",
            "labels_quality": "test",
            "valid_laps": [],
            "borderline_laps": [],
            "context_laps": [],
            "excluded_laps": [],
            "include_in_lap_summary": False,
        }
    )
