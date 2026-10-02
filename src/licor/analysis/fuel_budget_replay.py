"""Causal lap-boundary shadow decisions. No HUD conversion or live authority."""

from __future__ import annotations

import math
from dataclasses import dataclass

from licor.analysis.fuel_budget import calculate_fuel_budget


@dataclass(frozen=True)
class FuelPlan:
    plan_id: str
    saving_l: float
    time_cost_s: float
    admissible: bool


@dataclass(frozen=True)
class FuelBoundary:
    timestamp_s: float
    context_id: str
    completed_laps: int
    fuel_l: float | None
    nominal_remaining_laps: int | None
    upper_remaining_laps: int | None
    previous_lap_usable: bool = False
    executed_plan_id: str | None = None
    hud_total_laps: float | None = None
    hud_fuel_laps: float | None = None
    race_finished: bool = False


def _finite_nonnegative(value: float, name: str) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
    ):
        raise ValueError(f"{name} must be finite and nonnegative")


def _integer(value: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a nonnegative integer")


def replay_fuel_budget(
    events: list[FuelBoundary],
    plans: list[FuelPlan],
    *,
    baseline_push_l: float,
    reserve_l: float,
    initial_error_allowance_l: float,
    error_window_laps: int,
    horizon_release_confirmations: int,
) -> list[dict]:
    """Replay *whole remaining laps to finish* from explicit boundary observations.

    The allowance is max(initial allowance, positive consumption residuals from
    the last N usable laps). It is a diagnostic envelope, NOT a calibrated bound.
    Residuals require the actually executed plan, never the shadow suggestion.
    No negative residual reduces the initial allowance. Unusable intervals do
    not age the residual history. Context changes reset it to the explicit prior.

    Lower horizon estimates need K identical absolute finish-lap confirmations;
    increases apply immediately. Unknown inputs abstain, not silently freeze a
    fuel-feasible claim. HUD decimals are retained only as observations.
    Formation laps, refueling and partial laps require an external context reset;
    this first replay does not implement a race/stint estimator or zone learning.
    """
    for name, value in (
        ("baseline", baseline_push_l),
        ("reserve", reserve_l),
        ("allowance", initial_error_allowance_l),
    ):
        _finite_nonnegative(value, name)
    if baseline_push_l == 0:
        raise ValueError("positive baseline required")
    for value in (error_window_laps, horizon_release_confirmations):
        _integer(value, "window")
        if value == 0:
            raise ValueError("positive window required")
    if not plans or len({p.plan_id for p in plans}) != len(plans):
        raise ValueError("unique nonempty plan menu required")
    for plan in plans:
        if (
            not isinstance(plan.plan_id, str)
            or not plan.plan_id.strip()
            or not isinstance(plan.admissible, bool)
        ):
            raise ValueError("valid plan identity and admissibility required")
        _finite_nonnegative(plan.saving_l, "saving")
        _finite_nonnegative(plan.time_cost_s, "time cost")
        if plan.saving_l > baseline_push_l:
            raise ValueError("saving exceeds baseline consumption")
    eligible = [p for p in plans if p.admissible]
    by_id = {p.plan_id: p for p in plans}
    previous = None
    retained_end = pending_end = None
    pending_count = 0
    residuals: list[float] = []
    result = []
    for event in events:
        _finite_nonnegative(event.timestamp_s, "timestamp")
        _integer(event.completed_laps, "completed laps")
        if not isinstance(event.context_id, str) or not event.context_id.strip():
            raise ValueError("context identity required")
        if not isinstance(event.previous_lap_usable, bool) or not isinstance(
            event.race_finished, bool
        ):
            raise ValueError("interval usability must be explicit boolean")
        for name in ("fuel_l", "hud_total_laps", "hud_fuel_laps"):
            value = getattr(event, name)
            if value is not None:
                _finite_nonnegative(value, name)
        for value in (event.nominal_remaining_laps, event.upper_remaining_laps):
            if value is not None:
                _integer(value, "remaining laps")
        if previous is not None and event.timestamp_s <= previous.timestamp_s:
            raise ValueError("events must be strictly chronological")
        same_context = previous is not None and event.context_id == previous.context_id
        if same_context and event.completed_laps <= previous.completed_laps:
            raise ValueError(
                "one boundary per completed lap, increasing within context"
            )
        notes = []
        if not same_context:
            residuals, retained_end, pending_end, pending_count = [], None, None, 0
            notes.append("context_prior_reset")
        residual = None
        refuel = (
            same_context
            and previous.fuel_l is not None
            and event.fuel_l is not None
            and event.fuel_l > previous.fuel_l
        )
        if refuel:
            raise ValueError("fuel increase requires explicit new context after refuel")
        if (
            same_context
            and event.completed_laps == previous.completed_laps + 1
            and event.previous_lap_usable
            and previous.fuel_l is not None
            and event.fuel_l is not None
            and event.executed_plan_id in by_id
        ):
            consumed = previous.fuel_l - event.fuel_l
            expected = baseline_push_l - by_id[event.executed_plan_id].saving_l
            residual = consumed - expected
            residuals = (residuals + [residual])[-error_window_laps:]
            notes.append("past_executed_plan_residual")
        else:
            notes.append("interval_not_learned")
        allowance = max([initial_error_allowance_l, *residuals])
        row = {
            "timestamp_s": event.timestamp_s,
            "context_id": event.context_id,
            "completed_laps": event.completed_laps,
            "fuel_l": event.fuel_l,
            "hud_total_laps": event.hud_total_laps,
            "hud_fuel_laps": event.hud_fuel_laps,
            "consumption_residual_l": residual,
            "error_allowance_l": allowance,
            "selected_plan_id": None,
            "retained_upper_remaining_laps": None,
            "required_saving_l": None,
            "predicted_finish_fuel_l": None,
            "conservative_finish_fuel_l": None,
            "reserve_shortfall_l": None,
        }
        nominal, upper = event.nominal_remaining_laps, event.upper_remaining_laps
        if event.race_finished and (nominal != 0 or upper != 0):
            raise ValueError("confirmed finish requires zero remaining laps")
        if nominal is not None and upper is not None and upper < nominal:
            raise ValueError("upper remaining laps below nominal")
        if event.fuel_l is None or nominal is None or upper is None:
            row["status"] = "abstain_missing_boundary_inputs"
            pending_end, pending_count = None, 0
        elif not eligible:
            row["status"] = "abstain_no_admissible_plan"
        else:
            proposed_end = event.completed_laps + upper
            if (
                event.race_finished
                or retained_end is None
                or proposed_end >= retained_end
            ):
                retained_end = proposed_end
                pending_end, pending_count = None, 0
            else:
                pending_count = pending_count + 1 if proposed_end == pending_end else 1
                pending_end = proposed_end
                if pending_count >= horizon_release_confirmations:
                    retained_end, pending_end, pending_count = proposed_end, None, 0
                    notes.append("lower_horizon_confirmed")
                else:
                    notes.append("lower_horizon_held")
            retained_laps = max(0, retained_end - event.completed_laps)
            budget = calculate_fuel_budget(
                remaining_fuel_l=event.fuel_l,
                remaining_laps_nominal=nominal,
                remaining_laps_upper=retained_laps,
                reserve_l=reserve_l,
                conservative_push_fuel_per_lap_l=baseline_push_l + allowance,
                max_validated_saving_per_lap_l=max(p.saving_l for p in eligible),
                target="finish",
                decision_boundary="lap_boundary",
            )
            feasible = [
                p
                for p in eligible
                if p.saving_l + 1e-12 >= budget.required_saving_per_lap_l
            ]
            choice = (
                min(feasible, key=lambda p: (p.time_cost_s, p.saving_l, p.plan_id))
                if feasible
                else min(
                    eligible, key=lambda p: (-p.saving_l, p.time_cost_s, p.plan_id)
                )
            )
            finish = event.fuel_l - retained_laps * (baseline_push_l - choice.saving_l)
            guarded_finish = finish - retained_laps * allowance
            row.update(
                status=budget.status,
                selected_plan_id=choice.plan_id if retained_laps else None,
                retained_upper_remaining_laps=retained_laps,
                required_saving_l=budget.required_saving_per_lap_l,
                predicted_finish_fuel_l=finish,
                conservative_finish_fuel_l=guarded_finish,
                reserve_shortfall_l=max(0.0, reserve_l - guarded_finish),
            )
        row["notes"] = ";".join(notes)
        result.append(row)
        previous = event
    return result
