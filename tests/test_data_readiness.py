import polars as pl

from licor.analysis import (
    DataReadinessConfig,
    load_collection_protocol,
    summarize_collection_protocol_readiness,
    summarize_zone_data_readiness,
)


def test_summarizes_zone_readiness_for_well_covered_zone():
    readiness = summarize_zone_data_readiness(
        _zone_passes(),
        config=DataReadinessConfig(
            min_valid_passes_per_zone=6,
            min_baseline_passes_per_zone=3,
            min_lico_passes_per_zone=3,
            min_lico_distance_bins_per_zone=3,
        ),
    )

    row = readiness.filter(pl.col("zone_id") == "spa_t05_t06").row(0, named=True)
    assert row["readiness_status"] == "ready_for_curve_update"
    assert row["total_pass_count"] == 6
    assert row["baseline_pass_count"] == 3
    assert row["lico_pass_count"] == 3
    assert row["lico_distance_bin_count"] == 3
    assert row["collection_designs"] == ["baseline", "controlled_random"]
    assert row["readiness_flags"] == []


def test_zone_readiness_does_not_count_baseline_lift_as_lico_coverage():
    baseline_lift = pl.DataFrame(
        [
            _zone_pass_row(
                "spa_t05_t06",
                "T05-T06",
                "baseline_lift",
                7,
                "baseline",
                "none",
                True,
                60.0,
            )
        ]
    )
    row = summarize_zone_data_readiness(
        pl.concat([_zone_passes(), baseline_lift], how="diagonal"),
        config=DataReadinessConfig(
            min_valid_passes_per_zone=6,
            min_baseline_passes_per_zone=3,
            min_lico_passes_per_zone=3,
            min_lico_distance_bins_per_zone=3,
        ),
    ).filter(pl.col("zone_id") == "spa_t05_t06").row(0, named=True)

    assert row["lico_pass_count"] == 3
    assert row["baseline_detected_lico_pass_count"] == 1
    assert "baseline_contains_detected_lico" in row["readiness_flags"]


def test_zone_readiness_filters_partial_execution_quality():
    row = summarize_zone_data_readiness(
        _zone_passes().with_columns(
            pl.when(pl.col("lap_number") == 4)
            .then(pl.lit("partial"))
            .otherwise(pl.col("execution_quality"))
            .alias("execution_quality")
        ),
        config=DataReadinessConfig(
            min_valid_passes_per_zone=6,
            min_baseline_passes_per_zone=3,
            min_lico_passes_per_zone=3,
            min_lico_distance_bins_per_zone=3,
        ),
    ).filter(pl.col("zone_id") == "spa_t05_t06").row(0, named=True)

    assert row["valid_pass_count"] == 5
    assert row["lico_pass_count"] == 2
    assert row["readiness_status"] == "needs_lico_samples"


def test_zone_readiness_separates_invalid_passes_from_clean_coverage():
    zone_passes = pl.concat(
        [
            _zone_passes(),
            pl.DataFrame(
                [
                    _zone_pass_row(
                        "spa_t05_t06",
                        "T05-T06",
                        "run_bad",
                        99,
                        "controlled_random",
                        "unknown",
                        True,
                        90.0,
                        validity_label="incomplete_zone_coverage",
                    )
                ]
            ),
        ],
        how="diagonal",
    )

    row = summarize_zone_data_readiness(
        zone_passes,
        config=DataReadinessConfig(
            min_valid_passes_per_zone=6,
            min_baseline_passes_per_zone=3,
            min_lico_passes_per_zone=3,
            min_lico_distance_bins_per_zone=3,
        ),
    ).filter(pl.col("zone_id") == "spa_t05_t06").row(0, named=True)

    assert row["total_pass_count"] == 7
    assert row["invalid_pass_count"] == 1
    assert row["validity_labels"] == ["incomplete_zone_coverage", "valid"]
    assert "has_invalid_or_filtered_passes" in row["readiness_flags"]


def test_zone_readiness_reports_missing_baseline_before_curve_update():
    row = summarize_zone_data_readiness(
        _zone_passes().filter(pl.col("collection_design") != "baseline"),
        config=DataReadinessConfig(
            min_valid_passes_per_zone=3,
            min_baseline_passes_per_zone=1,
            min_lico_passes_per_zone=3,
            min_lico_distance_bins_per_zone=3,
        ),
    ).filter(pl.col("zone_id") == "spa_t05_t06").row(0, named=True)

    assert row["readiness_status"] == "needs_baseline"
    assert "needs_baseline_refresh" in row["readiness_flags"]


