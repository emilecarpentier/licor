from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import polars as pl

from licor.analysis.lap_summary import RunLapLabels
from licor.analysis.track_zones import TrackZoneDefinition, TrackZoneTable


@dataclass(frozen=True)
class ZonePassConfig:
    brake_threshold_pct: float = 5.0
    lift_start_throttle_pct: float = 99.0
    zero_input_throttle_pct: float = 1.0
    min_zero_input_duration_s: float = 0.10
    min_lift_duration_s: float = 0.20
    min_lift_distance_m: float = 10.0
    max_boundary_gap_m: float = 20.0
    require_driver_reviewed: bool = True
    optimization_roles: tuple[str, ...] = ("candidate",)


def extract_zone_passes(
    samples: pl.DataFrame,
    zone_table: TrackZoneTable,
    *,
    run_labels: RunLapLabels | None = None,
    config: ZonePassConfig | None = None,
) -> pl.DataFrame:
    """Extract one observation row for each lap pass through each complete zone."""

    pass_config = config or ZonePassConfig()
    zones = _included_zones(zone_table, pass_config)
    if samples.is_empty() or not zones:
        return _empty_zone_pass_frame()

    rows = []
    for lap_number in sorted(samples["lap_number"].unique().to_list()):
        lap_samples = samples.filter(pl.col("lap_number") == lap_number).sort("lap_distance_m")
        for zone in zones:
            rows.append(
                _zone_pass_row(
                    lap_samples,
                    zone,
                    run_labels=run_labels,
                    config=pass_config,
                )
            )

    return pl.DataFrame(rows, schema=_ZONE_PASS_SCHEMA, strict=False).select(_ZONE_PASS_COLUMNS)


def _included_zones(
    zone_table: TrackZoneTable,
    config: ZonePassConfig,
) -> list[TrackZoneDefinition]:
    zones = []
    for zone in zone_table.complete_zones():
        if config.require_driver_reviewed and zone.review_status != "driver_reviewed":
            continue
        if zone.optimization_role not in config.optimization_roles:
            continue
        zones.append(zone)
    return zones


def _zone_pass_row(
    lap_samples: pl.DataFrame,
    zone: TrackZoneDefinition,
    *,
    run_labels: RunLapLabels | None,
    config: ZonePassConfig,
) -> dict[str, Any]:
    zone_samples = lap_samples.filter(
        (pl.col("lap_distance_m") >= zone.start_distance_m)
        & (pl.col("lap_distance_m") <= zone.end_distance_m)
    ).sort("lap_distance_m")

    row = _base_row(lap_samples, zone, run_labels)
    if zone_samples.is_empty():
        row["validity_label"] = "no_samples"
        return row

    first = zone_samples.row(0, named=True)
    last = zone_samples.row(-1, named=True)
    fuel_start = _float_or_none(first.get("fuel_level_l"))
    fuel_end = _float_or_none(last.get("fuel_level_l"))
    brake_start = _first_brake_row(zone_samples, config.brake_threshold_pct)

    row.update(
        {
            "fuel_start_l": fuel_start,
            "fuel_end_l": fuel_end,
            "fuel_used_l": fuel_start - fuel_end if fuel_start is not None and fuel_end is not None else None,
            "elapsed_time_s": float(last["ts"]) - float(first["ts"]),
            "zone_start_throttle_pct": _float_or_none(first.get("throttle_pct")),
            "zone_start_zero_throttle": (
                float(first["throttle_pct"]) <= config.zero_input_throttle_pct
                if first.get("throttle_pct") is not None
                else None
            ),
            "brake_start_m": _float_or_none(brake_start.get("lap_distance_m")) if brake_start else None,
            "brake_start_speed_kph": _float_or_none(brake_start.get("ground_speed_kph")) if brake_start else None,
            "max_brake_pct": float(zone_samples["brake_pct"].max()),
            "min_speed_kph": float(zone_samples["ground_speed_kph"].min()),
            "exit_speed_kph": _float_or_none(last.get("ground_speed_kph")),
            "validity_label": _validity_label(zone_samples, zone, config),
        }
    )
    row.update(_lico_metrics(zone_samples, zone, config))
    return row


