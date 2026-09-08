import runpy
from pathlib import Path

import pytest
import polars as pl

from licor.analysis.track_zones import TrackZoneDefinition, TrackZoneTable


MODULE = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "scripts/build_paul_ricard_pilot_plan.py")
)


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
