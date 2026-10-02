"""Retrospective, prequential Sebring response replay; never a live controller."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import asdict
from pathlib import Path

import polars as pl

from licor.analysis.continual_learning import (
    MAX_RATIO_RESIDUAL,
    MAX_SCALE,
    MAX_SCALE_STEP,
    MIN_SCALE,
    PRIOR_EQUIVALENT_PASSES,
    LocalResponse,
    Support,
    observe,
)
from licor.analysis.low_data_response import fit_response

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "data/processed/experimental/four_circuit_harmonized_v1"
OUTPUT = ROOT / "data/processed/experimental/continual_sebring_replay_v1"
REVIEW = ROOT / "config/driver_reviews/sebring_phase_qualification_2026-09-12.json"
HISTORY = {"spa_francorchamps", "paul_ricard", "bahrain"}
RUN_LAPS = {
    "sebring_lico_20260912_132042": (2, 3, 5, 6),
    "sebring_abab_20260912_134132": (8, 9, 10),
}
ZONES = tuple(f"sbr_t{turn:02d}" for turn in (1, 3, 7, 10, 13, 15, 17))
TARGETS = ("fuel_saved_l", "time_lost_s")
CONTEXT = "sebring_frozen_prior_push_8_12_common_reference"
KEYS = ("run_id", "lap_number", "zone_id")


def record(path: Path) -> dict:
    with path.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    return {"path": str(path.resolve()), "sha256": digest}


def _cohorts(rows: pl.DataFrame, annotations: list[dict]) -> tuple[list, list]:
    required = {
        "observation_id",
        "circuit_id",
        *KEYS,
        "action",
        "acceleration",
        *TARGETS,
        "planned_action",
        "quality_tier",
    }
    if required - set(rows.columns):
        raise ValueError("missing canonical response columns")
    if (
        rows["observation_id"].null_count()
        or rows["observation_id"].n_unique() != rows.height
    ):
        raise ValueError("duplicate or null observation identity")
    if rows.select(KEYS).is_duplicated().any():
        raise ValueError("duplicate run/lap/zone")
    if set(rows["circuit_id"]) != HISTORY | {"sebring"}:
        raise ValueError("exactly the four existing circuits required")
    historical = rows.filter(pl.col("circuit_id").is_in(sorted(HISTORY)))
    if set(historical["quality_tier"]) != {"historical_qualified"}:
        raise ValueError("unexpected historical quality")
    if historical.filter(pl.col("run_id").str.contains("232207")).height:
        raise ValueError("locked Paul confirmation must remain excluded")
    train = historical.filter(
        pl.all_horizontal(
            [pl.col(c).is_finite() for c in ("action", "acceleration", *TARGETS)]
        )
        & (pl.col("action") > 0)
    )
    if set(train["circuit_id"]) != HISTORY:
        raise ValueError(
            "finite training support from all three prior circuits required"
        )
    destination = rows.filter(pl.col("circuit_id") == "sebring").to_dicts()
    expected = {
        (run, lap, zone)
        for run, laps in RUN_LAPS.items()
        for lap in laps
        for zone in ZONES
    }

    def key(row):
        return tuple(row[column] for column in KEYS)

    if {key(row) for row in destination} != expected:
        raise ValueError("exact frozen 49-passage destination cohort required")
    if set(train["run_id"]) & {row["run_id"] for row in destination}:
        raise ValueError("run leakage across prior and destination")
    if (
        len(annotations) != len(expected)
        or {key(row) for row in annotations} != expected
    ):
        raise ValueError("quality annotations require exact one-to-one coverage")
    lookup = {key(row): row for row in annotations}
    for row in destination:
        annotation = lookup[key(row)]
        if row["quality_tier"] != annotation["quality_tier"]:
            raise ValueError("quality tier mismatch with tracked annotation")
        if row["quality_tier"] not in {"strict_retry", "exploratory_only"}:
            raise ValueError("unexpected destination quality tier")
        row["quality_reasons"] = annotation["reasons"] or ""
    run_order = {run: index for index, run in enumerate(RUN_LAPS)}
    zone_order = {zone: index for index, zone in enumerate(ZONES)}
    destination.sort(
        key=lambda row: (
            run_order[row["run_id"]],
            row["lap_number"],
            zone_order[row["zone_id"]],
        )
    )
    return train.sort("observation_id").to_dicts(), destination


def evaluate(
    rows: pl.DataFrame, annotations: list[dict]
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame, list[dict]]:
    train, destination = _cohorts(rows, annotations)
    support = Support(
        min(row["action"] for row in train),
        max(row["action"] for row in train),
        min(row["acceleration"] for row in train),
        max(row["acceleration"] for row in train),
    )
    states, fits = {}, []
    for target in TARGETS:
        fitted = fit_response(
            [row["action"] for row in train],
            [row["acceleration"] for row in train],
            [row[target] for row in train],
            model="action_only",
        )
        for zone in ZONES:
            states[zone, target] = LocalResponse(fitted, support, CONTEXT)
        fits.append(
            {
                "target": target,
                **asdict(fitted),
                **asdict(support),
                "train_count": len(train),
                "train_observation_ids": [row["observation_id"] for row in train],
                "train_run_ids": sorted({row["run_id"] for row in train}),
                "train_circuits": sorted(HISTORY),
            }
        )
    events = []
    for sequence, row in enumerate(destination):
        for target in TARGETS:
            state = states[row["zone_id"], target]
            update = observe(
                state,
                context_id=CONTEXT,
                action=row["action"],
                acceleration=row["acceleration"],
                outcome=row[target],
                quality_ok=row["quality_tier"] == "strict_retry",
            )
            states[row["zone_id"], target] = update.after
            actual = row[target]
            finite_actual = actual is not None and math.isfinite(actual)
            fixed_error = (
                update.prior_prediction - actual
                if finite_actual and update.prior_prediction is not None
                else None
            )
            local_error = (
                update.prediction - actual
                if finite_actual and update.prediction is not None
                else None
            )
            events.append(
                {
                    "sequence": sequence,
                    "context_id": CONTEXT,
                    "target": target,
                    **{
                        name: row[name]
                        for name in (
                            "observation_id",
                            *KEYS,
                            "action",
                            "planned_action",
                            "acceleration",
                            "quality_tier",
                            "quality_reasons",
                        )
                    },
                    "actual": actual,
                    "fixed_prediction": update.prior_prediction,
                    "local_prediction": update.prediction,
                    "fixed_error": fixed_error,
                    "local_error": local_error,
                    "update_reason": update.reason,
                    "scale_before": update.before.scale,
                    "scale_after": update.after.scale,
                    "accepted_before": update.before.accepted_count,
                    "accepted_after": update.after.accepted_count,
                    "score_eligible": update.reason == "updated"
                    and fixed_error is not None
                    and local_error is not None,
                }
            )
    event_frame = pl.DataFrame(events, infer_schema_length=None)
    eligible = event_frame.filter(pl.col("score_eligible"))
    metrics = []
    lap_metrics = []
    for target in TARGETS:
        target_rows = eligible.filter(pl.col("target") == target).to_dicts()
        for model in ("fixed", "local"):
            errors = [row[f"{model}_error"] for row in target_rows]
            later_errors = [
                row[f"{model}_error"]
                for row in target_rows
                if row["accepted_before"] > 0
            ]
            metrics.append(
                {
                    "target": target,
                    "model": model,
                    "score_count": len(errors),
                    "later_pass_count": len(later_errors),
                    "later_pass_mae": sum(abs(value) for value in later_errors)
                    / len(later_errors)
                    if later_errors
                    else None,
                    "mae": sum(abs(value) for value in errors) / len(errors)
                    if errors
                    else None,
                    "bias": sum(errors) / len(errors) if errors else None,
                    "mean_fuel_overprediction_l": sum(max(value, 0) for value in errors)
                    / len(errors)
                    if errors and target == "fuel_saved_l"
                    else None,
                    "evaluation": "strict_matched_prequential_development",
                }
            )
            for run, lap in sorted(
                {(row["run_id"], row["lap_number"]) for row in target_rows}
            ):
                group = [
                    row
                    for row in target_rows
                    if (row["run_id"], row["lap_number"]) == (run, lap)
                ]
                lap_metrics.append(
                    {
                        "target": target,
                        "model": model,
                        "run_id": run,
                        "lap_number": lap,
                        "zone_count": len(group),
                        "zone_ids": "|".join(row["zone_id"] for row in group),
                        "actual_zone_sum": sum(row["actual"] for row in group),
                        "predicted_zone_sum": sum(
                            row[f"{model}_prediction"] for row in group
                        ),
                        "mean_absolute_error": sum(
                            abs(row[f"{model}_error"]) for row in group
                        )
                        / len(group),
                        "scope": "matched_qualified_windows_not_whole_lap",
                    }
                )
    return event_frame, pl.DataFrame(metrics), pl.DataFrame(lap_metrics), fits


def build(
    input_dir: Path = INPUT, output: Path = OUTPUT, review_path: Path = REVIEW
) -> dict:
    if output.exists():
        raise FileExistsError(f"refusing overwrite: {output}")
    source = input_dir / "canonical_response_rows.csv"
    upstream_path = input_dir / "manifest.json"
    sources = [record(path) for path in (source, upstream_path, review_path)]
    upstream = json.loads(upstream_path.read_text(encoding="utf-8"))
    expected = next(
        item["sha256"]
        for item in upstream["artifacts"]
        if Path(item["path"]).name == source.name
    )
    if sources[0]["sha256"] != expected:
        raise ValueError("harmonized input hash mismatch")
    review = json.loads(review_path.read_text(encoding="utf-8"))
    events, metrics, per_lap, fits = evaluate(
        pl.read_csv(source, infer_schema_length=None), review["annotations"]
    )
    if sources != [record(path) for path in (source, upstream_path, review_path)]:
        raise ValueError("input changed during replay")
    manifest = {
        "status": "retrospective_prequential_development_not_live_authority",
        "sources": sources
        + [
            record(Path(__file__)),
            record(ROOT / "src/licor/analysis/continual_learning.py"),
            record(ROOT / "src/licor/analysis/low_data_response.py"),
            record(ROOT / "src/licor/analysis/cross_circuit_ml.py"),
        ],
        "fixed_update_policy": {
            "prior_equivalent_passes": PRIOR_EQUIVALENT_PASSES,
            "max_ratio_residual": MAX_RATIO_RESIDUAL,
            "max_scale_step": MAX_SCALE_STEP,
            "scale_bounds": [MIN_SCALE, MAX_SCALE],
        },
        "destination_circuit": "sebring",
        "run_laps": RUN_LAPS,
        "zone_order": ZONES,
        "event_count": events.height,
        "metrics": metrics.to_dicts(),
        "fits": fits,
        "update_counts": events.group_by("target", "update_reason")
        .len()
        .sort("target", "update_reason")
        .to_dicts(),
        "limitations": [
            "All destination outcomes excluded from the initial prior. Model choice and constants are development choices, not fresh held-out confirmation.",
            "Action-only established baseline; acceleration retained for support checks, not incorporated into response prediction.",
            "Executed action is only known after passage; prediction-before-update is retrospective conditional response scoring, not proof of a deployable pre-cue decision.",
            "Five prior push laps and pre-reviewed geometry retained; short qualification, startup latency and autonomous new-track zone discovery are not validated.",
            "Tracked qualification masks were produced after driving. Strict retry is restricted sensitivity, not clean certification or a causal online quality detector.",
            "One quality tier serves both outcomes in this dataset; no unsupported phase-specific empirical labels are invented.",
            "Local context deliberately shared across initial and retry recordings with the same frozen push reference; session drift and fuel-mass confounding remain uncorrected.",
            "Zone and target states are independent. Updates require observed execution; excluded rows remain auditable and do not teach ineffectiveness.",
            "Marginal action/acceleration ranges do not certify joint physical support or lift safety.",
            "A zero prior cannot be corrected multiplicatively and is excluded from scoring. Scale bounds also prevent correcting more than 50% of the prior; this slice cannot discover a previously unseen effective zone.",
            "Matched qualified-window sums are not full-lap fuel budgets, optimized plans or mixed-zone counterfactual performance. No live exploration or cues changed.",
            "Budget-only adaptation would leave these zone predictions identical to fixed. No fabricated third model arm or full-race budget replay is reported.",
        ],
    }
    output.mkdir(parents=True)
    for name, frame in (("events", events), ("metrics", metrics), ("per_lap", per_lap)):
        frame.write_csv(output / f"{name}.csv")
    (output / "fits.json").write_text(
        json.dumps(fits, indent=2) + "\n", encoding="utf-8"
    )
    manifest["artifacts"] = [record(path) for path in sorted(output.iterdir())]
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=INPUT)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT)
    parser.add_argument("--review", type=Path, default=REVIEW)
    args = parser.parse_args()
    print(json.dumps(build(args.input_dir, args.output_dir, args.review), indent=2))
