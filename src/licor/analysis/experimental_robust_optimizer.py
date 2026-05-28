from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import polars as pl

from licor.analysis.zone_optimizer import ZoneOptimizerConfig, optimize_zone_lico_plan


@dataclass(frozen=True)
class ExperimentalRobustOptimizerConfig:
    baseline_intensity: str = "none"
    support_radius_m: float = 15.0
    target_support_pass_count: int = 6
    gap_scale_m: float = 15.0
    tail_scale_m: float = 25.0
    fuel_std_multiplier: float = 0.35
    time_std_multiplier: float = 0.35
    max_fuel_penalty_fraction: float = 0.22
    max_time_penalty_fraction: float = 0.32
    dynamics_penalty_scale: float = 0.08
    recommended_range_ratio_fraction: float = 0.92
    recommended_range_support_fraction: float = 0.85
    min_recommended_support_score: float = 0.45


def build_experimental_robust_zone_models(
    zone_models: pl.DataFrame,
    zone_dynamics: pl.DataFrame,
    *,
    model_comparison: pl.DataFrame | None = None,
    config: ExperimentalRobustOptimizerConfig | None = None,
) -> pl.DataFrame:
    """Create a support-aware experimental model table from existing zone curves."""

    robust_config = config or ExperimentalRobustOptimizerConfig()
    if zone_models.is_empty():
        return zone_models

    comparison_map = _comparison_lookup(model_comparison)
    dynamics_support = _support_observations(zone_dynamics, config=robust_config)

    rows = []
    for row in zone_models.iter_rows(named=True):
        output = dict(row)
        candidate_distance_m = float(row["lico_distance_m"])
        predicted_fuel_saved_l = float(row["predicted_fuel_saved_l"])
        predicted_time_lost_s = float(row["predicted_time_lost_s"])
        zone_id = str(row["zone_id"])

        if candidate_distance_m <= 0.0 or predicted_fuel_saved_l <= 0.0:
            output.update(
                {
                    "local_support_pass_count": 0,
                    "left_support_pass_count": 0,
                    "right_support_pass_count": 0,
                    "nearest_observed_gap_m": 0.0,
                    "tail_span_to_max_observed_m": 0.0,
                    "local_mean_fuel_saved_l": 0.0,
                    "local_mean_time_lost_s": 0.0,
                    "local_std_fuel_saved_l": 0.0,
                    "local_std_time_lost_s": 0.0,
                    "dynamics_r2_improvement": _comparison_value(
                        comparison_map.get(zone_id),
                        "r2_improvement",
                    )
                    or 0.0,
                    "support_score": 1.0,
                    "support_penalty_fraction": 0.0,
                    "robust_predicted_fuel_saved_l": predicted_fuel_saved_l,
                    "robust_predicted_time_lost_s": predicted_time_lost_s,
                    "robust_predicted_fuel_saved_per_second_lps": _ratio(
                        predicted_fuel_saved_l,
                        predicted_time_lost_s,
                    ),
                    "robust_range_tier": "baseline",
                }
            )
            rows.append(output)
            continue

        support_row = _support_row(
            zone_id=zone_id,
            candidate_distance_m=candidate_distance_m,
            support_frame=dynamics_support,
            comparison_row=comparison_map.get(zone_id),
            config=robust_config,
        )
        penalty_fraction = float(support_row["support_penalty_fraction"])
        robust_fuel_saved_l = max(
            0.0,
            predicted_fuel_saved_l * (1.0 - penalty_fraction)
            - float(support_row["local_std_fuel_saved_l"]) * robust_config.fuel_std_multiplier,
        )
        robust_time_lost_s = (
            predicted_time_lost_s * (1.0 + penalty_fraction)
            + float(support_row["local_std_time_lost_s"]) * robust_config.time_std_multiplier
        )
        output.update(
            support_row
            | {
                "robust_predicted_fuel_saved_l": robust_fuel_saved_l,
                "robust_predicted_time_lost_s": robust_time_lost_s,
                "robust_predicted_fuel_saved_per_second_lps": _ratio(
                    robust_fuel_saved_l,
                    robust_time_lost_s,
                ),
                "robust_range_tier": _range_tier(float(support_row["support_score"])),
            }
        )
        rows.append(output)

    return pl.DataFrame(rows, strict=False).select(rows[0].keys() if rows else zone_models.columns)


