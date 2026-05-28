import json
from pathlib import Path

import polars as pl

import licor.analysis.processed_artifacts as processed_artifacts_module
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


def test_build_spa_v2_readiness_artifacts_forwards_live_cue_events_csv(
    tmp_path: Path,
    monkeypatch,
):
    protocol_path = tmp_path / "protocol.json"
    protocol_path.write_text(json.dumps(_protocol()), encoding="utf-8")
    cue_events_path = tmp_path / "live_cue_events.csv"
    pl.DataFrame(
        [
            {"plan_id": "plan_v1", "run_id": "recommendation_execution_selected_01"},
            {"plan_id": "plan_v1", "run_id": "recommendation_execution_selected_01"},
        ]
    ).write_csv(cue_events_path)

    captured: dict[str, object] = {}

    def fake_build_labeled_zone_passes(**_: object) -> pl.DataFrame:
        return _zone_passes()

    def fake_write_zone_pass_artifacts(
        zone_passes: pl.DataFrame,
        *,
        csv_path: str | Path,
        parquet_path: str | Path | None = None,
    ):
        csv_path = Path(csv_path)
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        zone_passes.write_csv(csv_path)
        return processed_artifacts_module.ZonePassArtifactPaths(
            zone_passes_csv=csv_path,
            zone_passes_parquet=None,
        )

    def fake_write_data_readiness_artifacts(
        zone_passes: pl.DataFrame,
        *,
        protocol_file: str | Path,
        zone_readiness_csv_path: str | Path,
        protocol_readiness_csv_path: str | Path,
        live_cue_events: pl.DataFrame | None = None,
        config=None,
    ):
        del zone_passes, protocol_file, config
        captured["live_cue_events_height"] = 0 if live_cue_events is None else live_cue_events.height
        zone_readiness_csv_path = Path(zone_readiness_csv_path)
        protocol_readiness_csv_path = Path(protocol_readiness_csv_path)
        zone_readiness_csv_path.parent.mkdir(parents=True, exist_ok=True)
        pl.DataFrame(
            [{"zone_id": "spa_t05_t06", "readiness_status": "ready_for_curve_update"}]
        ).write_csv(zone_readiness_csv_path)
        pl.DataFrame(
            [{"collection_design": "baseline", "readiness_status": "complete"}]
        ).write_csv(protocol_readiness_csv_path)
        return processed_artifacts_module.DataReadinessArtifactPaths(
            zone_readiness_csv=zone_readiness_csv_path,
            protocol_readiness_csv=protocol_readiness_csv_path,
        )

    monkeypatch.setattr(
        processed_artifacts_module,
        "build_labeled_zone_passes",
        fake_build_labeled_zone_passes,
    )
    monkeypatch.setattr(
        processed_artifacts_module,
        "write_zone_pass_artifacts",
        fake_write_zone_pass_artifacts,
    )
    monkeypatch.setattr(
        processed_artifacts_module,
        "write_data_readiness_artifacts",
        fake_write_data_readiness_artifacts,
    )

    processed_artifacts_module.build_spa_v2_readiness_artifacts(
        project_root=tmp_path,
        output_dir="out",
        dataset_label_file="dataset.json",
        track_zone_file="zones.json",
        protocol_file=protocol_path.name,
        live_cue_events_csv=cue_events_path.name,
        write_parquet=False,
    )

    assert captured["live_cue_events_height"] == 2


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
