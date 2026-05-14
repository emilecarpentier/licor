from __future__ import annotations

from dataclasses import dataclass

import polars as pl

from licor.analysis.track_zones import TrackZoneTable


@dataclass(frozen=True)
class TrackZoneProposalConfig:
    lico_start_buffer_m: float = 30.0
    brake_reference_strategy: str = "earliest_push_observed"
    default_zone_end_before_next_start_m: float = 40.0
    minimum_zone_length_after_brake_m: float = 80.0
    fallback_zone_start_before_brake_m: float = 120.0


def assign_detected_zones_to_track_zones(
    braking_zones: pl.DataFrame,
    zone_table: TrackZoneTable,
) -> pl.DataFrame:
    if braking_zones.is_empty():
        return braking_zones

    ordered_zones = zone_table.zones
    assigned_rows = []
    for _, lap_zones in braking_zones.sort(
        ["lap_number", "start_lap_distance_m"]
    ).group_by("lap_number", maintain_order=True):
        for index, row in enumerate(lap_zones.iter_rows(named=True)):
            assigned = dict(row)
            assigned["detected_zone_order"] = index + 1
            if index < len(ordered_zones):
                zone = ordered_zones[index]
                assigned["zone_id"] = zone.zone_id
                assigned["turn_numbers"] = list(zone.turn_numbers)
                assigned["display_label"] = zone.display_label
                assigned["lico_eligible"] = zone.lico_eligible
            else:
                assigned["zone_id"] = None
                assigned["turn_numbers"] = []
                assigned["display_label"] = None
                assigned["lico_eligible"] = None
            assigned_rows.append(assigned)
    return pl.DataFrame(assigned_rows)


def assign_detected_zones_to_track_zones_by_reference(
    braking_zones: pl.DataFrame,
    zone_table: TrackZoneTable,
    reference_zones: pl.DataFrame,
    *,
    max_assignment_distance_m: float = 350.0,
) -> pl.DataFrame:
    if braking_zones.is_empty():
        return braking_zones

    references = _reference_rows(zone_table, reference_zones)
    assigned_rows = []
    for _, lap_zones in braking_zones.sort(
        ["lap_number", "start_lap_distance_m"]
    ).group_by("lap_number", maintain_order=True):
        used_zone_ids: set[str] = set()
        for index, row in enumerate(lap_zones.iter_rows(named=True)):
            assigned = dict(row)
            assigned["detected_zone_order"] = index + 1
            reference = _nearest_unused_reference(
                float(row["start_lap_distance_m"]),
                references,
                used_zone_ids,
                max_assignment_distance_m=max_assignment_distance_m,
            )
            if reference is None:
                assigned["zone_id"] = None
                assigned["turn_numbers"] = []
                assigned["display_label"] = None
                assigned["lico_eligible"] = None
                assigned["assignment_delta_m"] = None
            else:
                used_zone_ids.add(str(reference["zone_id"]))
                assigned["zone_id"] = reference["zone_id"]
                assigned["turn_numbers"] = reference["turn_numbers"]
                assigned["display_label"] = reference["display_label"]
                assigned["lico_eligible"] = reference["lico_eligible"]
                assigned["assignment_delta_m"] = (
                    float(row["start_lap_distance_m"])
                    - float(reference["reference_distance_m"])
                )
            assigned_rows.append(assigned)
    return pl.DataFrame(assigned_rows)


def attach_track_zones_to_lico(
    lico_zones: pl.DataFrame,
    assigned_braking_zones: pl.DataFrame,
) -> pl.DataFrame:
    if lico_zones.is_empty():
        return lico_zones
    return lico_zones.join(
        assigned_braking_zones.select(
            "brake_zone_id",
            "lap_number",
            "zone_id",
            "turn_numbers",
            "display_label",
            "lico_eligible",
        ),
        on=["brake_zone_id", "lap_number"],
        how="left",
    )


def propose_track_zone_distances(
    zone_table: TrackZoneTable,
    *,
    push_braking_zones: pl.DataFrame,
    high_lico_zones: pl.DataFrame,
    config: TrackZoneProposalConfig | None = None,
) -> pl.DataFrame:
    proposal_config = config or TrackZoneProposalConfig()
    push_refs = _push_brake_references(push_braking_zones)
    high_refs = _high_lico_references(high_lico_zones, config=proposal_config)

    rows = []
    for zone in zone_table.zones:
        push = push_refs.get(zone.zone_id, {})
        high = high_refs.get(zone.zone_id, {})
        proposed_brake_reference_m = push.get("proposed_brake_reference_m")
        proposed_lico_window_start_m = high.get("proposed_lico_window_start_m")
        if zone.lico_eligible is False:
            proposed_lico_window_start_m = None
        elif proposed_lico_window_start_m is None and proposed_brake_reference_m is not None:
            proposed_lico_window_start_m = max(
                0.0,
                float(proposed_brake_reference_m)
                - proposal_config.fallback_zone_start_before_brake_m,
            )

        rows.append(
            {
                "zone_id": zone.zone_id,
                "turn_numbers": list(zone.turn_numbers),
                "display_label": zone.display_label,
                "lico_eligible": zone.lico_eligible,
                "proposed_brake_reference_m": proposed_brake_reference_m,
                "push_brake_reference_min_m": push.get("push_brake_reference_min_m"),
                "push_brake_reference_median_m": push.get(
                    "push_brake_reference_median_m"
                ),
                "push_observation_count": push.get("push_observation_count", 0),
                "high_lico_start_min_m": high.get("high_lico_start_min_m"),
                "proposed_lico_window_start_m": proposed_lico_window_start_m,
                "high_lico_observation_count": high.get(
                    "high_lico_observation_count", 0
                ),
                "proposal_status": _proposal_status(
                    zone.lico_eligible,
                    proposed_brake_reference_m,
                    proposed_lico_window_start_m,
                ),
            }
        )
    return _with_proposed_end_distances(pl.DataFrame(rows), config=proposal_config)


