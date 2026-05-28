from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

import polars as pl


@dataclass(frozen=True)
class ExperimentalZoneDynamicsDriverReviewConfig:
    baseline_intensity: str = "none"
    strong_brake_later_correlation: float = 0.45
    strong_entry_speed_correlation: float = -0.75
    apex_hold_delta_kph: float = -0.5
    apex_improve_delta_kph: float = 0.5
    apex_fragile_delta_kph: float = -1.0
    exit_hold_delta_kph: float = -0.5
    exit_fragile_delta_kph: float = -0.75
    low_time_cost_s: float = 0.05
    moderate_time_cost_s: float = 0.09
    material_r2_improvement: float = 0.15
    tyre_relief_delta_c: float = -3.0


def summarize_experimental_zone_dynamics_driver_review(
    zone_dynamics: pl.DataFrame,
    *,
    model_comparison: pl.DataFrame | None = None,
    current_zone_status: pl.DataFrame | None = None,
    config: ExperimentalZoneDynamicsDriverReviewConfig | None = None,
) -> pl.DataFrame:
    """Summarize experimental zone dynamics into driver-facing verdicts."""

    review_config = config or ExperimentalZoneDynamicsDriverReviewConfig()
    if zone_dynamics.is_empty():
        return pl.DataFrame()

    focus = zone_dynamics.filter(
        pl.col("lico_intensity").fill_null(review_config.baseline_intensity)
        != review_config.baseline_intensity
    )
    if focus.is_empty():
        return pl.DataFrame()

    model_lookup = _row_lookup(model_comparison)
    status_lookup = _row_lookup(current_zone_status)

    rows = []
    for zone in (
        focus.select("zone_id", "display_label")
        .unique(subset=["zone_id"], keep="first")
        .sort("zone_id")
        .iter_rows(named=True)
    ):
        zone_id = str(zone["zone_id"])
        zone_frame = focus.filter(pl.col("zone_id") == zone_id)
        rows.append(
            _build_review_row(
                zone_frame,
                zone_info=zone,
                model_row=model_lookup.get(zone_id),
                status_row=status_lookup.get(zone_id),
                config=review_config,
            )
        )

    return pl.from_dicts(rows).sort("zone_id")


