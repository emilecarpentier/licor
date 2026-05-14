from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

import polars as pl
from pydantic import BaseModel, Field


ZoneReviewStatus = Literal["draft", "needs_driver_review", "driver_reviewed"]
ZoneOptimizationRole = Literal[
    "candidate",
    "validation_only",
    "excluded",
    "needs_driver_review",
]
ValidationEndRule = Literal[
    "manual_distance",
    "stable_full_throttle",
    "driver_review_needed",
]


class TrackZoneDefinition(BaseModel):
    zone_id: str
    turn_numbers: tuple[int, ...] = Field(default_factory=tuple)
    display_label: str
    start_distance_m: float | None = None
    lico_window_start_m: float | None = None
    brake_reference_m: float | None = None
    end_distance_m: float | None = None
    lico_eligible: bool | None = None
    optimization_role: ZoneOptimizationRole = "needs_driver_review"
    validation_end_rule: ValidationEndRule = "driver_review_needed"
    review_status: ZoneReviewStatus = "needs_driver_review"
    notes: str = ""

    def is_complete(self) -> bool:
        return not self.validation_issues()

    def validation_issues(self) -> list[str]:
        issues = []
        if not self.turn_numbers:
            issues.append("missing_turn_numbers")
        if self.start_distance_m is None:
            issues.append("missing_start_distance_m")
        if self.brake_reference_m is None:
            issues.append("missing_brake_reference_m")
        if self.end_distance_m is None:
            issues.append("missing_end_distance_m")
        if self.lico_eligible is None:
            issues.append("missing_lico_eligible")
        if self.lico_eligible and self.lico_window_start_m is None:
            issues.append("missing_lico_window_start_m")
        if self.optimization_role == "candidate" and self.lico_eligible is not True:
            issues.append("candidate_must_be_lico_eligible")
        if self.optimization_role in {"validation_only", "excluded"} and self.lico_eligible:
            issues.append("non_candidate_should_not_be_lico_eligible")
        issues.extend(self._distance_order_issues())
        return issues

    def _distance_order_issues(self) -> list[str]:
        issues = []
        if (
            self.start_distance_m is not None
            and self.brake_reference_m is not None
            and self.start_distance_m > self.brake_reference_m
        ):
            issues.append("start_after_brake_reference")
        if (
            self.brake_reference_m is not None
            and self.end_distance_m is not None
            and self.brake_reference_m > self.end_distance_m
        ):
            issues.append("brake_reference_after_end")
        if self.lico_window_start_m is not None:
            if (
                self.start_distance_m is not None
                and self.start_distance_m > self.lico_window_start_m
            ):
                issues.append("start_after_lico_window_start")
            if (
                self.brake_reference_m is not None
                and self.lico_window_start_m > self.brake_reference_m
            ):
                issues.append("lico_window_start_after_brake_reference")
        return issues


class TrackZoneTable(BaseModel):
    schema_version: int = 1
    track_name: str
    car_class: str
    distance_unit: Literal["m"] = "m"
    status: ZoneReviewStatus = "needs_driver_review"
    source: str = ""
    zones: list[TrackZoneDefinition] = Field(default_factory=list)

    def validation_issues(self) -> dict[str, list[str]]:
        issues = {}
        seen_zone_ids = set()
        seen_turns = set()
        duplicate_zone_ids = set()
        duplicate_turns = set()
        for zone in self.zones:
            if zone.zone_id in seen_zone_ids:
                duplicate_zone_ids.add(zone.zone_id)
            seen_zone_ids.add(zone.zone_id)
            for turn_number in zone.turn_numbers:
                if turn_number in seen_turns:
                    duplicate_turns.add(turn_number)
                seen_turns.add(turn_number)
            zone_issues = zone.validation_issues()
            if zone_issues:
                issues[zone.zone_id] = zone_issues
        if duplicate_zone_ids:
            issues["_table"] = [
                f"duplicate_zone_id:{zone_id}" for zone_id in sorted(duplicate_zone_ids)
            ]
        if duplicate_turns:
            issues.setdefault("_table", []).extend(
                f"duplicate_turn_number:{turn_number}"
                for turn_number in sorted(duplicate_turns)
            )
        return issues

    def complete_zones(self) -> list[TrackZoneDefinition]:
        return [zone for zone in self.zones if zone.is_complete()]


def load_track_zone_table(path: str | Path) -> TrackZoneTable:
    with Path(path).open(encoding="utf-8") as file:
        return TrackZoneTable.model_validate(json.load(file))


def track_zones_to_frame(table: TrackZoneTable) -> pl.DataFrame:
    return pl.DataFrame([zone.model_dump() for zone in table.zones])
