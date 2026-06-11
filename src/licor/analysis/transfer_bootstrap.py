from __future__ import annotations

from typing import Literal

import polars as pl
from pydantic import BaseModel, Field

from licor.analysis.strategy_priors import (
    StrategyPriorTable,
    TransferPriorTable,
    default_transfer_prior_table,
    infer_transfer_archetype_id_for_track_zone,
)
from licor.analysis.track_zones import TrackZoneTable


TransferUncertaintyLabel = Literal["low", "medium", "high"]
LocalEvidenceStatus = Literal[
    "reviewed_zone_only",
    "push_baseline_ready",
    "varied_lico_ready",
]
TransferChecklistStatus = Literal["ready", "review_required", "blocked"]


class TransferBootstrapZoneProvenance(BaseModel):
    target_track_name: str
    car_class: str
    target_zone_id: str
    target_display_label: str = ""
    source_track_name: str
    source_model_id: str = ""
    transfer_profile_name: str
    assigned_archetype_id: str
    assigned_strategy_role: str
    predicted_lico_feasibility: int = Field(ge=0, le=5)
    uncertainty_label: TransferUncertaintyLabel
    requires_manual_review: bool = False
    local_evidence_status: LocalEvidenceStatus = "reviewed_zone_only"
    inference_basis: tuple[str, ...] = Field(default_factory=tuple)
    max_lico_distance_m: float | None = Field(default=None, gt=0.0)
    notes: str = ""


class TransferBootstrapProvenanceTable(BaseModel):
    schema_version: int = 1
    dataset_id: str
    target_track_name: str
    car_class: str
    source_track_name: str
    source_model_id: str = ""
    transfer_profile_name: str
    notes: str = ""
    zones: list[TransferBootstrapZoneProvenance] = Field(default_factory=list)

    def to_frame(self) -> pl.DataFrame:
        if not self.zones:
            return pl.DataFrame(schema=_TRANSFER_BOOTSTRAP_PROVENANCE_SCHEMA)
        return pl.DataFrame(
            [zone.model_dump() for zone in self.zones],
            schema=_TRANSFER_BOOTSTRAP_PROVENANCE_SCHEMA,
            strict=False,
        ).select(_TRANSFER_BOOTSTRAP_PROVENANCE_COLUMNS)


def build_transfer_bootstrap_provenance(
    track_zone_table: TrackZoneTable,
    strategy_prior_table: StrategyPriorTable,
    *,
    source_track_name: str = "Spa-Francorchamps",
    source_model_id: str = "",
    transfer_priors: TransferPriorTable | None = None,
    notes: str = "",
) -> TransferBootstrapProvenanceTable:
    table_issues = track_zone_table.validation_issues()
    if table_issues:
        raise ValueError(
            "track zone table must be complete and internally consistent before "
            f"building transfer bootstrap provenance: {table_issues}"
        )

    prior_by_zone = {
        zone_prior.zone_id: zone_prior
        for zone_prior in strategy_prior_table.zones
    }
    missing_zone_ids = [
        zone.zone_id
        for zone in track_zone_table.zones
        if zone.zone_id not in prior_by_zone
    ]
    if missing_zone_ids:
        raise ValueError(
            "strategy prior table is missing track zones required for bootstrap "
            f"provenance: {sorted(missing_zone_ids)}"
        )

    archetype_table = transfer_priors or default_transfer_prior_table()
    zones = []
    for zone in track_zone_table.zones:
        zone_prior = prior_by_zone[zone.zone_id]
        archetype_id = infer_transfer_archetype_id_for_track_zone(zone)
        zones.append(
            TransferBootstrapZoneProvenance(
                target_track_name=track_zone_table.track_name,
                car_class=track_zone_table.car_class,
                target_zone_id=zone.zone_id,
                target_display_label=zone.display_label,
                source_track_name=source_track_name,
                source_model_id=source_model_id,
                transfer_profile_name=archetype_table.profile_name,
                assigned_archetype_id=archetype_id,
                assigned_strategy_role=zone_prior.strategy_role,
                predicted_lico_feasibility=zone_prior.feasibility_score,
                uncertainty_label=_uncertainty_label_for_zone(
                    zone=zone,
                    strategy_role=zone_prior.strategy_role,
                    archetype_id=archetype_id,
                ),
                requires_manual_review=_requires_manual_review(
                    zone=zone,
                    strategy_role=zone_prior.strategy_role,
                    archetype_id=archetype_id,
                ),
                local_evidence_status="reviewed_zone_only",
                inference_basis=_inference_basis_for_zone(zone),
                max_lico_distance_m=zone_prior.max_lico_distance_m,
                notes=" | ".join(
                    part
                    for part in (
                        f"transfer_profile={archetype_table.profile_name}",
                        f"transfer_archetype={archetype_id}",
                        zone_prior.notes.strip(),
                        notes.strip(),
                    )
                    if part
                ),
            )
        )

    return TransferBootstrapProvenanceTable(
        dataset_id=strategy_prior_table.dataset_id,
        target_track_name=track_zone_table.track_name,
        car_class=track_zone_table.car_class,
        source_track_name=source_track_name,
        source_model_id=source_model_id,
        transfer_profile_name=archetype_table.profile_name,
        notes=notes.strip(),
        zones=zones,
    )


