import polars as pl

from licor.analysis import (
    TrackZoneProposalConfig,
    TrackZoneTable,
    assign_detected_zones_to_track_zones,
    assign_detected_zones_to_track_zones_by_reference,
    attach_track_zones_to_lico,
    propose_track_zone_distances,
)


def test_assigns_detected_zones_to_track_zones_by_lap_order():
    table = _zone_table()
    braking_zones = pl.DataFrame(
        [
            _brake_zone(1, 1, 500.0),
            _brake_zone(2, 1, 100.0),
            _brake_zone(3, 1, 300.0),
            _brake_zone(4, 2, 110.0),
            _brake_zone(5, 2, 320.0),
            _brake_zone(6, 2, 520.0),
        ]
    )

    assigned = assign_detected_zones_to_track_zones(braking_zones, table)

    assert assigned.select("lap_number", "brake_zone_id", "zone_id").rows() == [
        (1, 2, "synthetic_t01"),
        (1, 3, "synthetic_t02"),
        (1, 1, "synthetic_t03"),
        (2, 4, "synthetic_t01"),
        (2, 5, "synthetic_t02"),
        (2, 6, "synthetic_t03"),
    ]


def test_proposes_zone_distances_from_push_and_high_lico():
    table = _zone_table()
    push_braking_zones = assign_detected_zones_to_track_zones(
        pl.DataFrame(
            [
                _brake_zone(1, 1, 100.0),
                _brake_zone(2, 1, 300.0),
                _brake_zone(3, 1, 500.0),
                _brake_zone(4, 2, 95.0),
                _brake_zone(5, 2, 310.0),
                _brake_zone(6, 2, 490.0),
            ]
        ),
        table,
    )
    high_braking_zones = assign_detected_zones_to_track_zones(
        pl.DataFrame(
            [
                _brake_zone(10, 31, 115.0),
                _brake_zone(11, 31, 330.0),
                _brake_zone(12, 31, 520.0),
            ]
        ),
        table,
    )
    high_lico_zones = attach_track_zones_to_lico(
        pl.DataFrame(
            [
                _lico_zone(10, 31, True, 70.0),
                _lico_zone(11, 31, True, 260.0),
                _lico_zone(12, 31, True, 450.0),
            ]
        ),
        high_braking_zones,
    )

    proposals = propose_track_zone_distances(
        table,
        push_braking_zones=push_braking_zones,
        high_lico_zones=high_lico_zones,
        config=TrackZoneProposalConfig(lico_start_buffer_m=30.0),
    )

    rows = {
        row["zone_id"]: row
        for row in proposals.select(
            "zone_id",
            "proposed_brake_reference_m",
            "proposed_lico_window_start_m",
            "proposed_end_distance_m",
            "proposal_status",
        ).iter_rows(named=True)
    }
    assert rows["synthetic_t01"]["proposed_brake_reference_m"] == 95.0
    assert rows["synthetic_t01"]["proposed_lico_window_start_m"] == 40.0
    assert rows["synthetic_t01"]["proposed_end_distance_m"] == 190.0
    assert rows["synthetic_t01"]["proposal_status"] == "ready_for_manual_end"
    assert rows["synthetic_t03"]["proposed_brake_reference_m"] == 490.0
    assert rows["synthetic_t03"]["proposed_lico_window_start_m"] is None
    assert rows["synthetic_t03"]["proposed_end_distance_m"] == 570.0
    assert rows["synthetic_t03"]["proposal_status"] == "non_candidate_ready_for_manual_end"


def test_assigns_non_push_zones_by_nearest_push_reference():
    table = _zone_table()
    references = pl.DataFrame(
        [
            {
                "zone_id": "synthetic_t01",
                "proposed_brake_reference_m": 100.0,
            },
            {
                "zone_id": "synthetic_t02",
                "proposed_brake_reference_m": 300.0,
            },
            {
                "zone_id": "synthetic_t03",
                "proposed_brake_reference_m": 500.0,
            },
        ]
    )
    braking_zones = pl.DataFrame(
        [
            _brake_zone(1, 31, 120.0),
            _brake_zone(2, 31, 520.0),
        ]
    )

    assigned = assign_detected_zones_to_track_zones_by_reference(
        braking_zones,
        table,
        references,
        max_assignment_distance_m=80.0,
    )

    assert assigned.select("brake_zone_id", "zone_id", "assignment_delta_m").rows() == [
        (1, "synthetic_t01", 20.0),
        (2, "synthetic_t03", 20.0),
    ]


def test_uses_fallback_zone_start_when_high_lico_is_missing():
    table = _zone_table()
    push_braking_zones = assign_detected_zones_to_track_zones(
        pl.DataFrame([_brake_zone(1, 1, 300.0)]),
        table,
    )

    proposals = propose_track_zone_distances(
        table,
        push_braking_zones=push_braking_zones,
        high_lico_zones=pl.DataFrame(),
        config=TrackZoneProposalConfig(fallback_zone_start_before_brake_m=120.0),
    )

    row = proposals.filter(pl.col("zone_id") == "synthetic_t01").row(0, named=True)
    assert row["proposed_brake_reference_m"] == 300.0
    assert row["proposed_lico_window_start_m"] == 180.0
    assert row["proposal_status"] == "ready_for_manual_end"


def _zone_table() -> TrackZoneTable:
    return TrackZoneTable.model_validate(
        {
            "track_name": "Synthetic Spa",
            "car_class": "LMP2_TEST",
            "zones": [
                {
                    "zone_id": "synthetic_t01",
                    "turn_numbers": [1],
                    "display_label": "T01",
                    "lico_eligible": True,
                },
                {
                    "zone_id": "synthetic_t02",
                    "turn_numbers": [2],
                    "display_label": "T02",
                    "lico_eligible": True,
                },
                {
                    "zone_id": "synthetic_t03",
                    "turn_numbers": [3],
                    "display_label": "T03",
                    "lico_eligible": False,
                    "optimization_role": "validation_only",
                },
            ],
        }
    )


def _brake_zone(brake_zone_id: int, lap_number: int, start_m: float) -> dict[str, float | int]:
    return {
        "brake_zone_id": brake_zone_id,
        "lap_number": lap_number,
        "start_ts": start_m / 100.0,
        "end_ts": start_m / 100.0 + 1.0,
        "start_lap_distance_m": start_m,
        "end_lap_distance_m": start_m + 80.0,
        "duration_s": 1.0,
        "distance_m": 80.0,
        "active_brake_duration_s": 1.0,
        "peak_brake_pct": 80.0,
        "mean_brake_pct": 60.0,
        "brake_start_speed_kph": 250.0,
        "min_speed_kph": 120.0,
        "raw_segment_count": 1,
    }


def _lico_zone(
    brake_zone_id: int,
    lap_number: int,
    has_lico: bool,
    lico_start_m: float,
) -> dict[str, float | int | bool | str | None]:
    return {
        "lico_zone_id": brake_zone_id,
        "brake_zone_id": brake_zone_id,
        "lap_number": lap_number,
        "has_lico": has_lico,
        "validity_label": "detected" if has_lico else "not_detected",
        "brake_start_m": lico_start_m + 100.0,
        "brake_start_ts": 0.0,
        "lico_start_m": lico_start_m,
        "lico_end_m": lico_start_m + 60.0,
        "lico_start_distance_before_brake_m": 100.0,
        "lico_duration_s": 1.0,
        "lico_distance_m": 60.0,
        "minimum_throttle_pct_before_brake": 0.0,
        "average_throttle_pct_before_brake": 20.0,
        "throttle_release_rate_pct_per_s": 100.0,
    }