def _build_review_row(
    zone_frame: pl.DataFrame,
    *,
    zone_info: dict[str, Any],
    model_row: dict[str, Any] | None,
    status_row: dict[str, Any] | None,
    config: ExperimentalZoneDynamicsDriverReviewConfig,
) -> dict[str, Any]:
    zone_id = str(zone_info["zone_id"])
    display_label = str(zone_info.get("display_label") or zone_id)

    mean_fuel_saved_l = _safe_mean(zone_frame["fuel_saved_vs_baseline_l"].to_list())
    mean_time_lost_s = _safe_mean(zone_frame["time_lost_vs_baseline_s"].to_list())
    mean_brake_delta_m = _safe_mean(
        zone_frame["brake_start_delta_vs_baseline_m"].to_list()
    )
    mean_brake_speed_delta_kph = _safe_mean(
        zone_frame["brake_start_speed_delta_vs_baseline_kph"].to_list()
    )
    mean_apex_delta_kph = _safe_mean(zone_frame["apex_speed_delta_vs_baseline_kph"].to_list())
    mean_exit_delta_kph = _safe_mean(zone_frame["exit_speed_delta_vs_baseline_kph"].to_list())
    mean_temp_delta_c = _safe_mean(
        zone_frame["carcass_temp_zone_start_delta_vs_baseline_c"].to_list()
    )
    min_distance_m = _safe_min(zone_frame["lico_distance_before_brake_m"].to_list())
    max_distance_m = _safe_max(zone_frame["lico_distance_before_brake_m"].to_list())

    corr_lico_brake_delta = _safe_correlation(
        zone_frame["lico_distance_before_brake_m"].to_list(),
        zone_frame["brake_start_delta_vs_baseline_m"].to_list(),
    )
    corr_lico_brake_speed_delta = _safe_correlation(
        zone_frame["lico_distance_before_brake_m"].to_list(),
        zone_frame["brake_start_speed_delta_vs_baseline_kph"].to_list(),
    )
    corr_lico_apex_delta = _safe_correlation(
        zone_frame["lico_distance_before_brake_m"].to_list(),
        zone_frame["apex_speed_delta_vs_baseline_kph"].to_list(),
    )
    corr_lico_exit_delta = _safe_correlation(
        zone_frame["lico_distance_before_brake_m"].to_list(),
        zone_frame["exit_speed_delta_vs_baseline_kph"].to_list(),
    )
    corr_lico_time_lost = _safe_correlation(
        zone_frame["lico_distance_before_brake_m"].to_list(),
        zone_frame["time_lost_vs_baseline_s"].to_list(),
    )
    corr_brake_delta_apex = _safe_correlation(
        zone_frame["brake_start_delta_vs_baseline_m"].to_list(),
        zone_frame["apex_speed_delta_vs_baseline_kph"].to_list(),
    )
    corr_apex_time_lost = _safe_correlation(
        zone_frame["apex_speed_delta_vs_baseline_kph"].to_list(),
        zone_frame["time_lost_vs_baseline_s"].to_list(),
    )

    current_model_status = _string_or_empty(status_row, "current_model_status")
    current_quality_flags = _string_or_empty(status_row, "current_quality_flags")
    direct_r2 = _float_or_none(model_row, "direct_r2")
    dynamics_r2 = _float_or_none(model_row, "dynamics_r2")
    r2_improvement = _float_or_none(model_row, "r2_improvement")
    model_recommendation = _string_or_empty(model_row, "recommendation")

    brake_later_clear = (
        corr_lico_brake_delta is not None
        and corr_lico_brake_delta >= config.strong_brake_later_correlation
        and mean_brake_delta_m is not None
        and mean_brake_delta_m >= 1.0
    )
    approach_slower_clear = (
        corr_lico_brake_speed_delta is not None
        and corr_lico_brake_speed_delta <= config.strong_entry_speed_correlation
        and mean_brake_speed_delta_kph is not None
        and mean_brake_speed_delta_kph <= -4.0
    )
    apex_improves = (
        mean_apex_delta_kph is not None
        and mean_apex_delta_kph >= config.apex_improve_delta_kph
    )
    apex_holds = (
        mean_apex_delta_kph is not None
        and mean_apex_delta_kph >= config.apex_hold_delta_kph
    )
    apex_fragile = (
        mean_apex_delta_kph is not None
        and mean_apex_delta_kph <= config.apex_fragile_delta_kph
    ) or (
        corr_lico_apex_delta is not None and corr_lico_apex_delta <= -0.2
    )
    exit_holds = (
        mean_exit_delta_kph is not None
        and mean_exit_delta_kph >= config.exit_hold_delta_kph
    )
    exit_fragile = (
        mean_exit_delta_kph is not None
        and mean_exit_delta_kph <= config.exit_fragile_delta_kph
    ) or (
        corr_lico_exit_delta is not None
        and corr_lico_exit_delta <= -0.35
        and mean_exit_delta_kph is not None
        and mean_exit_delta_kph <= config.exit_hold_delta_kph
    )
    dynamics_matter_materially = (
        r2_improvement is not None
        and r2_improvement >= config.material_r2_improvement
    )
    tyre_relief_present = (
        mean_temp_delta_c is not None and mean_temp_delta_c <= config.tyre_relief_delta_c
    )

    primary_label = _primary_label(
        brake_later_clear=brake_later_clear,
        approach_slower_clear=approach_slower_clear,
        apex_improves=apex_improves,
        apex_fragile=apex_fragile,
        exit_holds=exit_holds,
        exit_fragile=exit_fragile,
    )
    secondary_label = _secondary_label(
        dynamics_matter_materially=dynamics_matter_materially,
        mean_time_lost_s=mean_time_lost_s,
        tyre_relief_present=tyre_relief_present,
        config=config,
    )

    driver_summary = _driver_summary(
        display_label=display_label,
        brake_later_clear=brake_later_clear,
        approach_slower_clear=approach_slower_clear,
        apex_improves=apex_improves,
        apex_holds=apex_holds,
        apex_fragile=apex_fragile,
        exit_holds=exit_holds,
        exit_fragile=exit_fragile,
        dynamics_matter_materially=dynamics_matter_materially,
        tyre_relief_present=tyre_relief_present,
    )
    pilot_takeaway = _pilot_takeaway(
        primary_label=primary_label,
        secondary_label=secondary_label,
        current_model_status=current_model_status,
    )

    return {
        "zone_id": zone_id,
        "display_label": display_label,
        "pass_count": zone_frame.height,
        "min_lico_distance_before_brake_m": min_distance_m,
        "max_lico_distance_before_brake_m": max_distance_m,
        "mean_fuel_saved_vs_baseline_l": mean_fuel_saved_l,
        "mean_time_lost_vs_baseline_s": mean_time_lost_s,
        "mean_brake_start_delta_vs_baseline_m": mean_brake_delta_m,
        "mean_brake_start_speed_delta_vs_baseline_kph": mean_brake_speed_delta_kph,
        "mean_apex_speed_delta_vs_baseline_kph": mean_apex_delta_kph,
        "mean_exit_speed_delta_vs_baseline_kph": mean_exit_delta_kph,
        "mean_carcass_temp_zone_start_delta_vs_baseline_c": mean_temp_delta_c,
        "corr_lico_brake_start_delta": corr_lico_brake_delta,
        "corr_lico_brake_start_speed_delta": corr_lico_brake_speed_delta,
        "corr_lico_apex_speed_delta": corr_lico_apex_delta,
        "corr_lico_exit_speed_delta": corr_lico_exit_delta,
        "corr_lico_time_lost": corr_lico_time_lost,
        "corr_brake_start_delta_apex_speed": corr_brake_delta_apex,
        "corr_apex_speed_time_lost": corr_apex_time_lost,
        "current_model_status": current_model_status,
        "current_quality_flags": current_quality_flags,
        "direct_r2": direct_r2,
        "dynamics_r2": dynamics_r2,
        "r2_improvement": r2_improvement,
        "model_recommendation": model_recommendation,
        "primary_review_label": primary_label,
        "secondary_review_label": secondary_label,
        "driver_summary": driver_summary,
        "pilot_takeaway": pilot_takeaway,
    }


