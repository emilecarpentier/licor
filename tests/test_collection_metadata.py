import json

import polars as pl

from licor.analysis import (
    CollectionProtocol,
    CollectionProtocolSession,
    DatasetLapLabels,
    attach_collection_metadata_to_zone_passes,
    run_collection_metadata_frame,
    validate_dataset_collection_metadata,
)


def test_builds_run_collection_metadata_frame_from_v2_sidecar():
    labels = _dataset_labels(
        [
            _run_label_dict(
                run_id="random_01",
                collection_design="controlled_random",
                target_zones=["spa_t05_t06", "spa_t08"],
                planned_lico_profile_id="random_short_medium_long",
            )
        ]
    )

    metadata = run_collection_metadata_frame(labels)

    row = metadata.row(0, named=True)
    assert row["collection_protocol_id"] == "spa_lmp2_v2_collection_protocol"
    assert row["collection_design"] == "controlled_random"
    assert row["target_zones"] == ["spa_t05_t06", "spa_t08"]
    assert row["execution_quality"] == "clean"


def test_validates_dataset_collection_metadata_against_protocol():
    labels = _dataset_labels(
        [
            _run_label_dict(
                run_id="baseline",
                collection_design="baseline",
            ),
            _run_label_dict(
                run_id="targeted",
                collection_design="targeted_zone",
                target_zones=["spa_t05_t06"],
                planned_lico_profile_id="t05_variation",
            ),
            _run_label_dict(
                run_id="bad_target",
                collection_design="targeted_zone",
                target_zones=["spa_unknown"],
                planned_lico_profile_id="unknown_target",
            ),
            _run_label_dict(
                run_id="recommendation",
                collection_design="recommendation_execution",
                target_zones="from_exported_plan",
                planned_lico_profile_id="plan_profile",
                audio_cue_plan_id="spa_plan_v1",
            ),
        ]
    )

    validation = validate_dataset_collection_metadata(labels, _protocol())

    assert validation.select("run_id", "metadata_status", "metadata_flags").rows() == [
        ("baseline", "ready", []),
        ("targeted", "ready", []),
        ("bad_target", "needs_review", ["target_zones_not_in_protocol"]),
        ("recommendation", "ready", []),
    ]
    recommendation = validation.filter(pl.col("run_id") == "recommendation").row(
        0,
        named=True,
    )
    assert recommendation["target_zones"] == []
    assert recommendation["target_zones_source"] == "from_exported_plan"


def test_validation_reports_missing_v2_metadata_without_inference_from_label():
    labels = _dataset_labels(
        [
            {
                **_run_label_dict(run_id="legacy_low", collection_design=""),
                "collection_protocol_id": "",
                "execution_quality": "",
            }
        ]
    )

    row = validate_dataset_collection_metadata(labels, _protocol()).row(0, named=True)

    assert row["metadata_status"] == "needs_metadata"
    assert row["metadata_flags"] == [
        "missing_collection_protocol_id",
        "missing_collection_design",
    ]


def test_validation_keeps_legacy_context_visible_alongside_ready_v2_runs():
    labels = _dataset_labels(
        [
            {
                **_run_label_dict(run_id="legacy_high", collection_design=""),
                "collection_label": "high",
                "collection_protocol_id": "",
                "execution_quality": "",
            },
            _run_label_dict(
                run_id="baseline_refresh",
                collection_design="baseline",
            ),
        ]
    )

    validation = validate_dataset_collection_metadata(labels, _protocol())

    assert validation.select("run_id", "metadata_status", "metadata_flags").rows() == [
        (
            "legacy_high",
            "needs_metadata",
            ["missing_collection_protocol_id", "missing_collection_design"],
        ),
        ("baseline_refresh", "ready", []),
    ]


def test_validation_rejects_targeted_zone_with_source_instead_of_explicit_targets():
    labels = _dataset_labels(
        [
            _run_label_dict(
                run_id="bad_target_source",
                collection_design="targeted_zone",
                target_zones="from_exported_plan",
                planned_lico_profile_id="target_profile",
            )
        ]
    )

    row = validate_dataset_collection_metadata(labels, _protocol()).row(0, named=True)

    assert row["target_zones_source"] == "from_exported_plan"
    assert row["metadata_status"] == "needs_metadata"
    assert row["metadata_flags"] == ["missing_target_zones"]


