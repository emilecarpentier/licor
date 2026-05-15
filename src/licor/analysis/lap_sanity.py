from __future__ import annotations

from dataclasses import dataclass

import polars as pl


@dataclass(frozen=True)
class FullLapSanityConfig:
    baseline_intensity: str = "none"
    valid_laps_only: bool = True
    min_ratio_denominator: float = 1e-6


def summarize_full_lap_sanity(
    lap_summary: pl.DataFrame,
    zone_curve_points: pl.DataFrame,
    *,
    config: FullLapSanityConfig | None = None,
) -> pl.DataFrame:
    """Compare full-lap deltas with summed observed zone-level deltas."""

    sanity_config = config or FullLapSanityConfig()
    if lap_summary.is_empty():
        return _empty_full_lap_sanity_frame()

    laps = _analysis_laps(lap_summary, sanity_config)
    if laps.is_empty():
        return _empty_full_lap_sanity_frame()

    baseline = laps.filter(pl.col("collection_label") == sanity_config.baseline_intensity)
    if baseline.is_empty():
        return _empty_full_lap_sanity_frame()

    baseline_mean_fuel_used_l = float(baseline["fuel_used_l"].mean())
    baseline_mean_lap_time_s = float(baseline["lap_time_s"].mean())
    zone_sums = _zone_sums(zone_curve_points)

    return (
        laps.with_columns(
            pl.lit(baseline_mean_fuel_used_l).alias("baseline_mean_fuel_used_l"),
            pl.lit(baseline_mean_lap_time_s).alias("baseline_mean_lap_time_s"),
        )
        .with_columns(
            (
                pl.col("baseline_mean_fuel_used_l") - pl.col("fuel_used_l")
            ).alias("lap_fuel_saved_vs_baseline_l"),
            (
                pl.col("lap_time_s") - pl.col("baseline_mean_lap_time_s")
            ).alias("lap_time_lost_vs_baseline_s"),
        )
        .join(zone_sums, on=["run_id", "lap_number"], how="left")
        .with_columns(
            pl.col("zone_observed_fuel_saved_l").fill_null(0.0),
            pl.col("zone_observed_time_lost_s").fill_null(0.0),
            pl.col("included_zone_count").fill_null(0),
            pl.col("observed_lico_zone_count").fill_null(0),
            pl.col("observed_lico_distance_m").fill_null(0.0),
        )
        .with_columns(
            (
                pl.col("lap_fuel_saved_vs_baseline_l")
                - pl.col("zone_observed_fuel_saved_l")
            ).alias("fuel_residual_l"),
            (
                pl.col("lap_time_lost_vs_baseline_s")
                - pl.col("zone_observed_time_lost_s")
            ).alias("time_residual_s"),
        )
        .with_columns(
            _safe_ratio(
                numerator="zone_observed_fuel_saved_l",
                denominator="lap_fuel_saved_vs_baseline_l",
                config=sanity_config,
            ).alias("zone_to_lap_fuel_ratio"),
            _safe_ratio(
                numerator="zone_observed_time_lost_s",
                denominator="lap_time_lost_vs_baseline_s",
                config=sanity_config,
            ).alias("zone_to_lap_time_ratio"),
        )
        .select(_FULL_LAP_SANITY_COLUMNS)
        .sort(["collection_label", "lap_number"])
    )


def _analysis_laps(
    lap_summary: pl.DataFrame,
    config: FullLapSanityConfig,
) -> pl.DataFrame:
    laps = lap_summary
    if config.valid_laps_only and "is_valid_lap" in lap_summary.columns:
        laps = laps.filter(pl.col("is_valid_lap"))
    return laps.select(
        "run_id",
        "file_name",
        "collection_label",
        "lap_number",
        "lap_time_s",
        "fuel_used_l",
    )


def _zone_sums(zone_curve_points: pl.DataFrame) -> pl.DataFrame:
    if zone_curve_points.is_empty():
        return pl.DataFrame(schema=_ZONE_SUM_SCHEMA)
    return zone_curve_points.group_by("run_id", "lap_number").agg(
        pl.col("fuel_saved_vs_baseline_l").sum().alias("zone_observed_fuel_saved_l"),
        pl.col("time_lost_vs_baseline_s").sum().alias("zone_observed_time_lost_s"),
        pl.col("zone_id").n_unique().alias("included_zone_count"),
        pl.col("has_lico").sum().cast(pl.Int64).alias("observed_lico_zone_count"),
        pl.col("lico_distance_before_brake_m").sum().alias("observed_lico_distance_m"),
    )


def _safe_ratio(
    *,
    numerator: str,
    denominator: str,
    config: FullLapSanityConfig,
) -> pl.Expr:
    return (
        pl.when(pl.col(denominator).abs() > config.min_ratio_denominator)
        .then(pl.col(numerator) / pl.col(denominator))
        .otherwise(None)
    )


def _empty_full_lap_sanity_frame() -> pl.DataFrame:
    return pl.DataFrame(schema=_FULL_LAP_SANITY_SCHEMA)


_FULL_LAP_SANITY_COLUMNS = [
    "run_id",
    "file_name",
    "collection_label",
    "lap_number",
    "fuel_used_l",
    "baseline_mean_fuel_used_l",
    "lap_fuel_saved_vs_baseline_l",
    "zone_observed_fuel_saved_l",
    "fuel_residual_l",
    "zone_to_lap_fuel_ratio",
    "lap_time_s",
    "baseline_mean_lap_time_s",
    "lap_time_lost_vs_baseline_s",
    "zone_observed_time_lost_s",
    "time_residual_s",
    "zone_to_lap_time_ratio",
    "included_zone_count",
    "observed_lico_zone_count",
    "observed_lico_distance_m",
]

_FULL_LAP_SANITY_SCHEMA = {
    "run_id": pl.String,
    "file_name": pl.String,
    "collection_label": pl.String,
    "lap_number": pl.Int64,
    "fuel_used_l": pl.Float64,
    "baseline_mean_fuel_used_l": pl.Float64,
    "lap_fuel_saved_vs_baseline_l": pl.Float64,
    "zone_observed_fuel_saved_l": pl.Float64,
    "fuel_residual_l": pl.Float64,
    "zone_to_lap_fuel_ratio": pl.Float64,
    "lap_time_s": pl.Float64,
    "baseline_mean_lap_time_s": pl.Float64,
    "lap_time_lost_vs_baseline_s": pl.Float64,
    "zone_observed_time_lost_s": pl.Float64,
    "time_residual_s": pl.Float64,
    "zone_to_lap_time_ratio": pl.Float64,
    "included_zone_count": pl.UInt32,
    "observed_lico_zone_count": pl.Int64,
    "observed_lico_distance_m": pl.Float64,
}

_ZONE_SUM_SCHEMA = {
    "run_id": pl.String,
    "lap_number": pl.Int64,
    "zone_observed_fuel_saved_l": pl.Float64,
    "zone_observed_time_lost_s": pl.Float64,
    "included_zone_count": pl.UInt32,
    "observed_lico_zone_count": pl.Int64,
    "observed_lico_distance_m": pl.Float64,
}