def test_zone_readiness_supports_legacy_global_labels_without_collection_design():
    legacy = _zone_passes().drop("collection_design")

    row = summarize_zone_data_readiness(
        legacy,
        config=DataReadinessConfig(
            min_valid_passes_per_zone=6,
            min_baseline_passes_per_zone=3,
            min_lico_passes_per_zone=3,
            min_lico_distance_bins_per_zone=3,
        ),
    ).filter(pl.col("zone_id") == "spa_t05_t06").row(0, named=True)

    assert row["baseline_pass_count"] == 3
    assert row["collection_designs"] == ["high", "none"]
    assert "missing_collection_design_context" not in row["readiness_flags"]


def test_zone_readiness_treats_empty_collection_design_as_legacy_metadata():
    legacy = _zone_passes().with_columns(pl.lit("").alias("collection_design"))

    row = summarize_zone_data_readiness(
        legacy,
        config=DataReadinessConfig(
            min_valid_passes_per_zone=6,
            min_baseline_passes_per_zone=3,
            min_lico_passes_per_zone=3,
            min_lico_distance_bins_per_zone=3,
        ),
    ).filter(pl.col("zone_id") == "spa_t05_t06").row(0, named=True)

    assert row["readiness_status"] == "ready_for_curve_update"
    assert row["baseline_pass_count"] == 3
    assert row["collection_designs"] == ["high", "none"]


def test_summarizes_collection_protocol_readiness_from_zone_passes():
    protocol = _protocol_sessions()

    readiness = summarize_collection_protocol_readiness(
        _zone_passes(),
        protocol,
        config=DataReadinessConfig(),
    )

    baseline = readiness.filter(pl.col("collection_design") == "baseline").row(
        0,
        named=True,
    )
    controlled = readiness.filter(
        pl.col("collection_design") == "controlled_random"
    ).row(0, named=True)
    pitstop = readiness.filter(pl.col("collection_design") == "pitstop_validation").row(
        0,
        named=True,
    )
    recommendation = readiness.filter(
        pl.col("collection_design") == "recommendation_execution"
    ).row(0, named=True)

    assert baseline["readiness_status"] == "complete"
    assert controlled["readiness_status"] == "complete"
    assert pitstop["readiness_status"] == "not_applicable_to_zone_pass_readiness"
    assert recommendation["readiness_status"] == "needs_plan_or_execution_logs"
    assert "target_zones_source:from_exported_plan" in recommendation["readiness_flags"]
    assert "missing_cue_event_logs" in recommendation["readiness_flags"]


def test_recommendation_execution_requires_cue_logs_even_with_zone_passes():
    recommendation_passes = pl.DataFrame(
        [
            _zone_pass_row(
                "spa_t05_t06",
                "T05-T06",
                "recommendation",
                1,
                "recommendation_execution",
                "unknown",
                True,
                90.0,
            ),
            _zone_pass_row(
                "spa_t05_t06",
                "T05-T06",
                "recommendation",
                2,
                "recommendation_execution",
                "unknown",
                True,
                95.0,
            ),
        ]
    )
    recommendation_session = _protocol_sessions().filter(
        pl.col("collection_design") == "recommendation_execution"
    )

    row = summarize_collection_protocol_readiness(
        recommendation_passes,
        recommendation_session,
    ).row(0, named=True)

    assert row["readiness_status"] == "needs_plan_or_execution_logs"
    assert row["observed_clean_laps"] == 2
    assert row["observed_cue_event_count"] == 0
    assert "missing_cue_event_logs" in row["readiness_flags"]


def test_recommendation_execution_can_complete_with_cue_logs():
    recommendation_passes = pl.DataFrame(
        [
            _zone_pass_row(
                "spa_t05_t06",
                "T05-T06",
                "recommendation",
                1,
                "recommendation_execution",
                "unknown",
                True,
                90.0,
            ),
            _zone_pass_row(
                "spa_t05_t06",
                "T05-T06",
                "recommendation",
                2,
                "recommendation_execution",
                "unknown",
                True,
                95.0,
            ),
        ]
    )
    recommendation_session = _protocol_sessions().filter(
        pl.col("collection_design") == "recommendation_execution"
    )
    cue_events = pl.DataFrame(
        [
            {"plan_id": "plan_v1", "zone_id": "spa_t05_t06"},
            {"plan_id": "plan_v1", "zone_id": "spa_t05_t06"},
        ]
    )

    row = summarize_collection_protocol_readiness(
        recommendation_passes,
        recommendation_session,
        live_cue_events=cue_events,
    ).row(0, named=True)

    assert row["readiness_status"] == "complete"
    assert row["observed_cue_event_count"] == 2
    assert "missing_cue_event_logs" not in row["readiness_flags"]