def test_validation_accepts_paths(tmp_path):
    label_path = tmp_path / "labels.json"
    protocol_path = tmp_path / "protocol.json"
    label_path.write_text(
        json.dumps(
            {
                "dataset_id": "synthetic_spa_v2",
                "description": "Synthetic metadata validation.",
                "runs": [_run_label_dict(run_id="baseline", collection_design="baseline")],
            }
        ),
        encoding="utf-8",
    )
    protocol_path.write_text(
        _protocol().model_dump_json(),
        encoding="utf-8",
    )

    row = validate_dataset_collection_metadata(label_path, protocol_path).row(0, named=True)

    assert row["run_id"] == "baseline"
    assert row["metadata_status"] == "ready"


def test_attaches_collection_metadata_to_existing_zone_passes():
    labels = _dataset_labels(
        [
            _run_label_dict(
                run_id="targeted",
                collection_design="targeted_zone",
                target_zones=["spa_t05_t06"],
                planned_lico_profile_id="t05_variation",
            )
        ]
    )
    zone_passes = pl.DataFrame(
        [
            {
                "run_id": "targeted",
                "lap_number": 1,
                "zone_id": "spa_t05_t06",
            }
        ]
    )

    enriched = attach_collection_metadata_to_zone_passes(zone_passes, labels)

    row = enriched.row(0, named=True)
    assert row["collection_design"] == "targeted_zone"
    assert row["target_zones"] == ["spa_t05_t06"]
    assert row["planned_lico_profile_id"] == "t05_variation"


def test_attach_collection_metadata_fills_existing_empty_columns():
    labels = _dataset_labels(
        [
            _run_label_dict(
                run_id="targeted",
                collection_design="targeted_zone",
                target_zones=["spa_t05_t06"],
                planned_lico_profile_id="t05_variation",
            )
        ]
    )
    zone_passes = pl.DataFrame(
        [
            {
                "run_id": "targeted",
                "lap_number": 1,
                "zone_id": "spa_t05_t06",
                "collection_design": "",
                "target_zones": [],
                "planned_lico_profile_id": None,
            }
        ]
    )

    enriched = attach_collection_metadata_to_zone_passes(zone_passes, labels)

    row = enriched.row(0, named=True)
    assert row["collection_design"] == "targeted_zone"
    assert row["target_zones"] == ["spa_t05_t06"]
    assert row["planned_lico_profile_id"] == "t05_variation"


def _dataset_labels(runs: list[dict[str, object]]) -> DatasetLapLabels:
    return DatasetLapLabels.from_dict(
        {
            "dataset_id": "synthetic_spa_v2",
            "description": "Synthetic Spa v2 runs.",
            "runs": runs,
        }
    )


def _run_label_dict(
    *,
    run_id: str,
    collection_design: str,
    target_zones: list[str] | str | None = None,
    planned_lico_profile_id: str = "",
    audio_cue_plan_id: str = "",
) -> dict[str, object]:
    return {
        "run_id": run_id,
        "file": f"data/{run_id}.duckdb",
        "track": "Circuit de Spa-Francorchamps",
        "car_class": "LMP2_ELMS",
        "car": "Oreca 07 ELMS Custom Team 2025 #397",
        "session_type": "Practice",
        "run_type": "synthetic",
        "collection_label": "unknown",
        "labels_quality": "medium",
        "valid_laps": [1, 2],
        "borderline_laps": [],
        "context_laps": [],
        "excluded_laps": [],
        "include_in_lap_summary": True,
        "collection_protocol_id": "spa_lmp2_v2_collection_protocol",
        "collection_design": collection_design,
        "target_zones": target_zones or [],
        "planned_lico_profile_id": planned_lico_profile_id,
        "planned_lico_profile_description": "Synthetic profile.",
        "audio_cue_plan_id": audio_cue_plan_id,
        "execution_quality": "clean",
        "driver_notes": "Synthetic test run.",
    }


def _protocol() -> CollectionProtocol:
    return CollectionProtocol(
        protocol_id="spa_lmp2_v2_collection_protocol",
        dataset_id="synthetic_spa_v2",
        track_name="Circuit de Spa-Francorchamps",
        car_class="LMP2_ELMS",
        purpose="Synthetic protocol.",
        sessions=[
            CollectionProtocolSession(
                session_id="baseline",
                collection_design="baseline",
                objective="Refresh baseline.",
                minimum_clean_laps=2,
            ),
            CollectionProtocolSession(
                session_id="targeted",
                collection_design="targeted_zone",
                objective="Target one zone.",
                target_zones=("spa_t05_t06", "spa_t08"),
                minimum_clean_laps=2,
            ),
            CollectionProtocolSession(
                session_id="recommendation",
                collection_design="recommendation_execution",
                objective="Execute plan.",
                target_zones_source="from_exported_plan",
                minimum_clean_laps=2,
            ),
        ],
    )
