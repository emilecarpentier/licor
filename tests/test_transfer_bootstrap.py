import polars as pl
import pytest

from licor.analysis import (
    build_strategy_prior_table_from_track_zones,
    build_transfer_bootstrap_evaluation_checklist,
    build_transfer_bootstrap_provenance,
)
from licor.analysis.track_zones import TrackZoneTable


def _reviewed_track_zone_table() -> TrackZoneTable:
    return TrackZoneTable.model_validate(
        {
            "track_name": "Synthetic Monza",
            "car_class": "LMP2_TEST",
            "status": "driver_reviewed",
            "zones": [
                {
                    "zone_id": "monza_t1",
                    "turn_numbers": [1],
                    "display_label": "T01",
                    "start_distance_m": 100.0,
                    "lico_window_start_m": 210.0,
                    "brake_reference_m": 250.0,
                    "end_distance_m": 360.0,
                    "lico_eligible": True,
                    "optimization_role": "candidate",
                    "review_status": "driver_reviewed",
                },
                {
                    "zone_id": "monza_t4",
                    "turn_numbers": [4],
                    "display_label": "T04",
                    "start_distance_m": 600.0,
                    "lico_window_start_m": 680.0,
                    "brake_reference_m": 830.0,
                    "end_distance_m": 920.0,
                    "lico_eligible": True,
                    "optimization_role": "candidate",
                    "review_status": "driver_reviewed",
                },
                {
                    "zone_id": "monza_t11",
                    "turn_numbers": [11],
                    "display_label": "T11",
                    "start_distance_m": 1300.0,
                    "brake_reference_m": 1370.0,
                    "end_distance_m": 1460.0,
                    "lico_eligible": False,
                    "optimization_role": "validation_only",
                    "review_status": "driver_reviewed",
                },
            ],
        }
    )


def test_build_transfer_bootstrap_provenance():
    track_zones = _reviewed_track_zone_table()
    strategy_priors = build_strategy_prior_table_from_track_zones(
        track_zones,
        dataset_id="monza_bootstrap_v1",
    )

    provenance = build_transfer_bootstrap_provenance(
        track_zones,
        strategy_priors,
        source_track_name="Spa-Francorchamps",
        source_model_id="spa_transfer_v1",
        notes="bootstrap_reviewed_zones_only",
    )
    frame = provenance.to_frame()

    assert provenance.dataset_id == "monza_bootstrap_v1"
    assert frame.select(
        "target_zone_id",
        "assigned_archetype_id",
        "assigned_strategy_role",
        "predicted_lico_feasibility",
        "uncertainty_label",
    ).rows() == [
        ("monza_t1", "candidate_short", "usable", 3, "medium"),
        ("monza_t4", "candidate_regular", "usable", 4, "medium"),
        ("monza_t11", "validation_only", "excluded", 0, "low"),
    ]
    assert frame.filter(pl.col("target_zone_id") == "monza_t1").row(0, named=True)[
        "source_model_id"
    ] == "spa_transfer_v1"
    assert frame.filter(pl.col("target_zone_id") == "monza_t1").row(0, named=True)[
        "inference_basis"
    ] == ["optimization_role", "review_status", "lico_window_length"]


def test_transfer_bootstrap_provenance_requires_prior_coverage():
    track_zones = _reviewed_track_zone_table()
    strategy_priors = build_strategy_prior_table_from_track_zones(
        track_zones,
        dataset_id="monza_bootstrap_v1",
    )
    strategy_priors.zones.pop()

    with pytest.raises(ValueError, match="missing track zones required for bootstrap provenance"):
        build_transfer_bootstrap_provenance(track_zones, strategy_priors)


def test_build_transfer_bootstrap_evaluation_checklist_ready():
    track_zones = _reviewed_track_zone_table()
    strategy_priors = build_strategy_prior_table_from_track_zones(
        track_zones,
        dataset_id="monza_bootstrap_v1",
    )
    provenance = build_transfer_bootstrap_provenance(track_zones, strategy_priors)

    checklist = build_transfer_bootstrap_evaluation_checklist(
        track_zones,
        strategy_priors,
        provenance,
    )

    assert checklist.filter(
        pl.col("check_id") == "transfer_bootstrap_ready_for_new_data"
    ).row(0, named=True)["status"] == "ready"
    assert checklist.filter(
        pl.col("check_id") == "candidate_zone_caps_present"
    ).row(0, named=True)["status"] == "ready"


def test_build_transfer_bootstrap_evaluation_checklist_flags_uncapped_candidates():
    track_zones = _reviewed_track_zone_table()
    strategy_priors = build_strategy_prior_table_from_track_zones(
        track_zones,
        dataset_id="monza_bootstrap_v1",
    )
    strategy_priors.zones[0].max_lico_distance_m = None
    provenance = build_transfer_bootstrap_provenance(track_zones, strategy_priors)

    checklist = build_transfer_bootstrap_evaluation_checklist(
        track_zones,
        strategy_priors,
        provenance,
    )

    assert checklist.filter(
        pl.col("check_id") == "candidate_zone_caps_present"
    ).row(0, named=True)["status"] == "review_required"
    assert checklist.filter(
        pl.col("check_id") == "transfer_bootstrap_ready_for_new_data"
    ).row(0, named=True)["status"] == "review_required"
