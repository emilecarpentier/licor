from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import polars as pl


@dataclass(frozen=True)
class ExperimentalZoneReclassificationRule:
    zone_id: str
    experimental_model_status: str
    rationale: str
    max_lico_distance_m_override: float | None = None
    allow_diagnostic_model_override: bool | None = None


@dataclass(frozen=True)
class ExperimentalZoneReclassificationConfig:
    micro_lico_status: str = "micro_lico_only"
    micro_lico_default_cap_m: float = 20.0
    rules: tuple[ExperimentalZoneReclassificationRule, ...] = (
        ExperimentalZoneReclassificationRule(
            zone_id="spa_t01",
            experimental_model_status="model_ready",
            rationale=(
                "Promote from diagnostic_only: the dynamics review is coherent, and the "
                "remaining noise is consistent with multiple valid entry styles."
            ),
        ),
        ExperimentalZoneReclassificationRule(
            zone_id="spa_t08",
            experimental_model_status="model_ready",
            rationale=(
                "Promote from diagnostic_only: recalibrated zone start plus the dynamics "
                "review now tell a coherent entry-to-apex story."
            ),
        ),
        ExperimentalZoneReclassificationRule(
            zone_id="spa_t12_t13",
            experimental_model_status="model_ready",
            rationale=(
                "Promote from diagnostic_only: the zone now presents a coherent dynamics "
                "signal and should be treated as experimental model-ready."
            ),
        ),
        ExperimentalZoneReclassificationRule(
            zone_id="spa_t14",
            experimental_model_status="micro_lico_only",
            max_lico_distance_m_override=20.0,
            allow_diagnostic_model_override=False,
            rationale=(
                "Reclassify as micro-LICO only: the zone is usable, but only for very "
                "small pre-brake lift distances."
            ),
        ),
    )


def summarize_experimental_zone_reclassification(
    zone_models: pl.DataFrame,
    *,
    config: ExperimentalZoneReclassificationConfig | None = None,
) -> pl.DataFrame:
    """Return one row per zone describing the experimental reclassification policy."""

    review_config = config or ExperimentalZoneReclassificationConfig()
    if zone_models.is_empty():
        return pl.DataFrame()

    rule_map = {rule.zone_id: rule for rule in review_config.rules}
    rows = []
    for row in (
        zone_models.select("zone_id", "display_label", "model_status", "quality_flags")
        .unique(subset=["zone_id"], keep="first")
        .sort("zone_id")
        .iter_rows(named=True)
    ):
        zone_id = str(row["zone_id"])
        base_status = str(row["model_status"])
        rule = rule_map.get(zone_id)
        experimental_status = (
            rule.experimental_model_status if rule is not None else base_status
        )
        rows.append(
            {
                "zone_id": zone_id,
                "display_label": str(row["display_label"]),
                "base_model_status": base_status,
                "experimental_model_status": experimental_status,
                "reclassification_action": _reclassification_action(
                    base_status,
                    experimental_status,
                    config=review_config,
                ),
                "max_lico_distance_m_override": (
                    rule.max_lico_distance_m_override if rule is not None else None
                ),
                "allow_diagnostic_model_override": (
                    rule.allow_diagnostic_model_override if rule is not None else None
                ),
                "quality_flags": _format_quality_flags(row.get("quality_flags")),
                "reclassification_rationale": rule.rationale if rule is not None else "",
            }
        )

    return pl.DataFrame(rows).sort("zone_id")


def apply_experimental_zone_reclassification(
    zone_models: pl.DataFrame,
    reclassification: pl.DataFrame,
) -> pl.DataFrame:
    """Apply experimental model-status overrides to a zone-model table."""

    if zone_models.is_empty() or reclassification.is_empty():
        return zone_models

    reclassification_map = _row_lookup(reclassification)
    rows = []
    for row in zone_models.iter_rows(named=True):
        zone_id = str(row["zone_id"])
        override = reclassification_map.get(zone_id)
        experimental_status = (
            str(override["experimental_model_status"])
            if override is not None
            else str(row["model_status"])
        )
        base_status = str(row["model_status"])
        quality_flags = _quality_flags_with_reclassification(
            row.get("quality_flags"),
            base_status=base_status,
            experimental_status=experimental_status,
        )
        output = dict(row)
        output.update(
            {
                "base_model_status": base_status,
                "model_status": experimental_status,
                "experimental_model_status": experimental_status,
                "reclassification_action": (
                    str(override["reclassification_action"]) if override is not None else "unchanged"
                ),
                "reclassification_rationale": (
                    str(override["reclassification_rationale"]) if override is not None else ""
                ),
                "quality_flags": quality_flags,
            }
        )
        rows.append(output)

    return pl.DataFrame(rows, strict=False).select(rows[0].keys() if rows else zone_models.columns)


