from __future__ import annotations

from dataclasses import dataclass

import polars as pl

from licor.ingestion import LmuTelemetryDatabase


@dataclass(frozen=True)
class BrakeZoneDetectionConfig:
    brake_threshold_pct: float = 5.0
    min_brake_duration_s: float = 0.25
    max_merge_gap_s: float = 0.25
    max_merge_gap_m: float = 25.0


@dataclass(frozen=True)
class LicoZoneDetectionConfig:
    lift_start_throttle_pct: float = 99.0
    zero_input_throttle_pct: float = 1.0
    min_lift_duration_s: float = 0.20
    min_lift_distance_m: float = 10.0
    min_zero_input_duration_s: float = 0.10
    max_lookback_s: float = 8.0
    max_lookback_distance_m: float = 500.0
    max_lift_to_brake_gap_s: float = 1.0


def build_lap_telemetry(
    telemetry: LmuTelemetryDatabase,
    *,
    lap_numbers: set[int] | None = None,
) -> pl.DataFrame:
    """Build a normalized per-sample lap table on the Brake Pos timeline."""

    brake = _fixed_channel(telemetry, "Brake Pos", "brake_pct")
    aligned = (
        brake.join_asof(
            _fixed_channel(telemetry, "Throttle Pos", "throttle_pct"),
            on="ts",
            strategy="backward",
        )
        .join_asof(
            _fixed_channel(telemetry, "Lap Dist", "lap_distance_m"),
            on="ts",
            strategy="backward",
        )
        .join_asof(
            _fixed_channel(telemetry, "Ground Speed", "ground_speed_kph"),
            on="ts",
            strategy="backward",
        )
        .join_asof(
            _fixed_channel(telemetry, "Fuel Level", "fuel_level_l"),
            on="ts",
            strategy="backward",
        )
        .sort("ts")
    )

    frames = []
    selected_laps = lap_numbers or {interval.lap_number for interval in telemetry.lap_intervals()}
    for interval in telemetry.lap_intervals():
        if interval.lap_number not in selected_laps:
            continue
        lap = aligned.filter((pl.col("ts") >= interval.start_ts) & (pl.col("ts") < interval.end_ts))
        if lap.is_empty():
            continue
        frames.append(
            lap.with_columns(
                pl.lit(interval.lap_number).alias("lap_number"),
                pl.lit(interval.start_ts).alias("lap_start_ts"),
                pl.lit(interval.end_ts).alias("lap_end_ts"),
                (pl.col("ts") - interval.start_ts).alias("lap_elapsed_s"),
            ).select(
                "lap_number",
                "lap_start_ts",
                "lap_end_ts",
                "ts",
                "lap_elapsed_s",
                "lap_distance_m",
                "brake_pct",
                "throttle_pct",
                "ground_speed_kph",
                "fuel_level_l",
            )
        )

    if not frames:
        return pl.DataFrame()
    return pl.concat(frames).sort(["lap_number", "ts"])


def detect_brake_segments(
    samples: pl.DataFrame,
    *,
    config: BrakeZoneDetectionConfig | None = None,
) -> pl.DataFrame:
    detection_config = config or BrakeZoneDetectionConfig()
    return _detect_threshold_segments(
        samples,
        value_column="brake_pct",
        threshold=detection_config.brake_threshold_pct,
        min_duration_s=detection_config.min_brake_duration_s,
        segment_prefix="brake_segment",
    )


def detect_braking_zones(
    samples: pl.DataFrame,
    *,
    config: BrakeZoneDetectionConfig | None = None,
) -> pl.DataFrame:
    detection_config = config or BrakeZoneDetectionConfig()
    segments = detect_brake_segments(samples, config=detection_config)
    return merge_brake_segments(segments, config=detection_config)


