from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import polars as pl


@dataclass(frozen=True)
class RaceStrategyConfig:
    race_duration_min: float
    tank_capacity_l: float
    baseline_fuel_per_lap_l: float
    baseline_lap_time_s: float
    pit_lane_commitment_time_s: float
    refill_rate_lps: float
    starting_fuel_l: float | None = None
    mandatory_stop_count: int = 0
    count_final_lap_after_clock: bool = True
    race_laps_override: int | None = None


def evaluate_race_strategy_scenarios(
    scenarios: pl.DataFrame,
    *,
    config: RaceStrategyConfig,
) -> pl.DataFrame:
    """Evaluate race stop counts and total-time estimates for fuel scenarios."""

    if scenarios.is_empty():
        return _empty_strategy_frame()

    race_laps = _race_laps(config)
    starting_fuel_l = _starting_fuel_l(config)
    rows = []
    for scenario in scenarios.iter_rows(named=True):
        rows.append(_strategy_row(scenario, race_laps, starting_fuel_l, config=config))
    return pl.DataFrame(rows, schema=_STRATEGY_SCHEMA, strict=False).select(_STRATEGY_COLUMNS)


def compare_push_and_lico_strategy(
    *,
    fuel_saved_per_lap_l: float,
    time_lost_per_lap_s: float,
    config: RaceStrategyConfig,
) -> pl.DataFrame:
    """Compare full-push baseline with one LICO fuel-saving scenario."""

    scenarios = pl.DataFrame(
        [
            {
                "scenario_id": "full_push",
                "fuel_per_lap_l": config.baseline_fuel_per_lap_l,
                "lap_time_s": config.baseline_lap_time_s,
                "fuel_saved_per_lap_l": 0.0,
                "time_lost_per_lap_s": 0.0,
            },
            {
                "scenario_id": "lico_plan",
                "fuel_per_lap_l": config.baseline_fuel_per_lap_l - fuel_saved_per_lap_l,
                "lap_time_s": config.baseline_lap_time_s + time_lost_per_lap_s,
                "fuel_saved_per_lap_l": fuel_saved_per_lap_l,
                "time_lost_per_lap_s": time_lost_per_lap_s,
            },
        ]
    )
    evaluated = evaluate_race_strategy_scenarios(scenarios, config=config)
    baseline = evaluated.filter(pl.col("scenario_id") == "full_push").row(0, named=True)
    return evaluated.with_columns(
        (pl.col("estimated_total_time_s") - float(baseline["estimated_total_time_s"])).alias(
            "estimated_time_delta_vs_full_push_s"
        ),
        (int(baseline["required_stop_count"]) - pl.col("required_stop_count")).alias(
            "stops_saved_vs_full_push"
        ),
    ).select(_STRATEGY_COMPARISON_COLUMNS)


def build_fuel_saving_targets(*, config: RaceStrategyConfig) -> pl.DataFrame:
    """Compute fuel-per-lap targets needed to make lower stop counts feasible."""

    race_laps = _race_laps(config)
    baseline_stops = required_stop_count(
        race_laps=race_laps,
        fuel_per_lap_l=config.baseline_fuel_per_lap_l,
        tank_capacity_l=config.tank_capacity_l,
        mandatory_stop_count=config.mandatory_stop_count,
    )
    rows = []
    for target_stop_count in range(baseline_stops + 1):
        available_fuel_l = config.tank_capacity_l * (target_stop_count + 1)
        target_fuel_per_lap_l = available_fuel_l / race_laps
        required_saving_l = max(
            0.0,
            config.baseline_fuel_per_lap_l - target_fuel_per_lap_l,
        )
        rows.append(
            {
                "target_stop_count": target_stop_count,
                "race_laps": race_laps,
                "available_fuel_l": available_fuel_l,
                "target_fuel_per_lap_l": target_fuel_per_lap_l,
                "required_fuel_saving_per_lap_l": required_saving_l,
                "is_less_than_baseline_stop_count": target_stop_count < baseline_stops,
                "is_feasible_without_saving": required_saving_l == 0.0,
                "baseline_stop_count": baseline_stops,
            }
        )
    return pl.DataFrame(rows, schema=_TARGET_SCHEMA, strict=False).select(_TARGET_COLUMNS)


def estimated_race_laps(
    race_duration_min: float,
    lap_time_s: float,
    *,
    count_final_lap_after_clock: bool = True,
) -> int:
    race_duration_s = race_duration_min * 60.0
    if race_duration_s <= 0.0 or lap_time_s <= 0.0:
        raise ValueError("race duration and lap time must be positive")
    if count_final_lap_after_clock:
        return math.ceil(race_duration_s / lap_time_s)
    return math.floor(race_duration_s / lap_time_s)


def required_stop_count(
    *,
    race_laps: int,
    fuel_per_lap_l: float,
    tank_capacity_l: float,
    mandatory_stop_count: int = 0,
) -> int:
    if race_laps <= 0:
        raise ValueError("race_laps must be positive")
    if fuel_per_lap_l <= 0.0 or tank_capacity_l <= 0.0:
        raise ValueError("fuel per lap and tank capacity must be positive")
    stint_laps = math.floor(tank_capacity_l / fuel_per_lap_l)
    if stint_laps <= 0:
        raise ValueError("fuel per lap exceeds tank capacity")
    fuel_stops = max(0, math.ceil(race_laps / stint_laps) - 1)
    return max(fuel_stops, mandatory_stop_count)


