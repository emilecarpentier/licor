from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import polars as pl


@dataclass(frozen=True)
class ZoneModelConfig:
    distance_step_m: float = 10.0
    min_nonzero_bins: int = 2
    min_positive_delta: float = 1e-6
    min_ratio_time_loss_s: float = 0.05
    monotone_fuel: bool = True
    monotone_time: bool = True


def build_zone_piecewise_models(
    curve_bins: pl.DataFrame,
    *,
    zone_annotations: pl.DataFrame | None = None,
    config: ZoneModelConfig | None = None,
) -> pl.DataFrame:
    """Build transparent piecewise-linear zone cost/benefit model predictions."""

    model_config = config or ZoneModelConfig()
    if curve_bins.is_empty():
        return _empty_zone_model_frame()

    annotation_map = _zone_annotation_map(zone_annotations)
    rows = []
    for zone_id in sorted(curve_bins["zone_id"].unique().to_list()):
        zone_bins = curve_bins.filter(pl.col("zone_id") == zone_id).sort(
            "mean_lico_distance_before_brake_m"
        )
        rows.extend(
            _zone_model_rows(
                zone_bins,
                signal_tags=annotation_map.get(zone_id, []),
                config=model_config,
            )
        )

    if not rows:
        return _empty_zone_model_frame()
    return pl.DataFrame(rows, schema=_ZONE_MODEL_SCHEMA, strict=False).select(_ZONE_MODEL_COLUMNS)


def _zone_model_rows(
    zone_bins: pl.DataFrame,
    *,
    signal_tags: list[str],
    config: ZoneModelConfig,
) -> list[dict[str, Any]]:
    display_label = str(zone_bins["display_label"][0])
    zone_id = str(zone_bins["zone_id"][0])
    control_points = _control_points(zone_bins, config=config)
    if not control_points:
        return []

    flags = _quality_flags(zone_bins, control_points, signal_tags, config=config)
    status = _model_status(flags)
    max_distance_m = max(point["distance_m"] for point in control_points)
    grid_distances = _grid_distances(max_distance_m, config.distance_step_m, control_points)
    source_bin_count = int(zone_bins.height)
    nonzero_source_bin_count = int(
        zone_bins.filter(
            (pl.col("detected_lico_passes") > 0)
            & (pl.col("mean_lico_distance_before_brake_m") > config.min_positive_delta)
        ).height
    )

    return [
        {
            "zone_id": zone_id,
            "display_label": display_label,
            "lico_distance_m": distance_m,
            "predicted_fuel_saved_l": _linear_interpolate(
                control_points,
                distance_m,
                value_key="fuel_saved_l",
            ),
            "predicted_time_lost_s": _linear_interpolate(
                control_points,
                distance_m,
                value_key="time_lost_s",
            ),
            "predicted_fuel_saved_per_second_lps": _ratio_at_distance(
                control_points,
                distance_m,
                config=config,
            ),
            "is_extrapolated": False,
            "model_status": status,
            "quality_flags": flags,
            "source_bin_count": source_bin_count,
            "nonzero_source_bin_count": nonzero_source_bin_count,
            "observed_max_lico_distance_m": max_distance_m,
        }
        for distance_m in grid_distances
    ]


def _control_points(
    zone_bins: pl.DataFrame,
    *,
    config: ZoneModelConfig,
) -> list[dict[str, float]]:
    points = [
        {"distance_m": 0.0, "fuel_saved_l": 0.0, "time_lost_s": 0.0},
    ]
    nonzero_bins = zone_bins.filter(
        (pl.col("detected_lico_passes") > 0)
        & (pl.col("mean_lico_distance_before_brake_m") > config.min_positive_delta)
    ).sort("mean_lico_distance_before_brake_m")
    for row in nonzero_bins.iter_rows(named=True):
        points.append(
            {
                "distance_m": float(row["mean_lico_distance_before_brake_m"]),
                "fuel_saved_l": float(row["mean_fuel_saved_l"]),
                "time_lost_s": float(row["mean_time_lost_s"]),
            }
        )

    points = _unique_sorted_points(points)
    if config.monotone_fuel:
        points = _apply_monotone(points, value_key="fuel_saved_l", floor_at_zero=True)
    if config.monotone_time:
        points = _apply_monotone(points, value_key="time_lost_s", floor_at_zero=True)
    return points


def _unique_sorted_points(points: list[dict[str, float]]) -> list[dict[str, float]]:
    by_distance: dict[float, list[dict[str, float]]] = {}
    for point in points:
        by_distance.setdefault(point["distance_m"], []).append(point)
    unique_points = []
    for distance_m, group in by_distance.items():
        unique_points.append(
            {
                "distance_m": distance_m,
                "fuel_saved_l": sum(point["fuel_saved_l"] for point in group) / len(group),
                "time_lost_s": sum(point["time_lost_s"] for point in group) / len(group),
            }
        )
    return sorted(unique_points, key=lambda point: point["distance_m"])


def _apply_monotone(
    points: list[dict[str, float]],
    *,
    value_key: str,
    floor_at_zero: bool,
) -> list[dict[str, float]]:
    adjusted = []
    current = 0.0 if floor_at_zero else points[0][value_key]
    for point in points:
        current = max(current, point[value_key])
        updated = dict(point)
        updated[value_key] = current
        adjusted.append(updated)
    return adjusted