def merge_brake_segments(
    segments: pl.DataFrame,
    *,
    config: BrakeZoneDetectionConfig | None = None,
) -> pl.DataFrame:
    if segments.is_empty():
        return segments

    detection_config = config or BrakeZoneDetectionConfig()
    rows = segments.sort(["lap_number", "start_ts"]).iter_rows(named=True)
    merged: list[dict[str, float | int]] = []
    active: dict[str, float | int] | None = None

    for row in rows:
        current = dict(row)
        if active is None:
            active = _start_merged_brake_zone(current)
            continue

        same_lap = int(current["lap_number"]) == int(active["lap_number"])
        gap_s = float(current["start_ts"]) - float(active["end_ts"])
        gap_m = float(current["start_lap_distance_m"]) - float(active["end_lap_distance_m"])
        should_merge = (
            same_lap
            and gap_s <= detection_config.max_merge_gap_s
            and gap_m <= detection_config.max_merge_gap_m
        )
        if should_merge:
            _extend_merged_brake_zone(active, current)
        else:
            merged.append(active)
            active = _start_merged_brake_zone(current)

    if active is not None:
        merged.append(active)

    for index, row in enumerate(merged, start=1):
        row["brake_zone_id"] = index

    return pl.DataFrame(merged).select(
        "brake_zone_id",
        "lap_number",
        "start_ts",
        "end_ts",
        "start_lap_distance_m",
        "end_lap_distance_m",
        "duration_s",
        "distance_m",
        "active_brake_duration_s",
        "peak_brake_pct",
        "mean_brake_pct",
        "brake_start_speed_kph",
        "min_speed_kph",
        "raw_segment_count",
    )


def detect_lift_and_coast_zones(
    samples: pl.DataFrame,
    braking_zones: pl.DataFrame,
    *,
    config: LicoZoneDetectionConfig | None = None,
) -> pl.DataFrame:
    if braking_zones.is_empty():
        return pl.DataFrame()

    detection_config = config or LicoZoneDetectionConfig()
    rows = []
    for brake_zone in braking_zones.sort(["lap_number", "start_ts"]).iter_rows(named=True):
        lap_samples = samples.filter(pl.col("lap_number") == brake_zone["lap_number"]).sort("ts")
        lookback = lap_samples.filter(
            (pl.col("ts") < brake_zone["start_ts"])
            & (pl.col("ts") >= float(brake_zone["start_ts"]) - detection_config.max_lookback_s)
            & (
                pl.col("lap_distance_m")
                >= float(brake_zone["start_lap_distance_m"])
                - detection_config.max_lookback_distance_m
            )
            & (pl.col("lap_distance_m") <= brake_zone["start_lap_distance_m"])
        )
        lift_segments = _detect_threshold_segments(
            lookback,
            value_column="throttle_pct",
            threshold=detection_config.lift_start_throttle_pct,
            min_duration_s=detection_config.min_lift_duration_s,
            segment_prefix="lico_segment",
            active_when_below=True,
        )
        if not lift_segments.is_empty():
            lift_segments = lift_segments.filter(
                (pl.col("distance_m") >= detection_config.min_lift_distance_m)
                & (
                    float(brake_zone["start_ts"]) - pl.col("end_ts")
                    <= detection_config.max_lift_to_brake_gap_s
                )
            )
            lift_segments = _filter_zero_input_lift_segments(
                lookback,
                lift_segments,
                config=detection_config,
            )

        if lift_segments.is_empty():
            rows.append(_empty_lico_row(brake_zone))
            continue

        lift = lift_segments.sort("end_ts").tail(1).row(0, named=True)
        rows.append(_lico_row(samples, brake_zone, lift))

    for index, row in enumerate(rows, start=1):
        row["lico_zone_id"] = index
    return pl.DataFrame(rows).select(
        "lico_zone_id",
        "brake_zone_id",
        "lap_number",
        "has_lico",
        "validity_label",
        "brake_start_m",
        "brake_start_ts",
        "lico_start_m",
        "lico_end_m",
        "lico_start_distance_before_brake_m",
        "lico_duration_s",
        "lico_distance_m",
        "minimum_throttle_pct_before_brake",
        "average_throttle_pct_before_brake",
        "throttle_release_rate_pct_per_s",
    )


def _fixed_channel(
    telemetry: LmuTelemetryDatabase,
    channel_name: str,
    output_column: str,
) -> pl.DataFrame:
    return (
        telemetry.fixed_channel(channel_name)
        .select("ts", pl.col("value").alias(output_column))
        .sort("ts")
    )