def _with_proposed_end_distances(
    proposals: pl.DataFrame,
    *,
    config: TrackZoneProposalConfig,
) -> pl.DataFrame:
    if proposals.is_empty():
        return proposals

    ordered_rows = proposals.iter_rows(named=True)
    rows = [dict(row) for row in ordered_rows]
    for index, row in enumerate(rows):
        next_start = _next_zone_start(rows, index)
        brake_reference = row.get("proposed_brake_reference_m")
        minimum_end = (
            float(brake_reference) + config.minimum_zone_length_after_brake_m
            if brake_reference is not None
            else None
        )
        proposed_end = (
            next_start - config.default_zone_end_before_next_start_m
            if next_start is not None
            else None
        )
        if minimum_end is not None and proposed_end is not None:
            proposed_end = max(proposed_end, minimum_end)
        elif minimum_end is not None:
            proposed_end = minimum_end

        row["proposed_end_distance_m"] = proposed_end
        row["end_proposal_status"] = (
            "proposed_from_next_zone"
            if next_start is not None
            else "needs_manual_review"
        )
    return pl.DataFrame(rows)


def _next_zone_start(rows: list[dict[str, object]], index: int) -> float | None:
    for next_row in rows[index + 1 :]:
        start = next_row.get("proposed_lico_window_start_m")
        brake = next_row.get("proposed_brake_reference_m")
        candidates = [value for value in (start, brake) if value is not None]
        if candidates:
            return float(min(candidates))
    return None


def _push_brake_references(braking_zones: pl.DataFrame) -> dict[str, dict[str, float | int]]:
    if braking_zones.is_empty():
        return {}
    grouped = braking_zones.filter(pl.col("zone_id").is_not_null()).group_by("zone_id").agg(
        pl.col("start_lap_distance_m").min().alias("push_brake_reference_min_m"),
        pl.col("start_lap_distance_m").median().alias("push_brake_reference_median_m"),
        pl.len().alias("push_observation_count"),
    )
    return {
        str(row["zone_id"]): {
            "proposed_brake_reference_m": float(row["push_brake_reference_min_m"]),
            "push_brake_reference_min_m": float(row["push_brake_reference_min_m"]),
            "push_brake_reference_median_m": float(row["push_brake_reference_median_m"]),
            "push_observation_count": int(row["push_observation_count"]),
        }
        for row in grouped.iter_rows(named=True)
    }


def _reference_rows(
    zone_table: TrackZoneTable,
    reference_zones: pl.DataFrame,
) -> list[dict[str, object]]:
    if reference_zones.is_empty():
        return []
    reference_by_zone = {
        str(row["zone_id"]): float(row["proposed_brake_reference_m"])
        for row in reference_zones.filter(
            pl.col("zone_id").is_not_null()
            & pl.col("proposed_brake_reference_m").is_not_null()
        ).iter_rows(named=True)
    }
    rows = []
    for zone in zone_table.zones:
        reference = reference_by_zone.get(zone.zone_id)
        if reference is None:
            continue
        rows.append(
            {
                "zone_id": zone.zone_id,
                "turn_numbers": list(zone.turn_numbers),
                "display_label": zone.display_label,
                "lico_eligible": zone.lico_eligible,
                "reference_distance_m": reference,
            }
        )
    return rows


def _nearest_unused_reference(
    distance_m: float,
    references: list[dict[str, object]],
    used_zone_ids: set[str],
    *,
    max_assignment_distance_m: float,
) -> dict[str, object] | None:
    candidates = [
        reference
        for reference in references
        if str(reference["zone_id"]) not in used_zone_ids
    ]
    if not candidates:
        return None
    nearest = min(
        candidates,
        key=lambda reference: abs(distance_m - float(reference["reference_distance_m"])),
    )
    if abs(distance_m - float(nearest["reference_distance_m"])) > max_assignment_distance_m:
        return None
    return nearest


def _high_lico_references(
    lico_zones: pl.DataFrame,
    *,
    config: TrackZoneProposalConfig,
) -> dict[str, dict[str, float | int]]:
    if lico_zones.is_empty() or "zone_id" not in lico_zones.columns:
        return {}
    grouped = (
        lico_zones.filter(pl.col("zone_id").is_not_null() & pl.col("has_lico"))
        .group_by("zone_id")
        .agg(
            pl.col("lico_start_m").min().alias("high_lico_start_min_m"),
            pl.len().alias("high_lico_observation_count"),
        )
    )
    return {
        str(row["zone_id"]): {
            "high_lico_start_min_m": float(row["high_lico_start_min_m"]),
            "proposed_lico_window_start_m": max(
                0.0,
                float(row["high_lico_start_min_m"]) - config.lico_start_buffer_m,
            ),
            "high_lico_observation_count": int(row["high_lico_observation_count"]),
        }
        for row in grouped.iter_rows(named=True)
    }


def _proposal_status(
    lico_eligible: bool | None,
    brake_reference_m: float | None,
    lico_window_start_m: float | None,
) -> str:
    if lico_eligible is None:
        return "needs_lico_eligibility_review"
    if brake_reference_m is None:
        return "missing_push_reference"
    if lico_eligible is False:
        return "non_candidate_ready_for_manual_end"
    if lico_window_start_m is None:
        return "missing_high_lico_reference"
    return "ready_for_manual_end"
