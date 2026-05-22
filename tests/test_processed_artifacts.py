import json
from pathlib import Path

import polars as pl

from licor.analysis import (
    build_lap_quality_manifest,
    write_lap_quality_manifest_artifact,
    write_data_readiness_artifacts,
    write_zone_pass_artifacts,
)


def test_writes_zone_pass_csv_and_parquet(tmp_path: Path):
    zone_passes = _zone_passes().with_columns(
        pl.lit([1, 2]).alias("turn_numbers")
    )

    paths = write_zone_pass_artifacts(
        zone_passes,
        csv_path=tmp_path / "zone_passes.csv",
        parquet_path=tmp_path / "zone_passes.parquet",
    )

    assert paths.zone_passes_csv == tmp_path / "zone_passes.csv"
    assert paths.zone_passes_parquet == tmp_path / "zone_passes.parquet"
    assert pl.read_csv(paths.zone_passes_csv).height == zone_passes.height
    assert pl.read_csv(paths.zone_passes_csv)["turn_numbers"].to_list() == [
        "1|2",
    ] * zone_passes.height
    assert pl.read_parquet(paths.zone_passes_parquet).height == zone_passes.height
    assert pl.read_parquet(paths.zone_passes_parquet)["turn_numbers"].to_list()[0] == [
        1,
        2,
    ]


def test_writes_data_readiness_artifacts(tmp_path: Path):
    protocol_path = tmp_path / "protocol.json"
    protocol_path.write_text(json.dumps(_protocol()), encoding="utf-8")

    paths = write_data_readiness_artifacts(
        _zone_passes(),
        protocol_file=protocol_path,
        zone_readiness_csv_path=tmp_path / "zone_readiness.csv",
        protocol_readiness_csv_path=tmp_path / "protocol_readiness.csv",
    )

    zone_readiness = pl.read_csv(paths.zone_readiness_csv)
    protocol_readiness = pl.read_csv(paths.protocol_readiness_csv)
    assert zone_readiness.select("zone_id", "readiness_status").rows() == [
        ("spa_t05_t06", "ready_for_curve_update"),
    ]
    assert protocol_readiness.select("collection_design", "readiness_status").rows() == [
        ("baseline", "complete"),
        ("controlled_random", "complete"),
    ]


def test_writes_lap_quality_manifest_artifact(tmp_path: Path):
    manifest = build_lap_quality_manifest(
        _lap_summary(),
        zone_passes=_zone_passes().with_columns(
            pl.lit(False).alias("zone_start_zero_throttle"),
            pl.lit(100.0).alias("brake_start_m"),
            pl.lit(100.0).alias("brake_reference_m"),
        ),
    )

    paths = write_lap_quality_manifest_artifact(
        manifest,
        csv_path=tmp_path / "lap_quality.csv",
    )

    assert paths.lap_quality_manifest_csv == tmp_path / "lap_quality.csv"
    written = pl.read_csv(paths.lap_quality_manifest_csv)
    assert written.height == manifest.height
    assert "report_only" in written["recommended_uses"].to_list()[0]


def _lap_summary() -> pl.DataFrame:
    return pl.DataFrame(
        [
            {
                "run_id": "baseline",
                "file_name": "baseline.duckdb",
                "lap_number": 1,
                "collection_label": "none",
                "collection_protocol_id": "",
                "collection_design": "",
                "execution_quality": "unknown",
                "labels_quality": "high",
                "driver_lap_label": "valid",
                "driver_included": True,
                "is_valid_lap": True,
                "lap_time_s": 123.0,
                "fuel_used_l": 3.4,
                "max_lap_distance_m": 7000.0,
                "mean_throttle_pct": 80.0,
                "max_brake_pct": 90.0,
                "exclusion_reason": None,
            }
        ]
    )


def _protocol() -> dict[str, object]:
    return {
        "protocol_id": "synthetic_protocol",
        "dataset_id": "synthetic",
        "track_name": "Synthetic Spa",
        "car_class": "LMP2_TEST",
        "purpose": "Synthetic readiness.",
        "sessions": [
            {
                "session_id": "baseline",
                "collection_design": "baseline",
                "objective": "Refresh baseline.",
                "minimum_clean_laps": 3,
            },
            {
                "session_id": "controlled",
                "collection_design": "controlled_random",
                "objective": "Fill curves.",
                "target_zones": ["spa_t05_t06"],
                "minimum_clean_laps": 3,
            },
        ],
    }


def _zone_passes() -> pl.DataFrame:
    rows = []
    for lap_number in (1, 2, 3):
        rows.append(
            _zone_pass_row(
                run_id="baseline",
                lap_number=lap_number,
                collection_design="baseline",
                lico_intensity="none",
                has_lico=False,
                lico_distance_m=None,
            )
        )
    for lap_number, distance_m in enumerate((40.0, 80.0, 130.0), start=4):
        rows.append(
            _zone_pass_row(
                run_id="random",
                lap_number=lap_number,
                collection_design="controlled_random",
                lico_intensity="unknown",
                has_lico=True,
                lico_distance_m=distance_m,
            )
        )
    return pl.DataFrame(rows)


def _zone_pass_row(
    *,
    run_id: str,
    lap_number: int,
    collection_design: str,
    lico_intensity: str,
    has_lico: bool,
    lico_distance_m: float | None,
) -> dict[str, object]:
    return {
        "file_name": f"{run_id}.duckdb",
        "run_id": run_id,
        "lap_number": lap_number,
        "zone_id": "spa_t05_t06",
        "display_label": "T05-T06",
        "lico_intensity": lico_intensity,
        "collection_design": collection_design,
        "execution_quality": "clean",
        "has_lico": has_lico,
        "lico_start_distance_before_brake_m": lico_distance_m,
        "validity_label": "valid",
    }
