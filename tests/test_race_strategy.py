import polars as pl
import pytest

from licor.analysis import (
    RaceStrategyConfig,
    build_fuel_saving_targets,
    compare_push_and_lico_strategy,
    estimated_race_laps,
    evaluate_race_strategy_scenarios,
    required_stop_count,
)


def test_estimates_race_laps_with_final_lap_after_clock():
    assert estimated_race_laps(100.0, 120.0) == 50
    assert estimated_race_laps(100.0, 121.0) == 50
    assert estimated_race_laps(100.0, 121.0, count_final_lap_after_clock=False) == 49


def test_required_stop_count_uses_tank_capacity_and_mandatory_stops():
    assert required_stop_count(race_laps=50, fuel_per_lap_l=3.4, tank_capacity_l=75.0) == 2
    assert required_stop_count(race_laps=50, fuel_per_lap_l=3.0, tank_capacity_l=75.0) == 1
    assert (
        required_stop_count(
            race_laps=20,
            fuel_per_lap_l=3.0,
            tank_capacity_l=75.0,
            mandatory_stop_count=1,
        )
        == 1
    )


def test_compares_full_push_and_lico_strategy():
    config = RaceStrategyConfig(
        race_duration_min=100.0,
        tank_capacity_l=75.0,
        baseline_fuel_per_lap_l=3.4,
        baseline_lap_time_s=120.0,
        pit_lane_commitment_time_s=70.0,
        refill_rate_lps=2.0,
    )

    comparison = compare_push_and_lico_strategy(
        fuel_saved_per_lap_l=0.4,
        time_lost_per_lap_s=1.0,
        config=config,
    )

    push = comparison.filter(pl.col("scenario_id") == "full_push").row(0, named=True)
    lico = comparison.filter(pl.col("scenario_id") == "lico_plan").row(0, named=True)

    assert push["race_laps"] == 50
    assert push["required_stop_count"] == 2
    assert push["estimated_total_time_s"] == pytest.approx(6140.0)
    assert lico["fuel_per_lap_l"] == pytest.approx(3.0)
    assert lico["required_stop_count"] == 1
    assert lico["stops_saved_vs_full_push"] == 1
    assert lico["estimated_total_time_s"] == pytest.approx(6120.0)
    assert lico["estimated_time_delta_vs_full_push_s"] == pytest.approx(-20.0)


def test_builds_fuel_saving_targets_for_lower_stop_counts():
    config = RaceStrategyConfig(
        race_duration_min=100.0,
        tank_capacity_l=75.0,
        baseline_fuel_per_lap_l=3.4,
        baseline_lap_time_s=120.0,
        pit_lane_commitment_time_s=70.0,
        refill_rate_lps=2.0,
    )

    targets = build_fuel_saving_targets(config=config)

    rows = targets.select(
        "target_stop_count",
        "target_fuel_per_lap_l",
        "required_fuel_saving_per_lap_l",
        "is_less_than_baseline_stop_count",
    ).rows()
    assert [row[0] for row in rows] == [0, 1, 2]
    assert [row[1] for row in rows] == pytest.approx([1.5, 3.0, 4.5])
    assert [row[2] for row in rows] == pytest.approx([1.9, 0.4, 0.0])
    assert [row[3] for row in rows] == [True, True, False]


def test_evaluates_custom_scenario_frame():
    config = RaceStrategyConfig(
        race_duration_min=100.0,
        tank_capacity_l=75.0,
        baseline_fuel_per_lap_l=3.4,
        baseline_lap_time_s=120.0,
        pit_lane_commitment_time_s=70.0,
        refill_rate_lps=2.0,
    )
    scenarios = pl.DataFrame(
        [
            {"scenario_id": "push", "fuel_per_lap_l": 3.4, "lap_time_s": 120.0},
            {"scenario_id": "save", "fuel_per_lap_l": 3.0, "lap_time_s": 121.0},
        ]
    )

    evaluated = evaluate_race_strategy_scenarios(scenarios, config=config)

    save = evaluated.filter(pl.col("scenario_id") == "save").row(0, named=True)
    assert save["fuel_to_refill_l"] == pytest.approx(75.0)
    assert save["estimated_refill_duration_s"] == pytest.approx(37.5)
    assert save["max_stint_laps"] == 25


def test_can_override_race_lap_count_from_championship_result():
    config = RaceStrategyConfig(
        race_duration_min=100.0,
        tank_capacity_l=75.0,
        baseline_fuel_per_lap_l=3.446,
        baseline_lap_time_s=123.824,
        pit_lane_commitment_time_s=70.0,
        refill_rate_lps=2.0,
        race_laps_override=48,
    )

    targets = build_fuel_saving_targets(config=config)

    one_stop = targets.filter(pl.col("target_stop_count") == 1).row(0, named=True)
    assert one_stop["race_laps"] == 48
    assert one_stop["target_fuel_per_lap_l"] == pytest.approx(3.125)
    assert one_stop["required_fuel_saving_per_lap_l"] == pytest.approx(0.321)
