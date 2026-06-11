from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

import polars as pl
from pydantic import BaseModel, Field, field_validator, model_validator

from licor.analysis.track_zones import TrackZoneDefinition, TrackZoneTable


StrategyRole = Literal["preferred", "usable", "limited", "excluded"]


class ZoneStrategyPrior(BaseModel):
    zone_id: str
    display_label: str = ""
    feasibility_score: int = Field(ge=0, le=5)
    strategy_role: StrategyRole
    allow_diagnostic_model: bool = False
    max_lico_distance_m: float | None = Field(default=None, gt=0.0)
    notes: str = ""

    @field_validator("strategy_role")
    @classmethod
    def excluded_role_must_match_zero_score(
        cls,
        strategy_role: StrategyRole,
        info,
    ) -> StrategyRole:
        feasibility_score = info.data.get("feasibility_score")
        if feasibility_score == 0 and strategy_role != "excluded":
            raise ValueError("0/5 feasibility zones must use strategy_role='excluded'")
        return strategy_role


class StrategyPriorTable(BaseModel):
    schema_version: int = 1
    dataset_id: str
    track_name: str
    car_class: str
    notes: str = ""
    zones: list[ZoneStrategyPrior] = Field(default_factory=list)

    @model_validator(mode="after")
    def zone_ids_must_be_unique(self) -> StrategyPriorTable:
        zone_ids = [zone.zone_id for zone in self.zones]
        if len(zone_ids) != len(set(zone_ids)):
            raise ValueError("zone strategy prior zone_id values must be unique")
        return self

    def to_frame(self) -> pl.DataFrame:
        if not self.zones:
            return _empty_strategy_prior_frame()
        return pl.DataFrame(
            [zone.model_dump() for zone in self.zones],
            schema=_STRATEGY_PRIOR_SCHEMA,
            strict=False,
        ).select(_STRATEGY_PRIOR_COLUMNS)


class TransferPriorArchetype(BaseModel):
    archetype_id: str
    description: str = ""
    feasibility_score: int = Field(ge=0, le=5)
    strategy_role: StrategyRole
    allow_diagnostic_model: bool = False
    max_lico_distance_cap_m: float | None = Field(default=None, gt=0.0)
    max_lico_distance_fraction_of_window: float | None = Field(
        default=None,
        gt=0.0,
        le=1.0,
    )
    notes: str = ""

    @field_validator("strategy_role")
    @classmethod
    def excluded_role_must_match_zero_score(
        cls,
        strategy_role: StrategyRole,
        info,
    ) -> StrategyRole:
        feasibility_score = info.data.get("feasibility_score")
        if feasibility_score == 0 and strategy_role != "excluded":
            raise ValueError("0/5 feasibility archetypes must use strategy_role='excluded'")
        return strategy_role


class TransferPriorTable(BaseModel):
    schema_version: int = 1
    profile_name: str
    notes: str = ""
    archetypes: list[TransferPriorArchetype] = Field(default_factory=list)

    @model_validator(mode="after")
    def archetype_ids_must_be_unique(self) -> TransferPriorTable:
        archetype_ids = [archetype.archetype_id for archetype in self.archetypes]
        if len(archetype_ids) != len(set(archetype_ids)):
            raise ValueError("transfer prior archetype ids must be unique")
        return self

    def archetype_map(self) -> dict[str, TransferPriorArchetype]:
        return {archetype.archetype_id: archetype for archetype in self.archetypes}


def load_strategy_prior_table(path: str | Path) -> StrategyPriorTable:
    with Path(path).open(encoding="utf-8") as file:
        return StrategyPriorTable.model_validate(json.load(file))


def default_transfer_prior_table() -> TransferPriorTable:
    return TransferPriorTable(
        profile_name="default_transfer_v1",
        notes=(
            "Conservative cross-circuit bootstrap priors derived from generic "
            "zone geometry and review role, intended to seed a new-circuit "
            "StrategyPriorTable before any local LICO calibration."
        ),
        archetypes=[
            TransferPriorArchetype(
                archetype_id="needs_driver_review",
                description="Zone still needs human review before bootstrap planning.",
                feasibility_score=0,
                strategy_role="excluded",
                notes="Keep out of planning until reviewed.",
            ),
            TransferPriorArchetype(
                archetype_id="validation_only",
                description="Reviewed non-LICO zone kept for validation/reporting only.",
                feasibility_score=0,
                strategy_role="excluded",
                notes="Validation-only zone; not eligible for bootstrap planning.",
            ),
            TransferPriorArchetype(
                archetype_id="excluded",
                description="Explicitly excluded zone.",
                feasibility_score=0,
                strategy_role="excluded",
                notes="Explicitly excluded from planning.",
            ),
            TransferPriorArchetype(
                archetype_id="candidate_micro",
                description="Very short LICO window; usable only as a tightly capped helper.",
                feasibility_score=2,
                strategy_role="limited",
                max_lico_distance_cap_m=25.0,
                max_lico_distance_fraction_of_window=1.0,
                notes="Micro LICO candidate; keep recommendation small.",
            ),
            TransferPriorArchetype(
                archetype_id="candidate_short",
                description="Short but credible LICO window for a conservative first plan.",
                feasibility_score=3,
                strategy_role="usable",
                max_lico_distance_cap_m=60.0,
                max_lico_distance_fraction_of_window=0.9,
                notes="Short-window candidate; use a conservative first cap.",
            ),
            TransferPriorArchetype(
                archetype_id="candidate_regular",
                description="Regular candidate zone suitable for first-pass planning.",
                feasibility_score=4,
                strategy_role="usable",
                max_lico_distance_cap_m=100.0,
                max_lico_distance_fraction_of_window=0.8,
                notes="Regular candidate; cap by both local window and conservative ceiling.",
            ),
        ],
    )


