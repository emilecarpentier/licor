from __future__ import annotations

from pathlib import Path

import polars as pl

from licor.analysis.collection_protocol import (
    CollectionProtocol,
    load_collection_protocol,
)
from licor.analysis.lap_summary import (
    DatasetLapLabels,
    RunLapLabels,
    load_dataset_lap_labels,
)


VALID_EXECUTION_QUALITY_LABELS = ("clean", "partial", "poor", "unknown")
DESIGNS_REQUIRING_LICO_PROFILE = (
    "controlled_random",
    "targeted_zone",
    "recommendation_execution",
)


def run_collection_metadata_frame(labels: DatasetLapLabels) -> pl.DataFrame:
    """Return one metadata row per telemetry run in a dataset sidecar."""

    if not labels.runs:
        return empty_run_collection_metadata_frame()
    return pl.DataFrame(
        [
            {
                "dataset_id": labels.dataset_id,
                "run_id": run.run_id,
                "file_name": Path(run.file).name,
                "track": run.track,
                "car_class": run.car_class,
                "collection_label": run.collection_label,
                "labels_quality": run.labels_quality,
                **run.collection_metadata(),
            }
            for run in labels.runs
        ],
        schema=_RUN_COLLECTION_METADATA_SCHEMA,
        strict=False,
    ).select(_RUN_COLLECTION_METADATA_COLUMNS)


def validate_dataset_collection_metadata(
    labels: DatasetLapLabels | str | Path,
    protocol: CollectionProtocol | str | Path,
) -> pl.DataFrame:
    """Validate dataset run metadata against a collection protocol."""

    dataset_labels = (
        load_dataset_lap_labels(labels) if isinstance(labels, str | Path) else labels
    )
    collection_protocol = (
        load_collection_protocol(protocol)
        if isinstance(protocol, str | Path)
        else protocol
    )
    metadata = run_collection_metadata_frame(dataset_labels)
    if metadata.is_empty():
        return empty_collection_metadata_validation_frame()

    protocol_sessions = collection_protocol.to_frame()
    rows = [
        _validation_row(run, collection_protocol, protocol_sessions)
        for run in dataset_labels.runs
    ]
    return pl.DataFrame(
        rows,
        schema=_COLLECTION_METADATA_VALIDATION_SCHEMA,
        strict=False,
    ).select(_COLLECTION_METADATA_VALIDATION_COLUMNS)


def attach_collection_metadata_to_zone_passes(
    zone_passes: pl.DataFrame,
    labels: DatasetLapLabels | str | Path,
) -> pl.DataFrame:
    """Attach run-level collection metadata to an existing zone-pass table."""

    dataset_labels = (
        load_dataset_lap_labels(labels) if isinstance(labels, str | Path) else labels
    )
    metadata = run_collection_metadata_frame(dataset_labels)
    if zone_passes.is_empty() or metadata.is_empty():
        return zone_passes

    metadata_columns = [
        column
        for column in _RUN_COLLECTION_METADATA_COLUMNS
        if column not in {"dataset_id", "run_id", "file_name", "track", "car_class"}
    ]
    rename_map = {column: f"__metadata_{column}" for column in metadata_columns}
    enriched = zone_passes.join(
        metadata.select(["run_id", *metadata_columns]).rename(rename_map),
        on="run_id",
        how="left",
    )
    for column in metadata_columns:
        metadata_column = rename_map[column]
        if column in zone_passes.columns:
            enriched = enriched.with_columns(
                pl.when(_missing_metadata_value(column))
                .then(pl.col(metadata_column))
                .otherwise(pl.col(column))
                .alias(column)
            ).drop(metadata_column)
        else:
            enriched = enriched.rename({metadata_column: column})
    return enriched


def empty_run_collection_metadata_frame() -> pl.DataFrame:
    return pl.DataFrame(schema=_RUN_COLLECTION_METADATA_SCHEMA)


def empty_collection_metadata_validation_frame() -> pl.DataFrame:
    return pl.DataFrame(schema=_COLLECTION_METADATA_VALIDATION_SCHEMA)


def _validation_row(
    run: RunLapLabels,
    protocol: CollectionProtocol,
    protocol_sessions: pl.DataFrame,
) -> dict[str, object]:
    flags = _metadata_flags(run, protocol, protocol_sessions)
    return {
        "dataset_id": protocol.dataset_id,
        "run_id": run.run_id,
        "collection_protocol_id": run.collection_protocol_id,
        "collection_session_id": run.collection_session_id,
        "collection_design": run.collection_design,
        "target_zones": list(run.target_zones),
        "target_zones_source": run.target_zones_source,
        "execution_quality": run.execution_quality,
        "metadata_status": _metadata_status(flags),
        "metadata_flags": flags,
    }


