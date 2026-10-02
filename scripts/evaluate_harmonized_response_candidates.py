"""Development-only LOCO: harmonized acceleration, linear and convex candidates."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import polars as pl

from licor.analysis.low_data_response import MODELS, fit_response

from evaluate_four_circuit_low_data import (
    CIRCUITS,
    ROOT,
    TARGETS,
    ids,
    metric_rows,
    paired_rows,
    record,
    support_bounds,
    validate_rows,
)

INPUT = (
    ROOT
    / "data/processed/experimental/four_circuit_harmonized_v1/canonical_response_rows.csv"
)
OUTPUT = ROOT / "data/processed/experimental/four_circuit_response_candidates_v1"


def evaluate(
    rows: pl.DataFrame, *, cohort: str
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    validate_rows(rows)
    if cohort not in {"strict", "sensitivity"}:
        raise ValueError("unknown cohort")
    if cohort == "strict":
        rows = rows.filter(
            (pl.col("circuit_id") != "sebring")
            | (pl.col("quality_tier") == "strict_retry")
        )
    predictions, fits = [], []
    for target in TARGETS:
        usable = paired_rows(rows, target)
        if set(usable["circuit_id"]) != set(CIRCUITS):
            raise ValueError("four circuits with paired support required")
        for circuit in CIRCUITS:
            train = usable.filter(pl.col("circuit_id") != circuit)
            test = usable.filter(pl.col("circuit_id") == circuit)
            assert not set(train["run_id"]) & set(test["run_id"])
            for model in MODELS:
                fit = fit_response(
                    train["action"].to_list(),
                    train["acceleration"].to_list(),
                    train[target].to_list(),
                    model=model,
                )
                fits.append(
                    {
                        "cohort": cohort,
                        "held_out_circuit": circuit,
                        "target": target,
                        "model": model,
                        "linear": fit.linear,
                        "second": fit.second,
                        **support_bounds(train, test),
                        "train_ids": ids(train),
                        "test_ids": ids(test),
                    }
                )
                for row in test.iter_rows(named=True):
                    predicted = fit.predict(row["action"], row["acceleration"])
                    predictions.append(
                        {
                            "cohort": cohort,
                            "held_out_circuit": circuit,
                            "target": target,
                            "model": model,
                            "observation_id": row["observation_id"],
                            "quality_tier": row["quality_tier"],
                            "actual": row[target],
                            "predicted": predicted,
                            "error": predicted - row[target],
                        }
                    )
    prediction_frame = pl.DataFrame(predictions)
    metrics = metric_rows(
        prediction_frame, ["cohort", "held_out_circuit", "target", "model"]
    )
    # Fuel over-prediction is a shortfall risk, not interchangeable with symmetric MAE.
    risks = prediction_frame.group_by(
        "cohort", "held_out_circuit", "target", "model"
    ).agg(
        (pl.col("error") > 0).mean().alias("overprediction_fraction"),
        pl.col("error")
        .clip(lower_bound=0)
        .mean()
        .alias("mean_positive_overprediction"),
        pl.col("error").quantile(0.9).alias("p90_signed_error"),
    )
    return (
        prediction_frame,
        metrics.join(risks, on=["cohort", "held_out_circuit", "target", "model"]),
        pl.DataFrame(fits),
    )


def build(input_path: Path, output: Path) -> dict:
    if output.exists():
        raise FileExistsError(f"refusing overwrite: {output}")
    source = record(input_path)
    source_manifest_path = input_path.parent / "manifest.json"
    source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    expected = next(
        item["sha256"]
        for item in source_manifest["artifacts"]
        if Path(item["path"]).name == input_path.name
    )
    if source["sha256"] != expected:
        raise ValueError("harmonized input hash mismatch")
    rows = pl.read_csv(input_path)
    frames = {}
    for cohort in ("strict", "sensitivity"):
        predictions, metrics, fits = evaluate(rows, cohort=cohort)
        frames.update(
            {
                f"{cohort}_predictions": predictions,
                f"{cohort}_metrics": metrics,
                f"{cohort}_fits": fits,
            }
        )
    metrics = pl.concat([frames["strict_metrics"], frames["sensitivity_metrics"]])
    frames["macro_metrics"] = (
        metrics.group_by("cohort", "target", "model")
        .agg(
            pl.col("mae").mean().alias("macro_mae"),
            pl.col("mean_positive_overprediction")
            .mean()
            .alias("macro_mean_positive_overprediction"),
            pl.col("held_out_circuit").n_unique().alias("circuit_count"),
            pl.col("test_count").sum().alias("test_passages"),
        )
        .sort("cohort", "target", "model")
    )
    if source != record(input_path):
        raise ValueError("input changed during evaluation")
    manifest = {
        "status": "development_only_not_new_confirmatory_validation",
        "sources": [
            source,
            record(source_manifest_path),
            record(Path(__file__)),
            record(ROOT / "src/licor/analysis/low_data_response.py"),
            record(ROOT / "src/licor/analysis/cross_circuit_ml.py"),
            record(ROOT / "scripts/evaluate_four_circuit_low_data.py"),
        ],
        "models": MODELS,
        "selection": "No tuning or production selection; all candidates reported on identical cohorts.",
        "limitations": [
            "Four circuits already inspected: future selection on these scores requires new prospective confirmation.",
            "Executed-action response error is not autonomous planned-action policy performance.",
            "Convexity is in action at fixed acceleration; acceleration varies along a real approach.",
            "Non-negative coefficients do not provide calibrated lower fuel bounds.",
        ],
    }
    output.mkdir(parents=True)
    for name, frame in frames.items():
        frame.write_csv(output / f"{name}.csv")
    manifest["artifacts"] = [record(path) for path in sorted(output.iterdir())]
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=INPUT)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT)
    args = parser.parse_args()
    print(json.dumps(build(args.input, args.output_dir), indent=2))
