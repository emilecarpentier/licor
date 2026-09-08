import pytest
from pydantic import ValidationError

from licor.analysis import (
    TransferPriorArchetype,
    TransferPriorTable,
    build_strategy_prior_table_from_track_zones,
)
from licor.analysis.track_zones import TrackZoneTable


def test_build_strategy_prior_table_keeps_bootstrap_provenance_contract():
    track_zones = _track_zone_table(
        _zone(
            zone_id="synthetic_t07",
            turn_number=7,
            display_label="T07",
            start_distance_m=500.0,
            lico_window_start_m=540.0,
            brake_reference_m=600.0,
            end_distance_m=690.0,
            lico_eligible=True,
            optimization_role="candidate",
            notes="local calibration pending",
        )
    )
    transfer_priors = TransferPriorTable(
        profile_name="evaluation_checklist_v1",
        archetypes=[
            TransferPriorArchetype(
                archetype_id="candidate_short",
                feasibility_score=3,
                strategy_role="usable",
                allow_diagnostic_model=True,
                max_lico_distance_cap_m=45.0,
                max_lico_distance_fraction_of_window=0.5,
                notes="Checklist helper cap from custom profile.",
            )
        ],
    )

    priors = build_strategy_prior_table_from_track_zones(
        track_zones,
        dataset_id="synthetic_transfer",
        transfer_priors=transfer_priors,
        notes="  bootstrap_eval  ",
    )
    row = priors.to_frame().row(0, named=True)

    assert priors.dataset_id == "synthetic_transfer"
    assert priors.track_name == "Synthetic Circuit"
    assert priors.car_class == "LMP2_TEST"
    assert priors.notes == "bootstrap_eval transfer_profile=evaluation_checklist_v1"
    assert row["zone_id"] == "synthetic_t07"
    assert row["feasibility_score"] == 3
    assert row["strategy_role"] == "usable"
    assert row["allow_diagnostic_model"] is True
    assert row["max_lico_distance_m"] == 30.0
    assert row["notes"] == (
        "transfer_archetype=candidate_short | optimization_role=candidate | "
        "Checklist helper cap from custom profile. | local calibration pending"
    )


def test_build_strategy_prior_table_covers_default_transfer_checklist_branches():
    track_zones = _track_zone_table(
        _zone(
            zone_id="needs_review",
            turn_number=1,
            display_label="T01",
            start_distance_m=100.0,
            brake_reference_m=170.0,
            end_distance_m=230.0,
            lico_eligible=False,
            optimization_role="needs_driver_review",
            review_status="needs_driver_review",
        ),
        _zone(
            zone_id="excluded_zone",
            turn_number=2,
            display_label="T02",
            start_distance_m=260.0,
            brake_reference_m=320.0,
            end_distance_m=390.0,
            lico_eligible=False,
            optimization_role="excluded",
        ),
        _zone(
            zone_id="validation_zone",
            turn_number=3,
            display_label="T03",
            start_distance_m=430.0,
            brake_reference_m=490.0,
            end_distance_m=560.0,
            lico_eligible=False,
            optimization_role="validation_only",
        ),
        _zone(
            zone_id="short_candidate",
            turn_number=4,
            display_label="T04",
            start_distance_m=600.0,
            lico_window_start_m=660.0,
            brake_reference_m=720.0,
            end_distance_m=800.0,
            lico_eligible=True,
            optimization_role="candidate",
        ),
        _zone(
            zone_id="regular_candidate",
            turn_number=5,
            display_label="T05",
            start_distance_m=840.0,
            lico_window_start_m=910.0,
            brake_reference_m=1000.0,
            end_distance_m=1080.0,
            lico_eligible=True,
            optimization_role="candidate",
        ),
    )

    priors = build_strategy_prior_table_from_track_zones(
        track_zones,
        dataset_id="synthetic_transfer",
    )
    frame = priors.to_frame()

    assert priors.notes == "transfer_profile=default_transfer_v1"
    assert frame.select(
        "zone_id",
        "feasibility_score",
        "strategy_role",
        "max_lico_distance_m",
    ).rows() == [
        ("needs_review", 0, "excluded", None),
        ("excluded_zone", 0, "excluded", None),
        ("validation_zone", 0, "excluded", None),
        ("short_candidate", 3, "usable", 54.0),
        ("regular_candidate", 4, "usable", 72.0),
    ]
    notes_by_zone = {
        row["zone_id"]: row["notes"]
        for row in frame.select("zone_id", "notes").iter_rows(named=True)
    }
    assert "transfer_archetype=needs_driver_review" in notes_by_zone["needs_review"]
    assert "transfer_archetype=excluded" in notes_by_zone["excluded_zone"]
    assert "transfer_archetype=validation_only" in notes_by_zone["validation_zone"]
    assert "transfer_archetype=candidate_short" in notes_by_zone["short_candidate"]
    assert "transfer_archetype=candidate_regular" in notes_by_zone["regular_candidate"]


def test_transfer_prior_archetype_rejects_zero_score_non_excluded_role():
    with pytest.raises(
        ValidationError,
        match="0/5 feasibility archetypes must use strategy_role='excluded'",
    ):
        TransferPriorArchetype(
            archetype_id="bad_zero_score",
            feasibility_score=0,
            strategy_role="limited",
        )


def _track_zone_table(*zones: dict[str, object]) -> TrackZoneTable:
    return TrackZoneTable.model_validate(
        {
            "track_name": "Synthetic Circuit",
            "car_class": "LMP2_TEST",
            "status": "driver_reviewed",
            "zones": list(zones),
        }
    )


def _zone(
    *,
    zone_id: str,
    turn_number: int,
    display_label: str,
    start_distance_m: float,
    brake_reference_m: float,
    end_distance_m: float,
    lico_eligible: bool,
    optimization_role: str,
    lico_window_start_m: float | None = None,
    review_status: str = "driver_reviewed",
    notes: str = "",
) -> dict[str, object]:
    return {
        "zone_id": zone_id,
        "turn_numbers": [turn_number],
        "display_label": display_label,
        "start_distance_m": start_distance_m,
        "lico_window_start_m": lico_window_start_m,
        "brake_reference_m": brake_reference_m,
        "end_distance_m": end_distance_m,
        "lico_eligible": lico_eligible,
        "optimization_role": optimization_role,
        "review_status": review_status,
        "notes": notes,
    }