def _primary_label(
    *,
    brake_later_clear: bool,
    approach_slower_clear: bool,
    apex_improves: bool,
    apex_fragile: bool,
    exit_holds: bool,
    exit_fragile: bool,
) -> str:
    if not brake_later_clear or not approach_slower_clear:
        return "limited_entry_conversion"
    if apex_fragile and exit_fragile:
        return "corner_state_degrades"
    if apex_fragile:
        return "apex_penalized"
    if exit_fragile:
        return "exit_fragile"
    if apex_improves and exit_holds:
        return "structurally_favorable"
    return "entry_compensation_successful"


def _secondary_label(
    *,
    dynamics_matter_materially: bool,
    mean_time_lost_s: float | None,
    tyre_relief_present: bool,
    config: ExperimentalZoneDynamicsDriverReviewConfig,
) -> str:
    if dynamics_matter_materially:
        return "dynamics_matter_materially"
    if tyre_relief_present:
        return "tyre_relief_present"
    if mean_time_lost_s is None:
        return "time_signal_needs_context"
    if mean_time_lost_s <= config.low_time_cost_s:
        return "low_time_cost"
    if mean_time_lost_s <= config.moderate_time_cost_s:
        return "moderate_time_cost"
    return "time_cost_sensitive"


def _driver_summary(
    *,
    display_label: str,
    brake_later_clear: bool,
    approach_slower_clear: bool,
    apex_improves: bool,
    apex_holds: bool,
    apex_fragile: bool,
    exit_holds: bool,
    exit_fragile: bool,
    dynamics_matter_materially: bool,
    tyre_relief_present: bool,
) -> str:
    if brake_later_clear and approach_slower_clear:
        first = (
            f"{display_label}: more LICO clearly lowers arrival speed and moves braking later."
        )
    elif brake_later_clear:
        first = (
            f"{display_label}: more LICO usually moves braking later, but the arrival-speed pattern is less stable."
        )
    else:
        first = (
            f"{display_label}: the entry-compensation pattern is weak, so the raw time signal stays hard to trust."
        )

    if apex_improves and exit_holds:
        second = (
            " Apex and exit speed mostly hold, so the zone converts entry relief into usable corner performance."
        )
    elif apex_holds and exit_holds:
        second = " Apex and exit speed mostly hold, so the zone looks human-usable."
    elif apex_fragile:
        second = (
            " Apex speed drops, which suggests part of the observed cost comes from adaptation through the corner."
        )
    elif exit_fragile:
        second = (
            " Exit speed is fragile, so some of the cost appears to move downstream rather than disappear."
        )
    else:
        second = " Apex and exit behavior are mixed, so this zone still needs contextual reading."

    if dynamics_matter_materially and tyre_relief_present:
        third = (
            " The dynamics-aware model adds material explanatory power, and cooler tyres are likely helping some of the cleaner outcomes."
        )
    elif dynamics_matter_materially:
        third = (
            " The dynamics-aware model explains materially more variance than the direct 1D view."
        )
    elif tyre_relief_present:
        third = (
            " Cooler tyres are present in these passes and may still be helping the better local outcomes."
        )
    else:
        third = ""

    return f"{first}{second}{third}"


