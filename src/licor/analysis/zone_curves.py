from __future__ import annotations

from dataclasses import dataclass

import polars as pl


@dataclass(frozen=True)
class ZoneCurveConfig:
    baseline_intensity: str = "none"
    valid_labels: tuple[str, ...] = ("valid",)
    lico_distance_column: str = "lico_start_distance_before_brake_m"
    bin_size_m: float = 25.0
    min_bin_pass_count: int = 1
    min_positive_delta: float = 1e-6
    exclude_detected_lico_from_baseline: bool = True


def build_zone_curve_points(
    zone_passes: pl.DataFrame,
    *,
    config: ZoneCurveConfig | None = None,
) -> pl.DataFrame:
    """Build per-pass descriptive cost/benefit points against a zone baseline."""

    curve_config = config or ZoneCurveConfig()
    if zone_passes.is_empty():
        return _empty_zone_curve_points_frame()

    comparable = zone_passes.filter(pl.col("validity_label").is_in(curve_config.valid_labels))
    if curve_config.exclude_detected_lico_from_baseline:
        comparable = _exclude_contaminated_baseline_passes(
            comparable,
            baseline_intensity=curve_config.baseline_intensity,
        )
    if comparable.is_empty():
        return _empty_zone_curve_points_frame()

    baseline = (
        comparable.filter(pl.col("lico_intensity") == curve_config.baseline_intensity)
        .group_by("zone_id")
        .agg(
            pl.col("fuel_used_l").mean().alias("baseline_mean_fuel_used_l"),
            pl.col("elapsed_time_s").mean().alias("baseline_mean_elapsed_time_s"),
        )
    )

    if baseline.is_empty():
        return _empty_zone_curve_points_frame()

    return (
        comparable.join(baseline, on="zone_id", how="inner")
        .with_columns(
            pl.when(pl.col("has_lico"))
            .then(pl.col(curve_config.lico_distance_column))
            .otherwise(0.0)
            .fill_null(0.0)
            .alias("lico_distance_before_brake_m"),
            (
                pl.col("baseline_mean_fuel_used_l") - pl.col("fuel_used_l")
            ).alias("fuel_saved_vs_baseline_l"),
            (
                pl.col("elapsed_time_s") - pl.col("baseline_mean_elapsed_time_s")
            ).alias("time_lost_vs_baseline_s"),
        )
        .with_columns(
            pl.when(
                pl.col("has_lico")
                & (pl.col("fuel_saved_vs_baseline_l") > curve_config.min_positive_delta)
                & (pl.col("time_lost_vs_baseline_s") > curve_config.min_positive_delta)
            )
            .then(pl.col("fuel_saved_vs_baseline_l") / pl.col("time_lost_vs_baseline_s"))
            .otherwise(None)
            .alias("fuel_saved_per_second_lps")
        )
        .select(_ZONE_CURVE_POINT_COLUMNS)
        .sort(["zone_id", "lico_distance_before_brake_m", "lap_number"])
    )


def summarize_zone_curve_bins(
    curve_points: pl.DataFrame,
    *,
    config: ZoneCurveConfig | None = None,
) -> pl.DataFrame:
    """Aggregate per-pass curve points into simple distance bins."""

    curve_config = config or ZoneCurveConfig()
    if curve_points.is_empty():
        return _empty_zone_curve_bins_frame()

    binned = (
        curve_points.with_columns(
            (
                (pl.col("lico_distance_before_brake_m") / curve_config.bin_size_m).floor()
                * curve_config.bin_size_m
            ).alias("lico_distance_bin_start_m")
        )
        .with_columns(
            (pl.col("lico_distance_bin_start_m") + curve_config.bin_size_m).alias(
                "lico_distance_bin_end_m"
            ),
            (
                pl.col("lico_distance_bin_start_m") + curve_config.bin_size_m / 2.0
            ).alias("lico_distance_bin_mid_m"),
        )
        .group_by(
            "zone_id",
            "display_label",
            "lico_distance_bin_start_m",
            "lico_distance_bin_end_m",
            "lico_distance_bin_mid_m",
        )
        .agg(
            pl.len().alias("pass_count"),
            pl.col("has_lico").sum().cast(pl.Int64).alias("detected_lico_passes"),
            pl.col("lico_intensity").unique().sort().alias("lico_intensities"),
            pl.col("lico_distance_before_brake_m").mean().alias(
                "mean_lico_distance_before_brake_m"
            ),
            pl.col("fuel_saved_vs_baseline_l").mean().alias("mean_fuel_saved_l"),
            pl.col("time_lost_vs_baseline_s").mean().alias("mean_time_lost_s"),
            pl.col("fuel_saved_per_second_lps").mean().alias(
                "mean_observed_fuel_saved_per_second_lps"
            ),
            pl.col("min_speed_kph").mean().alias("mean_min_speed_kph"),
            pl.col("exit_speed_kph").mean().alias("mean_exit_speed_kph"),
        )
        .with_columns(
            (
                pl.col("detected_lico_passes") / pl.col("pass_count")
            ).alias("detected_lico_rate"),
            pl.when(
                (pl.col("detected_lico_passes") > 0)
                & (pl.col("mean_fuel_saved_l") > curve_config.min_positive_delta)
                & (pl.col("mean_time_lost_s") > curve_config.min_positive_delta)
            )
            .then(pl.col("mean_fuel_saved_l") / pl.col("mean_time_lost_s"))
            .otherwise(None)
            .alias("fuel_saved_per_second_lps"),
        )
        .filter(pl.col("pass_count") >= curve_config.min_bin_pass_count)
        .select(_ZONE_CURVE_BIN_COLUMNS)
        .sort(["zone_id", "lico_distance_bin_start_m"])
    )

    return binned


