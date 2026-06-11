import json

import pytest
from pydantic import ValidationError

from licor.analysis import (
    TransferPriorTable,
    build_strategy_prior_table_from_track_zones,
    default_transfer_prior_table,
    load_strategy_prior_table,
)
from licor.analysis.track_zones import TrackZoneTable


def test_loads_strategy_priors_to_frame(tmp_path):
    path = tmp_path / "priors.json"
    path.write_text(
        json.dumps(
            {
                "dataset_id": "synthetic",
                "track_name": "Synthetic Spa",
                "car_class": "LMP2_TEST",
                "zones": [
                    {
                        "zone_id": "spa_t05_t06",
                        "display_label": "T05-T06",
                        "feasibility_score": 5,
                        "strategy_role": "preferred",
                    },
                    {
                        "zone_id": "spa_t09",
                        "display_label": "T09",
                        "feasibility_score": 0,
                        "strategy_role": "excluded",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    priors = load_strategy_prior_table(path)
    frame = priors.to_frame()

    assert frame.select("zone_id", "feasibility_score", "strategy_role").rows() == [
        ("spa_t05_t06", 5, "preferred"),
        ("spa_t09", 0, "excluded"),
    ]


def test_rejects_zero_rating_without_excluded_role(tmp_path):
    path = tmp_path / "priors.json"
    path.write_text(
        json.dumps(
            {
                "dataset_id": "synthetic",
                "track_name": "Synthetic Spa",
                "car_class": "LMP2_TEST",
                "zones": [
                    {
                        "zone_id": "spa_t09",
                        "feasibility_score": 0,
                        "strategy_role": "usable",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError):
        load_strategy_prior_table(path)


def test_rejects_duplicate_zone_ids(tmp_path):
    path = tmp_path / "priors.json"
    path.write_text(
        json.dumps(
            {
                "dataset_id": "synthetic",
                "track_name": "Synthetic Spa",
                "car_class": "LMP2_TEST",
                "zones": [
                    {
                        "zone_id": "spa_t18",
                        "feasibility_score": 5,
                        "strategy_role": "preferred",
                    },
                    {
                        "zone_id": "spa_t18",
                        "feasibility_score": 4,
                        "strategy_role": "usable",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError):
        load_strategy_prior_table(path)


def test_builds_strategy_priors_from_reviewed_track_zones():
    track_zones = TrackZoneTable.model_validate(
        {
            "track_name": "Synthetic Circuit",
            "car_class": "LMP2_TEST",
            "status": "driver_reviewed",
            "zones": [
                {
                    "zone_id": "synthetic_t1",
                    "turn_numbers": [1],
                    "display_label": "T01",
                    "start_distance_m": 100.0,
                    "lico_window_start_m": 220.0,
                    "brake_reference_m": 250.0,
                    "end_distance_m": 360.0,
                    "lico_eligible": True,
                    "optimization_role": "candidate",
                    "review_status": "driver_reviewed",
                    "notes": "Short helper candidate.",
                },
                {
                    "zone_id": "synthetic_t5",
                    "turn_numbers": [5],
                    "display_label": "T05",
                    "start_distance_m": 500.0,
                    "lico_window_start_m": 560.0,
                    "brake_reference_m": 690.0,
                    "end_distance_m": 760.0,
                    "lico_eligible": True,
                    "optimization_role": "candidate",
                    "review_status": "driver_reviewed",
                },
                {
                    "zone_id": "synthetic_t19",
                    "turn_numbers": [19],
                    "display_label": "T19",
                    "start_distance_m": 900.0,
                    "brake_reference_m": 960.0,
                    "end_distance_m": 1040.0,
                    "lico_eligible": False,
                    "optimization_role": "validation_only",
                    "review_status": "driver_reviewed",
                },
            ],
        }
    )

    priors = build_strategy_prior_table_from_track_zones(
        track_zones,
        dataset_id="synthetic_transfer",
        notes="bootstrap_v1",
    )
    frame = priors.to_frame()

    assert priors.dataset_id == "synthetic_transfer"
    assert priors.notes == "bootstrap_v1 transfer_profile=default_transfer_v1"
    assert frame.select(
        "zone_id",
        "feasibility_score",
        "strategy_role",
        "max_lico_distance_m",
    ).rows() == [
        ("synthetic_t1", 2, "limited", 25.0),
        ("synthetic_t5", 4, "usable", 100.0),
        ("synthetic_t19", 0, "excluded", None),
    ]
    assert "transfer_archetype=candidate_micro" in frame.row(0, named=True)["notes"]
    assert "transfer_archetype=candidate_regular" in frame.row(1, named=True)["notes"]
    assert "transfer_archetype=validation_only" in frame.row(2, named=True)["notes"]


def test_build_strategy_priors_rejects_incomplete_track_zone_table():
    track_zones = TrackZoneTable.model_validate(
        {
            "track_name": "Synthetic Circuit",
            "car_class": "LMP2_TEST",
            "zones": [
                {
                    "zone_id": "synthetic_t1",
                    "turn_numbers": [1],
                    "display_label": "T01",
                    "start_distance_m": 100.0,
                    "brake_reference_m": 250.0,
                    "end_distance_m": 360.0,
                    "lico_eligible": True,
                    "optimization_role": "candidate",
                    "review_status": "driver_reviewed",
                }
            ],
        }
    )

    with pytest.raises(ValueError, match="track zone table must be complete"):
        build_strategy_prior_table_from_track_zones(
            track_zones,
            dataset_id="synthetic_transfer",
        )


def test_transfer_prior_table_rejects_duplicate_archetype_ids():
    with pytest.raises(ValidationError):
        TransferPriorTable.model_validate(
            {
                "profile_name": "duplicate",
                "archetypes": [
                    {
                        "archetype_id": "candidate_regular",
                        "feasibility_score": 4,
                        "strategy_role": "usable",
                    },
                    {
                        "archetype_id": "candidate_regular",
                        "feasibility_score": 3,
                        "strategy_role": "limited",
                    },
                ],
            }
        )


def test_default_transfer_prior_table_keeps_zero_score_archetypes_excluded():
    transfer_priors = default_transfer_prior_table()

    zero_score_roles = {
        archetype.archetype_id: archetype.strategy_role
        for archetype in transfer_priors.archetypes
        if archetype.feasibility_score == 0
    }

    assert zero_score_roles == {
        "needs_driver_review": "excluded",
        "validation_only": "excluded",
        "excluded": "excluded",
    }