def _quality_flags(
    zone_bins: pl.DataFrame,
    control_points: list[dict[str, float]],
    signal_tags: list[str],
    *,
    config: ZoneModelConfig,
) -> list[str]:
    flags = list(signal_tags)
    nonzero_bins = zone_bins.filter(
        (pl.col("detected_lico_passes") > 0)
        & (pl.col("mean_lico_distance_before_brake_m") > config.min_positive_delta)
    ).sort("mean_lico_distance_before_brake_m")

    if nonzero_bins.height < config.min_nonzero_bins:
        flags.append("low_nonzero_bin_count")
    if "no_credible_lico_signal" in signal_tags:
        flags.append("review_excluded_from_optimization")
    if not _raw_values_monotone(nonzero_bins, "mean_fuel_saved_l", config=config):
        flags.append("fuel_monotone_adjusted")
    if not _raw_values_monotone(nonzero_bins, "mean_time_lost_s", config=config):
        flags.append("time_not_monotone")
    if (
        not nonzero_bins.is_empty()
        and float(nonzero_bins["mean_time_lost_s"].min()) < -config.min_positive_delta
    ):
        flags.append("negative_time_loss_observed")
    if any(
        point["distance_m"] > config.min_positive_delta
        and point["fuel_saved_l"] > config.min_positive_delta
        and point["time_lost_s"] < config.min_ratio_time_loss_s
        for point in control_points
    ):
        flags.append("low_time_loss_ratio_suppressed")
    if max(point["fuel_saved_l"] for point in control_points) <= config.min_positive_delta:
        flags.append("fuel_signal_nonpositive")
    return sorted(set(flags))


def _raw_values_monotone(
    frame: pl.DataFrame,
    column: str,
    *,
    config: ZoneModelConfig,
) -> bool:
    if frame.height <= 1:
        return True
    values = [float(value) for value in frame[column].to_list()]
    return all(
        current + config.min_positive_delta >= previous
        for previous, current in zip(values, values[1:])
    )


def _model_status(flags: list[str]) -> str:
    if "review_excluded_from_optimization" in flags:
        return "review_excluded"
    if "low_nonzero_bin_count" in flags or "fuel_signal_nonpositive" in flags:
        return "low_data"
    if "time_signal_unclear" in flags or "noisy_time_signal" in flags:
        return "diagnostic_only"
    return "model_ready"


def _grid_distances(
    max_distance_m: float,
    step_m: float,
    control_points: list[dict[str, float]],
) -> list[float]:
    distances = {point["distance_m"] for point in control_points}
    current = 0.0
    while current <= max_distance_m:
        distances.add(round(current, 10))
        current += step_m
    distances.add(max_distance_m)
    return sorted(distances)


def _linear_interpolate(
    control_points: list[dict[str, float]],
    distance_m: float,
    *,
    value_key: str,
) -> float:
    if distance_m <= control_points[0]["distance_m"]:
        return control_points[0][value_key]
    for left, right in zip(control_points, control_points[1:]):
        if distance_m <= right["distance_m"]:
            span = right["distance_m"] - left["distance_m"]
            fraction = 0.0 if span <= 0 else (distance_m - left["distance_m"]) / span
            return left[value_key] + (right[value_key] - left[value_key]) * fraction
    return control_points[-1][value_key]


def _ratio_at_distance(
    control_points: list[dict[str, float]],
    distance_m: float,
    *,
    config: ZoneModelConfig,
) -> float | None:
    fuel_saved_l = _linear_interpolate(control_points, distance_m, value_key="fuel_saved_l")
    time_lost_s = _linear_interpolate(control_points, distance_m, value_key="time_lost_s")
    if fuel_saved_l <= config.min_positive_delta or time_lost_s < config.min_ratio_time_loss_s:
        return None
    return fuel_saved_l / time_lost_s


def _zone_annotation_map(zone_annotations: pl.DataFrame | None) -> dict[str, list[str]]:
    if zone_annotations is None or zone_annotations.is_empty():
        return {}
    return {
        str(row["zone_id"]): list(row["signal_tags"] or [])
        for row in zone_annotations.iter_rows(named=True)
    }


def _empty_zone_model_frame() -> pl.DataFrame:
    return pl.DataFrame(schema=_ZONE_MODEL_SCHEMA)


_ZONE_MODEL_COLUMNS = [
    "zone_id",
    "display_label",
    "lico_distance_m",
    "predicted_fuel_saved_l",
    "predicted_time_lost_s",
    "predicted_fuel_saved_per_second_lps",
    "is_extrapolated",
    "model_status",
    "quality_flags",
    "source_bin_count",
    "nonzero_source_bin_count",
    "observed_max_lico_distance_m",
]

_ZONE_MODEL_SCHEMA = {
    "zone_id": pl.String,
    "display_label": pl.String,
    "lico_distance_m": pl.Float64,
    "predicted_fuel_saved_l": pl.Float64,
    "predicted_time_lost_s": pl.Float64,
    "predicted_fuel_saved_per_second_lps": pl.Float64,
    "is_extrapolated": pl.Boolean,
    "model_status": pl.String,
    "quality_flags": pl.List(pl.String),
    "source_bin_count": pl.Int64,
    "nonzero_source_bin_count": pl.Int64,
    "observed_max_lico_distance_m": pl.Float64,
}