def _metadata_flags(
    run: RunLapLabels,
    protocol: CollectionProtocol,
    protocol_sessions: pl.DataFrame,
) -> list[str]:
    flags = []
    if not run.collection_protocol_id:
        flags.append("missing_collection_protocol_id")
    elif run.collection_protocol_id != protocol.protocol_id:
        flags.append("collection_protocol_id_mismatch")

    if not run.collection_design:
        flags.append("missing_collection_design")
        return flags

    matching_sessions = protocol_sessions.filter(
        pl.col("collection_design") == run.collection_design
    )
    if matching_sessions.is_empty():
        flags.append("unknown_collection_design")
    if run.collection_session_id:
        matching_sessions = matching_sessions.filter(
            pl.col("session_id") == run.collection_session_id
        )
        if matching_sessions.is_empty():
            flags.append("unknown_collection_session_id")

    flags.extend(_target_zone_flags(run, matching_sessions))

    if not run.execution_quality:
        flags.append("missing_execution_quality")
    elif run.execution_quality not in VALID_EXECUTION_QUALITY_LABELS:
        flags.append("unknown_execution_quality")
    if not run.labels_quality:
        flags.append("missing_labels_quality")
    if (
        run.collection_design in DESIGNS_REQUIRING_LICO_PROFILE
        and not run.planned_lico_profile_id
    ):
        flags.append("missing_planned_lico_profile_id")
    if (
        run.collection_design == "recommendation_execution"
        and not run.audio_cue_plan_id
    ):
        flags.append("missing_audio_cue_plan_id")
    return flags


def _target_zone_flags(
    run: RunLapLabels,
    matching_sessions: pl.DataFrame,
) -> list[str]:
    if run.collection_design == "targeted_zone" and not run.target_zones:
        return ["missing_target_zones"]
    if run.target_zones_source:
        return []
    if matching_sessions.is_empty() or not run.target_zones:
        return []

    protocol_targets = set()
    for row in matching_sessions.iter_rows(named=True):
        protocol_targets.update(row["target_zones"] or [])
    unknown_targets = sorted(set(run.target_zones) - protocol_targets)
    return ["target_zones_not_in_protocol"] if unknown_targets else []


def _metadata_status(flags: list[str]) -> str:
    if not flags:
        return "ready"
    if any(flag.startswith("missing_") for flag in flags):
        return "needs_metadata"
    return "needs_review"


def _missing_metadata_value(column: str) -> pl.Expr:
    if column == "target_zones":
        return pl.col(column).is_null() | (pl.col(column).list.len() == 0)
    return pl.col(column).is_null() | (pl.col(column).cast(pl.String) == "")


_RUN_COLLECTION_METADATA_COLUMNS = [
    "dataset_id",
    "run_id",
    "file_name",
    "track",
    "car_class",
    "collection_label",
    "collection_protocol_id",
    "collection_session_id",
    "collection_design",
    "target_zones",
    "target_zones_source",
    "planned_lico_profile_id",
    "planned_lico_profile_description",
    "audio_cue_plan_id",
    "execution_quality",
    "labels_quality",
    "driver_notes",
]

_RUN_COLLECTION_METADATA_SCHEMA = {
    "dataset_id": pl.String,
    "run_id": pl.String,
    "file_name": pl.String,
    "track": pl.String,
    "car_class": pl.String,
    "collection_label": pl.String,
    "collection_protocol_id": pl.String,
    "collection_session_id": pl.String,
    "collection_design": pl.String,
    "target_zones": pl.List(pl.String),
    "target_zones_source": pl.String,
    "planned_lico_profile_id": pl.String,
    "planned_lico_profile_description": pl.String,
    "audio_cue_plan_id": pl.String,
    "execution_quality": pl.String,
    "labels_quality": pl.String,
    "driver_notes": pl.String,
}

_COLLECTION_METADATA_VALIDATION_COLUMNS = [
    "dataset_id",
    "run_id",
    "collection_protocol_id",
    "collection_session_id",
    "collection_design",
    "target_zones",
    "target_zones_source",
    "execution_quality",
    "metadata_status",
    "metadata_flags",
]

_COLLECTION_METADATA_VALIDATION_SCHEMA = {
    "dataset_id": pl.String,
    "run_id": pl.String,
    "collection_protocol_id": pl.String,
    "collection_session_id": pl.String,
    "collection_design": pl.String,
    "target_zones": pl.List(pl.String),
    "target_zones_source": pl.String,
    "execution_quality": pl.String,
    "metadata_status": pl.String,
    "metadata_flags": pl.List(pl.String),
}