def _base_row(
    lap_samples: pl.DataFrame,
    zone: TrackZoneDefinition,
    run_labels: RunLapLabels | None,
) -> dict[str, Any]:
    lap_number = int(lap_samples["lap_number"][0]) if not lap_samples.is_empty() else None
    return {
        "file_name": run_labels.file if run_labels is not None else None,
        "run_id": run_labels.run_id if run_labels is not None else None,
        "lap_number": lap_number,
        "zone_id": zone.zone_id,
        "turn_numbers": list(zone.turn_numbers),
        "display_label": zone.display_label,
        "lico_intensity": run_labels.collection_label if run_labels is not None else None,
        "zone_start_m": zone.start_distance_m,
        "lico_window_start_m": zone.lico_window_start_m,
        "brake_reference_m": zone.brake_reference_m,
        "zone_end_m": zone.end_distance_m,
        "fuel_start_l": None,
        "fuel_end_l": None,
        "fuel_used_l": None,
        "elapsed_time_s": None,
        "zone_start_throttle_pct": None,
        "zone_start_zero_throttle": None,
        "has_lico": False,
        "lico_start_m": None,
        "lico_end_m": None,
        "lico_start_distance_before_brake_m": None,
        "lico_duration_s": None,
        "lico_distance_m": None,
        "throttle_release_rate_pct_per_s": None,
        "minimum_throttle_pct_before_brake": None,
        "average_throttle_pct_before_brake": None,
        "brake_start_m": None,
        "brake_start_speed_kph": None,
        "max_brake_pct": None,
        "min_speed_kph": None,
        "exit_speed_kph": None,
        "validity_label": "not_evaluated",
        "notes": "",
    }


def _lico_metrics(
    zone_samples: pl.DataFrame,
    zone: TrackZoneDefinition,
    config: ZonePassConfig,
) -> dict[str, float | bool | None]:
    pre_brake = zone_samples.filter(
        (pl.col("lap_distance_m") >= zone.lico_window_start_m)
        & (pl.col("lap_distance_m") < zone.brake_reference_m)
    ).sort("lap_distance_m")
    if pre_brake.is_empty():
        return _empty_lico_metrics()

    lift_segments = _threshold_segments(
        pre_brake,
        value_column="throttle_pct",
        threshold=config.lift_start_throttle_pct,
    )
    zero_segments = _threshold_segments(
        pre_brake,
        value_column="throttle_pct",
        threshold=config.zero_input_throttle_pct,
    )
    zero_segments = [
        segment for segment in zero_segments if segment["duration_s"] >= config.min_zero_input_duration_s
    ]
    lift_segments = [
        segment
        for segment in lift_segments
        if segment["duration_s"] >= config.min_lift_duration_s
        and segment["distance_m"] >= config.min_lift_distance_m
    ]
    if not zero_segments or not lift_segments:
        return _empty_lico_metrics()

    lift = _lift_segment_for_zero_input(lift_segments, zero_segments)
    if lift is None:
        return _empty_lico_metrics()

    lico_rows = pre_brake.filter(
        (pl.col("ts") >= lift["start_ts"])
        & (pl.col("ts") <= lift["end_ts"])
        & (pl.col("throttle_pct") <= config.lift_start_throttle_pct)
    )
    if lico_rows.is_empty():
        return _empty_lico_metrics()

    start = lico_rows.row(0, named=True)
    end = lico_rows.row(-1, named=True)
    duration_s = float(end["ts"]) - float(start["ts"])
    distance_m = float(end["lap_distance_m"]) - float(start["lap_distance_m"])

    minimum_throttle = float(lico_rows["throttle_pct"].min())
    return {
        "has_lico": True,
        "lico_start_m": float(start["lap_distance_m"]),
        "lico_end_m": float(end["lap_distance_m"]),
        "lico_start_distance_before_brake_m": float(zone.brake_reference_m)
        - float(start["lap_distance_m"]),
        "lico_duration_s": duration_s,
        "lico_distance_m": distance_m,
        "throttle_release_rate_pct_per_s": _throttle_release_rate(
            zone_samples,
            start,
            minimum_throttle,
        ),
        "minimum_throttle_pct_before_brake": minimum_throttle,
        "average_throttle_pct_before_brake": float(pre_brake["throttle_pct"].mean()),
    }


def _lift_segment_for_zero_input(
    lift_segments: list[dict[str, float]],
    zero_segments: list[dict[str, float]],
) -> dict[str, float] | None:
    for zero_segment in zero_segments:
        for lift_segment in lift_segments:
            if (
                lift_segment["start_ts"] <= zero_segment["start_ts"]
                and zero_segment["start_ts"] <= lift_segment["end_ts"]
            ):
                return lift_segment
    return None


def _empty_lico_metrics() -> dict[str, float | bool | None]:
    return {
        "has_lico": False,
        "lico_start_m": None,
        "lico_end_m": None,
        "lico_start_distance_before_brake_m": None,
        "lico_duration_s": None,
        "lico_distance_m": None,
        "throttle_release_rate_pct_per_s": None,
        "minimum_throttle_pct_before_brake": None,
        "average_throttle_pct_before_brake": None,
    }


def _threshold_segments(
    samples: pl.DataFrame,
    *,
    value_column: str,
    threshold: float,
) -> list[dict[str, float]]:
    segments = []
    active: list[dict[str, Any]] = []
    for sample in samples.sort("ts").iter_rows(named=True):
        if float(sample[value_column]) <= threshold:
            active.append(sample)
        elif active:
            segments.append(_segment_from_rows(active))
            active = []
    if active:
        segments.append(_segment_from_rows(active))
    return segments


