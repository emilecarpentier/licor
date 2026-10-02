import math

import pytest

from licor.analysis.fuel_budget import calculate_fuel_budget


def budget(**updates):
    arguments = {
        "remaining_fuel_l": 31.0,
        "remaining_laps_nominal": 10,
        "remaining_laps_upper": 10,
        "reserve_l": 1.0,
        "conservative_push_fuel_per_lap_l": 3.0,
        "max_validated_saving_per_lap_l": 0.5,
        "target": "finish",
        "decision_boundary": "lap_boundary",
    }
    return calculate_fuel_budget(**(arguments | updates))


def test_push_feasible_with_explicit_reserve():
    result = budget()
    assert result.status == "no_saving_required"
    assert result.available_driving_fuel_l == 30
    assert result.target_fuel_per_lap_l == 3
    assert result.required_saving_per_lap_l == 0


def test_upper_lap_plus_one_increases_constraint_without_changing_nominal():
    result = budget(remaining_laps_upper=11)
    assert result.remaining_laps_nominal == 10
    assert result.status == "saving_required"
    assert result.required_saving_per_lap_l == pytest.approx(3 / 11)
    assert result.target_fuel_per_lap_l == pytest.approx(30 / 11)


def test_fuel_drop_recomputes_constraint_and_signals_unreachable():
    assert budget(remaining_fuel_l=29).required_saving_per_lap_l == pytest.approx(0.2)
    exact = budget(remaining_fuel_l=26)
    assert exact.status == "saving_required"
    assert exact.required_saving_per_lap_l == 0.5
    result = budget(remaining_fuel_l=25)
    assert result.status == "target_unreachable"
    assert result.required_saving_per_lap_l == 0.6
    assert result.push_fuel_deficit_l == 6
    assert result.fuel_deficit_at_max_validated_saving_l == 1


def test_formation_is_only_future_burn_and_not_double_counted():
    before = budget(decision_boundary="before_race", formation_burn_remaining_l=1)
    after = budget(remaining_fuel_l=30, formation_burn_remaining_l=0)
    assert before.available_driving_fuel_l == after.available_driving_fuel_l
    assert before.required_saving_per_lap_l == after.required_saving_per_lap_l == 0.1


def test_next_refuel_does_not_credit_future_fuel():
    result = budget(target="next_refuel", remaining_fuel_l=25)
    assert result.target == "next_refuel"
    assert result.status == "target_unreachable"
    assert result.fuel_deficit_at_max_validated_saving_l == 1


def test_zero_fuel_and_reserve_larger_than_fuel_remain_unreachable():
    for fuel in (0, 0.5):
        result = budget(remaining_fuel_l=fuel)
        assert result.status == "target_unreachable"
        assert result.available_driving_fuel_l < 0
        assert result.required_saving_per_lap_l > 3


def test_no_remaining_laps_still_preserves_reserve_requirement():
    result = budget(remaining_laps_nominal=0, remaining_laps_upper=0)
    assert result.status == "no_saving_required"
    assert result.target_fuel_per_lap_l is None
    assert result.required_saving_per_lap_l == 0
    result = budget(
        remaining_laps_nominal=0, remaining_laps_upper=0, remaining_fuel_l=0
    )
    assert result.status == "target_unreachable"
    assert result.fuel_deficit_at_max_validated_saving_l == 1


@pytest.mark.parametrize("field", ["remaining_laps_nominal", "remaining_laps_upper"])
@pytest.mark.parametrize("invalid", [-1, 1.5, 10.0, True, math.nan, math.inf, "10"])
def test_lap_counts_must_be_actual_nonnegative_integers(field, invalid):
    with pytest.raises(ValueError):
        budget(**{field: invalid})


@pytest.mark.parametrize(
    "field",
    [
        "remaining_fuel_l",
        "reserve_l",
        "conservative_push_fuel_per_lap_l",
        "max_validated_saving_per_lap_l",
        "formation_burn_remaining_l",
    ],
)
@pytest.mark.parametrize("invalid", [-1, math.nan, math.inf, -math.inf, True, "3"])
def test_fuel_values_must_be_finite_nonnegative_numbers(field, invalid):
    with pytest.raises(ValueError):
        budget(**{field: invalid})


@pytest.mark.parametrize(
    "updates",
    [
        {"remaining_laps_upper": 9},
        {"conservative_push_fuel_per_lap_l": 0},
        {"max_validated_saving_per_lap_l": 3.1},
        {"target": "later_refuel"},
        {"decision_boundary": "mid_lap"},
        {"conservative_push_fuel_per_lap_l": 1e308},
    ],
)
def test_inconsistent_or_overflowing_contract_rejected(updates):
    with pytest.raises(ValueError):
        budget(**updates)