def summarize_experimental_robust_recommended_ranges(
    robust_zone_models: pl.DataFrame,
    robust_zone_plan: pl.DataFrame,
    *,
    config: ExperimentalRobustOptimizerConfig | None = None,
) -> pl.DataFrame:
    """Return one row per selected zone with a contiguous robust recommended range."""

    robust_config = config or ExperimentalRobustOptimizerConfig()
    if robust_zone_models.is_empty() or robust_zone_plan.is_empty():
        return pl.DataFrame()

    selected = robust_zone_plan.filter(pl.col("is_selected_for_lico"))
    if selected.is_empty():
        return pl.DataFrame()

    rows = []
    for plan_row in selected.iter_rows(named=True):
        zone_id = str(plan_row["zone_id"])
        selected_distance_m = float(plan_row["selected_lico_distance_m"])
        zone_model = robust_zone_models.filter(
            (pl.col("zone_id") == zone_id) & (pl.col("lico_distance_m") > 0.0)
        ).sort("lico_distance_m")
        if zone_model.is_empty():
            continue

        selected_model_row = _closest_distance_row(zone_model, selected_distance_m)
        selected_ratio = _float_or_zero(
            selected_model_row.get("robust_predicted_fuel_saved_per_second_lps")
        )
        selected_support = _float_or_zero(selected_model_row.get("support_score"))
        qualifying = zone_model.filter(
            pl.col("support_score")
            >= max(
                robust_config.min_recommended_support_score,
                selected_support * robust_config.recommended_range_support_fraction,
            )
        ).filter(
            pl.col("robust_predicted_fuel_saved_per_second_lps")
            >= selected_ratio * robust_config.recommended_range_ratio_fraction
        )
        if qualifying.is_empty():
            qualifying = zone_model.filter(
                pl.col("lico_distance_m") == selected_model_row["lico_distance_m"]
            )

        contiguous_rows = _contiguous_rows_around_distance(
            qualifying.sort("lico_distance_m"),
            selected_distance_m=selected_distance_m,
        )
        range_start_m = min(float(row["lico_distance_m"]) for row in contiguous_rows)
        range_end_m = max(float(row["lico_distance_m"]) for row in contiguous_rows)
        rows.append(
            {
                "zone_id": zone_id,
                "display_label": str(plan_row["display_label"]),
                "selected_lico_distance_m": selected_distance_m,
                "recommended_range_start_m": range_start_m,
                "recommended_range_end_m": range_end_m,
                "recommended_range_width_m": range_end_m - range_start_m,
                "selected_support_score": selected_support,
                "selected_robust_fuel_saved_per_second_lps": selected_ratio,
                "selected_robust_fuel_saved_l": float(
                    selected_model_row["robust_predicted_fuel_saved_l"]
                ),
                "selected_robust_time_lost_s": float(
                    selected_model_row["robust_predicted_time_lost_s"]
                ),
            }
        )

    return pl.DataFrame(rows).sort("zone_id")


def compare_experimental_zone_plans(
    naive_plan: pl.DataFrame,
    robust_plan: pl.DataFrame,
    robust_ranges: pl.DataFrame,
    robust_zone_models: pl.DataFrame,
) -> pl.DataFrame:
    """Join naive and robust selected plan information for easy review."""

    return compare_experimental_plan_variants(
        naive_plan,
        robust_plan,
        robust_ranges,
        robust_zone_models,
        left_prefix="naive",
        right_prefix="robust",
    )


