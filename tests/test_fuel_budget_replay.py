from dataclasses import replace
import math

import pytest

from licor.analysis.fuel_budget_replay import FuelBoundary, FuelPlan, replay_fuel_budget

PLANS = [
    FuelPlan("push", 0, 0, True),
    FuelPlan("low", 0.2, 0.1, True),
    FuelPlan("high", 0.4, 0.3, True),
]
CONFIG = dict(
    baseline_push_l=3.0,
    reserve_l=0.2,
    initial_error_allowance_l=0.05,
    error_window_laps=3,
    horizon_release_confirmations=3,
)


def event(lap=0, fuel=27.5, nominal=10, upper=10, **kwargs):
    return FuelBoundary(
        timestamp_s=lap * 100.0,
        context_id="race",
        completed_laps=lap,
        fuel_l=fuel,
        nominal_remaining_laps=nominal,
        upper_remaining_laps=upper,
        **kwargs,
    )


def run(events, **kwargs):
    return replay_fuel_budget(events, PLANS, **(CONFIG | kwargs))


def test_hud_is_diagnostic_and_does_not_override_litres_or_explicit_horizon():
    a = run([event(hud_total_laps=57.8, hud_fuel_laps=10.1)])[0]
    b = run([event(hud_total_laps=58.1, hud_fuel_laps=4.0)])[0]
    assert a["selected_plan_id"] == b["selected_plan_id"] == "high"
    assert a["required_saving_l"] == b["required_saving_l"]


def test_extra_lap_immediately_increases_target_and_can_be_unreachable():
    rows = run([event(), event(1, 24.85, 10, 11)])
    assert rows[1]["retained_upper_remaining_laps"] == 11
    assert rows[1]["status"] == "target_unreachable"
    assert rows[1]["reserve_shortfall_l"] > 0


def test_lower_total_horizon_needs_confirmations_not_fixed_remaining_count():
    rows = run(
        [
            event(0, 40, 10, 10),
            event(1, 37, 8, 8),
            event(2, 34, 7, 7),
            event(3, 31, 6, 6),
        ]
    )
    assert [r["retained_upper_remaining_laps"] for r in rows] == [10, 9, 8, 6]


def test_residual_uses_executed_not_shadow_plan_and_future_does_not_rewrite_past():
    first = event()
    second = event(1, 24.5, 9, 9, previous_lap_usable=True, executed_plan_id="push")
    prefix = run([first])
    rows = run(
        [
            first,
            second,
            event(2, 20, 8, 8, previous_lap_usable=True, executed_plan_id="high"),
        ]
    )
    assert rows[:1] == prefix
    assert rows[1]["consumption_residual_l"] == 0
    assert rows[1]["error_allowance_l"] == 0.05
    assert rows[2]["error_allowance_l"] == pytest.approx(1.9)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"previous_lap_usable": False, "executed_plan_id": "high"},
        {"previous_lap_usable": True, "executed_plan_id": "unknown"},
    ],
)
def test_bad_or_unidentified_execution_is_not_learned(kwargs):
    rows = run([event(), event(1, 20, 9, 9, **kwargs)])
    assert rows[1]["consumption_residual_l"] is None
    assert rows[1]["error_allowance_l"] == 0.05
    assert rows[1]["status"] == "target_unreachable"


def test_missing_data_abstains_and_does_not_divide_a_multilap_gap():
    rows = run(
        [
            event(),
            event(1, None, 9, 9),
            event(3, 19, 7, 7, previous_lap_usable=True, executed_plan_id="high"),
        ]
    )
    assert rows[1]["selected_plan_id"] is None
    assert rows[1]["status"] == "abstain_missing_boundary_inputs"
    assert rows[2]["consumption_residual_l"] is None


def test_adverse_margin_cannot_be_released_by_invalid_intervals():
    rows = run(
        [
            event(),
            event(1, 24.4, 9, 9, previous_lap_usable=True, executed_plan_id="high"),
            event(2, 22, 8, 8),
        ]
    )
    assert rows[1]["error_allowance_l"] == pytest.approx(0.5)
    assert rows[2]["error_allowance_l"] == pytest.approx(0.5)


def test_refuel_requires_context_reset_and_reset_discards_old_interval():
    with pytest.raises(ValueError, match="fuel increase"):
        run([event(), event(1, 40, 9, 9)])
    rows = run([event(), replace(event(1, 40, 9, 9), context_id="after_refuel")])
    assert rows[1]["consumption_residual_l"] is None
    assert "context_prior_reset" in rows[1]["notes"]


def test_confirmed_finish_overrides_horizon_hysteresis_and_preserves_reserve_check():
    rows = run([event(0, 6, 2, 2), event(1, 0.1, 0, 0, race_finished=True)])
    assert rows[1]["retained_upper_remaining_laps"] == 0
    assert rows[1]["status"] == "target_unreachable"
    assert rows[1]["reserve_shortfall_l"] == pytest.approx(0.1)
    assert rows[1]["selected_plan_id"] is None


def test_margin_releases_only_after_window_of_usable_prior_laps():
    rows = run(
        [
            event(),
            event(1, 24.4, 9, 9, previous_lap_usable=True, executed_plan_id="high"),
            event(2, 21.8, 8, 8, previous_lap_usable=True, executed_plan_id="high"),
            event(3, 19.2, 7, 7, previous_lap_usable=True, executed_plan_id="high"),
            event(4, 16.6, 6, 6, previous_lap_usable=True, executed_plan_id="high"),
        ]
    )
    assert rows[3]["error_allowance_l"] == pytest.approx(0.5)
    assert rows[4]["error_allowance_l"] == 0.05


def test_unknown_horizon_breaks_release_confirmations():
    rows = run(
        [
            event(0, 40, 10, 10),
            event(1, 37, 8, 8),
            event(2, 34, None, None),
            event(3, 31, 6, 6),
            event(4, 28, 5, 5),
        ]
    )
    assert rows[-1]["retained_upper_remaining_laps"] == 6


def test_confirmed_finish_with_reserve_has_no_further_plan():
    row = run([event(1, 0.3, 0, 0, race_finished=True)])[0]
    assert row["selected_plan_id"] is None
    assert row["status"] == "no_saving_required"


@pytest.mark.parametrize(
    "bad",
    [
        event(fuel=math.nan),
        event(nominal=10, upper=9),
        event(nominal=1.5),
        event(race_finished=True),
    ],
)
def test_invalid_boundaries_rejected(bad):
    with pytest.raises(ValueError):
        run([bad])


def test_unusable_plan_never_selected_and_time_breaks_feasible_ties():
    plans = [FuelPlan("weak", 0.6, 0.01, False), *PLANS]
    rows = replay_fuel_budget([event(fuel=30)], plans, **CONFIG)
    assert rows[0]["selected_plan_id"] == "low"


def test_duplicate_boundary_rejected():
    with pytest.raises(ValueError):
        run([event(), event()])
