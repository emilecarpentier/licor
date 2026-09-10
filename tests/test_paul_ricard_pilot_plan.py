import runpy
from pathlib import Path

import pytest
import polars as pl

from licor.analysis.track_zones import TrackZoneDefinition, TrackZoneTable


MODULE = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "scripts/build_paul_ricard_pilot_plan.py")
)
build_prediction_validation_plan = MODULE["build_prediction_validation_plan"]


def test_pilot_sanity_rejects_overlapping_candidates_but_not_validation_coverage():
    table = TrackZoneTable(
        track_name="Test",
        car_class="LMP2",
        zones=[
            TrackZoneDefinition(
                zone_id="a",
                display_label="A",
                start_distance_m=100,
                end_distance_m=300,
                optimization_role="candidate",
            ),
            TrackZoneDefinition(
                zone_id="b",
                display_label="B",
                start_distance_m=250,
                end_distance_m=400,
                optimization_role="candidate",
            ),
        ],
    )
    with pytest.raises(ValueError, match="Overlapping candidate zones"):
        MODULE["require_disjoint_candidates"](table)
    table.zones[1].optimization_role = "validation_only"
    assert MODULE["require_disjoint_candidates"](table) == ["a"]


def test_current_paul_candidate_sanity_set_is_disjoint():
    from licor.analysis.track_zones import load_track_zone_table

    table = load_track_zone_table(
        Path(__file__).resolve().parents[1]
        / "config/track_zones/paul_ricard_lmp2_zones.draft.json"
    )
    assert not table.validation_issues()
    included = MODULE["require_disjoint_candidates"](table)
    assert len(included) == 6
    assert "pr_t15" not in included


def test_pilot_rejects_unreviewed_lap_quality():
    passes = pl.DataFrame({"run_id": ["r"], "lap_number": [1]})
    quality = passes.with_columns(
        pl.lit("needs_review").alias("quality_status"),
        pl.lit("distance_monotonicity_warning").alias("quality_flags"),
    )
    with pytest.raises(ValueError, match="Unreviewed modeling lap quality"):
        MODULE["require_reviewed_lap_quality"](passes, quality)
    reviewed = quality.with_columns(
        pl.lit("review_recommended").alias("quality_status"),
        pl.lit("detected_lico").alias("quality_flags"),
    )
    MODULE["require_reviewed_lap_quality"](passes, reviewed)


def test_prediction_validation_selects_dense_supported_point_for_every_zone():
    models = pl.DataFrame(
        {
            "zone_id": ["a", "a", "b"],
            "display_label": ["A", "A", "B"],
            "lico_distance_m": [30.0, 60.0, 40.0],
            "predicted_fuel_saved_l": [0.02, 0.04, 0.03],
            "predicted_time_lost_s": [0.0, 0.1, 0.04],
            "is_extrapolated": [False, False, False],
            "model_status": ["model_ready"] * 3,
            "quality_flags": [["negative_time_loss_observed"], [], []],
        }
    )
    bins = pl.DataFrame(
        {
            "zone_id": ["a", "a", "b"],
            "detected_lico_passes": [5, 2, 3],
            "mean_lico_distance_before_brake_m": [30.0, 60.0, 40.0],
            "mean_fuel_saved_l": [0.02, 0.04, 0.03],
            "pass_count": [5, 2, 3],
        }
    )
    priors = pl.DataFrame(
        {
            "zone_id": ["a", "b"],
            "feasibility_score": [4, 4],
            "strategy_role": ["usable", "usable"],
            "max_lico_distance_m": [100.0, 100.0],
            "notes": ["", ""],
        }
    )

    plan = build_prediction_validation_plan(models, bins, priors)

    assert plan.select("zone_id", "selected_lico_distance_m").rows() == [
        ("a", 30.0),
        ("b", 40.0),
    ]
    assert plan["is_selected_for_lico"].to_list() == [True, True]
    assert plan["plan_purpose"].unique().to_list() == ["prediction_validation"]
    assert plan["target_fuel_saved_per_lap_l"].null_count() == 2


def test_prediction_validation_rejects_zone_without_dense_support():
    models = pl.DataFrame(
        {
            "zone_id": ["a"],
            "display_label": ["A"],
            "lico_distance_m": [30.0],
            "predicted_fuel_saved_l": [0.02],
            "predicted_time_lost_s": [0.1],
            "is_extrapolated": [False],
            "model_status": ["model_ready"],
            "quality_flags": [[]],
        }
    )
    bins = pl.DataFrame(
        {
            "zone_id": ["a"],
            "detected_lico_passes": [2],
            "mean_lico_distance_before_brake_m": [30.0],
            "mean_fuel_saved_l": [0.02],
            "pass_count": [2],
        }
    )
    priors = pl.DataFrame(
        {
            "zone_id": ["a"],
            "feasibility_score": [4],
            "strategy_role": ["usable"],
            "max_lico_distance_m": [100.0],
            "notes": [""],
        }
    )

    with pytest.raises(ValueError, match="No dense supported"):
        build_prediction_validation_plan(models, bins, priors)


def test_prediction_validation_rejects_usable_zone_without_ready_model():
    models = pl.DataFrame(
        {
            "zone_id": ["a"],
            "model_status": ["diagnostic_only"],
        }
    )
    priors = pl.DataFrame(
        {
            "zone_id": ["a"],
            "feasibility_score": [4],
            "strategy_role": ["usable"],
        }
    )

    with pytest.raises(ValueError, match="not model_ready: a"):
        build_prediction_validation_plan(models, pl.DataFrame(), priors)