def test_protocol_readiness_reports_unlinked_metadata_for_new_designs():
    targeted_session = _protocol_sessions().filter(
        pl.col("collection_design") == "targeted_zone"
    )

    row = summarize_collection_protocol_readiness(
        _zone_passes().drop("collection_design"),
        targeted_session,
    ).row(0, named=True)

    assert row["readiness_status"] == "unlinked_metadata"
    assert row["readiness_flags"] == ["missing_collection_design_metadata"]


def test_protocol_readiness_reports_null_collection_design_metadata():
    targeted_session = _protocol_sessions().filter(
        pl.col("collection_design") == "targeted_zone"
    )

    row = summarize_collection_protocol_readiness(
        _zone_passes().with_columns(pl.lit(None).alias("collection_design")),
        targeted_session,
    ).row(0, named=True)

    assert row["readiness_status"] == "unlinked_metadata"
    assert row["readiness_flags"] == ["missing_collection_design_metadata"]


def test_loads_real_spa_v2_protocol_for_readiness():
    protocol = load_collection_protocol(
        "config/collection_protocols/spa_lmp2_v2_protocol.json"
    ).to_frame()

    readiness = summarize_collection_protocol_readiness(
        pl.DataFrame(schema=_ZONE_PASS_SCHEMA),
        protocol,
    )

    assert set(readiness["collection_design"].to_list()) == {
        "baseline",
        "controlled_random",
        "targeted_zone",
        "pitstop_validation",
        "recommendation_execution",
    }
    recommendation = readiness.filter(
        pl.col("collection_design") == "recommendation_execution"
    ).row(0, named=True)
    assert recommendation["target_zones_source"] == "from_exported_plan"


def _protocol_sessions() -> pl.DataFrame:
    return pl.DataFrame(
        [
            _protocol_session("baseline", "baseline", [], 3),
            _protocol_session("controlled", "controlled_random", ["spa_t05_t06"], 3),
            _protocol_session("targeted", "targeted_zone", ["spa_t08"], 2),
            _protocol_session("pitstop", "pitstop_validation", [], 1),
            _protocol_session(
                "recommendation",
                "recommendation_execution",
                [],
                2,
                target_zones_source="from_exported_plan",
            ),
        ]
    )


def _protocol_session(
    session_id: str,
    collection_design: str,
    target_zones: list[str],
    minimum_clean_laps: int,
    *,
    target_zones_source: str = "",
) -> dict[str, object]:
    return {
        "protocol_id": "synthetic_protocol",
        "session_id": session_id,
        "collection_design": collection_design,
        "target_zones": target_zones,
        "target_zones_source": target_zones_source,
        "minimum_clean_laps": minimum_clean_laps,
    }


def _zone_passes() -> pl.DataFrame:
    rows = []
    for lap_number in (1, 2, 3):
        rows.append(
            _zone_pass_row(
                "spa_t05_t06",
                "T05-T06",
                "baseline",
                lap_number,
                "baseline",
                "none",
                False,
                None,
            )
        )
    for lap_number, distance_m in enumerate((40.0, 80.0, 130.0), start=4):
        rows.append(
            _zone_pass_row(
                "spa_t05_t06",
                "T05-T06",
                "random",
                lap_number,
                "controlled_random",
                "high",
                True,
                distance_m,
            )
        )
    rows.append(
        _zone_pass_row(
            "spa_t08",
            "T08",
            "targeted",
            1,
            "targeted_zone",
            "unknown",
            True,
            70.0,
        )
    )
    return pl.DataFrame(rows)


def _zone_pass_row(
    zone_id: str,
    display_label: str,
    run_id: str,
    lap_number: int,
    collection_design: str,
    lico_intensity: str,
    has_lico: bool,
    lico_distance_m: float | None,
    *,
    validity_label: str = "valid",
) -> dict[str, object]:
    return {
        "file_name": f"{run_id}.duckdb",
        "run_id": run_id,
        "lap_number": lap_number,
        "zone_id": zone_id,
        "display_label": display_label,
        "lico_intensity": lico_intensity,
        "collection_design": collection_design,
        "execution_quality": "clean",
        "has_lico": has_lico,
        "lico_start_distance_before_brake_m": lico_distance_m,
        "validity_label": validity_label,
    }


_ZONE_PASS_SCHEMA = {
    "file_name": pl.String,
    "run_id": pl.String,
    "lap_number": pl.Int64,
    "zone_id": pl.String,
    "display_label": pl.String,
    "lico_intensity": pl.String,
    "collection_design": pl.String,
    "execution_quality": pl.String,
    "has_lico": pl.Boolean,
    "lico_start_distance_before_brake_m": pl.Float64,
    "validity_label": pl.String,
}