def build_transfer_bootstrap_evaluation_checklist(
    track_zone_table: TrackZoneTable,
    strategy_prior_table: StrategyPriorTable,
    provenance_table: TransferBootstrapProvenanceTable,
) -> pl.DataFrame:
    prior_by_zone = {
        zone_prior.zone_id: zone_prior
        for zone_prior in strategy_prior_table.zones
    }
    provenance_by_zone = {
        provenance.target_zone_id: provenance
        for provenance in provenance_table.zones
    }
    candidate_zones = [
        zone
        for zone in track_zone_table.zones
        if zone.optimization_role == "candidate"
    ]
    reviewed_candidate_zone_ids = [zone.zone_id for zone in candidate_zones]
    uncapped_candidate_zone_ids = [
        zone.zone_id
        for zone in candidate_zones
        if prior_by_zone.get(zone.zone_id) is not None
        and prior_by_zone[zone.zone_id].max_lico_distance_m is None
    ]
    missing_prior_zone_ids = [
        zone.zone_id
        for zone in track_zone_table.zones
        if zone.zone_id not in prior_by_zone
    ]
    missing_provenance_zone_ids = [
        zone.zone_id
        for zone in track_zone_table.zones
        if zone.zone_id not in provenance_by_zone
    ]
    manual_review_zone_ids = [
        provenance.target_zone_id
        for provenance in provenance_table.zones
        if provenance.requires_manual_review
    ]
    table_issues = track_zone_table.validation_issues()
    rows = [
        _checklist_row(
            "track_zone_table_complete",
            "Track-zone table is reviewed and internally consistent.",
            status="ready" if not table_issues else "blocked",
            detail="none" if not table_issues else str(table_issues),
            observed_count=len(track_zone_table.zones),
        ),
        _checklist_row(
            "strategy_prior_coverage",
            "Every reviewed zone has a circuit-local strategy prior.",
            status="ready" if not missing_prior_zone_ids else "blocked",
            detail=(
                "all track zones covered"
                if not missing_prior_zone_ids
                else f"missing priors: {missing_prior_zone_ids}"
            ),
            observed_count=len(track_zone_table.zones) - len(missing_prior_zone_ids),
            expected_count=len(track_zone_table.zones),
        ),
        _checklist_row(
            "bootstrap_provenance_coverage",
            "Every reviewed zone has bootstrap provenance attached.",
            status="ready" if not missing_provenance_zone_ids else "blocked",
            detail=(
                "all track zones covered"
                if not missing_provenance_zone_ids
                else f"missing provenance: {missing_provenance_zone_ids}"
            ),
            observed_count=len(track_zone_table.zones) - len(missing_provenance_zone_ids),
            expected_count=len(track_zone_table.zones),
        ),
        _checklist_row(
            "candidate_zone_caps_present",
            "Every candidate zone has a conservative initial max LICO distance cap.",
            status="ready" if not uncapped_candidate_zone_ids else "review_required",
            detail=(
                "all candidate zones capped"
                if not uncapped_candidate_zone_ids
                else f"uncapped candidates: {uncapped_candidate_zone_ids}"
            ),
            observed_count=len(reviewed_candidate_zone_ids) - len(uncapped_candidate_zone_ids),
            expected_count=len(reviewed_candidate_zone_ids),
        ),
        _checklist_row(
            "manual_review_fallback_marked",
            "Manual fallback remains explicit for ambiguous or weakly supported zones.",
            status="ready",
            detail=(
                "no manual-review fallback zones in current reviewed roster"
                if not manual_review_zone_ids
                else f"manual review still required for: {manual_review_zone_ids}"
            ),
            observed_count=len(manual_review_zone_ids),
        ),
        _checklist_row(
            "transfer_bootstrap_ready_for_new_data",
            "Bootstrap artifacts are ready enough that the next real dependency is a new-circuit dataset.",
            status=(
                "ready"
                if not table_issues
                and not missing_prior_zone_ids
                and not missing_provenance_zone_ids
                and not uncapped_candidate_zone_ids
                else "review_required"
            ),
            detail=(
                "provenance, prior coverage, and conservative caps are in place"
                if not table_issues
                and not missing_prior_zone_ids
                and not missing_provenance_zone_ids
                and not uncapped_candidate_zone_ids
                else "resolve blocking checklist items before collecting a new circuit"
            ),
        ),
    ]
    return pl.DataFrame(rows, schema=_TRANSFER_BOOTSTRAP_CHECKLIST_SCHEMA, strict=False).select(
        _TRANSFER_BOOTSTRAP_CHECKLIST_COLUMNS
    )


