import importlib.util
import json
from pathlib import Path

import polars as pl
import pytest

SPEC = importlib.util.spec_from_file_location(
    "four_circuit_low_data",
    Path(__file__).resolve().parents[1] / "scripts/evaluate_four_circuit_low_data.py",
)
benchmark = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(benchmark)


def fixture_rows():
    rows = []
    for circuit in benchmark.CIRCUITS:
        runs = [(circuit + "_run", (1, 2, 3), "historical_qualified")]
        if circuit == "sebring":
            runs = [
                (benchmark.INITIAL_RUN, (2, 3, 5, 6), "exploratory_only"),
                ("retry", (8, 9, 10), "strict_retry"),
            ]
        for run, laps, tier in runs:
            for lap in laps:
                for zone_index, zone in enumerate(("z1", "z2")):
                    action = 0.2 + 0.1 * (lap % 2) + 0.1 * zone_index
                    acceleration = 0.5 + zone_index
                    rows.append(
                        {
                            "observation_id": f"{run}|{lap}|{zone}",
                            "circuit_id": circuit,
                            "run_id": run,
                            "lap_number": lap,
                            "zone_id": zone,
                            "action": action,
                            "acceleration": acceleration,
                            "fuel_saved_l": 0.07 * action
                            + 0.02 * action * acceleration,
                            "time_lost_s": 0.13 * action + 0.05 * action * acceleration,
                            "planned_action": 0.3,
                            "quality_tier": tier,
                        }
                    )
    return pl.DataFrame(rows)


def test_loco_uses_disjoint_whole_circuits_and_paired_models():
    rows = fixture_rows()
    predictions, metrics, fits, macro = benchmark.evaluate_loco(rows)
    assert macro["circuit_count"].to_list() == [4] * 4
    for row in fits.iter_rows(named=True):
        train_ids = set(json.loads(row["train_observation_ids"]))
        test_ids = set(json.loads(row["test_observation_ids"]))
        assert not train_ids & test_ids
        train = rows.filter(pl.col("observation_id").is_in(train_ids))
        test = rows.filter(pl.col("observation_id").is_in(test_ids))
        assert row["held_out_circuit"] not in set(train["circuit_id"])
        assert set(test["circuit_id"]) == {row["held_out_circuit"]}
        assert row["action_slope"] >= 0 and row["acceleration_slope"] >= 0
    for group in predictions.partition_by("target", "held_out_circuit"):
        left = group.filter(pl.col("model") == "action_only")["observation_id"].sort()
        right = group.filter(pl.col("model") == "action_acceleration")[
            "observation_id"
        ].sort()
        assert left.equals(right)
    expected = (
        metrics.group_by("target", "model")
        .agg(pl.col("mae").mean())
        .sort("target", "model")
    )
    assert macro["macro_four_circuit_mae"].to_list() == pytest.approx(
        expected["mae"].to_list()
    )
    assert predictions.filter(pl.col("circuit_id") == "sebring")[
        "quality_tier"
    ].unique().to_list() == ["strict_retry"]


def test_poisoning_held_out_sebring_targets_cannot_change_its_fits_or_predictions():
    rows = fixture_rows()
    poisoned = rows.with_columns(
        *[
            pl.when(pl.col("circuit_id") == "sebring")
            .then(pl.col(target) + 100)
            .otherwise(pl.col(target))
            .alias(target)
            for target in benchmark.TARGETS
        ]
    )
    before, _, fits, _ = benchmark.evaluate_loco(rows)
    after, _, new_fits, _ = benchmark.evaluate_loco(poisoned)
    selected = pl.col("held_out_circuit") == "sebring"
    assert fits.filter(selected).equals(new_fits.filter(selected))
    assert before.filter(selected)["predicted"].equals(
        after.filter(selected)["predicted"]
    )
    assert not before.filter(selected)["actual"].equals(
        after.filter(selected)["actual"]
    )


def test_few_lap_uses_fixed_original_test_and_never_retry_or_future_targets():
    rows = fixture_rows()
    before, metrics, fits, cohorts = benchmark.evaluate_few_lap(rows)
    assert set(before["run_id"]) == {benchmark.INITIAL_RUN}
    assert set(before["lap_number"]) == {5, 6}
    assert metrics["test_count"].to_list() == [4] * 10
    poisoned = rows.with_columns(
        *[
            pl.when(
                (pl.col("run_id") == benchmark.INITIAL_RUN)
                & pl.col("lap_number").is_in([5, 6])
            )
            .then(pl.col(target) + 10)
            .otherwise(pl.col(target))
            .alias(target)
            for target in benchmark.TARGETS
        ]
    )
    after, _, new_fits, new_cohorts = benchmark.evaluate_few_lap(poisoned)
    assert fits.equals(new_fits) and cohorts == new_cohorts
    assert before["predicted"].equals(after["predicted"])
    for row in fits.iter_rows(named=True):
        local = json.loads(row["calibration_observation_ids"])
        assert len(local) == row["budget_laps"]
        assert all("|5|" not in item and "|6|" not in item for item in local)
        if row["budget_laps"] == 1:
            assert "|2|" in local[0]
        if row["model"] == "prior_adapted":
            assert row["ridge_penalty"] == pytest.approx(2 * 0.3**2)


