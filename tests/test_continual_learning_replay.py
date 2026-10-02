import importlib.util
import json
from pathlib import Path

import polars as pl
import pytest

SPEC = importlib.util.spec_from_file_location(
    "continual_replay",
    Path(__file__).resolve().parents[1] / "scripts/replay_continual_learning.py",
)
replay = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(replay)


def fixture_rows():
    rows, annotations = [], []
    for circuit in sorted(replay.HISTORY):
        for index, action in enumerate((0.1, 0.8)):
            rows.append(
                dict(
                    observation_id=f"{circuit}-{index}",
                    circuit_id=circuit,
                    run_id=circuit,
                    lap_number=index,
                    zone_id="historical",
                    action=action,
                    acceleration=1.0,
                    planned_action=None,
                    fuel_saved_l=action * 0.1,
                    time_lost_s=action * 0.2,
                    quality_tier="historical_qualified",
                )
            )
    for run, laps in replay.RUN_LAPS.items():
        for lap in laps:
            for zone in replay.ZONES:
                tier = (
                    "strict_retry"
                    if lap >= 8 and zone in {"sbr_t07", "sbr_t10", "sbr_t13", "sbr_t15"}
                    else "exploratory_only"
                )
                identity = dict(run_id=run, lap_number=lap, zone_id=zone)
                rows.append(
                    dict(
                        observation_id=f"{run}-{lap}-{zone}",
                        circuit_id="sebring",
                        **identity,
                        action=0.3,
                        acceleration=1.0,
                        planned_action=0.4,
                        fuel_saved_l=0.036,
                        time_lost_s=0.072,
                        quality_tier=tier,
                    )
                )
                annotations.append(
                    {
                        **identity,
                        "quality_tier": tier,
                        "reasons": ""
                        if tier == "strict_retry"
                        else "driver_or_structure_uncertain",
                    }
                )
    return pl.DataFrame(rows), annotations


def test_chronology_quality_and_disjoint_prior():
    rows, annotations = fixture_rows()
    events, metrics, laps, fits = replay.evaluate(rows.reverse(), annotations[::-1])
    assert events.height == 98
    assert events["lap_number"].to_list()[::14] == [2, 3, 5, 6, 8, 9, 10]
    assert events.head(14)["zone_id"].to_list()[::2] == list(replay.ZONES)
    rejected = events.filter(pl.col("quality_tier") == "exploratory_only")
    assert rejected.height == 74
    assert set(rejected["update_reason"]) == {"quality_rejected"}
    assert rejected["accepted_before"].to_list() == rejected["accepted_after"].to_list()
    assert set(rejected["quality_reasons"]) == {"driver_or_structure_uncertain"}
    assert metrics["score_count"].to_list() == [12] * 4
    assert metrics["later_pass_count"].to_list() == [8] * 4
    assert set(laps["zone_count"]) == {4}
    for fit in fits:
        assert set(fit["train_circuits"]) == replay.HISTORY
        assert not set(fit["train_run_ids"]) & set(replay.RUN_LAPS)
        assert fit["train_count"] == 6


def test_current_and_future_outcomes_cannot_change_earlier_predictions():
    rows, annotations = fixture_rows()
    original = replay.evaluate(rows, annotations)[0]
    poisoned = rows.with_columns(
        pl.when((pl.col("circuit_id") == "sebring") & (pl.col("lap_number") >= 9))
        .then(pl.lit(500.0))
        .otherwise(pl.col("fuel_saved_l"))
        .alias("fuel_saved_l")
    )
    changed = replay.evaluate(poisoned, annotations)[0]
    columns = [
        "sequence",
        "target",
        "fixed_prediction",
        "local_prediction",
        "accepted_before",
    ]
    assert (
        original.filter(pl.col("lap_number") <= 9)
        .select(columns)
        .equals(changed.filter(pl.col("lap_number") <= 9).select(columns))
    )
    assert original.filter(pl.col("target") == "time_lost_s").equals(
        changed.filter(pl.col("target") == "time_lost_s")
    )
    assert original["fixed_prediction"].equals(changed["fixed_prediction"])
    assert not original.filter(
        (pl.col("target") == "fuel_saved_l") & (pl.col("lap_number") == 10)
    )["local_prediction"].equals(
        changed.filter(
            (pl.col("target") == "fuel_saved_l") & (pl.col("lap_number") == 10)
        )["local_prediction"]
    )