def compare_experimental_plan_variants(
    left_plan: pl.DataFrame,
    right_plan: pl.DataFrame,
    right_ranges: pl.DataFrame,
    right_zone_models: pl.DataFrame,
    *,
    left_prefix: str,
    right_prefix: str,
) -> pl.DataFrame:
    """Join two plan variants for direct zone-by-zone review."""

    frames = []
    if not left_plan.is_empty():
        frames.append(left_plan.select("zone_id", "display_label"))
    if not right_plan.is_empty():
        frames.append(right_plan.select("zone_id", "display_label"))
    if not frames:
        return pl.DataFrame()

    left_selected = left_plan.filter(pl.col("is_selected_for_lico")).rename(
        {
            "selected_lico_distance_m": f"{left_prefix}_selected_lico_distance_m",
            "predicted_fuel_saved_l": f"{left_prefix}_predicted_fuel_saved_l",
            "predicted_time_lost_s": f"{left_prefix}_predicted_time_lost_s",
            "model_status": f"{left_prefix}_model_status",
            "plan_status": f"{left_prefix}_plan_status",
        }
    )
    right_selected = right_plan.filter(pl.col("is_selected_for_lico")).rename(
        {
            "selected_lico_distance_m": f"{right_prefix}_selected_lico_distance_m",
            "predicted_fuel_saved_l": f"{right_prefix}_predicted_fuel_saved_l",
            "predicted_time_lost_s": f"{right_prefix}_predicted_time_lost_s",
            "model_status": f"{right_prefix}_model_status",
            "plan_status": f"{right_prefix}_plan_status",
        }
    )

    rows = []
    zone_rows = (
        pl.concat(frames)
        .unique(subset=["zone_id"], keep="first")
        .sort("zone_id")
        .iter_rows(named=True)
    )
    for zone_row in zone_rows:
        zone_id = str(zone_row["zone_id"])
        left_row = _first_row(left_selected, zone_id)
        right_row = _first_row(right_selected, zone_id)
        right_model_row = None
        if right_row is not None:
            right_model_row = _closest_distance_row(
                right_zone_models.filter(pl.col("zone_id") == zone_id),
                float(right_row[f"{right_prefix}_selected_lico_distance_m"]),
            )
        range_row = _first_row(right_ranges, zone_id)
        rows.append(
            {
                "zone_id": zone_id,
                "display_label": str(zone_row["display_label"]),
                f"{left_prefix}_selected_lico_distance_m": _optional_float(
                    left_row,
                    f"{left_prefix}_selected_lico_distance_m",
                ),
                f"{right_prefix}_selected_lico_distance_m": _optional_float(
                    right_row,
                    f"{right_prefix}_selected_lico_distance_m",
                ),
                "distance_shift_m": _distance_shift(
                    _optional_float(left_row, f"{left_prefix}_selected_lico_distance_m"),
                    _optional_float(right_row, f"{right_prefix}_selected_lico_distance_m"),
                ),
                f"{left_prefix}_predicted_fuel_saved_l": _optional_float(
                    left_row,
                    f"{left_prefix}_predicted_fuel_saved_l",
                ),
                f"{right_prefix}_plan_fuel_saved_l": _optional_float(
                    right_row,
                    f"{right_prefix}_predicted_fuel_saved_l",
                ),
                f"{left_prefix}_predicted_time_lost_s": _optional_float(
                    left_row,
                    f"{left_prefix}_predicted_time_lost_s",
                ),
                f"{right_prefix}_plan_time_lost_s": _optional_float(
                    right_row,
                    f"{right_prefix}_predicted_time_lost_s",
                ),
                f"{right_prefix}_support_score": (
                    _optional_float(right_model_row, "support_score")
                    if right_model_row is not None
                    else None
                ),
                f"{right_prefix}_local_support_pass_count": (
                    _optional_int(right_model_row, "local_support_pass_count")
                    if right_model_row is not None
                    else None
                ),
                f"{right_prefix}_nearest_observed_gap_m": (
                    _optional_float(right_model_row, "nearest_observed_gap_m")
                    if right_model_row is not None
                    else None
                ),
                f"{right_prefix}_tail_span_to_max_observed_m": (
                    _optional_float(right_model_row, "tail_span_to_max_observed_m")
                    if right_model_row is not None
                    else None
                ),
                "recommended_range_start_m": _optional_float(
                    range_row,
                    "recommended_range_start_m",
                ),
                "recommended_range_end_m": _optional_float(
                    range_row,
                    "recommended_range_end_m",
                ),
                "recommended_range_width_m": _optional_float(
                    range_row,
                    "recommended_range_width_m",
                ),
                f"{left_prefix}_plan_status": _optional_string(
                    left_row,
                    f"{left_prefix}_plan_status",
                ),
                f"{right_prefix}_plan_status": _optional_string(
                    right_row,
                    f"{right_prefix}_plan_status",
                ),
            }
        )

    return pl.DataFrame(rows).sort("zone_id")


