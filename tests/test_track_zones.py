import json

from licor.analysis import load_track_zone_table, track_zones_to_frame


def test_loads_complete_track_zone_table(tmp_path):
    path = tmp_path / "zones.json"
    path.write_text(
        json.dumps(
            {
                "track_name": "Synthetic Spa",
                "car_class": "LMP2_TEST",
                "zones": [
                    {
                        "zone_id": "synthetic_t1",
                        "turn_numbers": [1],
                        "display_label": "T01",
                        "start_distance_m": 100.0,
                        "lico_window_start_m": 180.0,
                        "brake_reference_m": 250.0,
                        "end_distance_m": 420.0,
                        "lico_eligible": True,
                        "optimization_role": "candidate",
                        "validation_end_rule": "stable_full_throttle",
                        "review_status": "driver_reviewed",
                    },
                    {
                        "zone_id": "synthetic_chicane_exit",
                        "turn_numbers": [19],
                        "display_label": "T19",
                        "start_distance_m": 500.0,
                        "lico_window_start_m": None,
                        "brake_reference_m": 540.0,
                        "end_distance_m": 620.0,
                        "lico_eligible": False,
                        "optimization_role": "validation_only",
                        "validation_end_rule": "manual_distance",
                        "review_status": "driver_reviewed",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    table = load_track_zone_table(path)
    frame = track_zones_to_frame(table)

    assert table.validation_issues() == {}
    assert [zone.zone_id for zone in table.complete_zones()] == [
        "synthetic_t1",
        "synthetic_chicane_exit",
    ]
    assert frame.select("zone_id", "turn_numbers", "lico_eligible").rows() == [
        ("synthetic_t1", [1], True),
        ("synthetic_chicane_exit", [19], False),
    ]


def test_reports_incomplete_and_inconsistent_track_zones(tmp_path):
    path = tmp_path / "zones.json"
    path.write_text(
        json.dumps(
            {
                "track_name": "Synthetic Spa",
                "car_class": "LMP2_TEST",
                "zones": [
                    {
                        "zone_id": "missing_review",
                        "turn_numbers": [1],
                        "display_label": "T01",
                        "start_distance_m": None,
                        "lico_window_start_m": None,
                        "brake_reference_m": 250.0,
                        "end_distance_m": 400.0,
                        "lico_eligible": None,
                    },
                    {
                        "zone_id": "bad_order",
                        "turn_numbers": [5],
                        "display_label": "T05",
                        "start_distance_m": 500.0,
                        "lico_window_start_m": 560.0,
                        "brake_reference_m": 540.0,
                        "end_distance_m": 620.0,
                        "lico_eligible": True,
                        "optimization_role": "candidate",
                    },
                    {
                        "zone_id": "wrong_role",
                        "turn_numbers": [19],
                        "display_label": "T19",
                        "start_distance_m": 700.0,
                        "brake_reference_m": 760.0,
                        "end_distance_m": 820.0,
                        "lico_eligible": True,
                        "optimization_role": "validation_only",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    issues = load_track_zone_table(path).validation_issues()

    assert issues["missing_review"] == [
        "missing_start_distance_m",
        "missing_lico_eligible",
    ]
    assert "lico_window_start_after_brake_reference" in issues["bad_order"]
    assert "non_candidate_should_not_be_lico_eligible" in issues["wrong_role"]


def test_reports_missing_and_duplicate_turn_numbers(tmp_path):
    path = tmp_path / "zones.json"
    path.write_text(
        json.dumps(
            {
                "track_name": "Synthetic Spa",
                "car_class": "LMP2_TEST",
                "zones": [
                    {
                        "zone_id": "missing_turn",
                        "turn_numbers": [],
                        "display_label": "T??",
                        "start_distance_m": 100.0,
                        "brake_reference_m": 150.0,
                        "end_distance_m": 220.0,
                        "lico_eligible": False,
                        "optimization_role": "validation_only",
                    },
                    {
                        "zone_id": "duplicate_a",
                        "turn_numbers": [8],
                        "display_label": "T08",
                        "start_distance_m": 300.0,
                        "brake_reference_m": 350.0,
                        "end_distance_m": 420.0,
                        "lico_eligible": False,
                        "optimization_role": "validation_only",
                    },
                    {
                        "zone_id": "duplicate_b",
                        "turn_numbers": [8],
                        "display_label": "T08 duplicate",
                        "start_distance_m": 500.0,
                        "brake_reference_m": 550.0,
                        "end_distance_m": 620.0,
                        "lico_eligible": False,
                        "optimization_role": "validation_only",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    issues = load_track_zone_table(path).validation_issues()

    assert "missing_turn_numbers" in issues["missing_turn"]
    assert "duplicate_turn_number:8" in issues["_table"]