def test_negative_targets_cannot_produce_negative_slopes():
    rows = fixture_rows().with_columns(
        pl.lit(-1.0).alias("fuel_saved_l"), pl.lit(-2.0).alias("time_lost_s")
    )
    predictions, _, fits, _ = benchmark.evaluate_loco(rows)
    assert fits["action_slope"].min() >= 0
    assert fits["acceleration_slope"].min() >= 0
    assert predictions["predicted"].min() >= 0


def test_rejects_duplicate_rows_and_missing_fourth_cohort():
    rows = fixture_rows()
    with pytest.raises(ValueError, match="duplicate"):
        benchmark.evaluate_loco(pl.concat([rows, rows.head(1)]))
    with pytest.raises(ValueError, match="four non-empty"):
        benchmark.evaluate_loco(rows.filter(pl.col("circuit_id") != "sebring"))


def test_canonical_history_selects_destination_copy_and_checks_hash(tmp_path):
    rows = []
    for circuit, fold in benchmark.DESTINATION_FOLDS.items():
        for role in ("test", "train"):
            rows.append(
                {
                    "observation_id": circuit,
                    "circuit_id": circuit,
                    "run_id": circuit + "_run",
                    "lap_number": 1,
                    "zone_id": "z",
                    "fold_id": fold if role == "test" else "another_fold",
                    "split_role": role,
                    "score_eligible": role == "test",
                    "model_eligible": True,
                    "has_lico": True,
                    "executed_lift_lead_to_push_deceleration_ratio": 0.3,
                    "executed_acceleration_lookup_status": "in_range",
                    "push_acceleration_at_executed_lift_mps2": 1.2,
                    "target_fuel_saved_vs_fold_push_l": 0.04
                    if role == "test"
                    else 999.0,
                    "target_time_lost_vs_fold_push_s": 0.1,
                    "planned_lift_lead_to_push_deceleration_ratio": 0.3,
                }
            )
    path = tmp_path / "fold_feature_views.parquet"
    pl.DataFrame(rows).write_parquet(path)
    manifest = {"artifacts": {path.name: benchmark.record(path)}}
    (tmp_path / "build_manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    result = benchmark.canonical_history(path)
    assert result.height == 3
    assert result["fuel_saved_l"].to_list() == [0.04] * 3
    manifest["artifacts"][path.name]["sha256"] = "wrong"
    (tmp_path / "build_manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="hash mismatch"):
        benchmark.canonical_history(path)


def test_build_refuses_existing_output_before_reading_input(tmp_path):
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        benchmark.build(tmp_path / "missing.csv", tmp_path)


@pytest.mark.parametrize(
    "column", ["circuit_id", "run_id", "lap_number", "quality_tier"]
)
def test_rejects_missing_identity_or_quality(column):
    frame = fixture_rows().with_columns(pl.lit(None).alias(column))
    with pytest.raises(ValueError, match="null or empty|non-negative integers"):
        benchmark.evaluate_loco(frame)


def test_reports_extrapolation_and_zero_prediction_baseline():
    rows = fixture_rows().with_columns(
        pl.when(pl.col("circuit_id") == "sebring")
        .then(10.0)
        .otherwise(pl.col("action"))
        .alias("action")
    )
    predictions, metrics, fits, _ = benchmark.evaluate_loco(rows)
    selected = fits.filter(pl.col("held_out_circuit") == "sebring")
    assert selected["test_outside_train_marginal_ranges"].to_list() == [6] * 4
    assert selected["train_action_max"].max() < 10
    row = metrics.filter(
        (pl.col("held_out_circuit") == "sebring")
        & (pl.col("target") == "fuel_saved_l")
        & (pl.col("model") == "action_only")
    ).row(0, named=True)
    expected = (
        predictions.filter(
            (pl.col("held_out_circuit") == "sebring")
            & (pl.col("target") == "fuel_saved_l")
            & (pl.col("model") == "action_only")
        )["actual"]
        .abs()
        .mean()
    )
    assert row["zero_prediction_mae"] == pytest.approx(expected)


def test_build_rejects_qualification_hash_before_history_read(tmp_path):
    path = tmp_path / "qualified_response_rows.csv"
    fixture_rows().filter(pl.col("circuit_id") == "sebring").write_csv(path)
    (tmp_path / "manifest.json").write_text(
        json.dumps({"artifact_hashes": {path.name: "wrong"}}), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="qualified response hash mismatch"):
        benchmark.build(
            path, tmp_path / "new", history_path=tmp_path / "missing.parquet"
        )


def test_many_historical_null_planned_actions_preserve_later_sebring_values():
    base = fixture_rows().with_columns(
        pl.when(pl.col("circuit_id") != "sebring")
        .then(None)
        .otherwise(pl.col("planned_action"))
        .alias("planned_action")
    )
    rows = pl.concat(
        [
            base.with_columns(
                (pl.col("observation_id") + f"#{index}").alias("observation_id"),
                (pl.col("lap_number") + 100 * index).alias("lap_number"),
            )
            for index in range(10)
        ]
    )
    predictions, _, _, _ = benchmark.evaluate_loco(rows)
    assert (
        predictions.filter(pl.col("circuit_id") == "sebring")[
            "planned_action"
        ].null_count()
        == 0
    )