def _uncertainty_label_for_zone(
    *,
    zone,
    strategy_role: str,
    archetype_id: str,
) -> TransferUncertaintyLabel:
    if zone.review_status != "driver_reviewed" or archetype_id == "needs_driver_review":
        return "high"
    if strategy_role == "limited" or archetype_id == "candidate_micro":
        return "high"
    if strategy_role == "usable":
        return "medium"
    return "low"


def _requires_manual_review(
    *,
    zone,
    strategy_role: str,
    archetype_id: str,
) -> bool:
    return (
        zone.review_status != "driver_reviewed"
        or zone.optimization_role == "needs_driver_review"
        or strategy_role == "excluded"
        or archetype_id == "needs_driver_review"
    )


def _inference_basis_for_zone(zone) -> tuple[str, ...]:
    basis = ["optimization_role", "review_status"]
    if zone.lico_eligible:
        basis.append("lico_window_length")
    return tuple(basis)


def _checklist_row(
    check_id: str,
    objective: str,
    *,
    status: TransferChecklistStatus,
    detail: str,
    observed_count: int | None = None,
    expected_count: int | None = None,
) -> dict[str, object]:
    return {
        "check_id": check_id,
        "objective": objective,
        "status": status,
        "detail": detail,
        "observed_count": observed_count,
        "expected_count": expected_count,
    }


_TRANSFER_BOOTSTRAP_PROVENANCE_COLUMNS = [
    "target_track_name",
    "car_class",
    "target_zone_id",
    "target_display_label",
    "source_track_name",
    "source_model_id",
    "transfer_profile_name",
    "assigned_archetype_id",
    "assigned_strategy_role",
    "predicted_lico_feasibility",
    "uncertainty_label",
    "requires_manual_review",
    "local_evidence_status",
    "inference_basis",
    "max_lico_distance_m",
    "notes",
]

_TRANSFER_BOOTSTRAP_PROVENANCE_SCHEMA = {
    "target_track_name": pl.String,
    "car_class": pl.String,
    "target_zone_id": pl.String,
    "target_display_label": pl.String,
    "source_track_name": pl.String,
    "source_model_id": pl.String,
    "transfer_profile_name": pl.String,
    "assigned_archetype_id": pl.String,
    "assigned_strategy_role": pl.String,
    "predicted_lico_feasibility": pl.Int64,
    "uncertainty_label": pl.String,
    "requires_manual_review": pl.Boolean,
    "local_evidence_status": pl.String,
    "inference_basis": pl.List(pl.String),
    "max_lico_distance_m": pl.Float64,
    "notes": pl.String,
}

_TRANSFER_BOOTSTRAP_CHECKLIST_COLUMNS = [
    "check_id",
    "objective",
    "status",
    "detail",
    "observed_count",
    "expected_count",
]

_TRANSFER_BOOTSTRAP_CHECKLIST_SCHEMA = {
    "check_id": pl.String,
    "objective": pl.String,
    "status": pl.String,
    "detail": pl.String,
    "observed_count": pl.Int64,
    "expected_count": pl.Int64,
}
