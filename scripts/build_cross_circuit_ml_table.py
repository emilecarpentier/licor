from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import polars as pl

from licor.analysis.cross_circuit_ml import (
    attach_fold_push_references,
    build_cross_circuit_observations,
    build_split_assignments,
    evaluate_monotone_action_acceleration_baseline,
    evaluate_monotone_action_only_baseline,
    extract_physical_braking_events,
    feature_registry_frame,
    fit_fold_push_references,
    load_feature_contract,
    load_split_manifest,
    validate_feature_contract,
)
from licor.analysis.experimental_zone_dynamics import (
    build_labeled_experimental_lap_samples,
    summarize_experimental_zone_dynamics,
)
from licor.analysis.lap_summary import DatasetLapLabels, load_dataset_lap_labels
from licor.analysis.processed_artifacts import build_labeled_zone_passes


@dataclass(frozen=True)
class DatasetSource:
    dataset_file: str
    track_zone_file: str
    driver_review_file: str
    circuit_id: str
    track_length_m: float


SOURCES = (
    DatasetSource(
        dataset_file="config/datasets/spa_lmp2_v2_2026-05-21.json",
        track_zone_file="config/track_zones/spa_lmp2_zones.draft.json",
        driver_review_file="config/driver_reviews/spa_lmp2_v2_zone_review_2026-05-21.json",
        circuit_id="spa_francorchamps",
        track_length_m=7004.0,
    ),
    DatasetSource(
        dataset_file="config/datasets/paul_ricard_lmp2_2026-09-07.json",
        track_zone_file="config/track_zones/paul_ricard_lmp2_zones.draft.json",
        driver_review_file="config/driver_reviews/paul_ricard_zone_review_2026-09-07.json",
        circuit_id="paul_ricard",
        track_length_m=5842.0,
    ),
)

