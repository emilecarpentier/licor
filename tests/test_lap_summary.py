import json
from pathlib import Path

import duckdb
import pytest

from licor.analysis import (
    LapSummaryConfig,
    RunLapLabels,
    filter_valid_laps,
    summarize_labeled_dataset,
    summarize_laps,
)
from licor.ingestion import LmuTelemetryDatabase


def test_summarizes_laps_and_applies_driver_labels(tmp_path):
    db_path = tmp_path / "sample.duckdb"
    _create_synthetic_lmu_duckdb(db_path, lap_offset=1)
    labels = _run_labels(
        file_name="sample.duckdb",
        valid_laps=[2],
        excluded_laps=[3],
    )

    with LmuTelemetryDatabase(db_path) as telemetry:
        summary = summarize_laps(
            telemetry,
            run_labels=labels,
            config=LapSummaryConfig(min_lap_distance_m=800.0, max_lap_distance_m=1000.0),
        )

    lap_1 = summary.filter(summary["lap_number"] == 1).row(0, named=True)
    lap_2 = summary.filter(summary["lap_number"] == 2).row(0, named=True)
    lap_3 = summary.filter(summary["lap_number"] == 3).row(0, named=True)

    assert lap_1["in_pits"] is True
    assert lap_1["is_valid_lap"] is False
    assert lap_2["driver_lap_label"] == "valid"
    assert lap_2["is_valid_lap"] is True
    assert lap_2["fuel_used_l"] == pytest.approx(0.9, abs=1e-5)
    assert lap_2["max_lap_distance_m"] == pytest.approx(900.0)
    assert lap_3["driver_lap_label"] == "excluded"
    assert lap_3["is_valid_lap"] is False

    valid = filter_valid_laps(summary)
    assert valid["lap_number"].to_list() == [2]


