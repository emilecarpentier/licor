"""Build the prospective Paul static pilot from freshly audited intake outputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from dataclasses import asdict
from pathlib import Path

import polars as pl

from licor.analysis.lap_sanity import summarize_full_lap_sanity
from licor.analysis.strategy_priors import build_strategy_prior_table_from_track_zones
from licor.analysis.track_zones import load_track_zone_table
from licor.analysis.zone_curves import (
    ZoneCurveConfig,
    build_zone_curve_points,
    summarize_zone_curve_bins,
)
from licor.analysis.zone_models import ZoneModelConfig, build_zone_piecewise_models
from licor.analysis.zone_optimizer import ZoneOptimizerConfig, optimize_zone_lico_plan
from licor.analysis.zone_plan_diagnostics import (
    build_zone_marginal_efficiency,
    summarize_zone_plan_sensitivity,
)
from licor.reports.zone_plan_report import (
    create_zone_plan_report_figure,
    write_zone_plan_report_html,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / "data/processed/experimental/paul_ricard_pilot_2026_09"
ZONE_FILE = "config/track_zones/paul_ricard_lmp2_zones.draft.json"


def file_record(path: Path, root: Path) -> dict[str, str]:
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {
        "path": path.resolve().relative_to(root.resolve()).as_posix(),
        "sha256": digest,
    }


def csv_safe(frame: pl.DataFrame) -> pl.DataFrame:
    return frame.with_columns(
        pl.col(name).list.eval(pl.element().cast(pl.String)).list.join("|")
        for name, dtype in frame.schema.items()
        if isinstance(dtype, pl.List)
    )


def require_disjoint_candidates(zone_table) -> list[str]:
    zones = sorted(
        (z for z in zone_table.zones if z.optimization_role == "candidate"),
        key=lambda z: z.start_distance_m,
    )
    for left, right in zip(zones, zones[1:]):
        if left.end_distance_m > right.start_distance_m:
            raise ValueError(
                f"Overlapping candidate zones: {left.zone_id}, {right.zone_id}"
            )
    return [zone.zone_id for zone in zones]


def require_reviewed_lap_quality(passes: pl.DataFrame, quality: pl.DataFrame) -> None:
    """Permit reviewed collection flags, but fail on new severe/unknown issues."""
    checked = (
        passes.select("run_id", "lap_number")
        .unique()
        .join(quality, on=["run_id", "lap_number"], how="left")
    )
    accepted_flags = {
        "detected_lico",
        "zone_start_zero_throttle",
        "brake_reference_drift_warning",
        "fuel_delta_vs_baseline_warning",
        "lap_time_delta_vs_baseline_warning",
    }
    for row in checked.iter_rows(named=True):
        flags = set((row.get("quality_flags") or "").split("|")) - {""}
        if (
            row.get("quality_status") not in {"ready", "review_recommended"}
            or flags - accepted_flags
        ):
            raise ValueError(
                f"Unreviewed modeling lap quality: {row['run_id']} lap {row['lap_number']}"
            )


def build_plan(
    output_dir: Path = OUTPUT_DIR, project_root: Path = PROJECT_ROOT
) -> dict:
    # Import the intake gate only after argument parsing (including --help).
    from build_paul_ricard_intake import verify_intake_manifest

    verify_intake_manifest(output_dir, project_root)
    zone_table = load_track_zone_table(project_root / ZONE_FILE)
    if zone_table.validation_issues():
        raise ValueError(zone_table.validation_issues())
    candidate_ids = require_disjoint_candidates(zone_table)
    passes = pl.read_csv(output_dir / "zone_passes_modeling.csv", null_values=[""])
    passes = passes.filter(pl.col("zone_id").is_in(candidate_ids))
    require_reviewed_lap_quality(
        passes, pl.read_csv(output_dir / "lap_quality_manifest.csv", null_values=[""])
    )
    laps = pl.read_csv(output_dir / "lap_summary.csv", null_values=[""])
    curve_config = ZoneCurveConfig()
    model_config = ZoneModelConfig()
    optimizer_config = ZoneOptimizerConfig(target_fuel_saved_per_lap_l=0.05)
    points = build_zone_curve_points(passes, config=curve_config)
    bins = summarize_zone_curve_bins(points, config=curve_config)
    models = build_zone_piecewise_models(bins, config=model_config)
    priors = build_strategy_prior_table_from_track_zones(
        zone_table,
        dataset_id="paul_ricard_pilot_2026_09",
        notes="Geometry heuristic rebuilt from current zones; no learned Spa transfer.",
    )
    plan = optimize_zone_lico_plan(
        models, config=optimizer_config, zone_priors=priors.to_frame()
    )
    if plan.is_empty() or plan["plan_status"].unique().to_list() != ["target_met"]:
        raise ValueError(
            "Pilot target is not reachable under the existing conservative gates"
        )
    selected = plan.filter(pl.col("is_selected_for_lico"))
    support_rows = []
    for row in selected.iter_rows(named=True):
        local = points.filter(
            (pl.col("zone_id") == row["zone_id"]) & pl.col("has_lico")
        )
        distance = float(row["selected_lico_distance_m"])
        observed_max = local["lico_distance_before_brake_m"].max()
        if observed_max is None or distance > observed_max + 1e-6:
            raise ValueError(
                f"Selected distance beyond observed support: {row['zone_id']}"
            )
        nearby = local.filter(
            (pl.col("lico_distance_before_brake_m") - distance).abs() <= 25
        )
        support_rows.append(
            {
                "zone_id": row["zone_id"],
                "selected_lico_distance_m": distance,
                "observed_max_distance_m": observed_max,
                "nearby_radius_m": 25.0,
                "nearby_pass_count": nearby.height,
                "nearby_run_count": nearby["run_id"].n_unique(),
                "quality_flags": row["quality_flags"],
                "evaluation_status": "exploratory_fit_pending_prospective_pilot",
            }
        )
    artifacts = {
        "zone_curve_points.csv": points,
        "zone_curve_bins.csv": bins,
        "zone_models.csv": models,
        "strategy_priors.csv": priors.to_frame(),
        "zone_plan.csv": plan,
        "selected_support.csv": pl.DataFrame(support_rows),
        "lap_sanity.csv": summarize_full_lap_sanity(laps, points),
        "marginal_efficiency.csv": build_zone_marginal_efficiency(
            models, zone_plan=plan
        ),
        "plan_sensitivity.csv": summarize_zone_plan_sensitivity(
            models, base_config=optimizer_config, zone_priors=priors.to_frame()
        ),
    }
    for name, frame in artifacts.items():
        csv_safe(frame).write_csv(output_dir / name)
    (output_dir / "strategy_priors.json").write_text(
        priors.model_dump_json(indent=2), encoding="utf-8"
    )
    write_zone_plan_report_html(
        create_zone_plan_report_figure(
            models,
            plan,
            title="Paul Ricard prospective static pilot — exploratory predictions",
        ),
        output_dir / "zone_plan_report.html",
    )
    inputs = [
        output_dir / name
        for name in (
            "intake_manifest.json",
            "zone_passes_modeling.csv",
            "lap_summary.csv",
        )
    ]
    inputs.append(project_root / ZONE_FILE)
    sources = sorted((project_root / "src/licor").rglob("*.py")) + [Path(__file__)]
    manifest = {
        "schema_version": 1,
        "purpose": "prospective_static_pilot_not_validated_race_strategy",
        "target_fuel_saved_per_lap_l": 0.05,
        "predicted_fuel_saved_l": float(plan["total_predicted_fuel_saved_l"][0]),
        "predicted_time_lost_s": float(plan["total_predicted_time_lost_s"][0]),
        "selected_zones": selected["zone_id"].to_list(),
        "configs": {
            "curve": asdict(curve_config),
            "model": asdict(model_config),
            "optimizer": asdict(optimizer_config),
        },
        "sanity_scope": "disjoint candidate zones only; validation-only zones omitted to avoid double counting",
        "quality_review": {
            "date": "2026-09-07",
            "accepted_flags_basis": "Detected LICO, fuel/time deltas and brake drift are expected under varied-LICO collection. Zero-throttle boundary flags are retained; T08 extreme tail is not a selected distance. Excluded/context laps stay outside modeling; T03 lap13 exclusion stays visible.",
            "remaining_flags": "T11/T12 contaminated push passes are excluded from local baseline by existing curve config; selected T03/T08 have 9/10 uncontaminated push references. T08 time response remains noisy.",
        },
        "caveats": [
            "model_ready describes in-sample shape gates, not held-out accuracy",
            "0.05 L/lap is a pilot target; no Spa pit assumptions used",
            "sample-based zone boundaries and pooled baseline remain exploratory",
        ],
        "git_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=project_root, text=True
        ).strip(),
        "git_dirty": bool(
            subprocess.check_output(
                ["git", "status", "--porcelain"], cwd=project_root, text=True
            ).strip()
        ),
        "inputs": [file_record(p, project_root) for p in inputs],
        "source_files": [file_record(p, project_root) for p in sources],
        "outputs": [
            file_record(output_dir / n, project_root)
            for n in (*artifacts, "strategy_priors.json", "zone_plan_report.html")
        ],
    }
    (output_dir / "plan_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args()
    manifest = build_plan(args.output_dir.resolve())
    print(
        json.dumps(
            {
                k: manifest[k]
                for k in (
                    "selected_zones",
                    "predicted_fuel_saved_l",
                    "predicted_time_lost_s",
                )
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