def build_experimental_range_aware_plan(
    robust_zone_models: pl.DataFrame,
    robust_ranges: pl.DataFrame,
    *,
    target_fuel_saved_per_lap_l: float,
    zone_priors: pl.DataFrame | None = None,
    allowed_model_statuses: tuple[str, ...] = ("model_ready", "micro_lico_only"),
    top_up_scope: str = "selected_zones",
) -> pl.DataFrame:
    """Start from range floors, then top up only where the target still requires it."""

    if robust_zone_models.is_empty() or robust_ranges.is_empty():
        return pl.DataFrame()

    floor_rows = _range_floor_rows(robust_zone_models, robust_ranges)
    if not floor_rows:
        return pl.DataFrame()

    floor_plan = _range_aware_plan_frame(
        tuple(floor_rows),
        target_fuel_saved_per_lap_l=target_fuel_saved_per_lap_l,
        plan_status="target_met",
    )
    floor_fuel = float(floor_plan["total_predicted_fuel_saved_l"][0])
    if floor_fuel + 1e-12 >= target_fuel_saved_per_lap_l:
        return floor_plan

    delta_zone_models = _range_delta_zone_models(
        robust_zone_models,
        robust_ranges,
        floor_rows,
        zone_priors=zone_priors,
        allowed_model_statuses=allowed_model_statuses,
        top_up_scope=top_up_scope,
    )
    if delta_zone_models.is_empty():
        return floor_plan.with_columns(pl.lit("target_unreachable").alias("plan_status"))

    residual_target_fuel_l = max(0.0, target_fuel_saved_per_lap_l - floor_fuel)
    delta_plan = optimize_zone_lico_plan(
        delta_zone_models,
        config=ZoneOptimizerConfig(
            target_fuel_saved_per_lap_l=residual_target_fuel_l,
            allowed_model_statuses=allowed_model_statuses,
            min_positive_fuel_saved_l=1e-9,
            min_nonzero_time_loss_s=0.0,
            require_usable_ratio=False,
        ),
    )
    combined_rows = _apply_range_top_up(
        floor_rows,
        delta_plan,
        delta_zone_models,
        top_up_scope=top_up_scope,
    )
    plan_status = (
        str(delta_plan["plan_status"][0]) if not delta_plan.is_empty() else "target_unreachable"
    )
    return _range_aware_plan_frame(
        tuple(combined_rows),
        target_fuel_saved_per_lap_l=target_fuel_saved_per_lap_l,
        plan_status=plan_status,
    )


def _range_floor_rows(
    robust_zone_models: pl.DataFrame,
    robust_ranges: pl.DataFrame,
) -> list[dict[str, Any]]:
    rows = []
    for range_row in robust_ranges.sort("zone_id").iter_rows(named=True):
        zone_id = str(range_row["zone_id"])
        zone_model = _zone_model_inside_range(
            robust_zone_models,
            zone_id=zone_id,
            range_start_m=float(range_row["recommended_range_start_m"]),
            range_end_m=float(range_row["recommended_range_end_m"]),
        )
        if zone_model.is_empty():
            continue
        floor_row = _range_candidate_row(
            zone_model.row(0, named=True),
            range_start_m=float(range_row["recommended_range_start_m"]),
            range_end_m=float(range_row["recommended_range_end_m"]),
        )
        floor_row["range_selection_status"] = "range_floor"
        rows.append(floor_row)
    return rows


def _range_delta_zone_models(
    robust_zone_models: pl.DataFrame,
    robust_ranges: pl.DataFrame,
    floor_rows: list[dict[str, Any]],
    *,
    zone_priors: pl.DataFrame | None,
    allowed_model_statuses: tuple[str, ...],
    top_up_scope: str,
) -> pl.DataFrame:
    rows = []
    floor_map = {str(row["zone_id"]): row for row in floor_rows}
    prior_map = _range_prior_map(zone_priors)
    range_map = {
        str(row["zone_id"]): row for row in robust_ranges.iter_rows(named=True)
    }
    if top_up_scope == "selected_zones":
        candidate_zone_ids = sorted(floor_map)
    elif top_up_scope == "all_eligible_zones":
        candidate_zone_ids = sorted(
            str(zone_id) for zone_id in robust_zone_models["zone_id"].unique().to_list()
        )
    else:
        raise ValueError(f"Unsupported range-aware top-up scope: {top_up_scope}")

    for zone_id in candidate_zone_ids:
        zone_floor_row = floor_map.get(zone_id)
        range_row = range_map.get(zone_id)
        if zone_floor_row is not None and range_row is not None:
            zone_model = _zone_model_inside_range(
                robust_zone_models,
                zone_id=zone_id,
                range_start_m=float(range_row["recommended_range_start_m"]),
                range_end_m=float(range_row["recommended_range_end_m"]),
            )
            floor_distance_m = float(zone_floor_row["selected_lico_distance_m"])
            floor_fuel_saved_l = float(zone_floor_row["predicted_fuel_saved_l"])
            floor_time_lost_s = float(zone_floor_row["predicted_time_lost_s"])
            range_start_m = float(range_row["recommended_range_start_m"])
            range_end_m = float(range_row["recommended_range_end_m"])
        elif top_up_scope == "all_eligible_zones":
            zone_model = robust_zone_models.filter(pl.col("zone_id") == zone_id).sort("lico_distance_m")
            floor_distance_m = 0.0
            floor_fuel_saved_l = 0.0
            floor_time_lost_s = 0.0
            range_start_m = 0.0
            range_end_m = 0.0
        else:
            continue

        for model_row in zone_model.iter_rows(named=True):
            if not _range_top_up_allows_model_row(
                model_row,
                prior=prior_map.get(zone_id),
                allowed_model_statuses=allowed_model_statuses,
            ):
                continue
            absolute_distance_m = float(model_row["lico_distance_m"])
            delta_distance_m = max(0.0, absolute_distance_m - floor_distance_m)
            absolute_fuel_saved_l = float(model_row["robust_predicted_fuel_saved_l"])
            absolute_time_lost_s = float(model_row["robust_predicted_time_lost_s"])
            delta_fuel_saved_l = max(0.0, absolute_fuel_saved_l - floor_fuel_saved_l)
            delta_time_lost_s = max(0.0, absolute_time_lost_s - floor_time_lost_s)
            rows.append(
                {
                    "zone_id": zone_id,
                    "display_label": str(model_row["display_label"]),
                    "lico_distance_m": delta_distance_m,
                    "predicted_fuel_saved_l": delta_fuel_saved_l,
                    "predicted_time_lost_s": delta_time_lost_s,
                    "predicted_fuel_saved_per_second_lps": _ratio(
                        delta_fuel_saved_l,
                        delta_time_lost_s,
                    ),
                    "is_extrapolated": False,
                    "model_status": str(model_row.get("model_status") or ""),
                    "quality_flags": _format_quality_flags(model_row.get("quality_flags")),
                    "absolute_lico_distance_m": absolute_distance_m,
                    "absolute_predicted_fuel_saved_l": absolute_fuel_saved_l,
                    "absolute_predicted_time_lost_s": absolute_time_lost_s,
                    "support_score": _float_or_zero(model_row.get("support_score")),
                    "recommended_range_start_m": range_start_m,
                    "recommended_range_end_m": range_end_m,
                }
            )

    if not rows:
        return pl.DataFrame()
    return pl.DataFrame(rows, strict=False)