def apply_experimental_strategy_prior_overrides(
    zone_priors: pl.DataFrame,
    reclassification: pl.DataFrame,
    *,
    config: ExperimentalZoneReclassificationConfig | None = None,
) -> pl.DataFrame:
    """Apply experimental prior overrides such as micro-LICO caps."""

    review_config = config or ExperimentalZoneReclassificationConfig()
    if zone_priors.is_empty():
        return zone_priors

    reclassification_map = _row_lookup(reclassification)
    rows = []
    for row in zone_priors.iter_rows(named=True):
        zone_id = str(row["zone_id"])
        override = reclassification_map.get(zone_id)
        output = dict(row)
        output["base_allow_diagnostic_model"] = bool(row.get("allow_diagnostic_model"))
        output["base_max_lico_distance_m"] = row.get("max_lico_distance_m")
        if override is not None:
            experimental_status = str(override["experimental_model_status"])
            allow_override = override.get("allow_diagnostic_model_override")
            distance_override = override.get("max_lico_distance_m_override")
            if allow_override is not None:
                output["allow_diagnostic_model"] = bool(allow_override)
            if distance_override is not None:
                output["max_lico_distance_m"] = float(distance_override)
            elif (
                experimental_status == review_config.micro_lico_status
                and output.get("max_lico_distance_m") is None
            ):
                output["max_lico_distance_m"] = review_config.micro_lico_default_cap_m
            rationale = str(override.get("reclassification_rationale") or "")
            if rationale:
                notes = str(output.get("notes") or "")
                output["notes"] = (
                    f"{notes} Experimental reclassification: {rationale}".strip()
                )
        rows.append(output)

    return pl.DataFrame(rows, strict=False).select(rows[0].keys() if rows else zone_priors.columns)


def build_experimental_status_frame(
    reclassified_zone_models: pl.DataFrame,
) -> pl.DataFrame:
    """Return one row per zone for downstream experimental status-aware reports."""

    if reclassified_zone_models.is_empty():
        return pl.DataFrame()
    return (
        reclassified_zone_models.group_by("zone_id")
        .agg(
            pl.col("display_label").first().alias("display_label"),
            pl.col("base_model_status").first().alias("base_model_status"),
            pl.col("experimental_model_status").first().alias("current_model_status"),
            pl.col("quality_flags").first().alias("current_quality_flags"),
            pl.col("reclassification_action").first().alias("reclassification_action"),
            pl.col("reclassification_rationale").first().alias("reclassification_rationale"),
        )
        .sort("zone_id")
    )


def _reclassification_action(
    base_status: str,
    experimental_status: str,
    *,
    config: ExperimentalZoneReclassificationConfig,
) -> str:
    if base_status == experimental_status:
        return "unchanged"
    if experimental_status == "model_ready":
        return "promoted_to_model_ready"
    if experimental_status == config.micro_lico_status:
        return "reclassified_to_micro_lico_only"
    return "reclassified"


def _quality_flags_with_reclassification(
    flags: Any,
    *,
    base_status: str,
    experimental_status: str,
) -> list[str]:
    values = _quality_flag_list(flags)
    if experimental_status == "model_ready" and base_status != "model_ready":
        values.append(f"experimental_promoted_from_{base_status}")
    if experimental_status == "micro_lico_only":
        values.append("experimental_micro_lico_only")
    return sorted(set(values))


def _quality_flag_list(flags: Any) -> list[str]:
    if flags is None:
        return []
    if isinstance(flags, list):
        return [str(flag) for flag in flags]
    if isinstance(flags, str):
        if not flags:
            return []
        return [flag for flag in flags.split("|") if flag]
    return [str(flag) for flag in flags]


def _format_quality_flags(flags: Any) -> str:
    return "|".join(_quality_flag_list(flags))


def _row_lookup(frame: pl.DataFrame) -> dict[str, dict[str, Any]]:
    return {
        str(row["zone_id"]): row
        for row in frame.iter_rows(named=True)
    }