def build_strategy_prior_table_from_track_zones(
    track_zone_table: TrackZoneTable,
    *,
    dataset_id: str,
    transfer_priors: TransferPriorTable | None = None,
    notes: str = "",
) -> StrategyPriorTable:
    table_issues = track_zone_table.validation_issues()
    if table_issues:
        raise ValueError(
            "track zone table must be complete and internally consistent before "
            f"building strategy priors: {table_issues}"
        )

    archetype_table = transfer_priors or default_transfer_prior_table()
    archetype_map = archetype_table.archetype_map()
    zones = [
        _zone_strategy_prior_from_track_zone(zone, archetype_map=archetype_map)
        for zone in track_zone_table.zones
    ]

    combined_notes = " ".join(
        part
        for part in (
            notes.strip(),
            f"transfer_profile={archetype_table.profile_name}",
        )
        if part
    )
    return StrategyPriorTable(
        dataset_id=dataset_id,
        track_name=track_zone_table.track_name,
        car_class=track_zone_table.car_class,
        notes=combined_notes,
        zones=zones,
    )


def _empty_strategy_prior_frame() -> pl.DataFrame:
    return pl.DataFrame(schema=_STRATEGY_PRIOR_SCHEMA)


def _zone_strategy_prior_from_track_zone(
    zone: TrackZoneDefinition,
    *,
    archetype_map: dict[str, TransferPriorArchetype],
) -> ZoneStrategyPrior:
    archetype_id = infer_transfer_archetype_id_for_track_zone(zone)
    archetype = archetype_map[archetype_id]
    max_lico_distance_m = _resolve_zone_max_lico_distance(zone, archetype=archetype)
    notes = " | ".join(
        part
        for part in (
            f"transfer_archetype={archetype_id}",
            f"optimization_role={zone.optimization_role}",
            archetype.notes.strip(),
            zone.notes.strip(),
        )
        if part
    )
    return ZoneStrategyPrior(
        zone_id=zone.zone_id,
        display_label=zone.display_label,
        feasibility_score=archetype.feasibility_score,
        strategy_role=archetype.strategy_role,
        allow_diagnostic_model=archetype.allow_diagnostic_model,
        max_lico_distance_m=max_lico_distance_m,
        notes=notes,
    )


def infer_transfer_archetype_id_for_track_zone(zone: TrackZoneDefinition) -> str:
    if zone.review_status != "driver_reviewed" or zone.optimization_role == "needs_driver_review":
        return "needs_driver_review"
    if zone.optimization_role == "excluded":
        return "excluded"
    if zone.optimization_role == "validation_only" or zone.lico_eligible is not True:
        return "validation_only"

    lico_window_length_m = _zone_lico_window_length_m(zone)
    if lico_window_length_m is None or lico_window_length_m <= 30.0:
        return "candidate_micro"
    if lico_window_length_m <= 70.0:
        return "candidate_short"
    return "candidate_regular"


def _zone_lico_window_length_m(zone: TrackZoneDefinition) -> float | None:
    if zone.lico_window_start_m is None or zone.brake_reference_m is None:
        return None
    return max(float(zone.brake_reference_m) - float(zone.lico_window_start_m), 0.0)


def _resolve_zone_max_lico_distance(
    zone: TrackZoneDefinition,
    *,
    archetype: TransferPriorArchetype,
) -> float | None:
    lico_window_length_m = _zone_lico_window_length_m(zone)
    candidates = []
    if archetype.max_lico_distance_cap_m is not None:
        candidates.append(float(archetype.max_lico_distance_cap_m))
    if (
        lico_window_length_m is not None
        and archetype.max_lico_distance_fraction_of_window is not None
    ):
        candidates.append(
            lico_window_length_m * float(archetype.max_lico_distance_fraction_of_window)
        )
    if not candidates:
        return None
    return min(candidates)


_STRATEGY_PRIOR_COLUMNS = [
    "zone_id",
    "display_label",
    "feasibility_score",
    "strategy_role",
    "allow_diagnostic_model",
    "max_lico_distance_m",
    "notes",
]

_STRATEGY_PRIOR_SCHEMA = {
    "zone_id": pl.String,
    "display_label": pl.String,
    "feasibility_score": pl.Int64,
    "strategy_role": pl.String,
    "allow_diagnostic_model": pl.Boolean,
    "max_lico_distance_m": pl.Float64,
    "notes": pl.String,
}
