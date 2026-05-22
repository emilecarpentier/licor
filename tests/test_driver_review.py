import json

import polars as pl

from licor.analysis import (
    apply_zone_pass_review,
    load_driver_zone_review,
)


def test_loads_driver_zone_review_and_builds_frames(tmp_path):
    path = tmp_path / "review.json"
    path.write_text(
        json.dumps(
            {
                "dataset_id": "synthetic",
                "track_name": "Synthetic Spa",
                "car_class": "LMP2_TEST",
                "review_status": "driver_reviewed",
                "zone_annotations": [
                    {
                        "zone_id": "synthetic_t01",
                        "signal_tags": ["clean_signal"],
                        "notes": "Looks clean.",
                    }
                ],
                "zone_pass_exclusions": [
                    {
                        "lap_number": 24,
                        "zone_id": "synthetic_t14",
                        "reason": "driver_error_outlier",
                        "notes": "Keep other lap 24 zones.",
                    }
                ],
                "zone_pass_annotations": [
                    {
                        "run_id": "synthetic",
                        "lap_number": 26,
                        "zone_id": "synthetic_t12_t13",
                        "review_tags": ["intentional_boundary_probe"],
                        "notes": "Keep and review zone boundary later.",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    review = load_driver_zone_review(path)

    assert review.review_status == "driver_reviewed"
    assert review.exclusion_frame().select("lap_number", "zone_id", "reason").rows() == [
        (24, "synthetic_t14", "driver_error_outlier")
    ]
    assert review.annotation_frame().select("zone_id", "signal_tags").rows() == [
        ("synthetic_t01", ["clean_signal"])
    ]
    assert review.pass_annotation_frame().select(
        "run_id",
        "lap_number",
        "zone_id",
        "review_tags",
    ).rows() == [
        ("synthetic", 26, "synthetic_t12_t13", ["intentional_boundary_probe"])
    ]


def test_applies_lap_zone_exclusions_without_removing_other_zones(tmp_path):
    review_path = tmp_path / "review.json"
    review_path.write_text(
        json.dumps(
            {
                "dataset_id": "synthetic",
                "track_name": "Synthetic Spa",
                "car_class": "LMP2_TEST",
                "zone_annotations": [
                    {
                        "zone_id": "synthetic_t09",
                        "signal_tags": ["no_credible_lico_signal"],
                        "notes": "No useful signal.",
                    }
                ],
                "zone_pass_exclusions": [
                    {
                        "lap_number": 24,
                        "zone_id": "synthetic_t01",
                        "reason": "driver_missed_brake_point",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    zone_passes = pl.DataFrame(
        [
            _zone_pass(24, "synthetic_t01", "T01"),
            _zone_pass(24, "synthetic_t14", "T14"),
            _zone_pass(25, "synthetic_t01", "T01"),
            _zone_pass(25, "synthetic_t09", "T09"),
        ]
    )

    reviewed = apply_zone_pass_review(zone_passes, load_driver_zone_review(review_path))

    assert reviewed.select("lap_number", "zone_id", "validity_label").rows() == [
        (24, "synthetic_t01", "driver_excluded"),
        (24, "synthetic_t14", "valid"),
        (25, "synthetic_t01", "valid"),
        (25, "synthetic_t09", "valid"),
    ]

    excluded = reviewed.filter(pl.col("zone_id") == "synthetic_t01").row(0, named=True)
    assert excluded["driver_review_exclusion_reason"] == "driver_missed_brake_point"

    t09 = reviewed.filter(pl.col("zone_id") == "synthetic_t09").row(0, named=True)
    assert t09["driver_review_signal_tags"] == ["no_credible_lico_signal"]
    assert t09["driver_review_zone_notes"] == "No useful signal."


def test_applies_run_specific_lap_zone_exclusions_only_to_matching_run(tmp_path):
    review_path = tmp_path / "review.json"
    review_path.write_text(
        json.dumps(
            {
                "dataset_id": "synthetic",
                "track_name": "Synthetic Spa",
                "car_class": "LMP2_TEST",
                "zone_pass_exclusions": [
                    {
                        "run_id": "run_b",
                        "lap_number": 32,
                        "zone_id": "synthetic_t14",
                        "reason": "driver_accident_contaminated_zone",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    zone_passes = pl.DataFrame(
        [
            _zone_pass(32, "synthetic_t14", "T14", run_id="run_a"),
            _zone_pass(32, "synthetic_t14", "T14", run_id="run_b"),
            _zone_pass(32, "synthetic_t18", "T18", run_id="run_b"),
        ]
    )

    reviewed = apply_zone_pass_review(zone_passes, load_driver_zone_review(review_path))

    assert reviewed.select("run_id", "lap_number", "zone_id", "validity_label").rows() == [
        ("run_a", 32, "synthetic_t14", "valid"),
        ("run_b", 32, "synthetic_t14", "driver_excluded"),
        ("run_b", 32, "synthetic_t18", "valid"),
    ]


def test_applies_lap_zone_annotations_without_excluding_observation(tmp_path):
    review_path = tmp_path / "review.json"
    review_path.write_text(
        json.dumps(
            {
                "dataset_id": "synthetic",
                "track_name": "Synthetic Spa",
                "car_class": "LMP2_TEST",
                "zone_pass_annotations": [
                    {
                        "run_id": "synthetic",
                        "lap_number": 26,
                        "zone_id": "synthetic_t12_t13",
                        "review_tags": [
                            "intentional_boundary_probe",
                            "candidate_lico_window_extension",
                        ],
                        "notes": "Intentional long LICO started before current zone window.",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    zone_passes = pl.DataFrame(
        [
            _zone_pass(26, "synthetic_t12_t13", "T12-T13"),
            _zone_pass(26, "synthetic_t18", "T18"),
        ]
    )

    reviewed = apply_zone_pass_review(zone_passes, load_driver_zone_review(review_path))

    annotated = reviewed.filter(pl.col("zone_id") == "synthetic_t12_t13").row(
        0,
        named=True,
    )
    assert annotated["validity_label"] == "valid"
    assert annotated["driver_review_pass_tags"] == [
        "intentional_boundary_probe",
        "candidate_lico_window_extension",
    ]
    assert annotated["driver_review_pass_notes"] == (
        "Intentional long LICO started before current zone window."
    )

    other = reviewed.filter(pl.col("zone_id") == "synthetic_t18").row(0, named=True)
    assert other["driver_review_pass_tags"] == []
    assert other["driver_review_pass_notes"] == ""


def test_loads_spa_v2_driver_review_annotations():
    review = load_driver_zone_review(
        "config/driver_reviews/spa_lmp2_v2_zone_review_2026-05-21.json"
    )

    row = review.pass_annotation_frame().row(0, named=True)
    assert row["run_id"] == "spa_lmp2_2026-05-21T22_57_26Z_controlled_random_01"
    assert row["lap_number"] == 26
    assert row["zone_id"] == "spa_t12_t13"
    assert "intentional_boundary_probe" in row["review_tags"]


def test_loads_spa_v2_baseline_zone_only_exclusion():
    review = load_driver_zone_review(
        "config/driver_reviews/spa_lmp2_v2_zone_review_2026-05-21.json"
    )

    row = (
        review.exclusion_frame()
        .filter(pl.col("run_id") == "spa_lmp2_2026-05-21T22_31_31Z_baseline_push_02")
        .row(0, named=True)
    )
    assert row["lap_number"] == 15
    assert row["zone_id"] == "spa_t08"
    assert row["reason"] == "driver_error_zone_only"


def _zone_pass(
    lap_number: int,
    zone_id: str,
    display_label: str,
    *,
    run_id: str = "synthetic",
) -> dict[str, object]:
    return {
        "file_name": "synthetic.duckdb",
        "run_id": run_id,
        "lap_number": lap_number,
        "zone_id": zone_id,
        "turn_numbers": [1],
        "display_label": display_label,
        "lico_intensity": "medium",
        "zone_start_m": 0.0,
        "lico_window_start_m": 0.0,
        "brake_reference_m": 100.0,
        "zone_end_m": 200.0,
        "fuel_start_l": 50.0,
        "fuel_end_l": 49.9,
        "fuel_used_l": 0.1,
        "elapsed_time_s": 2.0,
        "has_lico": True,
        "lico_start_m": 20.0,
        "lico_end_m": 90.0,
        "lico_start_distance_before_brake_m": 80.0,
        "lico_duration_s": 1.0,
        "lico_distance_m": 70.0,
        "throttle_release_rate_pct_per_s": 100.0,
        "minimum_throttle_pct_before_brake": 0.0,
        "average_throttle_pct_before_brake": 30.0,
        "brake_start_m": 100.0,
        "brake_start_speed_kph": 240.0,
        "max_brake_pct": 70.0,
        "min_speed_kph": 120.0,
        "exit_speed_kph": 180.0,
        "validity_label": "valid",
        "notes": "",
    }