def test_loads_multiple_labeled_duckdb_files(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _create_synthetic_lmu_duckdb(data_dir / "run_a.duckdb", lap_offset=10)
    _create_synthetic_lmu_duckdb(data_dir / "run_b.duckdb", lap_offset=20)
    label_file = tmp_path / "labels.json"
    label_file.write_text(
        json.dumps(
            {
                "dataset_id": "synthetic",
                "runs": [
                    _run_label_dict(
                        run_id="run_a",
                        file_name="data/run_a.duckdb",
                        valid_laps=[11],
                        excluded_laps=[12],
                    ),
                    _run_label_dict(
                        run_id="run_b",
                        file_name="data/run_b.duckdb",
                        valid_laps=[21],
                        excluded_laps=[22],
                    ),
                ],
            }
        ),
        encoding="utf-8",
    )

    summary = summarize_labeled_dataset(
        label_file,
        project_root=tmp_path,
        config=LapSummaryConfig(min_lap_distance_m=800.0, max_lap_distance_m=1000.0),
    )

    assert set(summary["run_id"]) == {"run_a", "run_b"}
    assert filter_valid_laps(summary).select("run_id", "lap_number").rows() == [
        ("run_a", 11),
        ("run_b", 21),
    ]


def test_loads_mixed_legacy_and_v2_run_metadata_without_list_schema_errors(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _create_synthetic_lmu_duckdb(data_dir / "legacy.duckdb", lap_offset=30)
    _create_synthetic_lmu_duckdb(data_dir / "random.duckdb", lap_offset=40)
    label_file = tmp_path / "labels.json"
    label_file.write_text(
        json.dumps(
            {
                "dataset_id": "synthetic_mixed",
                "runs": [
                    _run_label_dict(
                        run_id="legacy",
                        file_name="data/legacy.duckdb",
                        valid_laps=[31],
                        excluded_laps=[32],
                    ),
                    {
                        **_run_label_dict(
                            run_id="random",
                            file_name="data/random.duckdb",
                            valid_laps=[41],
                            excluded_laps=[42],
                        ),
                        "collection_label": "controlled_random",
                        "collection_protocol_id": "spa_lmp2_v2_collection_protocol",
                        "collection_session_id": "controlled_random",
                        "collection_design": "controlled_random",
                        "target_zones": ["spa_t05_t06"],
                        "planned_lico_profile_id": "synthetic_random_profile",
                        "planned_lico_profile_description": "Synthetic profile.",
                        "execution_quality": "clean",
                        "driver_notes": "Synthetic v2 run.",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    summary = summarize_labeled_dataset(
        label_file,
        project_root=tmp_path,
        config=LapSummaryConfig(min_lap_distance_m=800.0, max_lap_distance_m=1000.0),
    )

    legacy = summary.filter(summary["run_id"] == "legacy").row(0, named=True)
    random = summary.filter(summary["run_id"] == "random").row(0, named=True)
    assert legacy["target_zones"] == []
    assert legacy["collection_design"] == ""
    assert random["target_zones"] == ["spa_t05_t06"]
    assert random["collection_design"] == "controlled_random"


def _create_synthetic_lmu_duckdb(path: Path, *, lap_offset: int) -> None:
    con = duckdb.connect(str(path))
    con.execute("create table metadata(key varchar primary key, value varchar)")
    con.execute("insert into metadata values ('TrackName', 'Synthetic Spa')")
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
        ('Fuel Level', 1, 'L'),
        ('Lap Dist', 1, 'm'),
        ('Ground Speed', 1, 'km/h'),
        ('Throttle Pos', 1, '%'),
        ('Brake Pos', 1, '%')
        """
    )
    con.execute("create table eventsList(eventName varchar primary key, unit varchar)")
    con.execute("insert into eventsList values ('Lap', ''), ('In Pits', '')")
    con.execute('create table "Lap"(ts double, value usmallint)')
    con.execute(
        'insert into "Lap" values (0, ?), (10, ?), (20, ?), (30, ?)',
        [lap_offset, lap_offset + 1, lap_offset + 2, lap_offset + 3],
    )
    con.execute('create table "In Pits"(ts double, value utinyint)')
    con.execute('insert into "In Pits" values (0, 1), (5, 0)')

    con.execute('create table "Fuel Level"(value float)')
    con.execute('create table "Lap Dist"(value float)')
    con.execute('create table "Ground Speed"(value float)')
    con.execute('create table "Throttle Pos"(value float)')
    con.execute('create table "Brake Pos"(value float)')
    for sample_index in range(30):
        con.execute('insert into "Fuel Level" values (?)', [100.0 - sample_index * 0.1])
        con.execute('insert into "Lap Dist" values (?)', [(sample_index % 10) * 100.0])
        con.execute('insert into "Ground Speed" values (?)', [200.0 + sample_index])
        con.execute('insert into "Throttle Pos" values (?)', [90.0])
        con.execute('insert into "Brake Pos" values (?)', [0.0 if sample_index % 10 < 8 else 75.0])
    con.close()


def _run_labels(
    *,
    file_name: str,
    valid_laps: list[int],
    excluded_laps: list[int],
) -> RunLapLabels:
    return RunLapLabels.from_dict(
        _run_label_dict(
            run_id="synthetic_run",
            file_name=file_name,
            valid_laps=valid_laps,
            excluded_laps=excluded_laps,
        )
    )


def _run_label_dict(
    *,
    run_id: str,
    file_name: str,
    valid_laps: list[int],
    excluded_laps: list[int],
) -> dict[str, object]:
    return {
        "run_id": run_id,
        "file": file_name,
        "track": "Synthetic Spa",
        "car_class": "LMP2_TEST",
        "car": "Synthetic LMP2",
        "session_type": "Practice",
        "run_type": "synthetic",
        "collection_label": "none",
        "labels_quality": "test",
        "valid_laps": valid_laps,
        "borderline_laps": [],
        "context_laps": [],
        "excluded_laps": excluded_laps,
        "include_in_lap_summary": True,
    }
