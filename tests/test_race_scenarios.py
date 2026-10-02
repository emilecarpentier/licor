from dataclasses import replace

import pytest

from licor.analysis.fuel_budget_replay import FuelPlan
from licor.analysis.race_scenarios import compare_fuel_scenarios, leader_lap_switch


def switch(**updates):
    return leader_lap_switch(
        **(
            dict(
                remaining_time_s=975,
                seconds_to_next_crossing=80,
                completed_leader_laps=45,
                leader_pace_s=100,
                short_total_leader_laps=55,
                timing_tolerance_s=1,
            )
            | updates
        )
    )


def compare(**updates):
    return compare_fuel_scenarios(
        **(
            dict(
                remaining_fuel_l=30.5,
                short_remaining_laps=10,
                long_remaining_laps=11,
                baseline_push_l=3,
                error_allowance_l=0,
                reserve_l=0.5,
                plans=[
                    FuelPlan("push", 0, 0, True),
                    FuelPlan("low", 0.15, 0.2, True),
                    FuelPlan("high", 0.3, 0.6, True),
                ],
                target="finish",
                current_plan_id="push",
            )
            | updates
        )
    )


def test_pace_threshold_and_two_sides_do_not_claim_probability():
    row = switch()
    assert row["projected_total_leader_laps"] == 55
    assert row["short_crossing_minus_timer_s"] == 5
    assert row["future_full_laps_adjustable"] == 9
    assert row["switch_mean_full_lap_s"] == pytest.approx(895 / 9)
    assert row["pace_minus_switch_s_per_lap"] == pytest.approx(5 / 9)
    assert switch(leader_pace_s=99.4)["projected_total_leader_laps"] == 56
    assert switch(leader_pace_s=99.5)["projected_total_leader_laps"] == 55
    assert row["probability_longer_race"] is None


def test_exact_timer_tie_is_explicit_and_near_switch_not_certainty():
    row = switch(remaining_time_s=980)
    assert row["near_switch"]
    assert row["projected_total_leader_laps"] == 56
    assert row["pace_minus_switch_s_per_lap"] == 0


def test_no_full_lap_left_cannot_offer_per_lap_pace_adjustment():
    row = switch(completed_leader_laps=54, remaining_time_s=79)
    assert row["future_full_laps_adjustable"] == 0
    assert row["switch_mean_full_lap_s"] is None
    assert row["short_crossing_minus_timer_s"] == 1


def test_outside_pair_not_silently_clamped():
    row = switch(remaining_time_s=2000)
    assert row["projected_total_leader_laps"] > 56
    assert not row["projection_within_pair"]


def test_zero_timer_needs_next_crossing_not_zero_remaining():
    row = switch(remaining_time_s=0)
    assert row["projected_total_leader_laps"] == 46
    assert row["switch_mean_full_lap_s"] is None


def test_parallel_budgets_do_not_choose_longer_scenario_by_default():
    row = compare()
    short, long = row["scenarios"]
    assert short["recommended_plan_id"] == "push"
    assert long["recommended_plan_id"] == "high"
    assert short["current_plan_predicted_fuel_at_target_l"] == 0.5
    assert long["current_plan_predicted_fuel_at_target_l"] == -2.5
    assert long["current_plan_reserve_shortfall_l"] == 3
    assert long["predicted_time_cost_to_target_s"] == pytest.approx(6.6)
    assert row["driver_selected_scenario"] is None
    assert row["selected_plan_id"] is None


@pytest.mark.parametrize("choice,plan", [("short", "push"), ("long", "high")])
def test_driver_choice_is_explicit(choice, plan):
    assert compare(driver_selected_scenario=choice)["selected_plan_id"] == plan


def test_longer_unreachable_does_not_override_feasible_short_choice():
    row = compare(remaining_fuel_l=29, driver_selected_scenario="short")
    assert row["selected_plan_id"] == "low"
    assert row["scenarios"][1]["status"] == "target_unreachable"
    assert row["scenarios"][1]["recommended_plan_id"] is None
    assert row["scenarios"][1]["budget"]["fuel_deficit_at_max_validated_saving_l"] > 0


def test_driver_deviation_uses_measured_tank_without_assuming_recommendation_executed():
    before = compare(remaining_fuel_l=29)
    assert before["scenarios"][0]["recommended_plan_id"] == "low"
    # Driver actually burns 3 L (push), not the low plan's 2.85 L prediction.
    after = compare(
        remaining_fuel_l=26,
        short_remaining_laps=9,
        long_remaining_laps=10,
        current_plan_id=None,
    )
    assert after["reserve_l"] == 0.5
    assert after["scenarios"][0]["budget"][
        "required_saving_per_lap_l"
    ] == pytest.approx(1.5 / 9)
    assert after["scenarios"][0]["recommended_plan_id"] == "high"
    assert after["scenarios"][0]["current_plan_predicted_fuel_at_target_l"] is None


@pytest.mark.parametrize("remaining", [120, 15, 10, 1])
def test_no_automatic_last_15_lap_or_point_one_reserve(remaining):
    row = compare(short_remaining_laps=remaining, long_remaining_laps=remaining + 1)
    assert row["reserve_l"] == 0.5
    assert all(s["budget"]["reserve_l"] == 0.5 for s in row["scenarios"])


def test_next_refuel_credits_only_current_tank_and_consumption_margin_stays_separate():
    row = compare(target="next_refuel", error_allowance_l=0.05)
    assert row["scenarios"][0]["budget"]["target"] == "next_refuel"
    assert row["scenarios"][0]["current_plan_guarded_fuel_at_target_l"] == 0
    assert row["scenarios"][0]["budget"]["available_driving_fuel_l"] == 30
    assert row["reserve_l"] == 0.5


def test_inadmissible_plans_not_recommended():
    plans = [replace(p, admissible=False) for p in [FuelPlan("push", 0, 0, True)]]
    row = compare(plans=plans)
    assert all(s["status"] == "abstain_no_admissible_plan" for s in row["scenarios"])


def test_predicted_time_cost_overflow_rejected():
    with pytest.raises(ValueError, match="time cost overflow"):
        compare(plans=[FuelPlan("push", 0, 1e308, True)])


@pytest.mark.parametrize(
    "updates",
    [
        {"reserve_l": -1},
        {"reserve_l": float("nan")},
        {"error_allowance_l": float("inf")},
        {"baseline_push_l": 0},
        {"short_remaining_laps": True},
        {"short_remaining_laps": 0},
        {"long_remaining_laps": 12},
        {"driver_selected_scenario": "auto"},
        {"current_plan_id": "unknown"},
        {"plans": []},
        {"target": "whole_race_with_future_refills"},
    ],
)
def test_invalid_budget_inputs(updates):
    with pytest.raises(ValueError):
        compare(**updates)


@pytest.mark.parametrize(
    "updates",
    [
        {"remaining_time_s": -1},
        {"leader_pace_s": 0},
        {"seconds_to_next_crossing": float("nan")},
        {"timing_tolerance_s": -1},
        {"short_total_leader_laps": 45},
        {"completed_leader_laps": True},
    ],
)
def test_invalid_switch_inputs(updates):
    with pytest.raises(ValueError):
        switch(**updates)
