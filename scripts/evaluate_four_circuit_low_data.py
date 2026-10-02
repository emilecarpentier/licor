"""Compact retrospective four-circuit response benchmark; preserve frozen packs."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import polars as pl

from licor.analysis.cross_circuit_ml import (
    _nonnegative_two_feature_slopes,
    _nonnegative_zero_intercept_slope,
)

ROOT = Path(__file__).resolve().parents[1]
HISTORY = (
    ROOT
    / "data/processed/experimental/cross_circuit_ml_v2_release/fold_feature_views.parquet"
)
INPUT = (
    ROOT
    / "data/processed/experimental/sebring_lmp2_transfer_2026_09/phase_qualification_v1/qualified_response_rows.csv"
)
OUTPUT = ROOT / "data/processed/experimental/four_circuit_low_data_v1"
DESTINATION_FOLDS = {
    "spa_francorchamps": "paul_bahrain_to_spa_zero_lico_shot",
    "paul_ricard": "spa_bahrain_to_paul_zero_lico_shot",
    "bahrain": "spa_paul_to_bahrain_zero_lico_shot",
}
CIRCUITS = (*DESTINATION_FOLDS, "sebring")
INITIAL_RUN = "sebring_lico_20260912_132042"
CALIBRATION_LAPS = (2, 3)
TEST_LAPS = (5, 6)
PRIOR_EQUIVALENT_PASSES = 2.0
TARGETS = ("fuel_saved_l", "time_lost_s")
COLUMNS = (
    "observation_id",
    "circuit_id",
    "run_id",
    "lap_number",
    "zone_id",
    "action",
    "acceleration",
    *TARGETS,
    "planned_action",
    "quality_tier",
)


def record(path: Path) -> dict:
    with path.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    return {"path": str(path.resolve()), "sha256": digest}


def validate_rows(rows: pl.DataFrame) -> None:
    missing = set(COLUMNS) - set(rows.columns)
    if missing:
        raise ValueError(f"missing response columns: {sorted(missing)}")
    for column in ("observation_id", "circuit_id", "run_id", "zone_id", "quality_tier"):
        if (
            rows[column].null_count()
            or rows.filter(
                pl.col(column).cast(pl.String).str.strip_chars() == ""
            ).height
        ):
            raise ValueError(f"null or empty identity/quality field: {column}")
    laps = rows["lap_number"].cast(pl.Float64)
    if (
        laps.null_count()
        or not laps.is_finite().all()
        or (laps < 0).any()
        or (laps != laps.floor()).any()
    ):
        raise ValueError("lap_number requires non-negative integers")
    if set(rows["quality_tier"]) - {
        "historical_qualified",
        "strict_retry",
        "exploratory_only",
    }:
        raise ValueError("unknown quality tier")
    if (
        rows["observation_id"].null_count()
        or rows["observation_id"].n_unique() != rows.height
    ):
        raise ValueError("duplicate or null observation_id")
    if set(rows["circuit_id"].unique()) - set(CIRCUITS):
        raise ValueError("unexpected circuit in compact benchmark")
    if (
        rows.group_by("run_id")
        .agg(pl.col("circuit_id").n_unique().alias("n"))
        .filter(pl.col("n") > 1)
        .height
    ):
        raise ValueError("one run cannot belong to multiple circuits")
    if rows.select("run_id", "lap_number", "zone_id").is_duplicated().any():
        raise ValueError("duplicate run/lap/zone observation")


def canonical_history(path: Path = HISTORY) -> pl.DataFrame:
    """One destination-fold copy per observation, with dedicated-push references."""
    manifest = json.loads(
        (path.parent / "build_manifest.json").read_text(encoding="utf-8")
    )
    if record(path)["sha256"] != manifest["artifacts"][path.name]["sha256"]:
        raise ValueError("historical fold-view hash mismatch")
    views = pl.read_parquet(path)
    parts = []
    for circuit, fold in DESTINATION_FOLDS.items():
        part = views.filter(
            (pl.col("circuit_id") == circuit)
            & (pl.col("fold_id") == fold)
            & (pl.col("split_role") == "test")
            & pl.col("score_eligible")
            & pl.col("model_eligible")
            & pl.col("has_lico")
            & pl.col("executed_lift_lead_to_push_deceleration_ratio").is_finite()
            & (pl.col("executed_lift_lead_to_push_deceleration_ratio") > 0)
            & (pl.col("executed_acceleration_lookup_status") == "in_range")
            & pl.col("push_acceleration_at_executed_lift_mps2").is_finite()
        ).select(
            "observation_id",
            "circuit_id",
            "run_id",
            "lap_number",
            "zone_id",
            pl.col("executed_lift_lead_to_push_deceleration_ratio").alias("action"),
            pl.col("push_acceleration_at_executed_lift_mps2").alias("acceleration"),
            pl.col("target_fuel_saved_vs_fold_push_l").alias("fuel_saved_l"),
            pl.col("target_time_lost_vs_fold_push_s").alias("time_lost_s"),
            pl.col("planned_lift_lead_to_push_deceleration_ratio").alias(
                "planned_action"
            ),
            pl.lit("historical_qualified").alias("quality_tier"),
        )
        if part.is_empty():
            raise ValueError(f"no canonical historical destination rows for {circuit}")
        parts.append(part)
    rows = pl.concat(parts, how="vertical_relaxed")
    validate_rows(rows)
    if rows.filter(pl.col("run_id").str.contains("232207")).height:
        raise ValueError("locked Paul confirmation must remain excluded")
    return rows.sort("observation_id")


def paired_rows(rows: pl.DataFrame, target: str) -> pl.DataFrame:
    """Same finite cohort for action-only and acceleration interaction models."""
    return rows.filter(
        pl.col("action").is_finite()
        & (pl.col("action") > 0)
        & pl.col("acceleration").is_finite()
        & pl.col(target).is_finite()
    ).sort("observation_id")


def ids(rows: pl.DataFrame) -> str:
    return json.dumps(sorted(rows["observation_id"].to_list()), separators=(",", ":"))


def coefficients(train: pl.DataFrame, target: str, model: str) -> tuple[float, float]:
    action = train["action"].to_list()
    outcome = train[target].to_list()
    if model == "action_only":
        fitted = _nonnegative_zero_intercept_slope(action, outcome)
        if fitted is None:
            raise ValueError("no finite action support")
        return fitted, 0.0
    interaction = (
        train["action"] * train["acceleration"].clip(lower_bound=0)
    ).to_list()
    fitted = _nonnegative_two_feature_slopes(action, interaction, outcome)
    if fitted is None:
        raise ValueError("no finite interaction support")
    return fitted


def metric_rows(predictions: pl.DataFrame, groups: list[str]) -> pl.DataFrame:
    return (
        predictions.group_by(groups)
        .agg(
            pl.len().alias("test_count"),
            pl.col("error").abs().mean().alias("mae"),
            (pl.col("error") ** 2).mean().sqrt().alias("rmse"),
            pl.col("error").mean().alias("bias"),
            pl.col("actual").abs().mean().alias("zero_prediction_mae"),
            (pl.col("actual") ** 2).mean().sqrt().alias("zero_prediction_rmse"),
        )
        .sort(groups)
    )


def support_bounds(train: pl.DataFrame, test: pl.DataFrame) -> dict:
    result = {"train_count": train.height, "test_count": test.height}
    outside = pl.lit(False)
    for column in ("action", "acceleration"):
        low, high = float(train[column].min()), float(train[column].max())
        result[f"train_{column}_min"] = low
        result[f"train_{column}_max"] = high
        outside = outside | (pl.col(column) < low) | (pl.col(column) > high)
    result["test_outside_train_marginal_ranges"] = test.filter(outside).height
    return result


def evaluate_loco(
    rows: pl.DataFrame, *, cohort: str = "strict"
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    validate_rows(rows)
    if cohort not in {"strict", "sensitivity"}:
        raise ValueError("cohort must be strict or sensitivity")
    selected = rows.filter(
        (pl.col("circuit_id") != "sebring")
        | (pl.col("quality_tier") == "strict_retry")
        | (
            (pl.col("quality_tier") == "exploratory_only")
            & pl.lit(cohort == "sensitivity")
        )
    )
    prediction_rows, fits = [], []
    for target in TARGETS:
        clean = paired_rows(selected, target)
        if set(clean["circuit_id"].unique()) != set(CIRCUITS):
            raise ValueError(
                f"four non-empty circuit cohorts required: {cohort}/{target}"
            )
        for circuit in CIRCUITS:
            train = clean.filter(pl.col("circuit_id") != circuit)
            test = clean.filter(pl.col("circuit_id") == circuit)
            if set(train["run_id"]) & set(test["run_id"]):
                raise ValueError("run leakage across LOCO roles")
            for model in ("action_only", "action_acceleration"):
                action_slope, acceleration_slope = coefficients(train, target, model)
                fits.append(
                    {
                        "cohort": cohort,
                        "held_out_circuit": circuit,
                        "target": target,
                        "model": model,
                        "action_slope": action_slope,
                        "acceleration_slope": acceleration_slope,
                        **support_bounds(train, test),
                        "train_observation_ids": ids(train),
                        "test_observation_ids": ids(test),
                        "train_run_ids": "|".join(sorted(set(train["run_id"]))),
                        "test_run_ids": "|".join(sorted(set(test["run_id"]))),
                    }
                )
                for row in test.iter_rows(named=True):
                    predicted = action_slope * row["action"] + acceleration_slope * row[
                        "action"
                    ] * max(row["acceleration"], 0)
                    prediction_rows.append(
                        {
                            "cohort": cohort,
                            "held_out_circuit": circuit,
                            "target": target,
                            "model": model,
                            **{key: row[key] for key in COLUMNS if key not in TARGETS},
                            "actual": row[target],
                            "predicted": predicted,
                            "error": predicted - row[target],
                        }
                    )
    predictions = pl.DataFrame(prediction_rows, infer_schema_length=None)
    metrics = metric_rows(
        predictions, ["cohort", "held_out_circuit", "target", "model"]
    )
    macro = (
        metrics.group_by("cohort", "target", "model")
        .agg(
            pl.col("held_out_circuit").n_unique().alias("circuit_count"),
            pl.col("mae").mean().alias("macro_four_circuit_mae"),
            pl.col("zero_prediction_mae").mean().alias("macro_four_circuit_zero_mae"),
            pl.col("test_count").sum().alias("total_test_rows"),
        )
        .sort("cohort", "target", "model")
    )
    return predictions, metrics, pl.DataFrame(fits), macro


def evaluate_few_lap(
    rows: pl.DataFrame,
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame, dict]:
    """Provisional original-run 2/3 -> 5/6 diagnostic; never replace tests by retry."""
    validate_rows(rows)
    historical = rows.filter(pl.col("circuit_id") != "sebring")
    destination = rows.filter(
        (pl.col("circuit_id") == "sebring") & (pl.col("run_id") == INITIAL_RUN)
    )
    prediction_rows, fit_rows, cohorts = [], [], {}
    for target in TARGETS:
        train = paired_rows(historical, target)
        if set(train["circuit_id"]) != set(DESTINATION_FOLDS):
            raise ValueError(
                "few-lap prior requires all three historical circuits only"
            )
        prior, _ = coefficients(train, target, "action_only")
        usable = paired_rows(destination, target)
        calibration = usable.filter(pl.col("lap_number").is_in(CALIBRATION_LAPS))
        test = usable.filter(pl.col("lap_number").is_in(TEST_LAPS))
        zones = []
        for zone in sorted(set(calibration["zone_id"])):
            cal = calibration.filter(pl.col("zone_id") == zone)
            held_out = test.filter(pl.col("zone_id") == zone)
            first = cal.filter(pl.col("lap_number") == CALIBRATION_LAPS[0])
            if (
                sorted(cal["lap_number"].to_list()) == list(CALIBRATION_LAPS)
                and sorted(held_out["lap_number"].to_list()) == list(TEST_LAPS)
                and first.filter(
                    pl.col("planned_action").is_finite()
                    & (pl.col("planned_action") > 0)
                ).height
                == 1
            ):
                zones.append(zone)
        if not zones:
            raise ValueError(
                f"no complete original frozen calibration/test cohort: {target}"
            )
        calibration = calibration.filter(pl.col("zone_id").is_in(zones))
        test = test.filter(pl.col("zone_id").is_in(zones))
        cohorts[target] = {
            "zones": zones,
            "calibration_observation_ids": ids(calibration),
            "test_observation_ids": ids(test),
            "eligible_original_rows": usable.height,
            "excluded_from_complete_cohort": usable.height
            - calibration.height
            - test.height,
            "status": "provisional_unlocalized_first_attempt_errors",
        }
        for budget in (0, 1, 2):
            for model in (
                ["global_prior"] if budget == 0 else ["prior_adapted", "local_only"]
            ):
                for zone in zones:
                    cal_zone = calibration.filter(pl.col("zone_id") == zone)
                    local = cal_zone.filter(
                        pl.col("lap_number").is_in(CALIBRATION_LAPS[:budget])
                    )
                    test_zone = test.filter(pl.col("zone_id") == zone)
                    planned = float(
                        cal_zone.filter(pl.col("lap_number") == CALIBRATION_LAPS[0])[
                            "planned_action"
                        ][0]
                    )
                    penalty = (
                        PRIOR_EQUIVALENT_PASSES * planned**2
                        if model == "prior_adapted"
                        else 0.0
                    )
                    xx = float((local["action"] ** 2).sum()) + penalty
                    xy = (
                        float((local["action"] * local[target]).sum()) + penalty * prior
                    )
                    fitted = prior if budget == 0 else max(0.0, xy / xx)
                    fit_rows.append(
                        {
                            "target": target,
                            "budget_laps": budget,
                            "model": model,
                            "zone_id": zone,
                            "slope": fitted,
                            "prior_slope": prior,
                            "ridge_penalty": penalty,
                            "planned_action_scale": planned,
                            "train_observation_ids": ids(train),
                            **support_bounds(train, test_zone),
                            "calibration_observation_ids": ids(local),
                            "test_observation_ids": ids(test_zone),
                            "calibration_count": local.height,
                            "status": "provisional_unlocalized_first_attempt_errors",
                        }
                    )
                    for row in test_zone.iter_rows(named=True):
                        predicted = fitted * row["action"]
                        prediction_rows.append(
                            {
                                "target": target,
                                "budget_laps": budget,
                                "model": model,
                                "observation_id": row["observation_id"],
                                "run_id": row["run_id"],
                                "lap_number": row["lap_number"],
                                "zone_id": zone,
                                "quality_tier": row["quality_tier"],
                                "actual": row[target],
                                "predicted": predicted,
                                "error": predicted - row[target],
                            }
                        )
    predictions = pl.DataFrame(prediction_rows)
    return (
        predictions,
        metric_rows(predictions, ["target", "budget_laps", "model"]),
        pl.DataFrame(fit_rows),
        cohorts,
    )


def build(
    input_path: Path = INPUT, output_dir: Path = OUTPUT, *, history_path: Path = HISTORY
) -> dict:
    if output_dir.exists():
        raise FileExistsError(f"refusing to overwrite compact benchmark: {output_dir}")
    input_record = record(input_path)
    qualification_manifest_path = input_path.parent / "manifest.json"
    qualification_manifest = json.loads(
        qualification_manifest_path.read_text(encoding="utf-8")
    )
    if (
        input_record["sha256"]
        != qualification_manifest["artifact_hashes"][input_path.name]
    ):
        raise ValueError("qualified response hash mismatch")
    history_record = record(history_path)
    historical = canonical_history(history_path)
    sebring = pl.read_csv(input_path)
    validate_rows(sebring)
    if set(sebring["circuit_id"]) != {"sebring"} or set(sebring["quality_tier"]) - {
        "strict_retry",
        "exploratory_only",
    }:
        raise ValueError("unexpected Sebring circuit or qualification tier")
    rows = pl.concat(
        [historical.select(COLUMNS), sebring.select(COLUMNS)], how="vertical_relaxed"
    )
    outputs = {"canonical_response_rows": rows}
    for cohort in ("strict", "sensitivity"):
        values = evaluate_loco(rows, cohort=cohort)
        outputs.update(
            {
                f"loco_{cohort}_{name}": frame
                for name, frame in zip(
                    ("predictions", "metrics", "fits", "macro_metrics"),
                    values,
                    strict=True,
                )
            }
        )
    predictions, metrics, fits, cohorts = evaluate_few_lap(rows)
    outputs.update(
        few_lap_predictions=predictions, few_lap_metrics=metrics, few_lap_fits=fits
    )
    if record(input_path) != input_record or record(history_path) != history_record:
        raise ValueError("input changed during benchmark")
    manifest = {
        "artifact_id": "four_circuit_low_data_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "retrospective_compact_response_benchmark_not_pipeline_v2_replacement",
        "sources": [
            input_record,
            record(qualification_manifest_path),
            history_record,
            record(history_path.parent / "build_manifest.json"),
            record(Path(__file__)),
            record(ROOT / "src/licor/analysis/cross_circuit_ml.py"),
        ],
        "canonical_history_policy": DESTINATION_FOLDS,
        "strict_policy": "Historical qualified rows plus Sebring strict_retry only: restricted conditional sensitivity, not clean-driver or complete-recovery certification. Both models use identical finite action/acceleration/target coverage per target.",
        "sensitivity_policy": "Includes exploratory Sebring rows with qualification flags preserved; not equal-quality evidence.",
        "grouping": "Entire held-out circuit, therefore entire runs, excluded from each response fit. First Sebring attempt and retry are correlated simulator-session recordings, not independent repetitions.",
        "macro_rule": "Unweighted arithmetic mean of four circuit MAEs, separately per target/model; not a pooled row-weighted MAE.",
        "few_lap": {
            "initial_run": INITIAL_RUN,
            "calibration_laps": CALIBRATION_LAPS,
            "test_laps": TEST_LAPS,
            "prior_equivalent_passes": PRIOR_EQUIVALENT_PASSES,
            "cohorts": cohorts,
            "status": "provisional_unlocalized_first_attempt_errors",
            "no_retry_test_replacement": True,
        },
        "limitations": [
            "Executed actions and qualified phase masks support retrospective diagnostics, not a new prospective blind-validation claim.",
            "Targets retain dedicated earlier push references. Same-attempt push controls are not pooled into the benchmark.",
            "Sebring acceleration uses directly sampled push grid; historical acceleration uses fold-local ratio-grid interpolation. Method difference limits attribution of interaction gains.",
            "No transforms, threshold tuning, uncertainty significance claim or new circuit recommendation is fitted from held-out outcomes.",
            "First-attempt few-lap curves are provisional due to unlocalized driver errors and shared baseline/session dependencies.",
        ],
    }
    output_dir.mkdir(parents=True)
    for name, frame in outputs.items():
        frame.write_csv(output_dir / f"{name}.csv")
    manifest["artifacts"] = [record(path) for path in sorted(output_dir.iterdir())]
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=INPUT)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT)
    parser.add_argument("--history", type=Path, default=HISTORY)
    args = parser.parse_args()
    print(
        json.dumps(
            build(args.input, args.output_dir, history_path=args.history), indent=2
        )
    )