def _race_laps(config: RaceStrategyConfig) -> int:
    if config.race_laps_override is not None:
        if config.race_laps_override <= 0:
            raise ValueError("race_laps_override must be positive")
        return config.race_laps_override
    return estimated_race_laps(
        config.race_duration_min,
        config.baseline_lap_time_s,
        count_final_lap_after_clock=config.count_final_lap_after_clock,
    )


def _strategy_row(
    scenario: dict[str, Any],
    race_laps: int,
    starting_fuel_l: float,
    *,
    config: RaceStrategyConfig,
) -> dict[str, Any]:
    fuel_per_lap_l = float(scenario["fuel_per_lap_l"])
    lap_time_s = float(scenario["lap_time_s"])
    total_fuel_needed_l = race_laps * fuel_per_lap_l
    stop_count = required_stop_count(
        race_laps=race_laps,
        fuel_per_lap_l=fuel_per_lap_l,
        tank_capacity_l=config.tank_capacity_l,
        mandatory_stop_count=config.mandatory_stop_count,
    )
    fuel_to_refill_l = max(0.0, total_fuel_needed_l - starting_fuel_l)
    estimated_refill_duration_s = fuel_to_refill_l / config.refill_rate_lps
    estimated_drive_time_s = race_laps * lap_time_s
    estimated_pit_commitment_time_s = stop_count * config.pit_lane_commitment_time_s
    estimated_total_time_s = estimated_drive_time_s + estimated_pit_commitment_time_s
    max_stint_laps = math.floor(config.tank_capacity_l / fuel_per_lap_l)
    return {
        "scenario_id": str(scenario["scenario_id"]),
        "race_laps": race_laps,
        "fuel_per_lap_l": fuel_per_lap_l,
        "lap_time_s": lap_time_s,
        "fuel_saved_per_lap_l": _optional_float(scenario.get("fuel_saved_per_lap_l")),
        "time_lost_per_lap_s": _optional_float(scenario.get("time_lost_per_lap_s")),
        "total_fuel_needed_l": total_fuel_needed_l,
        "starting_fuel_l": starting_fuel_l,
        "fuel_to_refill_l": fuel_to_refill_l,
        "estimated_refill_duration_s": estimated_refill_duration_s,
        "max_stint_laps": max_stint_laps,
        "required_stop_count": stop_count,
        "estimated_drive_time_s": estimated_drive_time_s,
        "estimated_pit_commitment_time_s": estimated_pit_commitment_time_s,
        "estimated_total_time_s": estimated_total_time_s,
        "pit_lane_commitment_time_s": config.pit_lane_commitment_time_s,
        "refill_rate_lps": config.refill_rate_lps,
        "mandatory_stop_count": config.mandatory_stop_count,
    }


def _starting_fuel_l(config: RaceStrategyConfig) -> float:
    if config.starting_fuel_l is None:
        return config.tank_capacity_l
    return config.starting_fuel_l


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _empty_strategy_frame() -> pl.DataFrame:
    return pl.DataFrame(schema=_STRATEGY_SCHEMA)


_STRATEGY_COLUMNS = [
    "scenario_id",
    "race_laps",
    "fuel_per_lap_l",
    "lap_time_s",
    "fuel_saved_per_lap_l",
    "time_lost_per_lap_s",
    "total_fuel_needed_l",
    "starting_fuel_l",
    "fuel_to_refill_l",
    "estimated_refill_duration_s",
    "max_stint_laps",
    "required_stop_count",
    "estimated_drive_time_s",
    "estimated_pit_commitment_time_s",
    "estimated_total_time_s",
    "pit_lane_commitment_time_s",
    "refill_rate_lps",
    "mandatory_stop_count",
]

_STRATEGY_COMPARISON_COLUMNS = [
    *_STRATEGY_COLUMNS,
    "estimated_time_delta_vs_full_push_s",
    "stops_saved_vs_full_push",
]

_STRATEGY_SCHEMA = {
    "scenario_id": pl.String,
    "race_laps": pl.Int64,
    "fuel_per_lap_l": pl.Float64,
    "lap_time_s": pl.Float64,
    "fuel_saved_per_lap_l": pl.Float64,
    "time_lost_per_lap_s": pl.Float64,
    "total_fuel_needed_l": pl.Float64,
    "starting_fuel_l": pl.Float64,
    "fuel_to_refill_l": pl.Float64,
    "estimated_refill_duration_s": pl.Float64,
    "max_stint_laps": pl.Int64,
    "required_stop_count": pl.Int64,
    "estimated_drive_time_s": pl.Float64,
    "estimated_pit_commitment_time_s": pl.Float64,
    "estimated_total_time_s": pl.Float64,
    "pit_lane_commitment_time_s": pl.Float64,
    "refill_rate_lps": pl.Float64,
    "mandatory_stop_count": pl.Int64,
}

_TARGET_COLUMNS = [
    "target_stop_count",
    "race_laps",
    "available_fuel_l",
    "target_fuel_per_lap_l",
    "required_fuel_saving_per_lap_l",
    "is_less_than_baseline_stop_count",
    "is_feasible_without_saving",
    "baseline_stop_count",
]

_TARGET_SCHEMA = {
    "target_stop_count": pl.Int64,
    "race_laps": pl.Int64,
    "available_fuel_l": pl.Float64,
    "target_fuel_per_lap_l": pl.Float64,
    "required_fuel_saving_per_lap_l": pl.Float64,
    "is_less_than_baseline_stop_count": pl.Boolean,
    "is_feasible_without_saving": pl.Boolean,
    "baseline_stop_count": pl.Int64,
}
