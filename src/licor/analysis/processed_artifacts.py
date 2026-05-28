from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import polars as pl

from licor.analysis.collection_protocol import load_collection_protocol
from licor.analysis.data_readiness import (
    DataReadinessConfig,
    summarize_collection_protocol_readiness,
    summarize_zone_data_readiness,
)
from licor.analysis.driver_review import apply_zone_pass_review, load_driver_zone_review
from licor.analysis.lap_quality import (
    LapQualityManifestConfig,
    build_lap_quality_manifest,
    write_lap_quality_manifest_csv,
)
from licor.analysis.lap_summary import (
    LapSummaryConfig,
    load_dataset_lap_labels,
    summarize_labeled_dataset,
)
from licor.analysis.track_zones import load_track_zone_table
from licor.analysis.zone_detection import build_lap_telemetry
from licor.analysis.zone_pass import ZonePassConfig, extract_zone_passes
from licor.ingestion import LmuTelemetryDatabase


@dataclass(frozen=True)
class ZonePassArtifactPaths:
    zone_passes_csv: Path
    zone_passes_parquet: Path | None = None


@dataclass(frozen=True)
class DataReadinessArtifactPaths:
    zone_readiness_csv: Path
    protocol_readiness_csv: Path


@dataclass(frozen=True)
class LapQualityManifestArtifactPaths:
    lap_quality_manifest_csv: Path


@dataclass(frozen=True)
class SpaV2ReadinessArtifactPaths:
    zone_passes_csv: Path
    zone_passes_parquet: Path | None
    zone_readiness_csv: Path
    protocol_readiness_csv: Path


@dataclass(frozen=True)
class SpaV2QualityArtifactPaths:
    lap_quality_manifest_csv: Path


def build_labeled_zone_passes(
    *,
    dataset_label_file: str | Path,
    track_zone_file: str | Path,
    project_root: str | Path = ".",
    driver_review_file: str | Path | None = None,
    config: ZonePassConfig | None = None,
) -> pl.DataFrame:
    """Rebuild zone-pass observations from labeled LMU telemetry files."""

    labels = load_dataset_lap_labels(dataset_label_file)
    zone_table = load_track_zone_table(track_zone_file)
    root = Path(project_root)
    frames = []
    for run in labels.runs:
        if not run.include_in_lap_summary:
            continue
        lap_numbers = set(run.valid_laps | run.borderline_laps)
        if not lap_numbers:
            continue
        with LmuTelemetryDatabase(root / run.file) as telemetry:
            samples = build_lap_telemetry(telemetry, lap_numbers=lap_numbers)
        passes = extract_zone_passes(
            samples,
            zone_table,
            run_labels=run,
            config=config,
        )
        if not passes.is_empty():
            frames.append(passes)

    if not frames:
        return _empty_zone_pass_frame(zone_table=zone_table, config=config)

    zone_passes = pl.concat(frames, how="diagonal").sort(["run_id", "lap_number", "zone_id"])
    if driver_review_file is not None:
        zone_passes = apply_zone_pass_review(
            zone_passes,
            load_driver_zone_review(driver_review_file),
        )
    return zone_passes


def build_labeled_lap_samples(
    *,
    dataset_label_file: str | Path,
    project_root: str | Path = ".",
) -> pl.DataFrame:
    """Rebuild normalized lap telemetry samples from labelled LMU files."""

    labels = load_dataset_lap_labels(dataset_label_file)
    root = Path(project_root)
    frames = []
    for run in labels.runs:
        if not run.include_in_lap_summary:
            continue
        lap_numbers = set(run.valid_laps | run.borderline_laps)
        if not lap_numbers:
            continue
        with LmuTelemetryDatabase(root / run.file) as telemetry:
            samples = build_lap_telemetry(telemetry, lap_numbers=lap_numbers)
        if samples.is_empty():
            continue
        frames.append(
            samples.with_columns(
                pl.lit(run.run_id).alias("run_id"),
                pl.lit(Path(run.file).name).alias("file_name"),
                pl.lit(run.collection_label).alias("collection_label"),
                pl.lit(run.collection_design).alias("collection_design"),
                pl.lit(run.execution_quality).alias("execution_quality"),
            )
        )
    if not frames:
        return pl.DataFrame()
    return pl.concat(frames, how="diagonal").sort(["run_id", "lap_number", "ts"])


def write_zone_pass_artifacts(
    zone_passes: pl.DataFrame,
    *,
    csv_path: str | Path,
    parquet_path: str | Path | None = None,
) -> ZonePassArtifactPaths:
    """Persist zone passes to CSV and optionally parquet."""

    csv_output = _write_csv(zone_passes, csv_path)
    parquet_output = _write_parquet(zone_passes, parquet_path) if parquet_path else None
    return ZonePassArtifactPaths(
        zone_passes_csv=csv_output,
        zone_passes_parquet=parquet_output,
    )


def write_data_readiness_artifacts(
    zone_passes: pl.DataFrame,
    *,
    protocol_file: str | Path,
    zone_readiness_csv_path: str | Path,
    protocol_readiness_csv_path: str | Path,
    live_cue_events: pl.DataFrame | None = None,
    config: DataReadinessConfig | None = None,
) -> DataReadinessArtifactPaths:
    """Persist zone and protocol readiness summaries."""

    protocol_sessions = load_collection_protocol(protocol_file).to_frame()
    zone_readiness = summarize_zone_data_readiness(zone_passes, config=config)
    protocol_readiness = summarize_collection_protocol_readiness(
        zone_passes,
        protocol_sessions,
        live_cue_events=live_cue_events,
        config=config,
    )
    return DataReadinessArtifactPaths(
        zone_readiness_csv=_write_csv(zone_readiness, zone_readiness_csv_path),
        protocol_readiness_csv=_write_csv(
            protocol_readiness,
            protocol_readiness_csv_path,
        ),
    )


