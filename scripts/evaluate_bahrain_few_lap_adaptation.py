"""Retrospective within-run Bahrain calibration-budget diagnostic, not LOCO."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import polars as pl


ROOT = Path(__file__).resolve().parents[1]
INPUT = (
    ROOT
    / "data/processed/experimental/cross_circuit_ml_v2_release/fold_feature_views.parquet"
)
OUTPUT = ROOT / "data/processed/experimental/bahrain_few_lap_adaptation_v1"
FOLD = "spa_paul_to_bahrain_zero_lico_shot"
RUN = "bahrain_lico_20260911_224825"
PUSH_RUN = "bahrain_push_20260911_212732"
ACTION = "executed_lift_lead_to_push_deceleration_ratio"
PLANNED = "planned_lift_lead_to_push_deceleration_ratio"
TARGETS = {
    "fuel_saved_l": "target_fuel_saved_vs_fold_push_l",
    "time_lost_s": "target_time_lost_vs_fold_push_s",
}
CALIBRATION_LAPS = (24, 25)
TEST_LAPS = (27, 28)
PRIOR_EQUIVALENT_PASSES = 2.0


def _positive_finite(column: str) -> pl.Expr:
    return pl.col(column).is_finite() & (pl.col(column) > 0)


def slope(
    frame: pl.DataFrame, target: str, *, prior: float = 0.0, penalty: float = 0.0
) -> float:
    """Constrained zero-intercept ridge slope; only supplied rows enter fit."""
    xx = float((frame[ACTION] ** 2).sum()) + penalty
    if xx <= 0:
        raise ValueError("slope has no action support")
    xy = float((frame[ACTION] * frame[target]).sum()) + penalty * prior
    return max(0.0, xy / xx)


def evaluate(
    views: pl.DataFrame,
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame, dict]:
    """Hold laps 27/28 fixed while fitting chronological budgets 0/1/2."""
    fold = views.filter(pl.col("fold_id") == FOLD)
    if fold.is_empty():
        raise ValueError(f"missing fold: {FOLD}")
    train = fold.filter(
        (pl.col("split_role") == "train")
        & pl.col("model_eligible")
        & _positive_finite(ACTION)
    )
    if train.filter(
        ~pl.col("circuit_id").is_in(["spa_francorchamps", "paul_ricard"])
    ).height:
        raise ValueError("global response prior must use Spa and Paul Ricard only")
    calibration_refs = fold.filter(
        (pl.col("circuit_id") == "bahrain") & (pl.col("split_role") == "calibration")
    )
    if calibration_refs.is_empty() or calibration_refs["run_id"].unique().to_list() != [
        PUSH_RUN
    ]:
        raise ValueError("Bahrain references require the dedicated earlier push run")
    destination = fold.filter(
        (pl.col("run_id") == RUN)
        & (pl.col("split_role") == "test")
        & pl.col("score_eligible")
        & pl.col("model_eligible")
        & _positive_finite(ACTION)
    )
    if destination.select("observation_id").n_unique() != destination.height:
        raise ValueError("duplicate destination observation IDs")
    prediction_rows, fit_rows, cohorts = [], [], {}
    for name, target in TARGETS.items():
        clean_train = train.filter(pl.col(target).is_finite())
        prior = slope(clean_train, target)
        # Missingness establishes one common cohort before the budget loop.
        # Neither values of test targets nor test actions influence any fit.
        usable = destination.filter(pl.col(target).is_finite())
        calibration = usable.filter(pl.col("lap_number").is_in(CALIBRATION_LAPS))
        test = usable.filter(pl.col("lap_number").is_in(TEST_LAPS))
        zones = []
        for zone in sorted(calibration["zone_id"].unique().to_list()):
            cal_zone = calibration.filter(pl.col("zone_id") == zone)
            test_zone = test.filter(pl.col("zone_id") == zone)
            first = cal_zone.filter(pl.col("lap_number") == CALIBRATION_LAPS[0])
            if (
                cal_zone.height == 2
                and test_zone.height == 2
                and sorted(cal_zone["lap_number"].to_list()) == list(CALIBRATION_LAPS)
                and sorted(test_zone["lap_number"].to_list()) == list(TEST_LAPS)
                and first.filter(_positive_finite(PLANNED)).height == 1
            ):
                zones.append(zone)
        calibration = calibration.filter(pl.col("zone_id").is_in(zones))
        test = test.filter(pl.col("zone_id").is_in(zones)).sort("observation_id")
        if test.is_empty():
            raise ValueError(f"no complete fixed calibration/test cohort for {name}")
        cohorts[name] = {
            "test_observation_ids": test["observation_id"].to_list(),
            "calibration_observation_ids": calibration["observation_id"]
            .sort()
            .to_list(),
            "zones": zones,
            "excluded_destination_observation_count": destination.height
            - calibration.height
            - test.height,
        }
        for budget in range(3):
            models = (
                ["global_prior"] if budget == 0 else ["prior_adapted", "local_only"]
            )
            for model in models:
                for zone in zones:
                    local = calibration.filter(
                        (pl.col("zone_id") == zone)
                        & pl.col("lap_number").is_in(CALIBRATION_LAPS[:budget])
                    )
                    planned = float(
                        calibration.filter(
                            (pl.col("zone_id") == zone)
                            & (pl.col("lap_number") == CALIBRATION_LAPS[0])
                        )[PLANNED][0]
                    )
                    penalty = PRIOR_EQUIVALENT_PASSES * planned**2
                    fitted = (
                        prior
                        if budget == 0
                        else slope(
                            local,
                            target,
                            prior=prior,
                            penalty=penalty if model == "prior_adapted" else 0.0,
                        )
                    )
                    fit_rows.append(
                        {
                            "target": name,
                            "budget_laps": budget,
                            "model": model,
                            "zone_id": zone,
                            "slope": fitted,
                            "global_prior_slope": prior,
                            "global_training_count": clean_train.height,
                            "calibration_count": local.height,
                            "calibration_observation_ids": "|".join(
                                local["observation_id"].sort().to_list()
                            ),
                            "planned_action_scale": planned,
                            "ridge_penalty": penalty
                            if model == "prior_adapted"
                            else 0.0,
                        }
                    )
                    for row in test.filter(pl.col("zone_id") == zone).iter_rows(
                        named=True
                    ):
                        predicted = fitted * float(row[ACTION])
                        prediction_rows.append(
                            {
                                "target": name,
                                "budget_laps": budget,
                                "model": model,
                                "observation_id": row["observation_id"],
                                "run_id": RUN,
                                "lap_number": row["lap_number"],
                                "zone_id": zone,
                                "executed_action_ratio": row[ACTION],
                                "actual": row[target],
                                "predicted": predicted,
                                "error": predicted - row[target],
                            }
                        )
    predictions = pl.DataFrame(prediction_rows)
    metrics = (
        predictions.group_by("target", "budget_laps", "model")
        .agg(
            pl.len().alias("test_count"),
            pl.col("zone_id").n_unique().alias("zone_count"),
            pl.col("error").abs().mean().alias("mae"),
            (pl.col("error") ** 2).mean().sqrt().alias("rmse"),
            pl.col("error").mean().alias("bias"),
        )
        .sort("target", "budget_laps", "model")
    )
    return predictions, metrics, pl.DataFrame(fit_rows), cohorts


def _record(path: Path) -> dict:
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def build(input_path: Path = INPUT, output: Path = OUTPUT) -> dict:
    if output.exists():
        raise FileExistsError(f"refusing to overwrite calibration diagnostic: {output}")
    source_manifest_path = input_path.parent / "build_manifest.json"
    source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    if (
        _record(input_path)["sha256"]
        != source_manifest["artifacts"][input_path.name]["sha256"]
    ):
        raise ValueError("source fold feature view hash mismatch")
    predictions, metrics, fits, cohorts = evaluate(pl.read_parquet(input_path))
    manifest = {
        "analysis_id": "bahrain_few_lap_adaptation_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_fold_id": FOLD,
        "evaluation_status": "retrospective_within_run_calibration_budget_diagnostic",
        "run_role_exception": "Explicit within-run study: original Bahrain test-run laps24/25 calibrate, laps27/28 remain test. This does not alter LOCO assignments or the locked prospective score.",
        "calibration_laps_chronological": list(CALIBRATION_LAPS),
        "fixed_test_laps": list(TEST_LAPS),
        "reference_policy": "Inherited destination references use only the earlier dedicated Bahrain push run; same-run push laps never enter these targets.",
        "prior": "Nonnegative zero-intercept global slope fitted on Spa/Paul train rows only, independently for fuel and time.",
        "adaptation": "Per-zone nonnegative zero-intercept slope; ridge toward global slope with penalty = 2 * pre-run planned action ratio squared. No held-out tuning.",
        "prior_equivalent_passes": PRIOR_EQUIVALENT_PASSES,
        "cohorts": cohorts,
        "limitations": [
            "Executed actions identify a response retrospectively; this is not prospective action selection.",
            "One planned dose per zone, four repetitions in a single run; larger lifts and response curvature remain untested.",
            "Calibration/test laps share run conditions and correlated errors; no different-run calibration evidence is available.",
            "Two final test laps and six zones are not independent circuit-level replications.",
            "Targets use frozen endpoints; later recovery diagnostics are not model labels here.",
        ],
        "sources": [
            _record(input_path),
            _record(source_manifest_path),
            _record(Path(__file__)),
        ],
    }
    output.mkdir(parents=True)
    predictions.write_csv(output / "predictions.csv")
    metrics.write_csv(output / "metrics.csv")
    fits.write_csv(output / "fits.csv")
    manifest["artifacts"] = [_record(path) for path in sorted(output.iterdir())]
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=INPUT)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT)
    args = parser.parse_args()
    build(args.input, args.output_dir)
    print(json.dumps(pl.read_csv(args.output_dir / "metrics.csv").to_dicts(), indent=2))


if __name__ == "__main__":
    main()
