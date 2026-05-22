import json
from pathlib import Path

import duckdb
import polars as pl
import pytest

from licor.reports import (
    LapTelemetryReportConfig,
    build_labeled_lap_telemetry_samples,
    create_lap_telemetry_report_figure,
    prepare_lap_telemetry_report_samples,
    write_lap_telemetry_report_html,
)


def test_builds_labeled_lap_telemetry_samples_from_dataset_sidecar(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _create_synthetic_lmu_duckdb(data_dir / "run_none.duckdb")
    label_file = tmp_path / "labels.json"
    label_file.write_text(
        json.dumps(
            {
                "dataset_id": "synthetic_spa",
                "runs": [
                    {
                        "run_id": "run_none",
                        "file": "data/run_none.duckdb",
                        "track": "Synthetic Spa",
                        "car_class": "LMP2_TEST",
                        "car": "Synthetic LMP2",
                        "session_type": "Practice",
                        "run_type": "push",
                        "collection_label": "none",
                        "labels_quality": "high",
                        "valid_laps": [2],
                        "borderline_laps": [],
                        "context_laps": [1],
                        "excluded_laps": [],
                        "include_in_lap_summary": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    samples = build_labeled_lap_telemetry_samples(
        label_file,
        project_root=tmp_path,
        config=LapTelemetryReportConfig(include_driver_lap_labels=("valid",)),
    )

    assert samples.select("run_id", "collection_label", "driver_lap_label").unique().rows() == [
        ("run_none", "none", "valid")
    ]
    assert samples["lap_number"].unique().to_list() == [2]
    assert samples["lap_distance_m"].max() == pytest.approx(400.0)


def test_creates_core_lap_telemetry_report_with_five_metric_rows():
    figure = create_lap_telemetry_report_figure(
        _samples(),
        title="Synthetic core telemetry",
    )

    assert figure.layout.title.text == "Synthetic core telemetry"
    assert len(figure.data) == 10
    assert len(figure.layout.annotations) == 5
    assert figure.layout.height == 1050
    assert {trace.name for trace in figure.data} == {
        "none run_none L1 (valid)",
        "low run_low L2 (borderline)",
    }
    assert figure.layout.yaxis.title.text == "km/h"
    assert figure.layout.yaxis2.title.text == "%"
    assert figure.layout.yaxis3.title.text == "%"
    assert figure.layout.yaxis4.title.text == "L"
    assert figure.layout.yaxis5.title.text == "m"


def test_prepares_elapsed_time_fallback_from_elapsed_s():
    samples = _samples().drop("lap_elapsed_s").with_columns(pl.col("ts").alias("elapsed_s"))

    prepared = prepare_lap_telemetry_report_samples(samples)

    assert "lap_elapsed_s" in prepared.columns
    assert prepared["lap_elapsed_s"].to_list()[:3] == [0.0, 1.0, 2.0]


def test_prepares_elapsed_time_fallback_from_ts_and_lap_start():
    samples = _samples().drop("lap_elapsed_s").with_columns(pl.lit(10.0).alias("lap_start_ts"))

    prepared = prepare_lap_telemetry_report_samples(samples)

    assert prepared["lap_elapsed_s"].to_list()[:3] == [-10.0, -9.0, -8.0]


def test_prepares_elapsed_time_fallback_from_ts_only():
    samples = _samples().drop("lap_elapsed_s")

    prepared = prepare_lap_telemetry_report_samples(samples)

    assert prepared["lap_elapsed_s"].to_list()[:3] == [0.0, 1.0, 2.0]


def test_creates_empty_lap_telemetry_report():
    figure = create_lap_telemetry_report_figure(
        pl.DataFrame(),
        title="Empty core telemetry",
    )

    assert figure.layout.title.text == "Empty core telemetry"
    assert len(figure.data) == 0


def test_rejects_missing_required_lap_telemetry_columns():
    with pytest.raises(ValueError, match="missing required columns"):
        create_lap_telemetry_report_figure(
            pl.DataFrame([{"lap_number": 1, "lap_elapsed_s": 0.0}]),
            title="Bad samples",
        )


def test_writes_lap_telemetry_report_html(tmp_path: Path):
    figure = create_lap_telemetry_report_figure(pl.DataFrame(), title="Empty")

    path = write_lap_telemetry_report_html(figure, tmp_path / "lap_telemetry.html")

    assert path.exists()
    assert path.read_text(encoding="utf-8").startswith("<html>")


def _samples() -> pl.DataFrame:
    rows = []
    for run_id, lap_number, label, driver_lap_label in (
        ("run_none", 1, "none", "valid"),
        ("run_low", 2, "low", "borderline"),
    ):
        for index, distance_m in enumerate((0.0, 100.0, 200.0)):
            rows.append(
                {
                    "run_id": run_id,
                    "lap_number": lap_number,
                    "collection_label": label,
                    "driver_lap_label": driver_lap_label,
                    "ts": float(index),
                    "lap_elapsed_s": float(index),
                    "lap_distance_m": distance_m,
                    "brake_pct": 80.0 if distance_m == 200.0 else 0.0,
                    "throttle_pct": 0.0 if label == "low" and distance_m == 100.0 else 100.0,
                    "ground_speed_kph": 260.0 - distance_m / 10.0,
                    "fuel_level_l": 50.0 - distance_m / 1000.0,
                }
            )
    return pl.DataFrame(rows)


def _create_synthetic_lmu_duckdb(path: Path) -> None:
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
    con.execute("insert into eventsList values ('Lap', '')")
    con.execute('create table "Lap"(ts double, value usmallint)')
    con.execute('insert into "Lap" values (0, 1), (5, 2), (10, 3)')

    con.execute('create table "Fuel Level"(value float)')
    con.execute('create table "Lap Dist"(value float)')
    con.execute('create table "Ground Speed"(value float)')
    con.execute('create table "Throttle Pos"(value float)')
    con.execute('create table "Brake Pos"(value float)')
    for sample_index in range(10):
        lap_distance_m = (sample_index % 5) * 100.0
        con.execute('insert into "Fuel Level" values (?)', [60.0 - sample_index * 0.1])
        con.execute('insert into "Lap Dist" values (?)', [lap_distance_m])
        con.execute('insert into "Ground Speed" values (?)', [250.0 - lap_distance_m / 10.0])
        con.execute('insert into "Throttle Pos" values (?)', [100.0])
        con.execute('insert into "Brake Pos" values (?)', [70.0 if lap_distance_m >= 300.0 else 0.0])
    con.close()
