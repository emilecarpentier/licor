import importlib.util
from pathlib import Path

import polars as pl
import pytest


SPEC = importlib.util.spec_from_file_location(
    "bahrain_few_lap",
    Path(__file__).resolve().parents[1]
    / "scripts/evaluate_bahrain_few_lap_adaptation.py",
)
diagnostic = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(diagnostic)


def fixture_views():
    rows = []
    for circuit, run, role, laps in [
        ("spa_francorchamps", "spa_train", "train", [1, 2]),
        ("paul_ricard", "paul_train", "train", [1, 2]),
        ("bahrain", diagnostic.PUSH_RUN, "calibration", [16, 17]),
        ("bahrain", diagnostic.RUN, "test", [24, 25, 27, 28]),
    ]:
        for lap in laps:
            for zone in ["z1", "z2"]:
                rows.append(
                    {
                        "fold_id": diagnostic.FOLD,
                        "circuit_id": circuit,
                        "run_id": run,
                        "split_role": role,
                        "lap_number": lap,
                        "zone_id": zone,
                        "observation_id": f"{run}:{lap}:{zone}",
                        "model_eligible": True,
                        "score_eligible": role == "test",
                        diagnostic.ACTION: 0.5,
                        diagnostic.PLANNED: 0.4,
                        diagnostic.TARGETS["fuel_saved_l"]: 0.04
                        if circuit != "bahrain"
                        else 0.03,
                        diagnostic.TARGETS["time_lost_s"]: 0.1
                        if circuit != "bahrain"
                        else 0.2,
                    }
                )
    return pl.DataFrame(rows)


def test_test_outcomes_cannot_change_fits_or_predictions():
    frame = fixture_views()
    original, _, fits, cohorts = diagnostic.evaluate(frame)
    changed = frame.with_columns(
        *[
            pl.when(
                (pl.col("run_id") == diagnostic.RUN)
                & pl.col("lap_number").is_in([27, 28])
            )
            .then(pl.col(target) + 10.0)
            .otherwise(pl.col(target))
            .alias(target)
            for target in diagnostic.TARGETS.values()
        ]
    )
    new, _, new_fits, new_cohorts = diagnostic.evaluate(changed)
    assert fits.equals(new_fits)
    assert original["predicted"].equals(new["predicted"])
    assert cohorts == new_cohorts
    assert not original["actual"].equals(new["actual"])


def test_every_budget_scores_same_cohort_and_obeys_chronology():
    predictions, metrics, fits, _ = diagnostic.evaluate(fixture_views())
    for target in diagnostic.TARGETS:
        groups = predictions.filter(pl.col("target") == target).partition_by(
            "budget_laps", "model"
        )
        ids = [group["observation_id"].sort().to_list() for group in groups]
        assert all(value == ids[0] for value in ids)
    assert metrics["test_count"].to_list() == [4] * 10
    assert fits.filter(pl.col("budget_laps") == 0)["calibration_count"].sum() == 0
    one = fits.filter(pl.col("budget_laps") == 1)
    assert all(
        ":24:" in ids and ":25:" not in ids
        for ids in one["calibration_observation_ids"]
    )
    assert all(
        ":27:" not in ids and ":28:" not in ids
        for ids in fits["calibration_observation_ids"]
    )


def test_ridge_uses_fixed_planned_scale_and_training_prior():
    _, _, fits, _ = diagnostic.evaluate(fixture_views())
    row = fits.filter(
        (pl.col("target") == "fuel_saved_l")
        & (pl.col("budget_laps") == 1)
        & (pl.col("model") == "prior_adapted")
    ).row(0, named=True)
    assert row["global_prior_slope"] == pytest.approx(0.08)
    assert row["ridge_penalty"] == pytest.approx(2 * 0.4**2)
    assert row["slope"] == pytest.approx((0.5 * 0.03 + 0.32 * 0.08) / (0.25 + 0.32))


def test_rejects_destination_outcomes_in_global_train():
    frame = fixture_views().with_columns(
        pl.when((pl.col("run_id") == diagnostic.RUN) & (pl.col("lap_number") == 24))
        .then(pl.lit("train"))
        .otherwise(pl.col("split_role"))
        .alias("split_role")
    )
    with pytest.raises(ValueError, match="Spa and Paul"):
        diagnostic.evaluate(frame)


def test_versioned_output_refuses_overwrite(tmp_path):
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        diagnostic.build(tmp_path / "missing.parquet", tmp_path)
