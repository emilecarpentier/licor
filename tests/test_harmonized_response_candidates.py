import importlib.util
import json
import sys
from pathlib import Path

import polars as pl
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
try:
    SPEC = importlib.util.spec_from_file_location(
        "response_candidates",
        ROOT / "scripts/evaluate_harmonized_response_candidates.py",
    )
    module = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(module)
finally:
    sys.path.pop(0)


def rows_fixture():
    return pl.DataFrame(
        [
            dict(
                observation_id=f"{circuit}:{lap}",
                circuit_id=circuit,
                run_id=circuit,
                lap_number=lap,
                zone_id="z",
                quality_tier="strict_retry"
                if circuit == "sebring"
                else "historical_qualified",
                action=0.1 * lap,
                planned_action=0.1 * lap,
                acceleration=float(lap),
                fuel_saved_l=0.05 * lap,
                time_lost_s=0.04 * lap**2,
            )
            for circuit in module.CIRCUITS
            for lap in (1, 2, 3)
        ]
    )


def test_candidate_fits_never_use_held_out_targets_and_models_are_paired():
    rows = rows_fixture()
    predictions, _, fits = module.evaluate(rows, cohort="strict")
    poisoned = rows.with_columns(
        [
            pl.when(pl.col("circuit_id") == "sebring")
            .then(9999)
            .otherwise(pl.col(target))
            .alias(target)
            for target in module.TARGETS
        ]
    )
    _, _, changed = module.evaluate(poisoned, cohort="strict")
    assert fits.filter(pl.col("held_out_circuit") == "sebring").equals(
        changed.filter(pl.col("held_out_circuit") == "sebring")
    )
    for row in fits.iter_rows(named=True):
        assert not set(json.loads(row["train_ids"])) & set(json.loads(row["test_ids"]))
    for group in predictions.partition_by("held_out_circuit", "target"):
        assert (
            group.group_by("model")
            .agg(pl.col("observation_id").sort())["observation_id"]
            .to_list()
            == [sorted(group["observation_id"].unique())] * 4
        )


def test_refuses_overwrite_before_reading_sources(tmp_path):
    with pytest.raises(FileExistsError):
        module.build(tmp_path / "missing.csv", tmp_path)
