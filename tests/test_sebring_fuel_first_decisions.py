from __future__ import annotations

import importlib.util
from pathlib import Path

import polars as pl
import pytest

SPEC = importlib.util.spec_from_file_location(
    "decision_audit",
    Path(__file__).resolve().parents[1]
    / "scripts/evaluate_sebring_fuel_first_decisions.py",
)
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


def rows():
    values = []
    for circuit in sorted(audit.HISTORY):
        for i, action in enumerate((0.1, 0.8)):
            values.append(
                dict(
                    observation_id=f"{circuit}{i}",
                    circuit_id=circuit,
                    run_id=circuit,
                    lap_number=i,
                    zone_id="z",
                    action=action,
                    acceleration=1.0,
                    fuel_saved_l=action * 0.1,
                    time_lost_s=action * 0.2,
                    planned_action=action,
                    acceleration_planned_harmonized=1.0,
                    quality_tier="historical_qualified",
                )
            )
    for lap in (2, 3, 5, 6):
        for zone in range(7):
            action = 0.2 if lap in (2, 6) else 0.4
            values.append(
                dict(
                    observation_id=f"s{lap}-{zone}",
                    circuit_id="sebring",
                    run_id=audit.RUN,
                    lap_number=lap,
                    zone_id=f"z{zone}",
                    action=action,
                    acceleration=1.0,
                    fuel_saved_l=action * 0.1,
                    time_lost_s=action * 0.2,
                    planned_action=action,
                    acceleration_planned_harmonized=1.0,
                    quality_tier="exploratory_only",
                )
            )
    return pl.DataFrame(values)


def choice_view(frame):
    return frame.select(
        "model",
        "menu",
        "target_fuel_l",
        "status",
        "selected_candidate_id",
        "predicted_fuel_l",
        "predicted_time_s",
    )


def test_fuel_priority_and_unreachable():
    menu = [
        dict(candidate_id="cheap", predicted_fuel_l=0.1, predicted_time_s=0.01),
        dict(candidate_id="fuel", predicted_fuel_l=0.3, predicted_time_s=2.0),
    ]
    chosen, status = audit.select_candidate(menu, 0.2)
    assert chosen["candidate_id"] == "fuel" and status == "target_met"
    chosen, status = audit.select_candidate(menu, 0.4)
    assert chosen["candidate_id"] == "fuel" and status == "target_unreachable"


def test_poison_test_outcomes_never_changes_choices_or_fits():
    source = rows()
    first, _, fits = audit.evaluate(source)
    poisoned = source.with_columns(
        [
            pl.when(pl.col("lap_number").is_in([5, 6]))
            .then(pl.col(c) + 100)
            .otherwise(pl.col(c))
            .alias(c)
            for c in ("fuel_saved_l", "time_lost_s")
        ]
    )
    second, _, second_fits = audit.evaluate(poisoned)
    assert choice_view(first).equals(choice_view(second))
    assert fits.equals(second_fits)


def test_test_execution_and_planned_features_unused():
    source = rows()
    first, _, _ = audit.evaluate(source)
    poisoned = source.with_columns(
        [
            pl.when(pl.col("lap_number").is_in([5, 6]))
            .then(pl.lit(999.0))
            .otherwise(pl.col(c))
            .alias(c)
            for c in (
                "action",
                "acceleration",
                "planned_action",
                "acceleration_planned_harmonized",
            )
        ]
    )
    second, _, _ = audit.evaluate(poisoned)
    assert first.equals(second)


def test_missing_fixed_test_does_not_use_retry():
    source = rows().filter(
        ~((pl.col("run_id") == audit.RUN) & (pl.col("lap_number") == 6))
    )
    with pytest.raises(ValueError, match="fixed"):
        audit.evaluate(source)


def test_null_test_outcome_is_rejected():
    source = rows().with_columns(
        pl.when(pl.col("lap_number") == 6)
        .then(None)
        .otherwise(pl.col("fuel_saved_l"))
        .alias("fuel_saved_l")
    )
    with pytest.raises(ValueError, match="finite held-out"):
        audit.evaluate(source)


def test_range_abstention_and_pseudo_regret_not_claimed():
    source = rows()
    decisions, _, _ = audit.evaluate(source)
    assert (
        decisions.filter(pl.col("menu") == "hypothetical_mixed_zone_replay")[
            "time_regret_s"
        ].null_count()
        == 10
    )
    outside = source.with_columns(
        pl.when(pl.col("circuit_id") == "sebring")
        .then(pl.lit(2.0))
        .otherwise(pl.col("planned_action"))
        .alias("planned_action")
    )
    decisions, _, _ = audit.evaluate(outside)
    assert set(decisions["status"]) == {"abstain_action_outside_train_range"}
    assert decisions["selected_candidate_id"].null_count() == decisions.height