def _detect_threshold_segments(
    samples: pl.DataFrame,
    *,
    value_column: str,
    threshold: float,
    min_duration_s: float,
    segment_prefix: str,
    active_when_below: bool = False,
) -> pl.DataFrame:
    if samples.is_empty():
        return pl.DataFrame()

    rows = samples.sort(["lap_number", "ts"]).iter_rows(named=True)
    segments = []
    active_rows: list[dict[str, float | int]] = []
    active_lap: int | None = None

    for row in rows:
        lap_number = int(row["lap_number"])
        value = float(row[value_column])
        is_active = value <= threshold if active_when_below else value >= threshold
        if active_lap is not None and lap_number != active_lap:
            _append_segment(segments, active_rows, value_column, min_duration_s)
            active_rows = []
            active_lap = None

        if is_active:
            if not active_rows:
                active_lap = lap_number
            active_rows.append(dict(row))
        elif active_rows:
            _append_segment(segments, active_rows, value_column, min_duration_s)
            active_rows = []
            active_lap = None

    _append_segment(segments, active_rows, value_column, min_duration_s)

    for index, segment in enumerate(segments, start=1):
        segment[f"{segment_prefix}_id"] = index
    if not segments:
        return pl.DataFrame()
    return pl.DataFrame(segments)


def _append_segment(
    segments: list[dict[str, float | int]],
    active_rows: list[dict[str, float | int]],
    value_column: str,
    min_duration_s: float,
) -> None:
    if not active_rows:
        return

    start = active_rows[0]
    end = active_rows[-1]
    duration_s = float(end["ts"]) - float(start["ts"])
    if duration_s < min_duration_s:
        return

    values = [float(row[value_column]) for row in active_rows]
    speeds = [
        float(row["ground_speed_kph"])
        for row in active_rows
        if row.get("ground_speed_kph") is not None
    ]
    segments.append(
        {
            "lap_number": int(start["lap_number"]),
            "start_ts": float(start["ts"]),
            "end_ts": float(end["ts"]),
            "start_lap_distance_m": float(start["lap_distance_m"]),
            "end_lap_distance_m": float(end["lap_distance_m"]),
            "duration_s": duration_s,
            "distance_m": float(end["lap_distance_m"]) - float(start["lap_distance_m"]),
            "peak_brake_pct": max(values) if value_column == "brake_pct" else None,
            "mean_brake_pct": (
                sum(values) / len(values) if value_column == "brake_pct" else None
            ),
            "minimum_throttle_pct": min(values) if value_column == "throttle_pct" else None,
            "average_throttle_pct": (
                sum(values) / len(values) if value_column == "throttle_pct" else None
            ),
            "brake_start_speed_kph": speeds[0] if speeds else None,
            "min_speed_kph": min(speeds) if speeds else None,
        }
    )


def _start_merged_brake_zone(row: dict[str, float | int]) -> dict[str, float | int]:
    return {
        "lap_number": int(row["lap_number"]),
        "start_ts": float(row["start_ts"]),
        "end_ts": float(row["end_ts"]),
        "start_lap_distance_m": float(row["start_lap_distance_m"]),
        "end_lap_distance_m": float(row["end_lap_distance_m"]),
        "duration_s": float(row["duration_s"]),
        "distance_m": float(row["distance_m"]),
        "active_brake_duration_s": float(row["duration_s"]),
        "peak_brake_pct": float(row["peak_brake_pct"]),
        "mean_brake_pct": float(row["mean_brake_pct"]),
        "brake_start_speed_kph": float(row["brake_start_speed_kph"]),
        "min_speed_kph": float(row["min_speed_kph"]),
        "raw_segment_count": 1,
    }


