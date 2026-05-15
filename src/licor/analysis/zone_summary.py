from __future__ import annotations

from dataclasses import dataclass

import polars as pl


@dataclass(frozen=True)
class ZoneSummaryConfig:
    baseline_intensity: str = "none"
    valid_labels: tuple[str, ...] = ("valid",)
    min_positive_delta: float = 1e-6


def summarize_zone_costs(
    zone_passes: pl.DataFrame,
    *,
    config: ZoneSummaryConfig | None = None,
) -> pl.DataFrame:
    """Summarize zone-pass observations and compare each group to push baseline."""

    summary_config = config or ZoneSummaryConfig()
    if zone_passes.is_empty():
        return _empty_zone_summary_frame()

    comparable = zone_passes.filter(pl.col("validity_label").is_in(summary_config.valid_labels))
    if comparable.is_empty():
        return _empty_zone_summary_frame()

    summary = (
        comparable.group_by("zone_id", "display_label", "lico_intensity")
        .agg(
            pl.len().alias("pass_count"),
            pl.col("has_lico").sum().cast(pl.Int64).alias("detected_lico_passes"),
            pl.col("fuel_used_l").mean().alias("mean_fuel_used_l"),
            pl.col("elapsed_time_s").mean().alias("mean_elapsed_time_s"),
            pl.col("lico_start_distance_before_brake_m")
            .mean()
            .alias("mean_lico_start_distance_before_brake_m"),
            pl.col("lico_duration_s").mean().alias("mean_lico_duration_s"),
            pl.col("lico_distance_m").mean().alias("mean_lico_distance_m"),
            pl.col("brake_start_m").mean().alias("mean_brake_start_m"),
            pl.col("brake_start_speed_kph").mean().alias("mean_brake_start_speed_kph"),
            pl.col("min_speed_kph").mean().alias("mean_min_speed_kph"),
            pl.col("exit_speed_kph").mean().alias("mean_exit_speed_kph"),
        )
        .with_columns(
            (
                pl.col("detected_lico_passes") / pl.col("pass_count")
            ).alias("detected_lico_rate")
        )
    )

    baseline = summary.filter(pl.col("lico_intensity") == summary_config.baseline_intensity).select(
        "zone_id",
        pl.col("mean_fuel_used_l").alias("baseline_mean_fuel_used_l"),
        pl.col("mean_elapsed_time_s").alias("baseline_mean_elapsed_time_s"),
        pl.col("mean_brake_start_m").alias("baseline_mean_brake_start_m"),
        pl.col("mean_brake_start_speed_kph").alias("baseline_mean_brake_start_speed_kph"),
        pl.col("mean_min_speed_kph").alias("baseline_mean_min_speed_kph"),
        pl.col("mean_exit_speed_kph").alias("baseline_mean_exit_speed_kph"),
    )

    return (
        summary.join(baseline, on="zone_id", how="left")
        .with_columns(
            (
                pl.col("baseline_mean_fuel_used_l") - pl.col("mean_fuel_used_l")
            ).alias("fuel_saved_vs_baseline_l"),
            (
                pl.col("mean_elapsed_time_s") - pl.col("baseline_mean_elapsed_time_s")
            ).alias("time_lost_vs_baseline_s"),
            (
                pl.col("mean_brake_start_m") - pl.col("baseline_mean_brake_start_m")
            ).alias("brake_start_delta_vs_baseline_m"),
            (
                pl.col("mean_brake_start_speed_kph")
                - pl.col("baseline_mean_brake_start_speed_kph")
            ).alias("brake_start_speed_delta_vs_baseline_kph"),
            (
                pl.col("mean_min_speed_kph") - pl.col("baseline_mean_min_speed_kph")
            ).alias("min_speed_delta_vs_baseline_kph"),
            (
                pl.col("mean_exit_speed_kph") - pl.col("baseline_mean_exit_speed_kph")
            ).alias("exit_speed_delta_vs_baseline_kph"),
        )
        .with_columns(
            pl.when(
                (pl.col("detected_lico_passes") > 0)
                & (pl.col("fuel_saved_vs_baseline_l") > summary_config.min_positive_delta)
                & (pl.col("time_lost_vs_baseline_s") > summary_config.min_positive_delta)
            )
            .then(pl.col("fuel_saved_vs_baseline_l") / pl.col("time_lost_vs_baseline_s"))
            .otherwise(None)
            .alias("fuel_saved_per_second_lps")
        )
        .select(_ZONE_SUMMARY_COLUMNS)
        .sort(["zone_id", "lico_intensity"])
    )


def rank_zone_cost_benefit(zone_summary: pl.DataFrame) -> pl.DataFrame:
    """Rank non-baseline zone summaries by fuel saved per second lost."""

    if zone_summary.is_empty():
        return zone_summary

    return (
        zone_summary.filter(pl.col("fuel_saved_per_second_lps").is_not_null())
        .sort(
            ["fuel_saved_per_second_lps", "fuel_saved_vs_baseline_l"],
            descending=[True, True],
        )
        .with_row_index("rank", offset=1)
    )


def _empty_zone_summary_frame() -> pl.DataFrame:
    return pl.DataFrame(schema=_ZONE_SUMMARY_SCHEMA)


_ZONE_SUMMARY_COLUMNS = [
    "zone_id",
    "display_label",
    "lico_intensity",
    "pass_count",
    "detected_lico_passes",
    "detected_lico_rate",
    "mean_fuel_used_l",
    "baseline_mean_fuel_used_l",
    "fuel_saved_vs_baseline_l",
    "mean_elapsed_time_s",
    "baseline_mean_elapsed_time_s",
    "time_lost_vs_baseline_s",
    "fuel_saved_per_second_lps",
    "mean_lico_start_distance_before_brake_m",
    "mean_lico_duration_s",
    "mean_lico_distance_m",
    "mean_brake_start_m",
    "brake_start_delta_vs_baseline_m",
    "mean_brake_start_speed_kph",
    "brake_start_speed_delta_vs_baseline_kph",
    "mean_min_speed_kph",
    "min_speed_delta_vs_baseline_kph",
    "mean_exit_speed_kph",
    "exit_speed_delta_vs_baseline_kph",
]

_ZONE_SUMMARY_SCHEMA = {
    "zone_id": pl.String,
    "display_label": pl.String,
    "lico_intensity": pl.String,
    "pass_count": pl.UInt32,
    "detected_lico_passes": pl.Int64,
    "detected_lico_rate": pl.Float64,
    "mean_fuel_used_l": pl.Float64,
    "baseline_mean_fuel_used_l": pl.Float64,
    "fuel_saved_vs_baseline_l": pl.Float64,
    "mean_elapsed_time_s": pl.Float64,
    "baseline_mean_elapsed_time_s": pl.Float64,
    "time_lost_vs_baseline_s": pl.Float64,
    "fuel_saved_per_second_lps": pl.Float64,
    "mean_lico_start_distance_before_brake_m": pl.Float64,
    "mean_lico_duration_s": pl.Float64,
    "mean_lico_distance_m": pl.Float64,
    "mean_brake_start_m": pl.Float64,
    "brake_start_delta_vs_baseline_m": pl.Float64,
    "mean_brake_start_speed_kph": pl.Float64,
    "brake_start_speed_delta_vs_baseline_kph": pl.Float64,
    "mean_min_speed_kph": pl.Float64,
    "min_speed_delta_vs_baseline_kph": pl.Float64,
    "mean_exit_speed_kph": pl.Float64,
    "exit_speed_delta_vs_baseline_kph": pl.Float64,
}
