from pathlib import Path

import polars as pl

from licor.analysis import (
    LapQualityManifestConfig,
    build_lap_quality_manifest,
    summarize_lap_sample_quality,
    write_lap_quality_manifest_csv,
)


def test_builds_clean_lap_quality_manifest_with_recommended_uses():
    manifest = build_lap_quality_manifest(
        _lap_summary(),
        lap_samples=_lap_samples(),
        zone_passes=_zone_passes(),
        config=LapQualityManifestConfig(
            min_telemetry_sample_count=3,
            max_time_gap_s=1.1,
            max_distance_gap_m=120.0,
        ),
    )

    row = manifest.row(0, named=True)
    assert row["quality_status"] == "ready"
    assert row["quality_flags"] == []
    assert row["telemetry_sample_count"] == 3
    assert row["zone_pass_count"] == 2
    assert row["recommended_uses"] == [
        "report_only",
        "lap_summary",
        "zone_readiness",
        "curve_update_candidate",
        "baseline_reference",
    ]


def test_flags_summary_invalid_and_driver_excluded_lap():
    summary = _lap_summary().with_columns(
        pl.lit(False).alias("is_valid_lap"),
        pl.lit(False).alias("driver_included"),
        pl.lit("excluded").alias("driver_lap_label"),
        pl.lit("driver_excluded").alias("exclusion_reason"),
    )

    row = build_lap_quality_manifest(
        summary,
        lap_samples=_lap_samples(),
        zone_passes=_zone_passes(),
        config=LapQualityManifestConfig(
            min_telemetry_sample_count=3,
            max_time_gap_s=1.1,
            max_distance_gap_m=120.0,
        ),
    ).row(0, named=True)

    assert row["quality_status"] == "needs_review"
    assert "invalid_lap_summary" in row["quality_flags"]
    assert "not_driver_included" in row["quality_flags"]
    assert row["recommended_uses"] == ["report_only"]


def test_flags_sample_gaps_distance_and_input_artifacts():
    bad_samples = pl.DataFrame(
        [
            _sample(0.0, 0.0, throttle_pct=100.0, brake_pct=0.0),
            _sample(1.5, 100.0, throttle_pct=102.0, brake_pct=0.0),
            _sample(1.7, 90.0, throttle_pct=100.0, brake_pct=-2.0),
            _sample(1.9, 300.0, throttle_pct=100.0, brake_pct=0.0),
        ]
    )

    row = build_lap_quality_manifest(
        _lap_summary(),
        lap_samples=bad_samples,
        zone_passes=_zone_passes(),
        config=LapQualityManifestConfig(min_telemetry_sample_count=3),
    ).row(0, named=True)

    assert row["quality_status"] == "needs_review"
    assert "large_time_gap" in row["quality_flags"]
    assert "large_distance_gap" in row["quality_flags"]
    assert "throttle_out_of_range" in row["quality_flags"]
    assert "brake_out_of_range" in row["quality_flags"]
    assert row["recommended_uses"] == ["report_only"]


def test_flags_zone_quality_and_detected_lico_in_baseline():
    zone_passes = pl.DataFrame(
        [
            _zone_pass("valid", has_lico=True, zero_throttle=True, brake_start_m=160.0),
            _zone_pass("incomplete_zone_coverage", has_lico=False, zero_throttle=False),
        ]
    )

    row = build_lap_quality_manifest(
        _lap_summary(),
        lap_samples=_lap_samples(),
        zone_passes=zone_passes,
        config=LapQualityManifestConfig(
            min_telemetry_sample_count=3,
            max_time_gap_s=1.1,
            min_valid_zone_pass_rate=0.75,
            max_distance_gap_m=120.0,
        ),
    ).row(0, named=True)

    assert row["quality_status"] == "needs_review"
    assert "low_valid_zone_pass_rate" in row["quality_flags"]
    assert "zone_start_zero_throttle" in row["quality_flags"]
    assert "brake_reference_drift_warning" in row["quality_flags"]
    assert "detected_lico" in row["quality_flags"]
    assert row["recommended_uses"] == ["report_only"]


def test_summarizes_lap_sample_quality():
    metrics = summarize_lap_sample_quality(_lap_samples())

    row = metrics.row(0, named=True)
    assert row["telemetry_sample_count"] == 3
    assert row["lap_elapsed_span_s"] == 2.0
    assert row["max_time_gap_s"] == 1.0
    assert row["max_distance_gap_m"] == 100.0


def test_writes_lap_quality_manifest_csv_with_list_columns(tmp_path: Path):
    manifest = build_lap_quality_manifest(
        _lap_summary(),
        lap_samples=_lap_samples(),
        zone_passes=_zone_passes(),
        config=LapQualityManifestConfig(
            min_telemetry_sample_count=3,
            max_time_gap_s=1.1,
            max_distance_gap_m=120.0,
        ),
    )

    path = write_lap_quality_manifest_csv(manifest, tmp_path / "manifest.csv")

    assert path.exists()
    assert "report_only|lap_summary" in path.read_text(encoding="utf-8")


def _lap_summary() -> pl.DataFrame:
    return pl.DataFrame(
        [
            {
                "run_id": "baseline",
                "file_name": "baseline.duckdb",
                "lap_number": 1,
                "collection_label": "none",
                "collection_protocol_id": "spa_lmp2_v2_collection_protocol",
                "collection_design": "baseline",
                "execution_quality": "clean",
                "labels_quality": "high",
                "driver_lap_label": "valid",
                "driver_included": True,
                "is_valid_lap": True,
                "lap_time_s": 123.0,
                "fuel_used_l": 3.4,
                "max_lap_distance_m": 7000.0,
                "mean_throttle_pct": 82.0,
                "max_brake_pct": 92.0,
                "exclusion_reason": None,
            }
        ]
    )


def _lap_samples() -> pl.DataFrame:
    return pl.DataFrame(
        [
            _sample(0.0, 0.0),
            _sample(1.0, 100.0),
            _sample(2.0, 200.0),
        ]
    )


def _sample(
    lap_elapsed_s: float,
    lap_distance_m: float,
    *,
    throttle_pct: float = 100.0,
    brake_pct: float = 0.0,
) -> dict[str, object]:
    return {
        "run_id": "baseline",
        "lap_number": 1,
        "lap_elapsed_s": lap_elapsed_s,
        "lap_distance_m": lap_distance_m,
        "fuel_level_l": 50.0 - lap_distance_m / 1000.0,
        "ground_speed_kph": 240.0 - lap_distance_m / 20.0,
        "throttle_pct": throttle_pct,
        "brake_pct": brake_pct,
    }


def _zone_passes() -> pl.DataFrame:
    return pl.DataFrame(
        [
            _zone_pass("valid", has_lico=False, zero_throttle=False),
            _zone_pass("valid", has_lico=False, zero_throttle=False),
        ]
    )


def _zone_pass(
    validity_label: str,
    *,
    has_lico: bool,
    zero_throttle: bool,
    brake_start_m: float = 102.0,
) -> dict[str, object]:
    return {
        "run_id": "baseline",
        "lap_number": 1,
        "validity_label": validity_label,
        "has_lico": has_lico,
        "zone_start_zero_throttle": zero_throttle,
        "brake_start_m": brake_start_m,
        "brake_reference_m": 100.0,
    }
