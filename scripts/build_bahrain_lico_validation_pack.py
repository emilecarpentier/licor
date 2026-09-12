"""Build and verify the frozen Bahrain zero-LICO-shot validation pack."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import statistics
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import polars as pl

from licor.analysis.cross_circuit_ml import (
    BrakingEventConfig,
    extract_physical_braking_events,
)
from licor.analysis.experimental_zone_dynamics import (
    build_labeled_experimental_lap_samples,
)
from licor.analysis.live_plan import LiveCuePlanConfig, build_live_cue_plan
from licor.analysis.processed_artifacts import build_labeled_zone_passes
from licor.analysis.track_zones import load_track_zone_table, track_zones_to_frame
from licor.analysis.zone_pass import ZonePassConfig
from licor.live.audio import RecordingAudioCueAdapter
from licor.live.lmu_shared_memory import LmuLiveTelemetrySample
from licor.live.runtime import LiveStaticCueSessionConfig, run_static_live_cue_session


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TRANSFER_ROOT = (
    PROJECT_ROOT / "data/processed/experimental/bahrain_lmp2_transfer_2026_09"
)
DEFAULT_PACK_DIR = TRANSFER_ROOT / "lico_validation_pack_v1"
DATASET_FILE = Path("config/datasets/bahrain_lmp2_circuit_c_2026-09.json")
ZONE_FILE = Path("config/track_zones/bahrain_lmp2_zones.draft.json")
REVIEW_FILE = Path("config/driver_reviews/bahrain_lmp2_push_review_2026-09-11.json")
FEATURE_CONTRACT_FILE = Path("config/ml/licor_lmp2_feature_contract_v1.json")
PROTOCOL_FILE = Path("config/collection_protocols/bahrain_lmp2_circuit_c_v1.json")
RUN_SHEET_FILE = Path("docs/bahrain_lico_validation_run_sheet.md")
CROSS_ML_DIR = Path("data/processed/experimental/cross_circuit_ml_v1")
BAHRAIN_RAW_FILE = Path(
    "data/Bahrain International Circuit_P_2026-09-12T01_49_14Z.duckdb"
)
BAHRAIN_RUN_ID = "bahrain_push_20260911_212732"
TRACK_LENGTH_M = 5385.0
PLAN_ID = "bahrain_lmp2_zero_lico_shot_static_v1"
SCORING_PATTERN = ("push", "lico", "lico", "push", "lico", "lico", "push")
LATENCY_S = 0.35
ACCELERATION_WEIGHTED_ACTION_LIMIT_MPS2 = 2.75547

# Distances are conservative prospective actions chosen from the push geometry.
# They are not fitted from a Bahrain LICO outcome.
SELECTED_DISTANCES_M = {
    "bhr_t01_t03": 75.0,
    "bhr_t04": 60.0,
    "bhr_t08": 40.0,
    "bhr_t10": 65.0,
    "bhr_t11": 55.0,
    "bhr_t14_t15": 70.0,
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def lap_schedule() -> list[dict[str, object]]:
    return [
        {
            "scored_index": index,
            "role": role,
            "cue_enabled": role == "lico",
        }
        for index, role in enumerate(SCORING_PATTERN, start=1)
    ]


def build_pack(pack_dir: Path = DEFAULT_PACK_DIR) -> dict[str, Any]:
    if pack_dir.exists():
        raise FileExistsError(f"refusing to replace frozen pack: {pack_dir}")
    _require_sources()
    pack_dir.mkdir(parents=True)

    references, events = _build_bahrain_push_references()
    model_fit = _fit_historical_response()
    predictions = _build_predictions(references, model_fit)
    selected = predictions.filter(pl.col("is_selected_for_lico"))
    if selected.height != len(SELECTED_DISTANCES_M):
        raise ValueError(
            "not all prospective Bahrain validation zones passed guardrails"
        )

    zone_table = load_track_zone_table(PROJECT_ROOT / ZONE_FILE)
    zones = track_zones_to_frame(zone_table)
    dynamic_zones = zones.drop("brake_reference_m").join(
        references.select(
            pl.col("zone_id"),
            pl.col("brake_onset_reference_m").alias("brake_reference_m"),
        ),
        on="zone_id",
        how="left",
    )
    zone_plan = predictions.with_columns(
        pl.col("is_selected_for_lico"),
        pl.col("predicted_fuel_saved_l"),
        pl.col("predicted_time_lost_s"),
        pl.col("approach_speed_reference_kph").alias("brake_start_speed_kph"),
        pl.lit("prospective_zero_lico_shot_validation").alias("plan_status"),
        pl.lit("pooled_monotone_action_only_v1").alias("model_status"),
        pl.col("selection_reason").alias("quality_flags"),
        pl.lit("prediction_validation").alias("strategy_role"),
    )
    plan = build_live_cue_plan(
        zone_plan,
        dynamic_zones,
        config=LiveCuePlanConfig(
            plan_id=PLAN_ID,
            track_name="Bahrain International Circuit",
            car_class="LMP2_ELMS",
            race_context_id="bahrain_circuit_c_first_lico_validation",
            minimum_confidence_label="prospective_validation_only",
            cue_tolerance_m=5.0,
            track_length_m=TRACK_LENGTH_M,
            cue_latency_compensation_s=LATENCY_S,
            notes=(
                "Frozen before any Bahrain LICO outcome. Follow each beep with a full "
                "lift until the normal braking point; static plan repeats on all LICO laps."
            ),
        ),
    )

    references.write_csv(pack_dir / "physical_references.csv")
    events.write_csv(pack_dir / "physical_events_audit.csv")
    pl.DataFrame(model_fit).write_csv(pack_dir / "zero_shot_model_fit.csv")
    predictions.write_csv(pack_dir / "predictions.csv")
    predictions.write_csv(pack_dir / "candidate_zone_review.csv")
    plan.write_csv(pack_dir / "plan.csv")
    (pack_dir / "track_zones.json").write_bytes((PROJECT_ROOT / ZONE_FILE).read_bytes())
    (pack_dir / "driver_review.json").write_bytes(
        (PROJECT_ROOT / REVIEW_FILE).read_bytes()
    )
    (pack_dir / "run_metadata_template.json").write_text(
        json.dumps(_run_metadata_template(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    _write_lap_notes(pack_dir / "lap_notes_template.csv")
    (pack_dir / "start_lico_validation.ps1").write_text(
        _powershell_launcher(pack_dir), encoding="utf-8"
    )
    (pack_dir / "start_lico_validation.cmd").write_text(
        _cmd_launcher(), encoding="utf-8"
    )
    (pack_dir / "README.md").write_text(_pack_readme(), encoding="utf-8")

    source_paths = _source_paths()
    plan_manifest = {
        "schema_version": 1,
        "plan_id": PLAN_ID,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "local_lico_outcomes_observed": False,
        "historical_training_circuits": ["spa_francorchamps", "paul_ricard"],
        "bahrain_input_role": "push_geometry_and_acceleration_calibration_only",
        "selection_policy": "six conservative telemetry-derived actions with acceleration and stability guardrails",
        "lap_pattern": list(SCORING_PATTERN),
        "selected_zones": selected["zone_id"].to_list(),
        "selected_distances_m": dict(SELECTED_DISTANCES_M),
        "predicted_fuel_saved_per_lico_lap_l": float(
            selected["predicted_fuel_saved_l"].sum()
        ),
        "predicted_time_lost_per_lico_lap_s": float(
            selected["predicted_time_lost_s"].sum()
        ),
        "model": {
            row["target"]: {
                "slope": row["slope"],
                "cross_circuit_p90_absolute_error": row["p90_absolute_error"],
                "source_slope_min": row["source_slope_min"],
                "source_slope_max": row["source_slope_max"],
                "training_rows": row["training_rows"],
            }
            for row in model_fit
        },
        "guardrails": {
            "minimum_physical_support": 3,
            "maximum_deceleration_cv": 0.15,
            "action_ratio_range": [0.15, 0.85],
            "maximum_acceleration_weighted_action_mps2": ACCELERATION_WEIGHTED_ACTION_LIMIT_MPS2,
            "acceleration_model_role": "shadow_only_interaction_not_identified",
        },
        "source_files": {
            path.as_posix(): sha256_file(PROJECT_ROOT / path) for path in source_paths
        },
    }
    (pack_dir / "plan_manifest.json").write_text(
        json.dumps(plan_manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    artifact_names = sorted(path.name for path in pack_dir.iterdir() if path.is_file())
    try:
        git_commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, text=True
        ).strip()
        git_dirty = bool(
            subprocess.check_output(
                ["git", "status", "--porcelain"], cwd=PROJECT_ROOT, text=True
            ).strip()
        )
    except OSError, subprocess.CalledProcessError:
        git_commit = "unavailable"
        git_dirty = True
    manifest = {
        "schema_version": 1,
        "pack_id": "bahrain_lmp2_zero_lico_shot_validation_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "plan_id": PLAN_ID,
        "pack_status": "frozen_pending_simulator_validation",
        "local_lico_outcomes_observed": False,
        "adaptive_mode": "offline_after_run_only",
        "plan_mode": "static_same_plan_on_four_lico_laps_variation_between_zones",
        "track_length_m": TRACK_LENGTH_M,
        "git_commit": git_commit,
        "git_dirty": git_dirty,
        "sources": {
            path.as_posix(): sha256_file(PROJECT_ROOT / path) for path in source_paths
        },
        "artifacts": {name: sha256_file(pack_dir / name) for name in artifact_names},
    }
    (pack_dir / "pack_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return verify_pack(pack_dir)


def verify_pack(pack_dir: Path = DEFAULT_PACK_DIR) -> dict[str, Any]:
    manifest_path = pack_dir / "pack_manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"pack manifest not found: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("local_lico_outcomes_observed") is not False:
        raise ValueError("pack is not a prospective zero-LICO-shot freeze")
    for relative, expected in manifest["sources"].items():
        path = (PROJECT_ROOT / relative).resolve()
        if not path.is_relative_to(PROJECT_ROOT) or sha256_file(path) != expected:
            raise ValueError(f"source hash mismatch: {relative}")
    for name, expected in manifest["artifacts"].items():
        path = pack_dir / name
        if not path.is_file() or sha256_file(path) != expected:
            raise ValueError(f"artifact hash mismatch: {name}")
    _verify_plan_consistency(pack_dir, manifest)
    preflight = preflight_schedule(pack_dir / "plan.csv")
    return {
        "pack": str(pack_dir.resolve()),
        "pack_id": manifest["pack_id"],
        "hashes_verified": True,
        "selected_zones": pl.read_csv(pack_dir / "plan.csv").height,
        "lap_pattern": list(SCORING_PATTERN),
        "silent_synthetic_preflight": [preflight],
    }


def _require_sources() -> None:
    missing = [path for path in _source_paths() if not (PROJECT_ROOT / path).is_file()]
    if missing:
        raise FileNotFoundError(f"required frozen source missing: {missing}")


def _source_paths() -> list[Path]:
    return [
        DATASET_FILE,
        PROTOCOL_FILE,
        ZONE_FILE,
        REVIEW_FILE,
        FEATURE_CONTRACT_FILE,
        RUN_SHEET_FILE,
        BAHRAIN_RAW_FILE,
        CROSS_ML_DIR / "fold_feature_views.parquet",
        CROSS_ML_DIR / "fold_push_references.csv",
        CROSS_ML_DIR / "diagnostic_action_only_predictions.csv",
        CROSS_ML_DIR / "diagnostic_action_only_metrics.csv",
        Path("scripts/build_bahrain_lico_validation_pack.py"),
        Path("src/licor/analysis/cross_circuit_ml.py"),
        Path("src/licor/live/runtime.py"),
        Path("src/licor/live/lmu_live_cli.py"),
    ]


def _build_bahrain_push_references() -> tuple[pl.DataFrame, pl.DataFrame]:
    zone_passes = build_labeled_zone_passes(
        dataset_label_file=PROJECT_ROOT / DATASET_FILE,
        track_zone_file=PROJECT_ROOT / ZONE_FILE,
        project_root=PROJECT_ROOT,
        driver_review_file=PROJECT_ROOT / REVIEW_FILE,
        include_run_ids={BAHRAIN_RUN_ID},
        config=ZonePassConfig(
            require_driver_reviewed=False,
            optimization_roles=("candidate", "validation_only"),
        ),
    )
    lap_samples = build_labeled_experimental_lap_samples(
        dataset_label_file=PROJECT_ROOT / DATASET_FILE,
        project_root=PROJECT_ROOT,
        include_run_ids={BAHRAIN_RUN_ID},
    )
    events = extract_physical_braking_events(
        zone_passes,
        lap_samples,
        track_length_m=TRACK_LENGTH_M,
        config=BrakingEventConfig(post_zone_capture_margin_m=75.0),
    ).filter(pl.col("braking_event_quality") == "ready")
    if events.height != 40:
        raise ValueError(
            f"expected 40 ready Bahrain physical events, found {events.height}"
        )

    zones = {
        zone.zone_id: zone
        for zone in load_track_zone_table(PROJECT_ROOT / ZONE_FILE).zones
    }
    rows = []
    for zone_id in sorted(zones):
        zone_events = events.filter(pl.col("zone_id") == zone_id)
        decel_events = zone_events
        acceleration_events = zone_events
        outcome_support = zone_events.height
        if zone_id == "bhr_t04":
            decel_events = decel_events.filter(pl.col("lap_number") != 19)
            outcome_support -= 1
        elif zone_id == "bhr_t05_t07":
            acceleration_events = acceleration_events.filter(pl.col("lap_number") != 19)
            outcome_support -= 1
        elif zone_id == "bhr_t14_t15":
            decel_events = decel_events.filter(pl.col("lap_number") != 20)
            outcome_support -= 2
        decelerations = decel_events["push_deceleration_distance_observed_m"].to_list()
        decel_mean = statistics.fmean(decelerations)
        decel_std = statistics.stdev(decelerations) if len(decelerations) > 1 else 0.0
        row: dict[str, Any] = {
            "zone_id": zone_id,
            "display_label": zones[zone_id].display_label,
            "optimization_role": zones[zone_id].optimization_role,
            "lico_eligible": zones[zone_id].lico_eligible,
            "boundary_review_status": zones[zone_id].review_status,
            "physical_support": zone_events.height,
            "deceleration_support": decel_events.height,
            "acceleration_support": acceleration_events.height,
            "outcome_support": outcome_support,
            "brake_onset_reference_m": _median(
                zone_events["main_brake_onset_m"].to_list()
            ),
            "deceleration_distance_reference_m": _median(decelerations),
            "deceleration_distance_std_m": decel_std,
            "deceleration_distance_cv": decel_std / decel_mean,
            "approach_speed_reference_kph": _median(
                zone_events["main_brake_onset_speed_kph"].to_list()
            ),
            "min_speed_reference_kph": _median(
                decel_events["min_speed_point_kph"].to_list()
            ),
            "physical_reference_status": "ready",
            "outcome_reference_status": (
                "ready" if outcome_support >= 3 else "insufficient_support"
            ),
        }
        for ratio_label in ("0_0", "0_25", "0_5", "1_0", "1_5"):
            column = f"approach_acceleration_ratio_{ratio_label}_mps2"
            values = [
                float(value)
                for value in acceleration_events[column].drop_nulls().to_list()
            ]
            row[f"acceleration_ratio_{ratio_label}_reference_mps2"] = (
                _median(values) if values else None
            )
            row[f"acceleration_ratio_{ratio_label}_support"] = len(values)
        row["acceleration_profile_status"] = (
            "ready"
            if all(
                row[f"acceleration_ratio_{label}_support"] >= 3
                for label in ("0_0", "0_25", "0_5", "1_0", "1_5")
            )
            else "insufficient_support"
        )
        rows.append(row)
    return pl.DataFrame(rows), events.sort(["zone_id", "lap_number"])


def _fit_historical_response() -> list[dict[str, Any]]:
    fold_views = pl.read_parquet(
        PROJECT_ROOT / CROSS_ML_DIR / "fold_feature_views.parquet"
    )
    historical = pl.concat(
        [
            fold_views.filter(
                (pl.col("fold_id") == "spa_to_paul_zero_lico_shot")
                & (pl.col("split_role") == "train")
            ),
            fold_views.filter(
                (pl.col("fold_id") == "paul_to_spa_zero_lico_shot")
                & (pl.col("split_role") == "train")
            ),
        ],
        how="diagonal_relaxed",
    ).unique("observation_id")
    diagnostic_predictions = pl.read_csv(
        PROJECT_ROOT / CROSS_ML_DIR / "diagnostic_action_only_predictions.csv"
    ).filter(
        (pl.col("model_name") == "pooled_monotone_action_only_v1")
        & pl.col("evaluation_regime").str.contains("cross_circuit")
    )
    diagnostic_metrics = pl.read_csv(
        PROJECT_ROOT / CROSS_ML_DIR / "diagnostic_action_only_metrics.csv"
    ).filter(
        (pl.col("model_name") == "pooled_monotone_action_only_v1")
        & pl.col("evaluation_regime").str.contains("cross_circuit")
    )
    rows = []
    for target in (
        "target_fuel_saved_vs_fold_push_l",
        "target_time_lost_vs_fold_push_s",
    ):
        diagnostic_target = (
            "fuel_saved_l"
            if target == "target_fuel_saved_vs_fold_push_l"
            else "time_lost_s"
        )
        eligible = historical.filter(
            pl.col("model_eligible")
            & pl.col("executed_lift_lead_to_push_deceleration_ratio").is_not_null()
            & pl.col(target).is_not_null()
        )
        x = eligible["executed_lift_lead_to_push_deceleration_ratio"].to_list()
        y = eligible[target].to_list()
        slope = max(
            0.0, sum(a * b for a, b in zip(x, y, strict=True)) / sum(a * a for a in x)
        )
        target_predictions = diagnostic_predictions.filter(
            pl.col("target_name") == diagnostic_target
        )
        p90_by_fold = (
            target_predictions.with_columns(pl.col("error").abs().alias("abs_error"))
            .group_by("fold_id")
            .agg(
                pl.col("abs_error").quantile(0.9, interpolation="nearest").alias("p90")
            )
        )
        target_metrics = diagnostic_metrics.filter(
            pl.col("target_name") == diagnostic_target
        )
        rows.append(
            {
                "model_name": "pooled_monotone_action_only_v1",
                "target": target,
                "slope": slope,
                "training_rows": eligible.height,
                "training_circuits": "spa_francorchamps|paul_ricard",
                "p90_absolute_error": float(p90_by_fold["p90"].max()),
                "source_slope_min": float(target_metrics["fitted_slope"].min()),
                "source_slope_max": float(target_metrics["fitted_slope"].max()),
                "bahrain_lico_rows_used": 0,
            }
        )
    return rows


def _build_predictions(
    references: pl.DataFrame, model_fit: list[dict[str, Any]]
) -> pl.DataFrame:
    fits = {row["target"]: row for row in model_fit}
    context_bounds = _historical_context_bounds()
    rows = []
    for reference in references.iter_rows(named=True):
        zone_id = reference["zone_id"]
        selected_distance = SELECTED_DISTANCES_M.get(zone_id)
        selected = selected_distance is not None
        ratio = (
            float(selected_distance)
            / float(reference["deceleration_distance_reference_m"])
            if selected
            else None
        )
        acceleration = _interpolate_acceleration(reference, ratio) if selected else None
        weighted_action = (
            ratio * max(float(acceleration), 0.0)
            if ratio is not None and acceleration is not None
            else None
        )
        physical_ready = (
            int(reference["deceleration_support"]) >= 3
            and float(reference["deceleration_distance_cv"]) <= 0.15
        )
        accel_ready = reference["acceleration_profile_status"] == "ready"
        action_ready = (
            ratio is not None
            and 0.15 <= ratio <= 0.85
            and weighted_action is not None
            and weighted_action <= ACCELERATION_WEIGHTED_ACTION_LIMIT_MPS2
        )
        if selected and not (physical_ready and accel_ready and action_ready):
            raise ValueError(f"selected zone fails zero-shot guardrails: {zone_id}")
        fuel = _prediction_interval(fits["target_fuel_saved_vs_fold_push_l"], ratio)
        time = _prediction_interval(fits["target_time_lost_vs_fold_push_s"], ratio)
        context_status = _context_status(reference, context_bounds)
        if not selected:
            selection_status = "excluded_from_first_live_plan"
            reason = "validation_only_zone"
        else:
            selection_status = "selected_prospective_validation"
            reason = (
                "stable_push_reference|acceleration_guard_pass|"
                f"boundary_{reference['boundary_review_status']}|{context_status}"
            )
        rows.append(
            {
                **reference,
                "action_ratio": ratio,
                "selected_lico_distance_m": selected_distance,
                "planned_lift_start_m": (
                    (
                        float(reference["brake_onset_reference_m"])
                        - float(selected_distance)
                    )
                    % TRACK_LENGTH_M
                    if selected
                    else None
                ),
                "acceleration_at_planned_lift_mps2": acceleration,
                "acceleration_weighted_action_mps2": weighted_action,
                "predicted_fuel_saved_l": fuel[0],
                "predicted_fuel_p90_low_l": fuel[1],
                "predicted_fuel_p90_high_l": fuel[2],
                "predicted_time_lost_s": time[0],
                "predicted_time_p90_low_s": time[1],
                "predicted_time_p90_high_s": time[2],
                "context_ood_status": context_status,
                "is_selected_for_lico": selected,
                "selection_status": selection_status,
                "selection_reason": reason,
            }
        )
    return pl.DataFrame(rows).sort("brake_onset_reference_m")


def _historical_context_bounds() -> dict[str, dict[str, float]]:
    references = pl.read_csv(PROJECT_ROOT / CROSS_ML_DIR / "fold_push_references.csv")
    historical = pl.concat(
        [
            references.filter(pl.col("fold_id") == "spa_to_paul_zero_lico_shot"),
            references.filter(pl.col("fold_id") == "paul_to_spa_zero_lico_shot"),
        ]
    ).unique(["circuit_id", "zone_id"])
    columns = {
        "deceleration_distance_reference_m": "push_deceleration_distance_reference_m",
        "approach_speed_reference_kph": "push_approach_speed_reference_kph",
        "min_speed_reference_kph": "push_min_speed_reference_kph",
    }
    return {
        local: {
            "min": float(historical[source].min()),
            "p05": float(historical[source].quantile(0.05, interpolation="nearest")),
            "p95": float(historical[source].quantile(0.95, interpolation="nearest")),
            "max": float(historical[source].max()),
        }
        for local, source in columns.items()
    }


def _context_status(
    reference: dict[str, Any], bounds: dict[str, dict[str, float]]
) -> str:
    outside_inner = False
    for column, limits in bounds.items():
        value = float(reference[column])
        if value < limits["min"] or value > limits["max"]:
            return "unsupported_context"
        outside_inner |= value < limits["p05"] or value > limits["p95"]
    return "caution_context_ood" if outside_inner else "inside_historical_p05_p95"


def _prediction_interval(
    fit: dict[str, Any], ratio: float | None
) -> tuple[float | None, float | None, float | None]:
    if ratio is None:
        return None, None, None
    central = float(fit["slope"]) * ratio
    low = max(
        0.0,
        float(fit["source_slope_min"]) * ratio - float(fit["p90_absolute_error"]),
    )
    high = float(fit["source_slope_max"]) * ratio + float(fit["p90_absolute_error"])
    return central, low, high


def _interpolate_acceleration(reference: dict[str, Any], ratio: float) -> float:
    grid = [
        (0.0, reference["acceleration_ratio_0_0_reference_mps2"]),
        (0.25, reference["acceleration_ratio_0_25_reference_mps2"]),
        (0.5, reference["acceleration_ratio_0_5_reference_mps2"]),
        (1.0, reference["acceleration_ratio_1_0_reference_mps2"]),
        (1.5, reference["acceleration_ratio_1_5_reference_mps2"]),
    ]
    for (left_x, left_y), (right_x, right_y) in zip(grid, grid[1:], strict=True):
        if left_x <= ratio <= right_x:
            weight = (ratio - left_x) / (right_x - left_x)
            return float(left_y) + weight * (float(right_y) - float(left_y))
    raise ValueError(f"action ratio outside acceleration grid: {ratio}")


def _verify_plan_consistency(pack_dir: Path, manifest: dict[str, Any]) -> None:
    plan = pl.read_csv(pack_dir / "plan.csv")
    predictions = pl.read_csv(pack_dir / "predictions.csv").filter(
        pl.col("is_selected_for_lico")
    )
    if set(plan["zone_id"].to_list()) != set(predictions["zone_id"].to_list()):
        raise ValueError("plan/prediction selected-zone mismatch")
    if plan.height != len(SELECTED_DISTANCES_M):
        raise ValueError("unexpected live plan zone count")
    joined = plan.join(predictions, on="zone_id", suffix="_prediction")
    for row in joined.iter_rows(named=True):
        for left, right in (
            ("selected_lico_distance_m", "selected_lico_distance_m_prediction"),
            ("expected_fuel_saved_l", "predicted_fuel_saved_l"),
            ("expected_time_lost_s", "predicted_time_lost_s"),
        ):
            if not math.isclose(float(row[left]), float(row[right]), abs_tol=1e-9):
                raise ValueError(f"plan/prediction mismatch: {row['zone_id']} {left}")
    plan_manifest = json.loads(
        (pack_dir / "plan_manifest.json").read_text(encoding="utf-8")
    )
    if plan_manifest["plan_id"] != manifest["plan_id"]:
        raise ValueError("plan manifest lineage mismatch")


class _SyntheticSource:
    def __init__(self, samples: list[LmuLiveTelemetrySample]):
        self.samples = iter(samples)

    def read_next_sample(self, *, timeout_ms: int):
        del timeout_ms
        try:
            return next(self.samples)
        except StopIteration:
            raise AssertionError("preflight runtime did not stop") from None

    def close(self) -> None:
        pass


def preflight_schedule(plan_path: Path) -> dict[str, int]:
    plan = pl.read_csv(plan_path)
    enabled = (11, 12, 14, 15)
    positions = sorted(
        {
            0.0,
            *[
                position
                for cue in plan["cue_distance_m"].to_list()
                for position in (max(0.0, float(cue) - 0.5), float(cue) + 0.5)
            ],
        }
    )
    samples = [
        LmuLiveTelemetrySample(
            lap_number=lap,
            lap_distance_m=distance,
            ts=float(index),
            elapsed_s=float(index),
        )
        for index, (lap, distance) in enumerate(
            (lap, distance) for lap in range(9, 18) for distance in positions
        )
    ]
    audio = RecordingAudioCueAdapter()
    with tempfile.TemporaryDirectory(prefix="licor-bahrain-preflight-") as temporary:
        events = run_static_live_cue_session(
            plan_path=plan_path,
            event_log_path=Path(temporary) / "events.csv",
            sample_source=_SyntheticSource(samples),
            audio_adapter=audio,
            config=LiveStaticCueSessionConfig(
                cue_lap_numbers=enabled,
                stop_after_lap_number=16,
            ),
        )
    expected = {(lap, zone) for lap in enabled for zone in plan["zone_id"].to_list()}
    actual = {(cue.lap_number, cue.zone_id) for cue in audio.cues}
    if actual != expected:
        raise AssertionError("Bahrain preflight cue schedule mismatch")
    if events.height != 8 * plan.height:
        raise AssertionError("Bahrain preflight crossing log mismatch")
    return {
        "scored_laps": 7,
        "cue_count": len(audio.cues),
        "logged_crossings": events.height,
    }


def _run_metadata_template() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "status": "prepared_not_run",
        "run_id": "",
        "telemetry_duckdb": "",
        "source_plan_id": PLAN_ID,
        "collection_protocol_id": "bahrain_lmp2_circuit_c_v1",
        "collection_session_id": "zero_lico_shot_validation_01",
        "collection_design": "static_prediction_validation",
        "run_type": "push_lico_interleaved",
        "lap_pattern": list(SCORING_PATTERN),
        "execution_quality": "unknown",
        "labels_quality": "pending_driver_review",
        "track_name_expected": "Bahrain International Circuit",
        "car_class_expected": "LMP2_ELMS",
        "car_expected": "Oreca 07 ELMS Custom Team 2025 #397",
        "starting_fuel_l": 55,
        "tire_wear_multiplier": 0,
        "weather_constant": True,
        "setup_id": "constant_not_recorded",
        "audio_cue_debrief": {"expected": 24, "heard": None, "missed": None},
        "driver_notes": "",
    }


def _write_lap_notes(path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "relative_lap",
                "role",
                "driver_lap_label",
                "execution_quality",
                "affected_turns",
                "cue_missed",
                "traffic_or_error",
                "notes",
            ],
        )
        writer.writeheader()
        for row in lap_schedule():
            writer.writerow(
                {
                    "relative_lap": row["scored_index"],
                    "role": row["role"],
                    "driver_lap_label": "",
                    "execution_quality": "",
                    "affected_turns": "",
                    "cue_missed": "",
                    "traffic_or_error": "",
                    "notes": "",
                }
            )


def _powershell_launcher(pack_dir: Path) -> str:
    relative_root = Path(os.path.relpath(PROJECT_ROOT, pack_dir)).as_posix()
    return """param(
    [ValidateRange(0,9999)][Nullable[int]]$FirstScoredLap = $null,
    [ValidatePattern('^[A-Za-z0-9_-]+$')][string]$RunId = ('bahrain_lico_' + (Get-Date -Format 'yyyyMMdd_HHmmss')),
    [switch]$ConfirmTelemetryRecording,
    [string]$TelemetryDir = 'C:\\Program Files (x86)\\Steam\\steamapps\\common\\Le Mans Ultimate\\UserData\\Telemetry'
)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '__ROOT__')).Path
$python = Join-Path $projectRoot '.venv/Scripts/python.exe'
Push-Location $projectRoot
try {
    if (-not $ConfirmTelemetryRecording) {
        throw 'Telemetry confirmation missing. Start LMU telemetry recording, then relaunch with -ConfirmTelemetryRecording.'
    }
    if (-not (Test-Path -LiteralPath $TelemetryDir)) { throw "LMU telemetry directory not found: $TelemetryDir" }
    & $python scripts/build_bahrain_lico_validation_pack.py --verify-only --pack-dir $PSScriptRoot
    if ($LASTEXITCODE -ne 0) { throw 'Pack preflight failed.' }
    $lapProbe = @(& $python scripts/run_lmu_live_cues.py --show-current-lap)
    if ($LASTEXITCODE -ne 0) { throw 'Could not read the current LMU lap. Enter the car and retry.' }
    $lapProbeText = $lapProbe -join [Environment]::NewLine
    Write-Host $lapProbeText
    if ($lapProbeText -notmatch 'absolute_lap_number=(?<lap>-?[0-9]+) lap_distance_m=(?<distance>-?[0-9]+(?:[.][0-9]+)?)') {
        throw 'Could not parse the current absolute LMU lap.'
    }
    $nextLap = [int]$Matches['lap'] + 1
    if ($null -eq $FirstScoredLap) {
        $FirstScoredLap = $nextLap
        Write-Host "FirstScoredLap auto-detected as $FirstScoredLap. Start before the next start/finish crossing."
    } elseif ($FirstScoredLap -lt $nextLap) {
        throw "FirstScoredLap=$FirstScoredLap is already in the past; use $nextLap or omit it."
    }
    $roles = @('push','lico','lico','push','lico','lico','push')
    $schedule = @(for ($i = 0; $i -lt 7; $i++) {
        [pscustomobject]@{scored_index=$i+1;lap_number=$FirstScoredLap+$i;role=$roles[$i];cue_enabled=($roles[$i] -eq 'lico');fuel_start_l='';cue_missed='';traffic_or_error='';notes=''}
    })
    $cueLaps = @($schedule | Where-Object cue_enabled | ForEach-Object lap_number)
    $sessionDir = Join-Path (Split-Path $PSScriptRoot -Parent) ('sessions/' + $RunId)
    if (Test-Path -LiteralPath $sessionDir) { throw 'Run directory already exists; choose a new RunId.' }
    New-Item -ItemType Directory -Path $sessionDir -Force | Out-Null
    $schedule | Export-Csv -LiteralPath (Join-Path $sessionDir 'lap_schedule.csv') -NoTypeInformation -Encoding UTF8
    foreach ($name in @('run_metadata_template.json','lap_notes_template.csv','pack_manifest.json','plan_manifest.json','plan.csv','predictions.csv','physical_references.csv','track_zones.json','driver_review.json')) {
        Copy-Item -LiteralPath (Join-Path $PSScriptRoot $name) -Destination $sessionDir
    }
    $metadataPath = Join-Path $sessionDir 'run_metadata_template.json'
    $metadata = Get-Content -LiteralPath $metadataPath | ConvertFrom-Json
    $metadata.run_id = $RunId
    $metadata.status = 'session_started'
    $metadata | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $metadataPath -Encoding UTF8
    $resolvedConfig = @{run_id=$RunId;first_scored_lap=$FirstScoredLap;scored_laps=7;lap_pattern=$roles;cue_laps=$cueLaps;stop_after_lap=$FirstScoredLap+6;emit_system_beep=$true;telemetry_log='telemetry.csv';adaptive_mode='offline_after_run_only'}
    $resolvedConfig | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $sessionDir 'session_config.json') -Encoding UTF8
    $schedule | Format-Table
    Write-Host 'Expected audio: 6 zones x 4 LICO laps = 24 beeps. Push laps remain silent but logged.'
    Write-Host 'At every beep: fully release the throttle, coast to your normal braking point, then drive the corner normally.'
    $telemetryStartedAt = Get-Date
    $liveArgs = @('scripts/run_lmu_live_cues.py','--plan',(Join-Path $PSScriptRoot 'plan.csv'),'--event-log',(Join-Path $sessionDir 'events.csv'),'--accuracy-log',(Join-Path $sessionDir 'events_accuracy.csv'),'--telemetry-log',(Join-Path $sessionDir 'telemetry.csv'),'--run-id',$RunId,'--stop-after-lap',($FirstScoredLap+6),'--cue-laps') + $cueLaps + @('--emit-system-beep')
    & $python @liveArgs
    if ($LASTEXITCODE -ne 0) { throw 'Live session exited with an error; preserve logs.' }
    Read-Host 'The 7 scored laps are complete. Return to the pits, stop/export LMU telemetry, then press Enter'
    $newTelemetry = Get-ChildItem -LiteralPath $TelemetryDir -Filter 'Bahrain International Circuit*.duckdb' |
        Where-Object LastWriteTime -ge $telemetryStartedAt.AddSeconds(-5) |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    $metadata = Get-Content -LiteralPath $metadataPath | ConvertFrom-Json
    if ($null -eq $newTelemetry) {
        $metadata.status = 'session_recorded_telemetry_not_found'
        Write-Warning 'No new Bahrain .duckdb found. Link it manually before analysis.'
    } else {
        $metadata.telemetry_duckdb = $newTelemetry.FullName
        $metadata.status = 'session_recorded_pending_lap_review'
        Write-Host "Linked LMU telemetry: $($newTelemetry.FullName)"
    }
    $metadata | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $metadataPath -Encoding UTF8
    Write-Host "RunId: $RunId"
    Write-Host 'Give Codex the RunId, beep count, and any errors by lap/turn.'
} finally { Pop-Location }
""".replace("__ROOT__", relative_root)


def _cmd_launcher() -> str:
    return """@echo off
setlocal
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_lico_validation.ps1" %*
exit /b %errorlevel%
"""


def _pack_readme() -> str:
    return """# Bahrain zero-LICO-shot static validation

1. Start LMU telemetry recording and enter the Bahrain LMP2 car.
2. From the LICOR root, run:

```powershell
& .\\data\\processed\\experimental\\bahrain_lmp2_transfer_2026_09\\lico_validation_pack_v1\\start_lico_validation.cmd -ConfirmTelemetryRecording
```

The launcher auto-detects the next absolute lap and runs `P/L/L/P/L/L/P`.
Six zones are cued on each LICO lap, for 24 expected beeps. This plan was frozen
before any Bahrain LICO result and has no adaptive authority during the run.
"""


def _median(values: list[float]) -> float:
    return float(statistics.median(float(value) for value in values))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack-dir", type=Path, default=DEFAULT_PACK_DIR)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    result = (
        verify_pack(args.pack_dir) if args.verify_only else build_pack(args.pack_dir)
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