def write_lap_quality_manifest_artifact(
    manifest: pl.DataFrame,
    *,
    csv_path: str | Path,
) -> LapQualityManifestArtifactPaths:
    return LapQualityManifestArtifactPaths(
        lap_quality_manifest_csv=write_lap_quality_manifest_csv(manifest, csv_path),
    )


def build_spa_v2_readiness_artifacts(
    *,
    project_root: str | Path = ".",
    output_dir: str | Path = "data/processed",
    dataset_label_file: str | Path = "config/datasets/spa_lmp2_v2_2026-05-21.json",
    track_zone_file: str | Path = "config/track_zones/spa_lmp2_zones.draft.json",
    driver_review_file: str | Path = "config/driver_reviews/spa_lmp2_v2_zone_review_2026-05-21.json",
    protocol_file: str | Path = "config/collection_protocols/spa_lmp2_v2_protocol.json",
    live_cue_events_csv: str | Path | None = None,
    write_parquet: bool = True,
    zone_pass_config: ZonePassConfig | None = None,
    readiness_config: DataReadinessConfig | None = None,
) -> SpaV2ReadinessArtifactPaths:
    """Build current Spa zone-pass and Spa v2 readiness artifacts."""

    root = Path(project_root)
    output = root / output_dir
    zone_passes = build_labeled_zone_passes(
        dataset_label_file=root / dataset_label_file,
        track_zone_file=root / track_zone_file,
        project_root=root,
        driver_review_file=root / driver_review_file if driver_review_file else None,
        config=zone_pass_config,
    )
    zone_paths = write_zone_pass_artifacts(
        zone_passes,
        csv_path=output / "spa_lmp2_zone_passes.csv",
        parquet_path=(
            output / "spa_lmp2_zone_passes.parquet"
            if write_parquet
            else None
        ),
    )
    live_cue_events = (
        pl.read_csv(root / live_cue_events_csv)
        if live_cue_events_csv is not None
        else None
    )
    readiness_paths = write_data_readiness_artifacts(
        zone_passes,
        protocol_file=root / protocol_file,
        zone_readiness_csv_path=output / "spa_lmp2_v2_zone_data_readiness.csv",
        protocol_readiness_csv_path=output / "spa_lmp2_v2_protocol_readiness.csv",
        live_cue_events=live_cue_events,
        config=readiness_config,
    )
    return SpaV2ReadinessArtifactPaths(
        zone_passes_csv=zone_paths.zone_passes_csv,
        zone_passes_parquet=zone_paths.zone_passes_parquet,
        zone_readiness_csv=readiness_paths.zone_readiness_csv,
        protocol_readiness_csv=readiness_paths.protocol_readiness_csv,
    )


def build_spa_v2_quality_artifacts(
    *,
    project_root: str | Path = ".",
    output_dir: str | Path = "data/processed",
    dataset_label_file: str | Path = "config/datasets/spa_lmp2_v2_2026-05-21.json",
    track_zone_file: str | Path = "config/track_zones/spa_lmp2_zones.draft.json",
    driver_review_file: str | Path = "config/driver_reviews/spa_lmp2_v2_zone_review_2026-05-21.json",
    lap_summary_config: LapSummaryConfig | None = None,
    zone_pass_config: ZonePassConfig | None = None,
    quality_config: LapQualityManifestConfig | None = None,
) -> SpaV2QualityArtifactPaths:
    """Build current Spa run/lap quality manifest artifact."""

    root = Path(project_root)
    output = root / output_dir
    lap_summary = summarize_labeled_dataset(
        root / dataset_label_file,
        project_root=root,
        config=lap_summary_config,
    )
    lap_samples = build_labeled_lap_samples(
        dataset_label_file=root / dataset_label_file,
        project_root=root,
    )
    zone_passes = build_labeled_zone_passes(
        dataset_label_file=root / dataset_label_file,
        track_zone_file=root / track_zone_file,
        project_root=root,
        driver_review_file=root / driver_review_file if driver_review_file else None,
        config=zone_pass_config,
    )
    manifest = build_lap_quality_manifest(
        lap_summary,
        lap_samples=lap_samples,
        zone_passes=zone_passes,
        config=quality_config,
    )
    return write_lap_quality_manifest_artifact(
        manifest,
        csv_path=output / "spa_lmp2_v2_lap_quality_manifest.csv",
    )


def _empty_zone_pass_frame(
    *,
    zone_table,
    config: ZonePassConfig | None,
) -> pl.DataFrame:
    return extract_zone_passes(
        pl.DataFrame(),
        zone_table,
        config=config,
    )


def _write_csv(frame: pl.DataFrame, path: str | Path) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _csv_safe_frame(frame).write_csv(output_path)
    return output_path


def _write_parquet(frame: pl.DataFrame, path: str | Path) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    frame.write_parquet(output_path)
    return output_path


def _csv_safe_frame(frame: pl.DataFrame) -> pl.DataFrame:
    list_columns = [
        column
        for column, dtype in frame.schema.items()
        if isinstance(dtype, pl.List)
    ]
    if not list_columns:
        return frame
    return frame.with_columns(
        [
            pl.col(column)
            .list.eval(pl.element().cast(pl.String))
            .list.join("|")
            .alias(column)
            for column in list_columns
        ]
    )