def _apply_range_top_up(
    floor_rows: list[dict[str, Any]],
    delta_plan: pl.DataFrame,
    delta_zone_models: pl.DataFrame,
    *,
    top_up_scope: str,
) -> list[dict[str, Any]]:
    combined_rows = []
    floor_zone_ids = {str(row["zone_id"]) for row in floor_rows}
    for floor_row in floor_rows:
        zone_id = str(floor_row["zone_id"])
        selected_delta_row = _first_row(delta_plan, zone_id)
        if (
            selected_delta_row is None
            or float(selected_delta_row["selected_lico_distance_m"]) <= 1e-9
        ):
            combined_rows.append(floor_row)
            continue

        absolute_row = _closest_distance_row(
            delta_zone_models.filter(pl.col("zone_id") == zone_id),
            float(selected_delta_row["selected_lico_distance_m"]),
        )
        combined_rows.append(
            {
                "zone_id": zone_id,
                "display_label": str(floor_row["display_label"]),
                "selected_lico_distance_m": float(absolute_row["absolute_lico_distance_m"]),
                "predicted_fuel_saved_l": float(absolute_row["absolute_predicted_fuel_saved_l"]),
                "predicted_time_lost_s": float(absolute_row["absolute_predicted_time_lost_s"]),
                "optimization_time_lost_s": float(absolute_row["absolute_predicted_time_lost_s"]),
                "optimization_action_cost": float(absolute_row["absolute_lico_distance_m"]),
                "model_status": str(absolute_row.get("model_status") or ""),
                "quality_flags": _format_quality_flags(absolute_row.get("quality_flags")),
                "support_score": _float_or_zero(absolute_row.get("support_score")),
                "recommended_range_start_m": float(floor_row["recommended_range_start_m"]),
                "recommended_range_end_m": float(floor_row["recommended_range_end_m"]),
                "range_selection_status": "range_top_up",
            }
        )
    if top_up_scope == "all_eligible_zones" and not delta_plan.is_empty():
        selected_new_zone_rows = delta_plan.filter(
            pl.col("is_selected_for_lico") & (~pl.col("zone_id").is_in(list(floor_zone_ids)))
        )
        for new_zone_row in selected_new_zone_rows.iter_rows(named=True):
            absolute_row = _closest_distance_row(
                delta_zone_models.filter(pl.col("zone_id") == str(new_zone_row["zone_id"])),
                float(new_zone_row["selected_lico_distance_m"]),
            )
            combined_rows.append(
                {
                    "zone_id": str(new_zone_row["zone_id"]),
                    "display_label": str(new_zone_row["display_label"]),
                    "selected_lico_distance_m": float(absolute_row["absolute_lico_distance_m"]),
                    "predicted_fuel_saved_l": float(absolute_row["absolute_predicted_fuel_saved_l"]),
                    "predicted_time_lost_s": float(absolute_row["absolute_predicted_time_lost_s"]),
                    "optimization_time_lost_s": float(absolute_row["absolute_predicted_time_lost_s"]),
                    "optimization_action_cost": float(absolute_row["absolute_lico_distance_m"]),
                    "model_status": str(absolute_row.get("model_status") or ""),
                    "quality_flags": _format_quality_flags(absolute_row.get("quality_flags")),
                    "support_score": _float_or_zero(absolute_row.get("support_score")),
                    "recommended_range_start_m": None,
                    "recommended_range_end_m": None,
                    "range_selection_status": "new_zone_top_up",
                }
            )
    return sorted(combined_rows, key=lambda row: str(row["zone_id"]))


