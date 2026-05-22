from __future__ import annotations
from dataclasses import dataclass
from typing import Any

import polars as pl


@dataclass(frozen=True)
class ZoneOptimizerConfig:
    target_fuel_saved_per_lap_l: float
    allowed_model_statuses: tuple[str, ...] = ("model_ready",)
    min_positive_fuel_saved_l: float = 1e-6
    min_nonzero_time_loss_s: float = 0.05
    require_usable_ratio: bool = True
    allow_review_excluded: bool = False
    max_combinations: int = 2_000_000


def optimize_zone_lico_plan(
    zone_models: pl.DataFrame,
    *,
    config: ZoneOptimizerConfig,
    zone_priors: pl.DataFrame | None = None,
) -> pl.DataFrame:
    """Select one model point per zone to meet a fuel target with minimal time loss."""

    if zone_models.is_empty():
        return _empty_zone_plan_frame()

    candidates = _candidate_rows(zone_models, config=config, zone_priors=zone_priors)
    if not candidates:
        return _empty_zone_plan_frame()

    grouped = _candidates_by_zone(candidates)
    frontier = _candidate_frontier(grouped, max_frontier_size=config.max_combinations)
    best = _best_combination(
        frontier,
        target_fuel_saved_l=config.target_fuel_saved_per_lap_l,
    )
    if best is None:
        best = _max_fuel_combination(frontier)
        plan_status = "target_unreachable"
    else:
        plan_status = "target_met"

    return _plan_frame(best, plan_status=plan_status, config=config)


def _candidate_rows(
    zone_models: pl.DataFrame,
    *,
    config: ZoneOptimizerConfig,
    zone_priors: pl.DataFrame | None,
) -> list[dict[str, Any]]:
    prior_map = _prior_map(zone_priors)
    frame = zone_models.filter(
        pl.col("model_status").is_in(config.allowed_model_statuses)
        & (~pl.col("is_extrapolated"))
        & (pl.col("predicted_fuel_saved_l") >= 0.0)
        & (pl.col("predicted_time_lost_s") >= 0.0)
    )
    rows = []
    for row in frame.iter_rows(named=True):
        prior = prior_map.get(str(row["zone_id"]))
        if prior is not None and _prior_excludes_candidate(row, prior, config=config):
            continue
        fuel_saved_l = float(row["predicted_fuel_saved_l"])
        time_lost_s = float(row["predicted_time_lost_s"])
        lico_distance_m = float(row["lico_distance_m"])
        is_nonzero_candidate = (
            lico_distance_m > 0.0 and fuel_saved_l > config.min_positive_fuel_saved_l
        )
        if is_nonzero_candidate and time_lost_s < config.min_nonzero_time_loss_s:
            continue
        if (
            is_nonzero_candidate
            and config.require_usable_ratio
            and row.get("predicted_fuel_saved_per_second_lps") is None
        ):
            continue
        rows.append(
            {
                "zone_id": str(row["zone_id"]),
                "display_label": str(row["display_label"]),
                "selected_lico_distance_m": lico_distance_m,
                "predicted_fuel_saved_l": fuel_saved_l,
                "predicted_time_lost_s": time_lost_s,
                "optimization_time_lost_s": (
                    time_lost_s if is_nonzero_candidate else 0.0
                ),
                "model_status": str(row["model_status"]),
                "quality_flags": _format_quality_flags(row.get("quality_flags")),
                "feasibility_score": _prior_field(prior, "feasibility_score"),
                "strategy_role": _prior_field(prior, "strategy_role") or "",
                "max_lico_distance_m": _prior_field(prior, "max_lico_distance_m"),
                "strategy_prior_notes": _prior_field(prior, "notes") or "",
            }
        )
    return rows


def _prior_map(zone_priors: pl.DataFrame | None) -> dict[str, dict[str, Any]]:
    if zone_priors is None or zone_priors.is_empty():
        return {}
    return {
        str(row["zone_id"]): row
        for row in zone_priors.iter_rows(named=True)
    }


def _prior_excludes_candidate(
    row: dict[str, Any],
    prior: dict[str, Any],
    *,
    config: ZoneOptimizerConfig,
) -> bool:
    if prior.get("strategy_role") == "excluded" or int(prior.get("feasibility_score") or 0) == 0:
        return True
    if str(row["model_status"]) == "review_excluded" and not config.allow_review_excluded:
        return True
    if (
        str(row["model_status"]) != "model_ready"
        and not bool(prior.get("allow_diagnostic_model"))
    ):
        return True
    max_distance_m = prior.get("max_lico_distance_m")
    return (
        max_distance_m is not None
        and float(row["lico_distance_m"]) > float(max_distance_m)
    )


def _prior_field(prior: dict[str, Any] | None, field_name: str) -> Any:
    if prior is None:
        return None
    return prior.get(field_name)


