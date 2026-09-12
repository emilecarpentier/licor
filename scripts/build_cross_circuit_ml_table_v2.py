"""Build a versioned Spa/Paul/Bahrain retrospective transfer benchmark."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import polars as pl

from licor.analysis.cross_circuit_ml import (
    BrakingEventConfig,
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
    ExperimentalZoneDynamicsConfig,
    build_labeled_experimental_lap_samples,
    summarize_experimental_zone_dynamics,
)
from licor.analysis.lap_summary import load_dataset_lap_labels
from licor.analysis.fixed_distance import NativeDistanceTrace
from licor.analysis.processed_artifacts import build_labeled_zone_passes
from licor.analysis.zone_pass import ZonePassConfig
from licor.ingestion import LmuTelemetryDatabase


PROJECT_ROOT = Path(__file__).resolve().parents[1]
V1_DIR = Path("data/processed/experimental/cross_circuit_ml_v1")
OUTPUT_DIR = Path("data/processed/experimental/cross_circuit_ml_v2")
DATASET_FILE = Path("config/datasets/bahrain_lmp2_circuit_c_2026-09.json")
ZONE_FILE = Path("config/track_zones/bahrain_lmp2_zones.draft.json")
REVIEW_FILE = Path("config/driver_reviews/bahrain_lmp2_push_review_2026-09-11.json")
SPLIT_FILE = Path("config/ml/licor_lmp2_split_manifest_v2.json")
FEATURE_FILE = Path("config/ml/licor_lmp2_feature_contract_v1.json")
BAHRAIN_PUSH = "bahrain_push_20260911_212732"
BAHRAIN_LICO = "bahrain_lico_20260911_224825"
BAHRAIN_SESSION = (
    Path("data/processed/experimental/bahrain_lmp2_transfer_2026_09/sessions")
    / BAHRAIN_LICO
)
PUSH_LAPS = (23, 26, 29)
LICO_LAPS = (24, 25, 27, 28)
SELECTED_ZONES = (
    "bhr_t01_t03",
    "bhr_t04",
    "bhr_t08",
    "bhr_t10",
    "bhr_t11",
    "bhr_t14_t15",
)


def file_record(path: Path) -> dict:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return {
        "path": path.as_posix(),
        "sha256": digest.hexdigest(),
        "size_bytes": path.stat().st_size,
    }


def apply_bahrain_schedule(
    observations: pl.DataFrame, plan: pl.DataFrame
) -> pl.DataFrame:
    """Keep detector evidence while treating the frozen schedule as treatment."""
    known = pl.col("run_id").is_in([BAHRAIN_PUSH, BAHRAIN_LICO])
    if observations.filter(~known).height:
        raise ValueError("unexpected run in Bahrain schedule input")
    unexpected = observations.filter(
        (pl.col("run_id") == BAHRAIN_LICO)
        & ~pl.col("lap_number").is_in([*PUSH_LAPS, *LICO_LAPS])
    )
    if unexpected.height:
        raise ValueError("Bahrain observation outside frozen scored schedule")
    is_lico_lap = (pl.col("run_id") == BAHRAIN_LICO) & pl.col("lap_number").is_in(
        LICO_LAPS
    )
    frame = observations.with_columns(
        pl.col("has_lico").alias("observed_has_lico"),
        pl.when(is_lico_lap)
        .then(pl.lit("lico"))
        .otherwise(pl.lit("push"))
        .alias("scheduled_lap_role"),
        (is_lico_lap & pl.col("zone_id").is_in(SELECTED_ZONES)).alias(
            "scheduled_action_enabled"
        ),
    ).with_columns(
        pl.col("scheduled_action_enabled").alias("has_lico"),
        (pl.col("scheduled_lap_role") == "push").alias("is_push_reference_candidate"),
    )
    return (
        frame.drop("planned_lift_start_m")
        .join(plan.select("zone_id", "planned_lift_start_m"), on="zone_id", how="left")
        .with_columns(
            pl.when(pl.col("scheduled_action_enabled"))
            .then(pl.col("planned_lift_start_m"))
            .otherwise(None)
            .alias("planned_lift_start_m"),
            pl.col("lico_start_m").alias("observed_lico_start_m"),
            pl.when(pl.col("scheduled_action_enabled"))
            .then(pl.col("lico_start_m"))
            .otherwise(None)
            .alias("lico_start_m"),
            pl.lit("frozen_schedule_and_native_execution").alias(
                "treatment_label_source"
            ),
        )
    )


def apply_phase_masks(observations: pl.DataFrame, review: dict) -> pl.DataFrame:
    """Preserve clean approach evidence on reviewed partial-error push laps."""
    frame = observations.with_columns(
        pl.col("validity_label").is_in(["valid", "borderline"]).alias("model_eligible"),
        pl.lit("").alias("phase_mask_reason"),
    )
    for mask in review.get("phase_metric_masks", []):
        selected = (
            (pl.col("run_id") == mask["run_id"])
            & (pl.col("lap_number") == mask["lap_number"])
            & (pl.col("zone_id") == mask["zone_id"])
        )
        columns = []
        excluded = set(mask["excluded_metrics"])
        mapping = {
            "zone_elapsed_time": ["elapsed_time_s"],
            "zone_fuel_used": ["fuel_used_l"],
            "exit_speed": ["exit_speed_kph"],
            "apex_speed": [
                "min_speed_point_kph",
                "min_speed_point_m",
                "push_deceleration_distance_observed_m",
                "approach_acceleration_ratio_0_25_mps2",
                "approach_acceleration_ratio_0_5_mps2",
                "approach_acceleration_ratio_1_0_mps2",
                "approach_acceleration_ratio_1_5_mps2",
            ],
            "pre_action_acceleration": [
                "approach_acceleration_ratio_0_0_mps2",
                "approach_acceleration_ratio_0_25_mps2",
                "approach_acceleration_ratio_0_5_mps2",
                "approach_acceleration_ratio_1_0_mps2",
                "approach_acceleration_ratio_1_5_mps2",
            ],
        }
        for metric in excluded:
            columns.extend(mapping.get(metric, []))
        frame = frame.with_columns(
            *[
                pl.when(selected).then(None).otherwise(pl.col(column)).alias(column)
                for column in columns
                if column in frame.columns
            ],
            pl.when(selected)
            .then(pl.lit(mask["reason"]))
            .otherwise(pl.col("phase_mask_reason"))
            .alias("phase_mask_reason"),
        )
    if "driver_review_exclusion_reason" in frame.columns:
        frame = frame.with_columns(
            (
                pl.col("model_eligible")
                & (pl.col("driver_review_exclusion_reason").fill_null("") == "")
            ).alias("model_eligible")
        )
    return frame


def build_bahrain_observations(root: Path) -> tuple[pl.DataFrame, dict]:
    labels = load_dataset_lap_labels(root / DATASET_FILE)
    run_ids = {BAHRAIN_PUSH, BAHRAIN_LICO}
    passes = build_labeled_zone_passes(
        dataset_label_file=root / DATASET_FILE,
        track_zone_file=root / ZONE_FILE,
        driver_review_file=root / REVIEW_FILE,
        project_root=root,
        include_run_ids=run_ids,
        config=ZonePassConfig(
            require_driver_reviewed=False,
            optimization_roles=("candidate", "validation_only"),
        ),
    )
    samples = build_labeled_experimental_lap_samples(
        dataset_label_file=root / DATASET_FILE,
        project_root=root,
        include_run_ids=run_ids,
    )
    dynamics = summarize_experimental_zone_dynamics(
        passes,
        samples,
        config=ExperimentalZoneDynamicsConfig(valid_labels=("valid", "borderline")),
    )
    events = extract_physical_braking_events(
        passes,
        samples,
        track_length_m=5385.0,
        config=BrakingEventConfig(post_zone_capture_margin_m=75.0),
    )
    raw_records = [
        file_record(root / run.file) for run in labels.runs if run.run_id in run_ids
    ]
    metadata = pl.DataFrame(
        [
            {
                "run_id": run.run_id,
                "source_raw_sha256": file_record(root / run.file)["sha256"],
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
            if run.run_id in run_ids
        ]
    )
    observations = build_cross_circuit_observations(
        dynamics,
        passes,
        events,
        metadata,
        dataset_id=labels.dataset_id,
        circuit_id="bahrain",
        track_length_m=5385.0,
        zone_definition_version=file_record(root / ZONE_FILE)["sha256"],
        extractor_version="cross_circuit_ml_v2",
    )
    observations = apply_bahrain_schedule(
        observations, pl.read_csv(root / BAHRAIN_SESSION / "plan.csv")
    )
    return observations, {
        "raw_files": raw_records,
        "dataset": file_record(root / DATASET_FILE),
        "zones": file_record(root / ZONE_FILE),
        "review": file_record(root / REVIEW_FILE),
    }


def replace_native_outcomes(
    root: Path, observations: pl.DataFrame
) -> tuple[pl.DataFrame, list]:
    """Recompute every circuit with one fixed-distance per-channel timestamp rule."""
    dataset_files = [
        "config/datasets/spa_lmp2_v2_2026-05-21.json",
        "config/datasets/paul_ricard_lmp2_2026-09-07.json",
        DATASET_FILE,
    ]
    files = {
        run.run_id: root / run.file
        for dataset_file in dataset_files
        for run in load_dataset_lap_labels(root / dataset_file).runs
    }
    rows, sources = [], []
    for (run_id,), group in observations.group_by("run_id", maintain_order=True):
        path = files[run_id]
        source = file_record(path)
        hashes = group["source_raw_sha256"].unique().to_list()
        if hashes != [source["sha256"]]:
            raise ValueError(f"raw source hash changed for {run_id}")
        sources.append({"run_id": run_id, **source})
        with LmuTelemetryDatabase(path) as telemetry:
            trace = NativeDistanceTrace.from_database(telemetry)
            for row in group.iter_rows(named=True):
                for name in ("elapsed_time_s", "fuel_used_l", "exit_speed_kph"):
                    row[f"legacy_{name}"] = row[name]
                    row[name] = None
                try:
                    values = trace.outcome(
                        int(row["lap_number"]),
                        float(row["zone_start_m"]),
                        float(row["zone_end_m"]),
                    )
                except (ValueError, KeyError) as error:
                    row["fixed_distance_status"] = str(error)
                else:
                    row.update(
                        {
                            name: values[name]
                            for name in (
                                "elapsed_time_s",
                                "fuel_used_l",
                                "exit_speed_kph",
                            )
                        }
                    )
                    row["fixed_distance_status"] = "ready"
                row["outcome_definition"] = "fixed_distance_native_v2_frozen_endpoints"
                rows.append(row)
    return pl.DataFrame(rows, infer_schema_length=None), sources


def fit_supported_references(
    observations: pl.DataFrame,
    assignments: pl.DataFrame,
    *,
    fold_id: str,
    minimum_support: int = 3,
    maximum_deceleration_cv: float = 0.15,
) -> pl.DataFrame:
    references = fit_fold_push_references(
        observations,
        assignments,
        fold_id=fold_id,
        minimum_support=minimum_support,
        maximum_deceleration_cv=maximum_deceleration_cv,
    )
    ids = assignments.filter(
        (pl.col("fold_id") == fold_id) & pl.col("push_reference_eligible")
    )["observation_id"]
    supports = observations.filter(
        pl.col("observation_id").is_in(ids.implode())
        & (pl.col("braking_event_quality") == "ready")
    )
    counts = supports.group_by("circuit_id", "zone_id").agg(
        pl.col("fuel_used_l").count().alias("push_fuel_support"),
        pl.col("elapsed_time_s").count().alias("push_time_support"),
        pl.col("push_deceleration_distance_observed_m")
        .count()
        .alias("push_deceleration_support"),
    )
    return references.join(
        counts, on=["circuit_id", "zone_id"], how="left"
    ).with_columns(
        pl.when(pl.col("push_deceleration_support") < minimum_support)
        .then(pl.lit("insufficient_push_denominator_support"))
        .otherwise(pl.col("push_reference_status"))
        .alias("push_reference_status"),
        pl.when(pl.col("push_fuel_support") >= minimum_support)
        .then(pl.col("push_fuel_used_reference_l"))
        .otherwise(None)
        .alias("push_fuel_used_reference_l"),
        pl.when(pl.col("push_time_support") >= minimum_support)
        .then(pl.col("push_elapsed_time_reference_s"))
        .otherwise(None)
        .alias("push_elapsed_time_reference_s"),
    )


def restrict_response_actions(view: pl.DataFrame) -> pl.DataFrame:
    """Do not let naturally detected coasts on scheduled push laps fit responses."""
    return view.with_columns(
        [
            pl.when(pl.col("has_lico"))
            .then(pl.col(column))
            .otherwise(None)
            .alias(column)
            for column in (
                "executed_lift_lead_to_push_deceleration_ratio",
                "executed_acceleration_weighted_action",
            )
        ]
    )


def write_frame(frame: pl.DataFrame, path: Path) -> None:
    frame.write_parquet(path.with_suffix(".parquet"))
    frame.with_columns(
        [
            pl.col(column).list.eval(pl.element().cast(pl.String)).list.join("|")
            for column, dtype in frame.schema.items()
            if isinstance(dtype, pl.List)
        ]
    ).write_csv(path.with_suffix(".csv"))


def build_pack(root: Path, output: Path) -> dict:
    if output.exists():
        raise FileExistsError(f"refusing to replace versioned ML pack: {output}")
    history_path = root / V1_DIR / "licor_lmp2_zone_observations.parquet"
    history_manifest_path = root / V1_DIR / "build_manifest.json"
    history_manifest = json.loads(history_manifest_path.read_text(encoding="utf-8"))
    expected_history_hash = history_manifest["artifacts"][history_path.name]["sha256"]
    if file_record(history_path)["sha256"] != expected_history_hash:
        raise ValueError("frozen v1 observation hash mismatch")
    history = pl.read_parquet(history_path).with_columns(
        pl.col("has_lico").alias("observed_has_lico"),
        pl.lit("historical_detector").alias("treatment_label_source"),
        pl.lit(None, dtype=pl.String).alias("scheduled_lap_role"),
        pl.lit(None, dtype=pl.Boolean).alias("scheduled_action_enabled"),
        pl.lit("").alias("phase_mask_reason"),
        pl.col("lico_start_m").alias("observed_lico_start_m"),
    )
    bahrain, bahrain_sources = build_bahrain_observations(root)
    pooled, native_sources = replace_native_outcomes(
        root, pl.concat([history, bahrain], how="diagonal_relaxed")
    )
    pooled = pl.concat(
        [
            pooled.filter(pl.col("circuit_id") != "bahrain"),
            apply_phase_masks(
                pooled.filter(pl.col("circuit_id") == "bahrain"),
                json.loads((root / REVIEW_FILE).read_text(encoding="utf-8")),
            ),
        ],
        how="diagonal_relaxed",
    ).with_columns(
        pl.lit("retrospective_executed_action_response").alias("evaluation_provenance")
    )
    contract = load_feature_contract(root / FEATURE_FILE)
    contract["contract_id"] = "licor_lmp2_feature_contract_v2"
    contract["column_groups"].append(
        {
            "role": "v2_provenance_and_legacy_diagnostic",
            "availability": "audit_only",
            "model_tasks": [],
            "default_definition": "Treatment schedule, outcome provenance or superseded value; never a decision predictor.",
            "columns": [
                "evaluation_provenance",
                "fixed_distance_status",
                "legacy_elapsed_time_s",
                "legacy_exit_speed_kph",
                "legacy_fuel_used_l",
                "observed_has_lico",
                "observed_lico_start_m",
                "outcome_definition",
                "phase_mask_reason",
                "scheduled_action_enabled",
                "scheduled_lap_role",
                "treatment_label_source",
            ],
        }
    )
    validate_feature_contract(pooled, contract)
    manifest = load_split_manifest(root / SPLIT_FILE)
    assignments = build_split_assignments(pooled, manifest)
    references, views = [], []
    for fold in manifest["folds"]:
        ref = fit_supported_references(
            pooled,
            assignments,
            fold_id=fold["fold_id"],
            minimum_support=manifest["minimum_push_support_per_zone"],
            maximum_deceleration_cv=manifest["maximum_push_deceleration_cv"],
        )
        references.append(ref)
        views.append(
            restrict_response_actions(
                attach_fold_push_references(
                    pooled, assignments, ref, fold_id=fold["fold_id"]
                )
            )
        )
    fold_views = pl.concat(views, how="diagonal_relaxed")
    evaluations = [
        evaluate_monotone_action_only_baseline(fold_views),
        evaluate_monotone_action_only_baseline(
            fold_views, require_acceleration_profile=True
        ),
        evaluate_monotone_action_acceleration_baseline(fold_views),
    ]
    predictions = pl.concat([value[0] for value in evaluations], how="diagonal_relaxed")
    metrics = pl.concat([value[1] for value in evaluations], how="diagonal_relaxed")
    output.mkdir(parents=True)
    feature_registry_frame(contract).with_columns(
        pl.col("model_tasks").list.join("|")
    ).write_csv(output / "feature_registry.csv")
    (output / "feature_contract_v2.json").write_text(
        json.dumps(contract, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    write_frame(pooled, output / "licor_lmp2_zone_observations")
    write_frame(fold_views, output / "fold_feature_views")
    assignments.write_csv(output / "split_assignments.csv")
    pl.concat(references, how="diagonal_relaxed").write_csv(
        output / "fold_push_references.csv"
    )
    predictions.write_csv(output / "diagnostic_predictions.csv")
    metrics.write_csv(output / "diagnostic_metrics.csv")
    result = {
        "schema_version": 2,
        "artifact_id": "licor_lmp2_cross_circuit_ml_v2",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "evaluation_status": "retrospective_after_bahrain_outcomes_observed",
        "outcome_definition": "fixed_distance_native_v2_frozen_endpoints",
        "history_source": file_record(history_path),
        "history_manifest": file_record(history_manifest_path),
        "bahrain_sources": bahrain_sources,
        "native_outcome_sources": native_sources,
        "fixed_distance_status_counts": pooled.group_by("fixed_distance_status")
        .len()
        .to_dicts(),
        "split_manifest": file_record(root / SPLIT_FILE),
        "feature_contract": file_record(root / FEATURE_FILE),
        "builder": file_record(Path(__file__)),
        "fixed_distance_implementation": file_record(
            root / "src/licor/analysis/fixed_distance.py"
        ),
        "counts": {
            "observations": pooled.height,
            "circuits": pooled["circuit_id"].n_unique(),
            "folds": len(manifest["folds"]),
            "predictions": predictions.height,
        },
        "guardrails": [
            "V1 inputs and the frozen Bahrain prospective score are not overwritten.",
            "Every run and raw hash occupies only one role in a fold.",
            "Held-out run push laps never fit a reference or response model.",
            "Scheduled push laps and silent zones do not score or fit intentional LICO.",
            "Paired acceleration comparison uses identical in-range coverage.",
            "Outcome-aware window revisions require a separate labeled sensitivity run.",
        ],
        "artifacts": {
            path.name: file_record(path) for path in sorted(output.iterdir())
        },
    }
    (output / "build_manifest.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args()
    root = args.project_root.resolve()
    result = build_pack(root, root / args.output_dir)
    print(json.dumps(result["counts"], indent=2))


if __name__ == "__main__":
    main()
