"""Development-only fuel-first menu audit; mixed-zone totals are hypothetical."""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
from pathlib import Path

import polars as pl

from licor.analysis.low_data_response import fit_response

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "data/processed/experimental/four_circuit_harmonized_v1"
OUTPUT = ROOT / "data/processed/experimental/sebring_fuel_first_decisions_v1_final"
RUN = "sebring_lico_20260912_132042"
TARGETS = (0.0, 0.15, 0.20, 0.25, 0.30)
MODELS = ("action_only", "action_accel_quadratic")
HISTORY = {"spa_francorchamps", "paul_ricard", "bahrain"}


def record(path: Path) -> dict:
    with path.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    return {"path": str(path.resolve()), "sha256": digest}


def select_candidate(menu: list[dict], target: float) -> tuple[dict, str]:
    if not math.isfinite(target) or target < 0 or not menu:
        raise ValueError("finite nonnegative target and nonempty menu required")
    feasible = [row for row in menu if row["predicted_fuel_l"] + 1e-12 >= target]
    if feasible:
        return min(
            feasible,
            key=lambda row: (
                row["predicted_time_s"],
                row["predicted_fuel_l"] - target,
                row["candidate_id"],
            ),
        ), "target_met"
    return min(
        menu,
        key=lambda row: (
            -row["predicted_fuel_l"],
            row["predicted_time_s"],
            row["candidate_id"],
        ),
    ), "target_unreachable"


def _cohorts(rows: pl.DataFrame) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    if rows.select("run_id", "lap_number", "zone_id").is_duplicated().any():
        raise ValueError("duplicate run/lap/zone")
    train = rows.filter(
        pl.col("circuit_id").is_in(sorted(HISTORY))
        & (pl.col("quality_tier") == "historical_qualified")
    )
    train = train.filter(
        pl.all_horizontal(
            [
                pl.col(c).is_finite()
                for c in ("action", "acceleration", "fuel_saved_l", "time_lost_s")
            ]
        )
        & (pl.col("action") > 0)
    )
    if (
        set(train["circuit_id"]) != HISTORY
        or train.filter(pl.col("run_id").str.contains("232207")).height
    ):
        raise ValueError("three historical circuits required; locked Paul excluded")
    local = rows.filter((pl.col("circuit_id") == "sebring") & (pl.col("run_id") == RUN))
    calibration = local.filter(pl.col("lap_number").is_in([2, 3]))
    test = local.filter(pl.col("lap_number").is_in([5, 6]))
    zones = sorted(set(calibration["zone_id"]))
    if len(zones) != 7 or set(test["zone_id"]) != set(zones):
        raise ValueError("fixed seven-zone calibration/test coverage required")
    for zone in zones:
        if sorted(
            calibration.filter(pl.col("zone_id") == zone)["lap_number"].to_list()
        ) != [2, 3] or sorted(
            test.filter(pl.col("zone_id") == zone)["lap_number"].to_list()
        ) != [5, 6]:
            raise ValueError("fixed calibration 2/3 and test 5/6 required")
    if not test.select(
        pl.all_horizontal(
            pl.col("fuel_saved_l").is_finite(), pl.col("time_lost_s").is_finite()
        )
        .fill_null(False)
        .all()
    ).item():
        raise ValueError(
            "finite held-out outcomes required; never impute missing tests"
        )
    return train, calibration, test