def _segment_from_rows(rows: list[dict[str, Any]]) -> dict[str, float]:
    start = rows[0]
    end = rows[-1]
    return {
        "start_ts": float(start["ts"]),
        "end_ts": float(end["ts"]),
        "start_lap_distance_m": float(start["lap_distance_m"]),
        "end_lap_distance_m": float(end["lap_distance_m"]),
        "duration_s": float(end["ts"]) - float(start["ts"]),
        "distance_m": float(end["lap_distance_m"]) - float(start["lap_distance_m"]),
    }


def _first_brake_row(samples: pl.DataFrame, brake_threshold_pct: float) -> dict[str, Any] | None:
    brake_samples = samples.filter(pl.col("brake_pct") >= brake_threshold_pct).sort("lap_distance_m")
    if brake_samples.is_empty():
        return None
    return brake_samples.row(0, named=True)


def _validity_label(
    zone_samples: pl.DataFrame,
    zone: TrackZoneDefinition,
    config: ZonePassConfig,
) -> str:
    first_distance = float(zone_samples["lap_distance_m"][0])
    last_distance = float(zone_samples["lap_distance_m"][-1])
    starts_near_boundary = first_distance <= float(zone.start_distance_m) + config.max_boundary_gap_m
    ends_near_boundary = last_distance >= float(zone.end_distance_m) - config.max_boundary_gap_m
    if starts_near_boundary and ends_near_boundary:
        return "valid"
    return "incomplete_zone_coverage"


def _throttle_release_rate(
    zone_samples: pl.DataFrame,
    start: dict[str, Any],
    minimum_throttle_pct: float,
) -> float | None:
    previous = (
        zone_samples.filter(
            (pl.col("ts") < start["ts"])
            & pl.col("throttle_pct").is_not_null()
        )
        .sort("ts")
        .tail(1)
    )
    if previous.is_empty():
        return None
    previous_row = previous.row(0, named=True)
    delta_t = float(start["ts"]) - float(previous_row["ts"])
    if delta_t <= 0.0:
        return None
    return (float(previous_row["throttle_pct"]) - minimum_throttle_pct) / delta_t


def _float_or_none(value: Any) -> float | None:
    return None if value is None else float(value)


def _empty_zone_pass_frame() -> pl.DataFrame:
    return pl.DataFrame(schema=_ZONE_PASS_SCHEMA)


_ZONE_PASS_COLUMNS = [
    "file_name",
    "run_id",
    "lap_number",
    "zone_id",
    "turn_numbers",
    "display_label",
    "lico_intensity",
    "zone_start_m",
    "lico_window_start_m",
    "brake_reference_m",
    "zone_end_m",
    "fuel_start_l",
    "fuel_end_l",
    "fuel_used_l",
    "elapsed_time_s",
    "zone_start_throttle_pct",
    "zone_start_zero_throttle",
    "has_lico",
    "lico_start_m",
    "lico_end_m",
    "lico_start_distance_before_brake_m",
    "lico_duration_s",
    "lico_distance_m",
    "throttle_release_rate_pct_per_s",
    "minimum_throttle_pct_before_brake",
    "average_throttle_pct_before_brake",
    "brake_start_m",
    "brake_start_speed_kph",
    "max_brake_pct",
    "min_speed_kph",
    "exit_speed_kph",
    "validity_label",
    "notes",
]

_ZONE_PASS_SCHEMA = {
    "file_name": pl.String,
    "run_id": pl.String,
    "lap_number": pl.Int64,
    "zone_id": pl.String,
    "turn_numbers": pl.List(pl.Int64),
    "display_label": pl.String,
    "lico_intensity": pl.String,
    "zone_start_m": pl.Float64,
    "lico_window_start_m": pl.Float64,
    "brake_reference_m": pl.Float64,
    "zone_end_m": pl.Float64,
    "fuel_start_l": pl.Float64,
    "fuel_end_l": pl.Float64,
    "fuel_used_l": pl.Float64,
    "elapsed_time_s": pl.Float64,
    "zone_start_throttle_pct": pl.Float64,
    "zone_start_zero_throttle": pl.Boolean,
    "has_lico": pl.Boolean,
    "lico_start_m": pl.Float64,
    "lico_end_m": pl.Float64,
    "lico_start_distance_before_brake_m": pl.Float64,
    "lico_duration_s": pl.Float64,
    "lico_distance_m": pl.Float64,
    "throttle_release_rate_pct_per_s": pl.Float64,
    "minimum_throttle_pct_before_brake": pl.Float64,
    "average_throttle_pct_before_brake": pl.Float64,
    "brake_start_m": pl.Float64,
    "brake_start_speed_kph": pl.Float64,
    "max_brake_pct": pl.Float64,
    "min_speed_kph": pl.Float64,
    "exit_speed_kph": pl.Float64,
    "validity_label": pl.String,
    "notes": pl.String,
}