def test_excluded_outcomes_never_update_any_prediction():
    rows, annotations = fixture_rows()
    changed = rows.with_columns(
        *[
            pl.when(pl.col("quality_tier") == "exploratory_only")
            .then(pl.lit(1000.0))
            .otherwise(pl.col(target))
            .alias(target)
            for target in replay.TARGETS
        ]
    )
    columns = ["fixed_prediction", "local_prediction", "scale_after", "accepted_after"]
    assert (
        replay.evaluate(rows, annotations)[0]
        .select(columns)
        .equals(replay.evaluate(changed, annotations)[0].select(columns))
    )


def test_zero_prior_not_scored_as_valid_ineffectiveness():
    rows, annotations = fixture_rows()
    rows = rows.with_columns(
        pl.when(pl.col("circuit_id") != "sebring")
        .then(pl.lit(0.0))
        .otherwise(pl.col("fuel_saved_l"))
        .alias("fuel_saved_l")
    )
    events, metrics, _, _ = replay.evaluate(rows, annotations)
    assert set(events.filter(pl.col("target") == "fuel_saved_l")["update_reason"]) == {
        "zero_prior"
    }
    assert metrics.filter(pl.col("target") == "fuel_saved_l")[
        "score_count"
    ].to_list() == [0, 0]


def test_missing_target_remains_independent_and_is_not_imputed():
    rows, annotations = fixture_rows()
    rows = rows.with_columns(
        pl.when((pl.col("lap_number") == 8) & (pl.col("zone_id") == "sbr_t07"))
        .then(None)
        .otherwise(pl.col("fuel_saved_l"))
        .alias("fuel_saved_l")
    )
    events, metrics, _, _ = replay.evaluate(rows, annotations)
    missing = events.filter(
        (pl.col("lap_number") == 8) & (pl.col("zone_id") == "sbr_t07")
    )
    assert missing["update_reason"].to_list() == ["missing_outcome", "updated"]
    assert metrics["score_count"].to_list() == [11, 11, 12, 12]


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "mismatch"])
def test_annotation_join_rejects_invalid_quality(mutation):
    rows, annotations = fixture_rows()
    if mutation == "missing":
        annotations.pop()
    elif mutation == "duplicate":
        annotations[-1] = annotations[0]
    else:
        annotations[0]["quality_tier"] = "strict_retry"
    with pytest.raises(ValueError, match="coverage|mismatch"):
        replay.evaluate(rows, annotations)


def write_fixture(tmp_path):
    rows, annotations = fixture_rows()
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    path = input_dir / "canonical_response_rows.csv"
    rows.write_csv(path)
    (input_dir / "manifest.json").write_text(
        json.dumps({"artifacts": [replay.record(path)]}), encoding="utf-8"
    )
    review = tmp_path / "review.json"
    review.write_text(json.dumps({"annotations": annotations}), encoding="utf-8")
    return input_dir, review


def test_build_hashes_and_refuses_overwrite(tmp_path):
    input_dir, review = write_fixture(tmp_path)
    output = tmp_path / "output"
    manifest = replay.build(input_dir, output, review)
    assert manifest["event_count"] == 98
    assert {Path(item["path"]).name for item in manifest["artifacts"]} == {
        "events.csv",
        "metrics.csv",
        "per_lap.csv",
        "fits.json",
    }
    with pytest.raises(FileExistsError, match="overwrite"):
        replay.build(input_dir, output, review)


def test_build_rejects_source_tampering(tmp_path):
    input_dir, review = write_fixture(tmp_path)
    source = input_dir / "canonical_response_rows.csv"
    source.write_text(source.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="hash mismatch"):
        replay.build(input_dir, tmp_path / "output", review)
    assert not (tmp_path / "output").exists()
