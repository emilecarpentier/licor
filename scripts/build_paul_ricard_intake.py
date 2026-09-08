"""Rebuild Paul Ricard observations from raw LMU files, without fitting models."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from dataclasses import asdict
from pathlib import Path

import polars as pl

from licor.analysis.collection_metadata import validate_dataset_collection_metadata
from licor.analysis.driver_review import apply_zone_pass_review, load_driver_zone_review
from licor.analysis.lap_quality import build_lap_quality_manifest
from licor.analysis.lap_summary import (
    LapSummaryConfig,
    load_dataset_lap_labels,
    summarize_laps,
)
from licor.analysis.processed_artifacts import write_data_readiness_artifacts
from licor.analysis.track_zones import load_track_zone_table, track_zones_to_frame
from licor.analysis.zone_detection import build_lap_telemetry
from licor.analysis.zone_pass import ZonePassConfig, extract_zone_passes
from licor.ingestion import LmuTelemetryDatabase

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = "data/processed/experimental/paul_ricard_pilot_2026_09"
DATASET_FILE = "config/datasets/paul_ricard_lmp2_2026-09-07.json"
PROTOCOL_FILE = "config/collection_protocols/paul_ricard_reconstruction_v1.json"
REVIEW_FILE = "config/driver_reviews/paul_ricard_zone_review_2026-09-07.json"
ZONE_FILE = "config/track_zones/paul_ricard_lmp2_zones.draft.json"


def _write_csv(frame: pl.DataFrame, path: Path) -> None:
    lists = [name for name, dtype in frame.schema.items() if isinstance(dtype, pl.List)]
    frame.with_columns(
        *[
            pl.col(name).list.eval(pl.element().cast(pl.String)).list.join("|")
            for name in lists
        ]
    ).write_csv(path)


def _sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _reviewed_summary(summary: pl.DataFrame, run_data: dict) -> pl.DataFrame:
    reviews = {row["lap_number"]: row for row in run_data.get("lap_reviews", [])}
    rows = []
    for row in summary.iter_rows(named=True):
        review = reviews.get(row["lap_number"], {})
        default_action = "candidate_clean" if row["is_valid_lap"] else "needs_review"
        rows.append(
            {
                "run_id": row["run_id"],
                "lap_number": row["lap_number"],
                "recommended_review_action": review.get("action", default_action),
                "review_notes": review.get("reason", ""),
                "zone_modeling_lap_eligible": bool(row["is_valid_lap"]),
            }
        )
    return summary.join(pl.DataFrame(rows), on=["run_id", "lap_number"], how="left")


def select_modeling_passes(passes: pl.DataFrame) -> pl.DataFrame:
    """Keep eligible candidate laps; retain zone exclusions as explicit rows."""
    return passes.filter(
        pl.col("zone_modeling_lap_eligible")
        & (pl.col("optimization_role") == "candidate")
        & pl.col("lico_eligible")
        & (pl.col("review_status") == "driver_reviewed")
    )


def _impact_rows(telemetry: LmuTelemetryDatabase, run_id: str) -> list[dict]:
    if "LastImpactMagnitude" not in telemetry.events():
        return []
    events = telemetry.event_series("LastImpactMagnitude")
    intervals = telemetry.lap_intervals()
    rows = []
    for index, row in enumerate(events.iter_rows(named=True)):
        lap = next(
            (
                lap.lap_number
                for lap in intervals
                if lap.start_ts <= row["ts"] < lap.end_ts
            ),
            None,
        )
        rows.append(
            {
                "run_id": run_id,
                "lap_number": lap,
                "ts": row["ts"],
                "recorded_value": str(row["value"]),
                "value_dtype": str(events.schema["value"]),
                "is_initial_snapshot": index == 0,
            }
        )
    return rows


def build_intake(
    *,
    project_root: Path = PROJECT_ROOT,
    output_dir: str | Path = DEFAULT_OUTPUT,
    dataset_file: str | Path = DATASET_FILE,
    track_zone_file: str | Path = ZONE_FILE,
    protocol_file: str | Path = PROTOCOL_FILE,
    driver_review_file: str | Path = REVIEW_FILE,
) -> Path:
    root = Path(project_root).resolve()
    output = root / output_dir
    dataset_path = root / dataset_file
    labels = load_dataset_lap_labels(dataset_path)
    payload = json.loads(dataset_path.read_text(encoding="utf-8"))
    metadata = validate_dataset_collection_metadata(labels, root / protocol_file)
    if metadata.filter(pl.col("metadata_status") != "ready").height:
        raise ValueError(f"Collection metadata must be ready: {metadata.to_dicts()}")
    review = load_driver_zone_review(root / driver_review_file)
    if review.dataset_id != labels.dataset_id:
        raise ValueError("Driver review dataset_id does not match dataset")
    zone_table = load_track_zone_table(root / track_zone_file)
    distance_min, distance_max = payload["lap_distance_range_m"]
    lap_config = LapSummaryConfig(
        min_lap_distance_m=distance_min, max_lap_distance_m=distance_max
    )
    pass_config = ZonePassConfig(
        require_driver_reviewed=False,
        optimization_roles=(
            "candidate",
            "validation_only",
            "excluded",
            "needs_driver_review",
        ),
    )
    summaries, samples, passes, inventory, impacts = [], [], [], [], []
    source_paths = [
        dataset_path,
        root / protocol_file,
        root / driver_review_file,
        root / track_zone_file,
    ]
    for run, run_data in zip(labels.runs, payload["runs"], strict=True):
        raw_path = root / run.file
        source_paths.append(raw_path)
        with LmuTelemetryDatabase(raw_path) as telemetry:
            observed = telemetry.metadata()
            if observed.get(
                "CarClass"
            ) != run.car_class or "Paul Ricard" not in observed.get("TrackName", ""):
                raise ValueError(f"Unexpected raw track/car for {run.run_id}")
            summary = _reviewed_summary(
                summarize_laps(telemetry, run_labels=run, config=lap_config), run_data
            )
            known = (
                run.valid_laps
                | run.borderline_laps
                | run.context_laps
                | run.excluded_laps
            )
            actual = set(summary["lap_number"].to_list())
            if known != actual:
                raise ValueError(
                    f"Completed lap labels differ from raw file for {run.run_id}: {known ^ actual}"
                )
            lap_samples = build_lap_telemetry(
                telemetry, lap_numbers=actual
            ).with_columns(pl.lit(run.run_id).alias("run_id"))
            lap_events = telemetry.event_series("Lap")
            inventory.append(
                {
                    "run_id": run.run_id,
                    "file": run.file,
                    "track_layout": observed.get("TrackLayout"),
                    "car": observed.get("CarName"),
                    "complete_lap_count": summary.height,
                    "last_unclosed_lap_number": int(lap_events["value"][-1]),
                    "has_impact_channel": "LastImpactMagnitude" in telemetry.events(),
                }
            )
            impacts.extend(_impact_rows(telemetry, run.run_id))
        zone_passes = extract_zone_passes(
            lap_samples, zone_table, run_labels=run, config=pass_config
        )
        zone_passes = zone_passes.join(
            summary.select(
                "run_id",
                "lap_number",
                "zone_modeling_lap_eligible",
                "recommended_review_action",
            ),
            on=["run_id", "lap_number"],
            how="left",
        ).join(
            track_zones_to_frame(zone_table).select(
                "zone_id", "optimization_role", "lico_eligible", "review_status"
            ),
            on="zone_id",
            how="left",
        )
        summaries.append(summary)
        samples.append(lap_samples)
        passes.append(zone_passes)
    lap_summary = pl.concat(summaries, how="diagonal").sort("run_id", "lap_number")
    all_passes = apply_zone_pass_review(pl.concat(passes, how="diagonal"), review).sort(
        "run_id", "lap_number", "zone_id"
    )
    modeling = select_modeling_passes(all_passes)
    quality = build_lap_quality_manifest(
        lap_summary,
        lap_samples=pl.concat(samples, how="diagonal"),
        zone_passes=all_passes.filter(pl.col("optimization_role") == "candidate"),
    )
    impact_frame = pl.DataFrame(
        impacts,
        schema={
            "run_id": pl.String,
            "lap_number": pl.Int64,
            "ts": pl.Float64,
            "recorded_value": pl.String,
            "value_dtype": pl.String,
            "is_initial_snapshot": pl.Boolean,
        },
    )
    impact_counts = (
        impact_frame.filter(~pl.col("is_initial_snapshot"))
        .group_by("run_id", "lap_number")
        .len()
        .rename({"len": "impact_value_change_count"})
    )
    quality = quality.join(
        impact_counts, on=["run_id", "lap_number"], how="left"
    ).with_columns(pl.col("impact_value_change_count").fill_null(0))
    baseline = lap_summary.filter(pl.col("collection_design") == "baseline")
    output.mkdir(parents=True, exist_ok=True)
    tables = {
        "metadata_validation.csv": metadata,
        "raw_inventory.csv": pl.DataFrame(inventory),
        "impact_events.csv": impact_frame,
        "lap_summary.csv": lap_summary,
        "baseline_summary.csv": baseline,
        "lap_quality_manifest.csv": quality,
        "zone_passes_all.csv": all_passes,
        "zone_passes_modeling.csv": modeling,
    }
    for name, frame in tables.items():
        _write_csv(frame, output / name)
    modeling.write_parquet(output / "zone_passes_modeling.parquet")
    write_data_readiness_artifacts(
        modeling,
        protocol_file=root / protocol_file,
        zone_readiness_csv_path=output / "zone_readiness.csv",
        protocol_readiness_csv_path=output / "protocol_readiness.csv",
    )
    source_paths.extend(
        [root / "scripts/build_paul_ricard_intake.py", root / "uv.lock"]
    )
    source_paths.extend(sorted((root / "src/licor/analysis").glob("*.py")))
    source_paths.extend(sorted((root / "src/licor/ingestion").glob("*.py")))
    git = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    manifest = {
        "schema_version": 1,
        "dataset_id": labels.dataset_id,
        "metadata_valid": True,
        "quality_status_counts": {
            row["quality_status"]: row["len"]
            for row in quality.group_by("quality_status").len().iter_rows(named=True)
        },
        "git_commit": git.stdout.strip() if git.returncode == 0 else None,
        "source_sha256": {
            path.relative_to(root).as_posix(): _sha256(path) for path in source_paths
        },
        "artifact_sha256": {
            path.name: _sha256(path)
            for path in sorted(output.iterdir())
            if path.name
            in {
                *tables,
                "zone_passes_modeling.parquet",
                "zone_readiness.csv",
                "protocol_readiness.csv",
            }
        },
        "lap_summary_config": asdict(lap_config),
        "zone_pass_config": asdict(pass_config),
        "counts": {
            "complete_laps": lap_summary.height,
            "modeling_laps": modeling.select("run_id", "lap_number").unique().height,
            "clean_whole_lap_baseline": baseline.filter(
                pl.col("recommended_review_action") == "candidate_clean"
            ).height,
            "modeling_passes": modeling.height,
            "driver_excluded_passes": modeling.filter(
                pl.col("validity_label") == "driver_excluded"
            ).height,
        },
        "limitations": [
            "Exploratory intake only; readiness is coverage, not held-out predictive validation.",
            "LastImpactMagnitude is Boolean in these raw files; event transitions are retained and must not be interpreted as physical magnitudes or exhaustive collision detection.",
            "Whole-lap baseline preserves 9 clean historical laps. Baseline02 lap13 restored for zone modeling except T03; lap12 excluded, lap14 context pending review.",
            "All completed laps and complete zones retained in audit tables; final unclosed lap events are inventory only.",
            "Run design metadata reconstructed retrospectively; historical tire-wear setting and prospective randomization seed unavailable.",
            "Protocol observed_clean_laps counts laps with usable zones, including reviewed lap13; it is not the 9-lap clean whole-lap baseline. Diagnostic lap-quality baseline includes eligible borderline laps.",
            "Existing sample-based zone metric definitions retained; no resampling, extrapolation or model fitting performed.",
        ],
    }
    manifest_path = output / "intake_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest_path


def verify_intake_manifest(
    output_dir: str | Path, project_root: str | Path = PROJECT_ROOT
) -> dict:
    """Fail closed when intake inputs or outputs have changed since generation."""
    root = Path(project_root).resolve()
    output = root / output_dir
    manifest = json.loads((output / "intake_manifest.json").read_text(encoding="utf-8"))
    if (
        manifest.get("schema_version") != 1
        or manifest.get("metadata_valid") is not True
    ):
        raise ValueError("Intake manifest has no valid metadata gate")
    for key, base in (("source_sha256", root), ("artifact_sha256", output)):
        entries = manifest.get(key, {})
        if not entries:
            raise ValueError(f"Intake manifest missing {key}")
        for name, expected in entries.items():
            path = base / name
            if not path.is_file() or _sha256(path) != expected:
                raise ValueError(f"Stale intake input/output: {name}; rebuild intake")
    validation = pl.read_csv(output / "metadata_validation.csv")
    if (
        validation.is_empty()
        or validation.filter(pl.col("metadata_status") != "ready").height
    ):
        raise ValueError("Intake metadata gate is not ready")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    manifest = build_intake(output_dir=args.output_dir)
    print(f"Intake rebuilt: {manifest}")
    print(json.loads(manifest.read_text(encoding="utf-8"))["counts"])


if __name__ == "__main__":
    main()