def _zone_model_inside_range(
    robust_zone_models: pl.DataFrame,
    *,
    zone_id: str,
    range_start_m: float,
    range_end_m: float,
) -> pl.DataFrame:
    return robust_zone_models.filter(
        (pl.col("zone_id") == zone_id)
        & (pl.col("lico_distance_m") >= range_start_m - 1e-9)
        & (pl.col("lico_distance_m") <= range_end_m + 1e-9)
    ).sort("lico_distance_m")


def _range_prior_map(zone_priors: pl.DataFrame | None) -> dict[str, dict[str, Any]]:
    if zone_priors is None or zone_priors.is_empty():
        return {}
    return {
        str(row["zone_id"]): row for row in zone_priors.iter_rows(named=True)
    }


def _range_top_up_allows_model_row(
    model_row: dict[str, Any],
    *,
    prior: dict[str, Any] | None,
    allowed_model_statuses: tuple[str, ...],
) -> bool:
    model_status = str(model_row.get("model_status") or "")
    if model_status not in allowed_model_statuses:
        return False
    if bool(model_row.get("is_extrapolated")):
        return False
    if prior is not None:
        if str(prior.get("strategy_role") or "") == "excluded":
            return False
        if int(prior.get("feasibility_score") or 0) == 0:
            return False
        max_distance_m = prior.get("max_lico_distance_m")
        if (
            max_distance_m is not None
            and float(model_row["lico_distance_m"]) > float(max_distance_m)
        ):
            return False
    return True


def _support_observations(
    zone_dynamics: pl.DataFrame,
    *,
    config: ExperimentalRobustOptimizerConfig,
) -> pl.DataFrame:
    if zone_dynamics.is_empty():
        return zone_dynamics
    return zone_dynamics.filter(
        (pl.col("lico_intensity").fill_null(config.baseline_intensity) != config.baseline_intensity)
        & (pl.col("has_lico"))
        & (pl.col("lico_distance_before_brake_m") > 0.0)
    )