FEATURE_CONTRACT = "config/ml/licor_lmp2_feature_contract_v1.json"
SPLIT_MANIFEST = "config/ml/licor_lmp2_split_manifest_v1.json"
OUTPUT_DIR = "data/processed/experimental/cross_circuit_ml_v1"
EXTRACTOR_VERSION = "cross_circuit_ml_v1"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the leakage-safe LICOR Spa-Paul ML observation pack."
    )
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--output-dir", default=OUTPUT_DIR)
    args = parser.parse_args()
    root = Path(args.project_root).resolve()
    output = root / args.output_dir

    observations = []
    source_manifest = []
    for source in SOURCES:
        frame, metadata = _build_source(root, source)
        observations.append(frame)
        source_manifest.append(metadata)
    pooled = pl.concat(observations, how="diagonal_relaxed")

    feature_contract_path = root / FEATURE_CONTRACT
    split_manifest_path = root / SPLIT_MANIFEST
    feature_contract = load_feature_contract(feature_contract_path)
    validate_feature_contract(pooled, feature_contract)
    feature_registry = feature_registry_frame(feature_contract)
    split_manifest = load_split_manifest(split_manifest_path)
    assignments = build_split_assignments(pooled, split_manifest)

    references = []
    fold_views = []
    for fold in split_manifest["folds"]:
        fold_id = str(fold["fold_id"])
        fold_references = fit_fold_push_references(
            pooled,
            assignments,
            fold_id=fold_id,
            minimum_support=int(split_manifest.get("minimum_push_support_per_zone", 3)),
            maximum_deceleration_cv=float(
                split_manifest.get("maximum_push_deceleration_cv", 0.15)
            ),
        )
        references.append(fold_references)
        fold_views.append(
            attach_fold_push_references(
                pooled,
                assignments,
                fold_references,
                fold_id=fold_id,
            )
        )

    output.mkdir(parents=True, exist_ok=True)
    _write_frame(pooled, output / "licor_lmp2_zone_observations")
    braking_quality = (
        pooled.filter(pl.col("is_push_reference_candidate"))
        .group_by("circuit_id", "zone_id", "braking_event_quality")
        .len(name="pass_count")
        .sort("circuit_id", "zone_id", "braking_event_quality")
    )
    braking_quality.write_csv(output / "push_braking_event_quality.csv")
    feature_registry.with_columns(
        pl.col("model_tasks").list.join("|").alias("model_tasks")
    ).write_csv(output / "feature_registry.csv")
    assignments.write_csv(output / "split_assignments.csv")
    all_references = pl.concat(references, how="diagonal_relaxed")
    all_references.write_csv(output / "fold_push_references.csv")
    all_fold_views = pl.concat(fold_views, how="diagonal_relaxed")
    _write_frame(all_fold_views, output / "fold_feature_views")
    action_predictions, action_metrics = evaluate_monotone_action_only_baseline(
        all_fold_views
    )
    paired_action_predictions, paired_action_metrics = (
        evaluate_monotone_action_only_baseline(
            all_fold_views, require_acceleration_profile=True
        )
    )
    acceleration_predictions, acceleration_metrics = (
        evaluate_monotone_action_acceleration_baseline(all_fold_views)
    )
    diagnostic_predictions = pl.concat(
        [action_predictions, paired_action_predictions, acceleration_predictions],
        how="diagonal_relaxed",
    )
    diagnostic_metrics = pl.concat(
        [action_metrics, paired_action_metrics, acceleration_metrics],
        how="diagonal_relaxed",
    )
    diagnostic_predictions.write_csv(output / "diagnostic_action_only_predictions.csv")
    diagnostic_metrics.write_csv(output / "diagnostic_action_only_metrics.csv")

    build_manifest = {
        "schema_version": 1,
        "artifact_id": "licor_lmp2_cross_circuit_ml_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "extractor_version": EXTRACTOR_VERSION,
        "feature_contract": _file_record(feature_contract_path),
        "split_manifest": _file_record(split_manifest_path),
        "locked_external_holdout_run_ids": split_manifest.get(
            "locked_external_holdout_run_ids", []
        ),
        "sources": source_manifest,
        "counts": {
            "observations": pooled.height,
            "model_eligible_observations": pooled.filter(
                pl.col("model_eligible")
            ).height,
            "circuits": pooled["circuit_id"].n_unique(),
            "runs": pooled["run_id"].n_unique(),
            "zones": pooled.select("circuit_id", "zone_id").unique().height,
            "folds": len(split_manifest["folds"]),
            "score_rows": assignments.filter(pl.col("score_eligible")).height,
            "ready_push_references": all_references.filter(
                pl.col("push_reference_status") == "ready"
            ).height,
            "diagnostic_predictions": diagnostic_predictions.height,
            "acceleration_profile_ready_references": all_references.filter(
                pl.col("push_acceleration_profile_status") == "ready"
            ).height,
        },
        "artifacts": {
            path.name: _file_record(path)
            for path in sorted(output.iterdir())
            if path.name != "build_manifest.json"
        },
        "guardrails": [
            "No globally fitted baseline or delta is present in the raw observation table.",
            "Push references are fitted independently inside each fold from train/calibration rows only.",
            "The Paul Ricard live confirmation run remains an external locked holdout.",
            "Observed-action and post-action fields are excluded from pre-action decision features by contract.",
            "Acceleration at a proposed lift is interpolated from fold-local clean-push profiles, never from the held-out LICO outcome.",
        ],
    }
    (output / "build_manifest.json").write_text(
        json.dumps(build_manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(build_manifest["counts"], indent=2))


def _build_source(root: Path, source: DatasetSource) -> tuple[pl.DataFrame, dict]:
    dataset_path = root / source.dataset_file
    zone_path = root / source.track_zone_file
    review_path = root / source.driver_review_file
    labels = load_dataset_lap_labels(dataset_path)
    available_run_ids = {
        run.run_id
        for run in labels.runs
        if run.include_in_lap_summary and (root / run.file).is_file()
    }
    zone_passes = build_labeled_zone_passes(
        dataset_label_file=dataset_path,
        track_zone_file=zone_path,
        driver_review_file=review_path,
        project_root=root,
        include_run_ids=available_run_ids,
    )
    lap_samples = build_labeled_experimental_lap_samples(
        dataset_label_file=dataset_path,
        project_root=root,
        include_run_ids=available_run_ids,
    )
    dynamics = summarize_experimental_zone_dynamics(zone_passes, lap_samples)
    events = extract_physical_braking_events(
        zone_passes,
        lap_samples,
        track_length_m=source.track_length_m,
    )
    raw_hashes = _raw_hashes(root, labels, include_run_ids=available_run_ids)
    run_metadata = _run_metadata(labels, raw_hashes)
    observations = build_cross_circuit_observations(
        dynamics,
        zone_passes,
        events,
        run_metadata,
        dataset_id=labels.dataset_id,
        circuit_id=source.circuit_id,
        track_length_m=source.track_length_m,
        zone_definition_version=_sha256(zone_path),
        extractor_version=EXTRACTOR_VERSION,
    )
    return observations, {
        "dataset": _file_record(dataset_path),
        "track_zones": _file_record(zone_path),
        "driver_review": _file_record(review_path),
        "circuit_id": source.circuit_id,
        "track_length_m": source.track_length_m,
        "raw_files": len(raw_hashes),
        "unavailable_run_ids": sorted(
            run.run_id
            for run in labels.runs
            if run.include_in_lap_summary and run.run_id not in available_run_ids
        ),
    }


def _run_metadata(labels: DatasetLapLabels, raw_hashes: dict[str, str]) -> pl.DataFrame:
    return pl.DataFrame(
        [
            {
                "run_id": run.run_id,
                "source_raw_sha256": raw_hashes[run.run_id],
                "track_name": run.track,
                "car_class": run.car_class,
                "car_model": run.car,
                "session_type": run.session_type,
                "run_type": run.run_type,
                "collection_protocol_id": run.collection_protocol_id,
                "collection_session_id": run.collection_session_id,
                "labels_quality": run.labels_quality,
                "execution_quality": run.execution_quality,
                "driver_id": None,
                "setup_id": None,
            }
            for run in labels.runs
            if run.include_in_lap_summary and run.run_id in raw_hashes
        ],
        schema={
            "run_id": pl.String,
            "source_raw_sha256": pl.String,
            "track_name": pl.String,
            "car_class": pl.String,
            "car_model": pl.String,
            "session_type": pl.String,
            "run_type": pl.String,
            "collection_protocol_id": pl.String,
            "collection_session_id": pl.String,
            "labels_quality": pl.String,
            "execution_quality": pl.String,
            "driver_id": pl.String,
            "setup_id": pl.String,
        },
    )


def _raw_hashes(
    root: Path,
    labels: DatasetLapLabels,
    *,
    include_run_ids: set[str],
) -> dict[str, str]:
    hashes = {}
    seen_hashes: dict[str, str] = {}
    for run in labels.runs:
        if not run.include_in_lap_summary or run.run_id not in include_run_ids:
            continue
        path = root / run.file
        digest = _sha256(path)
        if digest in seen_hashes:
            raise ValueError(
                f"duplicate raw telemetry content for {run.run_id} and {seen_hashes[digest]}"
            )
        hashes[run.run_id] = digest
        seen_hashes[digest] = run.run_id
    return hashes


def _write_frame(frame: pl.DataFrame, base_path: Path) -> None:
    csv_frame = frame.with_columns(
        [
            pl.col(column)
            .list.eval(pl.element().cast(pl.String))
            .list.join("|")
            .alias(column)
            for column, dtype in frame.schema.items()
            if isinstance(dtype, pl.List)
        ]
    )
    csv_frame.write_csv(base_path.with_suffix(".csv"))
    frame.write_parquet(base_path.with_suffix(".parquet"))


def _file_record(path: Path) -> dict[str, object]:
    return {
        "path": path.as_posix(),
        "sha256": _sha256(path),
        "size_bytes": path.stat().st_size,
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    main()