def _extend_merged_brake_zone(
    active: dict[str, float | int],
    current: dict[str, float | int],
) -> None:
    previous_active_duration = float(active["active_brake_duration_s"])
    current_duration = float(current["duration_s"])
    total_active_duration = previous_active_duration + current_duration

    active["end_ts"] = float(current["end_ts"])
    active["end_lap_distance_m"] = float(current["end_lap_distance_m"])
    active["duration_s"] = float(active["end_ts"]) - float(active["start_ts"])
    active["distance_m"] = float(active["end_lap_distance_m"]) - float(
        active["start_lap_distance_m"]
    )
    active["active_brake_duration_s"] = total_active_duration
    active["peak_brake_pct"] = max(float(active["peak_brake_pct"]), float(current["peak_brake_pct"]))
    active["mean_brake_pct"] = (
        float(active["mean_brake_pct"]) * previous_active_duration
        + float(current["mean_brake_pct"]) * current_duration
    ) / total_active_duration
    active["min_speed_kph"] = min(float(active["min_speed_kph"]), float(current["min_speed_kph"]))
    active["raw_segment_count"] = int(active["raw_segment_count"]) + 1


def _empty_lico_row(brake_zone: dict[str, float | int]) -> dict[str, float | int | bool | str | None]:
    return {
        "brake_zone_id": int(brake_zone["brake_zone_id"]),
        "lap_number": int(brake_zone["lap_number"]),
        "has_lico": False,
        "validity_label": "not_detected",
        "brake_start_m": float(brake_zone["start_lap_distance_m"]),
        "brake_start_ts": float(brake_zone["start_ts"]),
        "lico_start_m": None,
        "lico_end_m": None,
        "lico_start_distance_before_brake_m": None,
        "lico_duration_s": None,
        "lico_distance_m": None,
        "minimum_throttle_pct_before_brake": None,
        "average_throttle_pct_before_brake": None,
        "throttle_release_rate_pct_per_s": None,
    }


def _filter_zero_input_lift_segments(
    samples: pl.DataFrame,
    lift_segments: pl.DataFrame,
    *,
    config: LicoZoneDetectionConfig,
) -> pl.DataFrame:
    rows = []
    for segment in lift_segments.iter_rows(named=True):
        zero_input = samples.filter(
            (pl.col("lap_number") == segment["lap_number"])
            & (pl.col("ts") >= segment["start_ts"])
            & (pl.col("ts") <= segment["end_ts"])
            & (pl.col("throttle_pct") <= config.zero_input_throttle_pct)
        )
        if zero_input.is_empty():
            continue
        zero_duration_s = float(zero_input["ts"][-1]) - float(zero_input["ts"][0])
        if zero_duration_s >= config.min_zero_input_duration_s:
            rows.append(segment)
    if not rows:
        return pl.DataFrame()
    return pl.DataFrame(rows)


def _lico_row(
    samples: pl.DataFrame,
    brake_zone: dict[str, float | int],
    lift: dict[str, float | int],
) -> dict[str, float | int | bool | str | None]:
    release_rate = _throttle_release_rate(samples, lift)
    return {
        "brake_zone_id": int(brake_zone["brake_zone_id"]),
        "lap_number": int(brake_zone["lap_number"]),
        "has_lico": True,
        "validity_label": "detected",
        "brake_start_m": float(brake_zone["start_lap_distance_m"]),
        "brake_start_ts": float(brake_zone["start_ts"]),
        "lico_start_m": float(lift["start_lap_distance_m"]),
        "lico_end_m": float(lift["end_lap_distance_m"]),
        "lico_start_distance_before_brake_m": float(brake_zone["start_lap_distance_m"])
        - float(lift["start_lap_distance_m"]),
        "lico_duration_s": float(lift["duration_s"]),
        "lico_distance_m": float(lift["distance_m"]),
        "minimum_throttle_pct_before_brake": float(lift["minimum_throttle_pct"]),
        "average_throttle_pct_before_brake": float(lift["average_throttle_pct"]),
        "throttle_release_rate_pct_per_s": release_rate,
    }


def _throttle_release_rate(samples: pl.DataFrame, lift: dict[str, float | int]) -> float | None:
    previous = (
        samples.filter(
            (pl.col("lap_number") == lift["lap_number"])
            & (pl.col("ts") < lift["start_ts"])
            & pl.col("throttle_pct").is_not_null()
        )
        .sort("ts")
        .tail(1)
    )
    if previous.is_empty():
        return None
    previous_row = previous.row(0, named=True)
    delta_t = float(lift["start_ts"]) - float(previous_row["ts"])
    if delta_t <= 0:
        return None
    return (float(previous_row["throttle_pct"]) - float(lift["minimum_throttle_pct"])) / delta_t