def _support_row(
    *,
    zone_id: str,
    candidate_distance_m: float,
    support_frame: pl.DataFrame,
    comparison_row: dict[str, Any] | None,
    config: ExperimentalRobustOptimizerConfig,
) -> dict[str, Any]:
    zone_support = support_frame.filter(pl.col("zone_id") == zone_id)
    if zone_support.is_empty():
        return {
            "local_support_pass_count": 0,
            "left_support_pass_count": 0,
            "right_support_pass_count": 0,
            "nearest_observed_gap_m": candidate_distance_m,
            "tail_span_to_max_observed_m": 0.0,
            "local_mean_fuel_saved_l": 0.0,
            "local_mean_time_lost_s": 0.0,
            "local_std_fuel_saved_l": 0.0,
            "local_std_time_lost_s": 0.0,
            "dynamics_r2_improvement": _comparison_value(comparison_row, "r2_improvement") or 0.0,
            "support_score": 0.0,
            "support_penalty_fraction": config.max_fuel_penalty_fraction,
        }

    distances = [float(value) for value in zone_support["lico_distance_before_brake_m"].to_list()]
    nearest_gap_m = min(abs(distance_m - candidate_distance_m) for distance_m in distances)
    max_observed_distance_m = max(distances)
    tail_span_to_max_m = max(0.0, max_observed_distance_m - candidate_distance_m)
    local = zone_support.filter(
        (pl.col("lico_distance_before_brake_m") >= candidate_distance_m - config.support_radius_m)
        & (pl.col("lico_distance_before_brake_m") <= candidate_distance_m + config.support_radius_m)
    )
    left = zone_support.filter(
        (pl.col("lico_distance_before_brake_m") >= candidate_distance_m - config.support_radius_m)
        & (pl.col("lico_distance_before_brake_m") <= candidate_distance_m)
    )
    right = zone_support.filter(
        (pl.col("lico_distance_before_brake_m") >= candidate_distance_m)
        & (pl.col("lico_distance_before_brake_m") <= candidate_distance_m + config.support_radius_m)
    )
    local_support_pass_count = int(local.height)
    left_support_pass_count = int(left.height)
    right_support_pass_count = int(right.height)
    local_mean_fuel_saved_l = _series_stat(local, "fuel_saved_vs_baseline_l", "mean")
    local_mean_time_lost_s = _series_stat(local, "time_lost_vs_baseline_s", "mean")
    local_std_fuel_saved_l = _series_stat(local, "fuel_saved_vs_baseline_l", "std")
    local_std_time_lost_s = _series_stat(local, "time_lost_vs_baseline_s", "std")
    dynamics_r2_improvement = _comparison_value(comparison_row, "r2_improvement") or 0.0

    support_pass_factor = min(
        1.0,
        local_support_pass_count / max(config.target_support_pass_count, 1),
    )
    gap_factor = max(0.0, 1.0 - (nearest_gap_m / max(config.gap_scale_m, 1e-9)))
    tail_factor = min(1.0, tail_span_to_max_m / max(config.tail_scale_m, 1e-9))
    support_score = (
        0.45 * support_pass_factor
        + 0.35 * gap_factor
        + 0.20 * tail_factor
    )

    dynamics_penalty = min(
        config.max_fuel_penalty_fraction,
        max(dynamics_r2_improvement, 0.0) * config.dynamics_penalty_scale,
    )
    gap_penalty = config.max_fuel_penalty_fraction * (1.0 - gap_factor)
    tail_penalty = config.max_fuel_penalty_fraction * (1.0 - tail_factor) * 0.9
    support_penalty = config.max_fuel_penalty_fraction * (1.0 - support_pass_factor)
    penalty_fraction = min(
        config.max_fuel_penalty_fraction,
        0.35 * gap_penalty / max(config.max_fuel_penalty_fraction, 1e-9)
        + 0.35 * tail_penalty / max(config.max_fuel_penalty_fraction, 1e-9)
        + 0.20 * support_penalty / max(config.max_fuel_penalty_fraction, 1e-9)
        + 0.10 * dynamics_penalty / max(config.max_fuel_penalty_fraction, 1e-9),
    )

    return {
        "local_support_pass_count": local_support_pass_count,
        "left_support_pass_count": left_support_pass_count,
        "right_support_pass_count": right_support_pass_count,
        "nearest_observed_gap_m": nearest_gap_m,
        "tail_span_to_max_observed_m": tail_span_to_max_m,
        "local_mean_fuel_saved_l": local_mean_fuel_saved_l,
        "local_mean_time_lost_s": local_mean_time_lost_s,
        "local_std_fuel_saved_l": local_std_fuel_saved_l,
        "local_std_time_lost_s": local_std_time_lost_s,
        "dynamics_r2_improvement": dynamics_r2_improvement,
        "support_score": support_score,
        "support_penalty_fraction": penalty_fraction,
    }


def _series_stat(frame: pl.DataFrame, column: str, stat: str) -> float:
    if frame.is_empty():
        return 0.0
    series = frame[column].drop_nulls()
    if series.is_empty():
        return 0.0
    value = getattr(series, stat)()
    if value is None:
        return 0.0
    return float(value)


def _comparison_lookup(frame: pl.DataFrame | None) -> dict[str, dict[str, Any]]:
    if frame is None or frame.is_empty():
        return {}
    return {str(row["zone_id"]): row for row in frame.iter_rows(named=True)}


def _comparison_value(row: dict[str, Any] | None, key: str) -> float | None:
    if row is None:
        return None
    value = row.get(key)
    if value is None or value == "":
        return None
    return float(value)


def _ratio(fuel_saved_l: float, time_lost_s: float) -> float | None:
    if fuel_saved_l <= 1e-9 or time_lost_s <= 0.05:
        return None
    return fuel_saved_l / time_lost_s


def _range_tier(support_score: float) -> str:
    if support_score >= 0.8:
        return "strong"
    if support_score >= 0.6:
        return "supported"
    if support_score >= 0.45:
        return "fragile"
    return "weak"


def _closest_distance_row(frame: pl.DataFrame, selected_distance_m: float) -> dict[str, Any]:
    return (
        frame.with_columns(
            (pl.col("lico_distance_m") - selected_distance_m).abs().alias("_distance_error")
        )
        .sort("_distance_error")
        .drop("_distance_error")
        .row(0, named=True)
    )