def build_zone_curve_bins(
    zone_passes: pl.DataFrame,
    *,
    config: ZoneCurveConfig | None = None,
) -> pl.DataFrame:
    """Build binned descriptive curves directly from zone-pass observations."""

    curve_config = config or ZoneCurveConfig()
    points = build_zone_curve_points(zone_passes, config=curve_config)
    return summarize_zone_curve_bins(points, config=curve_config)


def _empty_zone_curve_points_frame() -> pl.DataFrame:
    return pl.DataFrame(schema=_ZONE_CURVE_POINT_SCHEMA)


def _empty_zone_curve_bins_frame() -> pl.DataFrame:
    return pl.DataFrame(schema=_ZONE_CURVE_BIN_SCHEMA)


def _exclude_contaminated_baseline_passes(
    zone_passes: pl.DataFrame,
    *,
    baseline_intensity: str,
) -> pl.DataFrame:
    baseline_condition = pl.col("lico_intensity") == baseline_intensity
    if "collection_design" in zone_passes.columns:
        baseline_condition = baseline_condition | (pl.col("collection_design") == "baseline")
    return zone_passes.filter(
        ~(
            baseline_condition
            & pl.col("has_lico").fill_null(False)
        )
    )


_ZONE_CURVE_POINT_COLUMNS = [
    "file_name",
    "run_id",
    "lap_number",
    "zone_id",
    "display_label",
    "lico_intensity",
    "has_lico",
    "lico_distance_before_brake_m",
    "fuel_used_l",
    "baseline_mean_fuel_used_l",
    "fuel_saved_vs_baseline_l",
    "elapsed_time_s",
    "baseline_mean_elapsed_time_s",
    "time_lost_vs_baseline_s",
    "fuel_saved_per_second_lps",
    "min_speed_kph",
    "exit_speed_kph",
    "validity_label",
]

_ZONE_CURVE_POINT_SCHEMA = {
    "file_name": pl.String,
    "run_id": pl.String,
    "lap_number": pl.Int64,
    "zone_id": pl.String,
    "display_label": pl.String,
    "lico_intensity": pl.String,
    "has_lico": pl.Boolean,
    "lico_distance_before_brake_m": pl.Float64,
    "fuel_used_l": pl.Float64,
    "baseline_mean_fuel_used_l": pl.Float64,
    "fuel_saved_vs_baseline_l": pl.Float64,
    "elapsed_time_s": pl.Float64,
    "baseline_mean_elapsed_time_s": pl.Float64,
    "time_lost_vs_baseline_s": pl.Float64,
    "fuel_saved_per_second_lps": pl.Float64,
    "min_speed_kph": pl.Float64,
    "exit_speed_kph": pl.Float64,
    "validity_label": pl.String,
}

_ZONE_CURVE_BIN_COLUMNS = [
    "zone_id",
    "display_label",
    "lico_distance_bin_start_m",
    "lico_distance_bin_end_m",
    "lico_distance_bin_mid_m",
    "pass_count",
    "detected_lico_passes",
    "detected_lico_rate",
    "lico_intensities",
    "mean_lico_distance_before_brake_m",
    "mean_fuel_saved_l",
    "mean_time_lost_s",
    "fuel_saved_per_second_lps",
    "mean_observed_fuel_saved_per_second_lps",
    "mean_min_speed_kph",
    "mean_exit_speed_kph",
]

_ZONE_CURVE_BIN_SCHEMA = {
    "zone_id": pl.String,
    "display_label": pl.String,
    "lico_distance_bin_start_m": pl.Float64,
    "lico_distance_bin_end_m": pl.Float64,
    "lico_distance_bin_mid_m": pl.Float64,
    "pass_count": pl.UInt32,
    "detected_lico_passes": pl.Int64,
    "detected_lico_rate": pl.Float64,
    "lico_intensities": pl.List(pl.String),
    "mean_lico_distance_before_brake_m": pl.Float64,
    "mean_fuel_saved_l": pl.Float64,
    "mean_time_lost_s": pl.Float64,
    "fuel_saved_per_second_lps": pl.Float64,
    "mean_observed_fuel_saved_per_second_lps": pl.Float64,
    "mean_min_speed_kph": pl.Float64,
    "mean_exit_speed_kph": pl.Float64,
}