def evaluate(rows: pl.DataFrame) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    train, calibration, test = _cohorts(rows)
    low, high = float(train["action"].min()), float(train["action"].max())
    zones = sorted(set(calibration["zone_id"]))
    decisions, candidates, fits = [], [], []
    # No held-out execution variables enter candidate construction or selection.
    planned = {}
    for row in calibration.iter_rows(named=True):
        action, acceleration = (
            row["planned_action"],
            row["acceleration_planned_harmonized"],
        )
        if (
            action is None
            or acceleration is None
            or not math.isfinite(action)
            or not math.isfinite(acceleration)
            or action <= 0
        ):
            raise ValueError(
                "finite positive planned dose and push acceleration required"
            )
        planned[row["zone_id"], "A" if row["lap_number"] == 2 else "B"] = (
            action,
            acceleration,
        )
    unsupported = any(not low <= action <= high for action, _ in planned.values())
    for model in MODELS:
        fitted = {}
        for target in ("fuel_saved_l", "time_lost_s"):
            fit = fit_response(
                train["action"].to_list(),
                train["acceleration"].to_list(),
                train[target].to_list(),
                model=model,
            )
            fitted[target] = fit
            fits.append(
                {
                    "model": model,
                    "target": target,
                    "linear": fit.linear,
                    "second": fit.second,
                    "train_count": train.height,
                    "train_action_min": low,
                    "train_action_max": high,
                    "train_observation_ids": json.dumps(
                        sorted(train["observation_id"])
                    ),
                    "calibration_predictor_laps": "2|3",
                    "test_outcome_laps": "5|6",
                    "local_response_fit_count": 0,
                }
            )
        for menu_name in (
            "whole_AB_or_reference_push",
            "hypothetical_mixed_zone_replay",
        ):
            assignments = (
                [("0",) * 7, ("A",) * 7, ("B",) * 7]
                if menu_name == "whole_AB_or_reference_push"
                else list(itertools.product(("0", "A", "B"), repeat=7))
            )
            menu = []
            for assignment in assignments:
                fuel = time = 0.0
                for zone, dose in zip(zones, assignment, strict=True):
                    if dose != "0":
                        action, acceleration = planned[zone, dose]
                        fuel += fitted["fuel_saved_l"].predict(action, acceleration)
                        time += fitted["time_lost_s"].predict(action, acceleration)
                menu.append(
                    {
                        "candidate_id": "|".join(assignment),
                        "predicted_fuel_l": fuel,
                        "predicted_time_s": time,
                    }
                )
            # Freeze choices before joining any held-out response.
            choices = [(target, *select_candidate(menu, target)) for target in TARGETS]
            actual = {
                (row["zone_id"], "B" if row["lap_number"] == 5 else "A"): row
                for row in test.iter_rows(named=True)
            }
            scored = {}
            for candidate in menu:
                fuel = time = 0.0
                for zone, dose in zip(
                    zones, candidate["candidate_id"].split("|"), strict=True
                ):
                    if dose != "0":
                        fuel += actual[zone, dose]["fuel_saved_l"]
                        time += actual[zone, dose]["time_lost_s"]
                scored[candidate["candidate_id"]] = {
                    **candidate,
                    "reference_fuel_saved_l": fuel,
                    "reference_time_lost_s": time,
                }
                candidates.append(
                    {
                        "model": model,
                        "menu": menu_name,
                        **scored[candidate["candidate_id"]],
                        "action_support_ok": not unsupported,
                    }
                )
            for target, selected, status in choices:
                if unsupported:
                    decisions.append(
                        {
                            "model": model,
                            "menu": menu_name,
                            "target_fuel_l": target,
                            "status": "abstain_action_outside_train_range",
                            "selected_candidate_id": None,
                        }
                    )
                    continue
                chosen = scored[selected["candidate_id"]]
                feasible = [
                    r
                    for r in scored.values()
                    if r["reference_fuel_saved_l"] + 1e-12 >= target
                ]
                actual_feasible = chosen["reference_fuel_saved_l"] + 1e-12 >= target
                oracle = (
                    min(feasible, key=lambda r: r["reference_time_lost_s"])
                    if feasible
                    else None
                )
                decisions.append(
                    {
                        "model": model,
                        "menu": menu_name,
                        "target_fuel_l": target,
                        "status": status,
                        "selected_candidate_id": selected["candidate_id"],
                        **{k: v for k, v in chosen.items() if k != "candidate_id"},
                        "actual_reference_feasible": actual_feasible,
                        "fuel_shortfall_l": max(
                            target - chosen["reference_fuel_saved_l"], 0.0
                        ),
                        "fuel_overpromise_l": max(
                            chosen["predicted_fuel_l"]
                            - chosen["reference_fuel_saved_l"],
                            0.0,
                        ),
                        "false_feasible": status == "target_met"
                        and not actual_feasible,
                        "time_regret_s": chosen["reference_time_lost_s"]
                        - oracle["reference_time_lost_s"]
                        if actual_feasible
                        and oracle
                        and menu_name == "whole_AB_or_reference_push"
                        else None,
                    }
                )
    return (
        pl.DataFrame(decisions, infer_schema_length=None),
        pl.DataFrame(candidates),
        pl.DataFrame(fits),
    )


def build(input_dir: Path = INPUT, output: Path = OUTPUT) -> dict:
    if output.exists():
        raise FileExistsError(f"refusing overwrite: {output}")
    path = input_dir / "canonical_response_rows.csv"
    manifest_path = input_dir / "manifest.json"
    source = record(path)
    upstream = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = next(
        r["sha256"] for r in upstream["artifacts"] if Path(r["path"]).name == path.name
    )
    if source["sha256"] != expected:
        raise ValueError("harmonized input hash mismatch")
    frames = evaluate(pl.read_csv(path, infer_schema_length=None))
    if record(path) != source:
        raise ValueError("input changed during evaluation")
    output.mkdir(parents=True)
    for name, frame in zip(
        ("decisions", "candidate_scores", "fits"), frames, strict=True
    ):
        frame.write_csv(output / f"{name}.csv")
    manifest = {
        "status": "retrospective_development_audit_not_race_feasibility",
        "targets_l": TARGETS,
        "models": MODELS,
        "candidate_zone_order": sorted(
            set(
                pl.read_csv(path, infer_schema_length=None).filter(
                    pl.col("circuit_id") == "sebring"
                )["zone_id"]
            )
        ),
        "sources": [
            source,
            record(manifest_path),
            record(Path(__file__)),
            record(ROOT / "src/licor/analysis/low_data_response.py"),
            record(ROOT / "src/licor/analysis/cross_circuit_ml.py"),
        ],
        "limitations": [
            "Seven frozen zone outcomes, not whole-lap or race fuel budget; no arrival guarantee.",
            "Only whole A/B correspond to recorded held-out plans (lap6 A, lap5 B), each once; reference push is zero by definition, not a held-out push trial.",
            "Mixed-zone menu splices outcomes from two laps; additivity, carryover and traffic independence unverified. No time regret reported for that menu.",
            "Initial driving errors remain unlocalized; no retry replacement. This is development evidence, not new prospective confirmation.",
            "Candidate predictors from planned doses and prior-push acceleration on calibration laps2/3 only. No local outcome adaptation; no test-calibrated safety margin.",
            "All candidates withheld when any nonzero candidate action is outside historical marginal action bounds. Range inclusion is not joint support certification.",
            "Targets are explicit exploratory fuel amounts per seven-zone group, not selected from test success.",
        ],
        "artifacts": [record(p) for p in sorted(output.glob("*.csv"))],
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=INPUT)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT)
    args = parser.parse_args()
    print(json.dumps(build(args.input_dir, args.output_dir), indent=2))