def _candidates_by_zone(candidates: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    by_zone: dict[str, list[dict[str, Any]]] = {}
    for candidate in candidates:
        by_zone.setdefault(candidate["zone_id"], []).append(candidate)

    grouped = []
    for zone_id in sorted(by_zone):
        zone_candidates = sorted(
            by_zone[zone_id],
            key=lambda candidate: (
                candidate["optimization_time_lost_s"],
                candidate["predicted_fuel_saved_l"],
                candidate["selected_lico_distance_m"],
            ),
        )
        grouped.append(_pareto_candidates(zone_candidates))
    return grouped


def _pareto_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    efficient = []
    best_fuel_at_or_below_time = -1.0
    for candidate in sorted(
        candidates,
        key=lambda row: (row["optimization_time_lost_s"], -row["predicted_fuel_saved_l"]),
    ):
        if candidate["predicted_fuel_saved_l"] > best_fuel_at_or_below_time:
            efficient.append(candidate)
            best_fuel_at_or_below_time = candidate["predicted_fuel_saved_l"]
    return efficient


def _best_combination(
    frontier: list[tuple[float, float, float, tuple[dict[str, Any], ...]]],
    *,
    target_fuel_saved_l: float,
) -> tuple[dict[str, Any], ...] | None:
    feasible = [
        item
        for item in frontier
        if item[1] + 1e-12 >= target_fuel_saved_l
    ]
    if not feasible:
        return None
    return min(
        feasible,
        key=lambda item: (item[0], item[1] - target_fuel_saved_l, item[2]),
    )[3]


def _max_fuel_combination(
    frontier: list[tuple[float, float, float, tuple[dict[str, Any], ...]]],
) -> tuple[dict[str, Any], ...]:
    return max(
        frontier,
        key=lambda item: (item[1], -item[0], -item[2]),
    )[3]


def _candidate_frontier(
    grouped: list[list[dict[str, Any]]],
    *,
    max_frontier_size: int,
) -> list[tuple[float, float, float, tuple[dict[str, Any], ...]]]:
    frontier: list[tuple[float, float, float, tuple[dict[str, Any], ...]]] = [
        (0.0, 0.0, 0.0, ())
    ]
    for group in grouped:
        expanded = []
        for total_time, total_fuel, total_distance, combination in frontier:
            for candidate in group:
                expanded.append(
                    (
                        total_time + float(candidate["optimization_time_lost_s"]),
                        total_fuel + float(candidate["predicted_fuel_saved_l"]),
                        total_distance + float(candidate["selected_lico_distance_m"]),
                        combination + (candidate,),
                    )
                )
        frontier = _pareto_frontier(expanded, max_frontier_size=max_frontier_size)
    return frontier


def _pareto_frontier(
    states: list[tuple[float, float, float, tuple[dict[str, Any], ...]]],
    *,
    max_frontier_size: int,
) -> list[tuple[float, float, float, tuple[dict[str, Any], ...]]]:
    efficient = []
    best_fuel_at_or_below_time = -1.0
    for state in sorted(states, key=lambda item: (item[0], -item[1], item[2])):
        if state[1] > best_fuel_at_or_below_time + 1e-12:
            efficient.append(state)
            best_fuel_at_or_below_time = state[1]
    if len(efficient) > max_frontier_size:
        raise ValueError("too many pareto states to optimize safely")
    return efficient


def _plan_frame(
    combination: tuple[dict[str, Any], ...],
    *,
    plan_status: str,
    config: ZoneOptimizerConfig,
) -> pl.DataFrame:
    total_fuel = sum(row["predicted_fuel_saved_l"] for row in combination)
    total_predicted_time = sum(row["predicted_time_lost_s"] for row in combination)
    total_optimization_time = sum(row["optimization_time_lost_s"] for row in combination)
    rows = []
    for row in combination:
        output = dict(row)
        output.update(
            {
                "is_selected_for_lico": row["selected_lico_distance_m"] > 0.0,
                "target_fuel_saved_per_lap_l": config.target_fuel_saved_per_lap_l,
                "total_predicted_fuel_saved_l": total_fuel,
                "total_predicted_time_lost_s": total_predicted_time,
                "total_optimization_time_lost_s": total_optimization_time,
                "fuel_surplus_l": total_fuel - config.target_fuel_saved_per_lap_l,
                "plan_status": plan_status,
            }
        )
        rows.append(output)
    return pl.DataFrame(rows, schema=_ZONE_PLAN_SCHEMA, strict=False).select(_ZONE_PLAN_COLUMNS)


def _empty_zone_plan_frame() -> pl.DataFrame:
    return pl.DataFrame(schema=_ZONE_PLAN_SCHEMA)


def _format_quality_flags(flags: Any) -> str:
    if flags is None:
        return ""
    if isinstance(flags, str):
        return flags
    return "|".join(str(flag) for flag in flags)


_ZONE_PLAN_COLUMNS = [
    "zone_id",
    "display_label",
    "selected_lico_distance_m",
    "is_selected_for_lico",
    "predicted_fuel_saved_l",
    "predicted_time_lost_s",
    "optimization_time_lost_s",
    "model_status",
    "quality_flags",
    "feasibility_score",
    "strategy_role",
    "max_lico_distance_m",
    "strategy_prior_notes",
    "target_fuel_saved_per_lap_l",
    "total_predicted_fuel_saved_l",
    "total_predicted_time_lost_s",
    "total_optimization_time_lost_s",
    "fuel_surplus_l",
    "plan_status",
]

_ZONE_PLAN_SCHEMA = {
    "zone_id": pl.String,
    "display_label": pl.String,
    "selected_lico_distance_m": pl.Float64,
    "is_selected_for_lico": pl.Boolean,
    "predicted_fuel_saved_l": pl.Float64,
    "predicted_time_lost_s": pl.Float64,
    "optimization_time_lost_s": pl.Float64,
    "model_status": pl.String,
    "quality_flags": pl.String,
    "feasibility_score": pl.Int64,
    "strategy_role": pl.String,
    "max_lico_distance_m": pl.Float64,
    "strategy_prior_notes": pl.String,
    "target_fuel_saved_per_lap_l": pl.Float64,
    "total_predicted_fuel_saved_l": pl.Float64,
    "total_predicted_time_lost_s": pl.Float64,
    "total_optimization_time_lost_s": pl.Float64,
    "fuel_surplus_l": pl.Float64,
    "plan_status": pl.String,
}