def _pilot_takeaway(
    *,
    primary_label: str,
    secondary_label: str,
    current_model_status: str,
) -> str:
    if primary_label == "structurally_favorable":
        return "Strong zone for deliberate LICO once the distance choice is calibrated."
    if primary_label == "entry_compensation_successful":
        return "Coherent zone: judge it mostly by where apex and exit stay stable."
    if primary_label == "apex_penalized":
        return "Promising zone, but adaptation through the corner still matters more than the raw LICO distance."
    if primary_label == "exit_fragile":
        return "Use care here: apparent entry gains can leak into the next phase of the corner."
    if primary_label == "corner_state_degrades":
        return "Keep this zone conservative until a later model can separate human adaptation from true cost."
    if current_model_status == "diagnostic_only" or secondary_label == "dynamics_matter_materially":
        return "Review this zone with the dynamics report before trusting a single optimum point."
    return "The current evidence is still too weak to treat this zone as a clean optimization surface."


def _row_lookup(frame: pl.DataFrame | None) -> dict[str, dict[str, Any]]:
    if frame is None or frame.is_empty() or "zone_id" not in frame.columns:
        return {}
    return {
        str(row["zone_id"]): row
        for row in frame.unique(subset=["zone_id"], keep="first").iter_rows(named=True)
    }


def _float_or_none(row: dict[str, Any] | None, key: str) -> float | None:
    if row is None:
        return None
    value = row.get(key)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _string_or_empty(row: dict[str, Any] | None, key: str) -> str:
    if row is None:
        return ""
    value = row.get(key)
    if value is None:
        return ""
    if isinstance(value, list):
        return "|".join(str(item) for item in value)
    return str(value)


def _safe_mean(values: list[object]) -> float | None:
    numbers = [float(value) for value in values if value is not None]
    if not numbers:
        return None
    return sum(numbers) / len(numbers)


def _safe_min(values: list[object]) -> float | None:
    numbers = [float(value) for value in values if value is not None]
    if not numbers:
        return None
    return min(numbers)


def _safe_max(values: list[object]) -> float | None:
    numbers = [float(value) for value in values if value is not None]
    if not numbers:
        return None
    return max(numbers)


def _safe_correlation(x_values: list[object], y_values: list[object]) -> float | None:
    pairs = [
        (float(x_value), float(y_value))
        for x_value, y_value in zip(x_values, y_values, strict=False)
        if x_value is not None and y_value is not None
    ]
    if len(pairs) < 2:
        return None

    x_mean = sum(x_value for x_value, _ in pairs) / len(pairs)
    y_mean = sum(y_value for _, y_value in pairs) / len(pairs)
    numerator = sum(
        (x_value - x_mean) * (y_value - y_mean) for x_value, y_value in pairs
    )
    x_scale = math.sqrt(sum((x_value - x_mean) ** 2 for x_value, _ in pairs))
    y_scale = math.sqrt(sum((y_value - y_mean) ** 2 for _, y_value in pairs))
    if x_scale <= 1e-12 or y_scale <= 1e-12:
        return None
    return numerator / (x_scale * y_scale)