def _contiguous_rows_around_distance(
    qualifying: pl.DataFrame,
    *,
    selected_distance_m: float,
) -> list[dict[str, Any]]:
    rows = qualifying.iter_rows(named=True)
    row_list = list(rows)
    if not row_list:
        return []
    distances = [float(row["lico_distance_m"]) for row in row_list]
    selected_index = min(
        range(len(row_list)),
        key=lambda index: abs(distances[index] - selected_distance_m),
    )
    start = selected_index
    while start > 0 and _is_gap_contiguous(row_list[start - 1], row_list[start]):
        start -= 1
    end = selected_index
    while end + 1 < len(row_list) and _is_gap_contiguous(row_list[end], row_list[end + 1]):
        end += 1
    return row_list[start : end + 1]


def _is_gap_contiguous(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return float(right["lico_distance_m"]) - float(left["lico_distance_m"]) <= 15.000001


def _first_row(frame: pl.DataFrame, zone_id: str) -> dict[str, Any] | None:
    if frame.is_empty():
        return None
    filtered = frame.filter(pl.col("zone_id") == zone_id)
    if filtered.is_empty():
        return None
    return filtered.row(0, named=True)


def _optional_float(row: dict[str, Any] | None, key: str) -> float | None:
    if row is None:
        return None
    value = row.get(key)
    if value is None or value == "":
        return None
    return float(value)


def _optional_int(row: dict[str, Any] | None, key: str) -> int | None:
    if row is None:
        return None
    value = row.get(key)
    if value is None or value == "":
        return None
    return int(value)


def _optional_string(row: dict[str, Any] | None, key: str) -> str:
    if row is None:
        return ""
    value = row.get(key)
    if value is None:
        return ""
    return str(value)


def _distance_shift(
    left_distance: float | None,
    right_distance: float | None,
) -> float | None:
    if left_distance is None or right_distance is None:
        return None
    return right_distance - left_distance


def _float_or_zero(value: Any) -> float:
    if value is None or value == "":
        return 0.0
    return float(value)


def _range_candidate_row(
    row: dict[str, Any],
    *,
    range_start_m: float,
    range_end_m: float,
) -> dict[str, Any]:
    distance_m = float(row["lico_distance_m"])
    predicted_time_lost_s = float(row["robust_predicted_time_lost_s"])
    return {
        "zone_id": str(row["zone_id"]),
        "display_label": str(row["display_label"]),
        "selected_lico_distance_m": distance_m,
        "predicted_fuel_saved_l": float(row["robust_predicted_fuel_saved_l"]),
        "predicted_time_lost_s": predicted_time_lost_s,
        "optimization_time_lost_s": predicted_time_lost_s if distance_m > 0.0 else 0.0,
        "optimization_action_cost": distance_m,
        "model_status": str(row.get("model_status") or ""),
        "quality_flags": _format_quality_flags(row.get("quality_flags")),
        "support_score": _float_or_zero(row.get("support_score")),
        "recommended_range_start_m": range_start_m,
        "recommended_range_end_m": range_end_m,
        "range_selection_status": (
            "inside_recommended_range" if distance_m > 0.0 else "zero_lico"
        ),
    }


def _range_aware_plan_frame(
    combination: tuple[dict[str, Any], ...],
    *,
    target_fuel_saved_per_lap_l: float,
    plan_status: str,
) -> pl.DataFrame:
    total_fuel = sum(row["predicted_fuel_saved_l"] for row in combination)
    total_time = sum(row["predicted_time_lost_s"] for row in combination)
    total_action = sum(row["optimization_action_cost"] for row in combination)
    rows = []
    for row in combination:
        output = dict(row)
        output.update(
            {
                "is_selected_for_lico": row["selected_lico_distance_m"] > 0.0,
                "target_fuel_saved_per_lap_l": target_fuel_saved_per_lap_l,
                "total_predicted_fuel_saved_l": total_fuel,
                "total_predicted_time_lost_s": total_time,
                "total_optimization_time_lost_s": total_time,
                "optimization_action_cost_m": row["optimization_action_cost"],
                "total_optimization_action_cost_m": total_action,
                "fuel_surplus_l": total_fuel - target_fuel_saved_per_lap_l,
                "plan_status": plan_status,
            }
        )
        rows.append(output)
    return pl.DataFrame(rows, strict=False).select(rows[0].keys() if rows else [])


def _format_quality_flags(flags: Any) -> str:
    if flags is None:
        return ""
    if isinstance(flags, str):
        return flags
    return "|".join(str(flag) for flag in flags)
