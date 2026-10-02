"""Offline fuel constraints at a lap boundary; no live or HUD authority."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class FuelBudget:
    status: Literal["no_saving_required", "saving_required", "target_unreachable"]
    target: Literal["next_refuel", "finish"]
    decision_boundary: Literal["before_race", "lap_boundary"]
    remaining_laps_nominal: int
    remaining_laps_upper: int
    available_driving_fuel_l: float
    target_fuel_per_lap_l: float | None
    required_saving_per_lap_l: float
    push_fuel_deficit_l: float
    fuel_deficit_at_max_validated_saving_l: float
    reserve_l: float
    formation_burn_remaining_l: float
    max_validated_saving_per_lap_l: float


def calculate_fuel_budget(
    *,
    remaining_fuel_l: float,
    remaining_laps_nominal: int,
    remaining_laps_upper: int,
    reserve_l: float,
    conservative_push_fuel_per_lap_l: float,
    max_validated_saving_per_lap_l: float,
    target: Literal["next_refuel", "finish"],
    decision_boundary: Literal["before_race", "lap_boundary"],
    formation_burn_remaining_l: float = 0.0,
) -> FuelBudget:
    """Compute the saving constraint, before minimizing the plan's time cost.

    Both lap counts are whole, still-unstarted laps to the same target. This
    function is not valid mid-lap: it does not account for a partial lap. The
    upper count and push consumption are caller-supplied conservative bounds,
    not calibrated probability guarantees. No uncertainty margin is invented.

    Only fuel already in the tank is credited, even for a next-refuel target.
    Formation burn is *still-future* burn outside those racing laps; pass zero
    when it has already been reflected in remaining fuel. Reserve is retained
    at the target. A negative available budget is preserved and reported as
    unreachable, not clipped into an apparently feasible zero-lap plan.

    The validated saving ceiling is an external prerequisite, not established
    by this arithmetic. No observations, future laps, or model fitting enter
    this function. Recompute with newly available inputs at each lap boundary.
    """
    for name, value in (
        ("remaining_fuel_l", remaining_fuel_l),
        ("reserve_l", reserve_l),
        ("conservative_push_fuel_per_lap_l", conservative_push_fuel_per_lap_l),
        ("max_validated_saving_per_lap_l", max_validated_saving_per_lap_l),
        ("formation_burn_remaining_l", formation_burn_remaining_l),
    ):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{name} must be a finite nonnegative number")
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"{name} must be a finite nonnegative number")
    for name, value in (
        ("remaining_laps_nominal", remaining_laps_nominal),
        ("remaining_laps_upper", remaining_laps_upper),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{name} must be a nonnegative integer")
    if remaining_laps_upper < remaining_laps_nominal:
        raise ValueError("upper lap count must be at least the nominal count")
    if conservative_push_fuel_per_lap_l <= 0:
        raise ValueError("push consumption must be positive")
    if max_validated_saving_per_lap_l > conservative_push_fuel_per_lap_l:
        raise ValueError("validated saving cannot exceed push consumption")
    if target not in ("next_refuel", "finish"):
        raise ValueError("target must be next_refuel or finish")
    if decision_boundary not in ("before_race", "lap_boundary"):
        raise ValueError("decision must be before_race or at a lap_boundary")

    available = remaining_fuel_l - reserve_l - formation_burn_remaining_l
    push_required = remaining_laps_upper * conservative_push_fuel_per_lap_l
    minimum_required = remaining_laps_upper * (
        conservative_push_fuel_per_lap_l - max_validated_saving_per_lap_l
    )
    if not all(
        math.isfinite(value) for value in (available, push_required, minimum_required)
    ):
        raise ValueError("fuel budget arithmetic overflow")
    push_deficit = max(0.0, push_required - available)
    minimum_deficit = max(0.0, minimum_required - available)
    if not all(math.isfinite(value) for value in (push_deficit, minimum_deficit)):
        raise ValueError("fuel budget arithmetic overflow")
    per_lap_target = available / remaining_laps_upper if remaining_laps_upper else None
    saving = push_deficit / remaining_laps_upper if remaining_laps_upper else 0.0
    status = (
        "target_unreachable"
        if minimum_deficit > 0
        else "saving_required"
        if push_deficit > 0
        else "no_saving_required"
    )
    return FuelBudget(
        status=status,
        target=target,
        decision_boundary=decision_boundary,
        remaining_laps_nominal=remaining_laps_nominal,
        remaining_laps_upper=remaining_laps_upper,
        available_driving_fuel_l=available,
        target_fuel_per_lap_l=per_lap_target,
        required_saving_per_lap_l=saving,
        push_fuel_deficit_l=push_deficit,
        fuel_deficit_at_max_validated_saving_l=minimum_deficit,
        reserve_l=reserve_l,
        formation_burn_remaining_l=formation_burn_remaining_l,
        max_validated_saving_per_lap_l=max_validated_saving_per_lap_l,
    )
