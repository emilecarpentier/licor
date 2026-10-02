"""Conditional race scenarios: driver risk choice, never automatic live authority."""

from __future__ import annotations

import math
from dataclasses import asdict
from typing import Literal

from licor.analysis.fuel_budget import calculate_fuel_budget
from licor.analysis.fuel_budget_replay import FuelPlan


def _number(value: float, name: str, *, positive: bool = False) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
        or (positive and value == 0)
    ):
        raise ValueError(
            f"{name} must be finite and {'positive' if positive else 'nonnegative'}"
        )


def _laps(value: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a nonnegative integer")


def leader_lap_switch(
    *,
    remaining_time_s: float,
    seconds_to_next_crossing: float,
    completed_leader_laps: int,
    leader_pace_s: float,
    short_total_leader_laps: int,
    timing_tolerance_s: float,
) -> dict:
    """Sensitivity of the leader's short/short+1 finish, NOT player lap count.

    Hold the predicted next crossing fixed. Vary the mean of the subsequent
    complete laps leading to the short-total crossing. A crossing at or before
    timer expiry requires another lap under this explicit prototype convention.
    No pit/traffic/strategy-intent model; no probability or native HUD formula.
    """
    for name, value in (
        ("remaining time", remaining_time_s),
        ("seconds to next crossing", seconds_to_next_crossing),
        ("timing tolerance", timing_tolerance_s),
    ):
        _number(value, name)
    _number(leader_pace_s, "leader pace", positive=True)
    _laps(completed_leader_laps, "leader completed laps")
    _laps(short_total_leader_laps, "short leader total")
    if short_total_leader_laps <= completed_leader_laps:
        raise ValueError("short total must be a future leader crossing")
    full_laps = short_total_leader_laps - completed_leader_laps - 1
    crossing_s = seconds_to_next_crossing + full_laps * leader_pace_s
    margin = crossing_s - remaining_time_s
    if not math.isfinite(crossing_s):
        raise ValueError("leader forecast overflow")
    quotient = (remaining_time_s - seconds_to_next_crossing) / leader_pace_s
    if not math.isfinite(quotient):
        raise ValueError("leader forecast overflow")
    projected_total = completed_leader_laps + 1 + max(0, math.floor(quotient) + 1)
    threshold = (
        (remaining_time_s - seconds_to_next_crossing) / full_laps
        if full_laps and remaining_time_s > seconds_to_next_crossing
        else None
    )
    return {
        "source": "licor_conditional_constant_pace_not_hud",
        "short_total_leader_laps": short_total_leader_laps,
        "long_total_leader_laps": short_total_leader_laps + 1,
        "projected_total_leader_laps": projected_total,
        "projection_within_pair": projected_total
        in (short_total_leader_laps, short_total_leader_laps + 1),
        "seconds_to_short_crossing": crossing_s,
        "short_crossing_minus_timer_s": margin,
        "near_switch": abs(margin) <= timing_tolerance_s,
        "future_full_laps_adjustable": full_laps,
        "switch_mean_full_lap_s": threshold,
        # Positive: faster full laps needed for the longer branch. Negative:
        # slower full laps needed to return to the shorter branch.
        "pace_minus_switch_s_per_lap": leader_pace_s - threshold
        if threshold is not None
        else None,
        "probability_longer_race": None,
        "assumption": "next_crossing_fixed_then_constant_mean_full_lap_pace",
    }


def compare_fuel_scenarios(
    *,
    remaining_fuel_l: float,
    short_remaining_laps: int,
    long_remaining_laps: int,
    baseline_push_l: float,
    error_allowance_l: float,
    reserve_l: float,
    plans: list[FuelPlan],
    target: Literal["finish", "next_refuel"],
    driver_selected_scenario: Literal["short", "long"] | None = None,
    current_plan_id: str | None = None,
) -> dict:
    """Compare explicit whole-player-lap hypotheses at a lap boundary.

    Both branches use the same explicit reserve and consumption allowance.
    This does NOT assert the longer branch bounds all possible race lengths.
    No late-race reserve change, future fuel credit, or inferred executed action.
    The fixed menu is supplied by the caller with admissibility already reviewed.
    """
    _laps(short_remaining_laps, "short remaining laps")
    _laps(long_remaining_laps, "long remaining laps")
    if short_remaining_laps < 1 or long_remaining_laps != short_remaining_laps + 1:
        raise ValueError("two adjacent positive player-lap hypotheses required")
    _number(baseline_push_l, "push", positive=True)
    _number(error_allowance_l, "error allowance")
    if driver_selected_scenario not in (None, "short", "long"):
        raise ValueError("driver selection must be short, long or None")
    if not plans or len({p.plan_id for p in plans}) != len(plans):
        raise ValueError("unique nonempty plan menu required")
    for plan in plans:
        if (
            not isinstance(plan.plan_id, str)
            or not plan.plan_id.strip()
            or not isinstance(plan.admissible, bool)
        ):
            raise ValueError("valid plan identity and admissibility required")
        _number(plan.saving_l, "plan saving")
        _number(plan.time_cost_s, "plan time cost")
        if plan.saving_l > baseline_push_l:
            raise ValueError("saving exceeds baseline")
    by_id = {p.plan_id: p for p in plans}
    if current_plan_id is not None and current_plan_id not in by_id:
        raise ValueError("unknown current plan; use None when execution is unknown")
    current = by_id.get(current_plan_id)
    eligible = [p for p in plans if p.admissible]
    result = []
    for name, count in (("short", short_remaining_laps), ("long", long_remaining_laps)):
        # Equal nominal/upper counts mean a fixed conditional hypothesis, not
        # silently adopting an uncertainty bound for the other branch.
        budget = calculate_fuel_budget(
            remaining_fuel_l=remaining_fuel_l,
            remaining_laps_nominal=count,
            remaining_laps_upper=count,
            reserve_l=reserve_l,
            conservative_push_fuel_per_lap_l=baseline_push_l + error_allowance_l,
            max_validated_saving_per_lap_l=max(
                (p.saving_l for p in eligible), default=0
            ),
            target=target,
            decision_boundary="lap_boundary",
        )
        feasible = [
            p
            for p in eligible
            if p.saving_l + 1e-12 >= budget.required_saving_per_lap_l
        ]
        recommendation = (
            min(feasible, key=lambda p: (p.time_cost_s, p.saving_l, p.plan_id))
            if feasible and budget.status != "target_unreachable"
            else None
        )
        current_fuel = (
            remaining_fuel_l - count * (baseline_push_l - current.saving_l)
            if current
            else None
        )
        current_guarded = current_fuel - count * error_allowance_l if current else None
        predicted_fuel = (
            remaining_fuel_l - count * (baseline_push_l - recommendation.saving_l)
            if recommendation
            else None
        )
        predicted_cost = count * recommendation.time_cost_s if recommendation else None
        if predicted_cost is not None and not math.isfinite(predicted_cost):
            raise ValueError("predicted time cost overflow")
        result.append(
            {
                "scenario": name,
                "remaining_laps": count,
                "budget": asdict(budget),
                "status": budget.status if eligible else "abstain_no_admissible_plan",
                "recommended_plan_id": recommendation.plan_id
                if recommendation
                else None,
                "predicted_fuel_at_target_l": predicted_fuel,
                "guarded_fuel_at_target_l": predicted_fuel - count * error_allowance_l
                if recommendation
                else None,
                "predicted_time_cost_to_target_s": predicted_cost,
                "current_plan_id": current_plan_id,
                "current_plan_predicted_fuel_at_target_l": current_fuel,
                "current_plan_guarded_fuel_at_target_l": current_guarded,
                "current_plan_reserve_shortfall_l": max(0, reserve_l - current_guarded)
                if current
                else None,
            }
        )
    return {
        "mode": "conditional_comparison_no_live_authority",
        "driver_selected_scenario": driver_selected_scenario,
        "selected_plan_id": next(
            (
                r["recommended_plan_id"]
                for r in result
                if r["scenario"] == driver_selected_scenario
            ),
            None,
        ),
        "reserve_l": reserve_l,
        "error_allowance_l": error_allowance_l,
        "scenarios": result,
    }
