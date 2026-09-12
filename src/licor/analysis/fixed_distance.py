"""Fixed-distance outcomes on native channel timestamps, without held-value bias."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import polars as pl

from licor.ingestion import LmuTelemetryDatabase


def distance_anchors(samples: pl.DataFrame, time_column: str = "ts") -> pl.DataFrame:
    """Keep the first timestamp of each distance update within one moving lap.

    A backward-asof join repeats a scoring distance until its next update. Using
    the last repeat as an interpolation anchor compresses the true update
    interval and introduces an endpoint-dependent timing error.
    """
    ordered = samples.sort(time_column)
    if ordered.is_empty():
        raise ValueError("empty lap")
    distances = ordered["lap_distance_m"].to_numpy()
    resets = np.flatnonzero(np.diff(distances) < -100.0)
    if len(resets):
        if len(resets) > 1 or resets[0] > 20:
            raise ValueError("unexpected distance reset inside lap")
        ordered = ordered.slice(int(resets[0]) + 1)
    anchors = ordered.filter(pl.col("lap_distance_m").diff().fill_null(1.0) != 0.0)
    if anchors.height < 2 or np.any(np.diff(anchors["lap_distance_m"]) <= 0):
        raise ValueError("distance must increase between update anchors")
    return anchors


def crossing_time(
    anchors: pl.DataFrame, distance_m: float, time_column: str = "ts"
) -> float:
    distances = anchors["lap_distance_m"].to_numpy()
    if not distances[0] <= distance_m <= distances[-1]:
        raise ValueError(f"lap does not bracket {distance_m} m")
    return float(np.interp(distance_m, distances, anchors[time_column].to_numpy()))


@dataclass
class NativeDistanceTrace:
    """Read channels once; evaluate each channel on its own timestamp grid."""

    distance: pl.DataFrame
    fuel: pl.DataFrame
    speed: pl.DataFrame
    intervals: dict

    @classmethod
    def from_database(cls, telemetry: LmuTelemetryDatabase) -> NativeDistanceTrace:
        return cls(
            telemetry.fixed_channel("Lap Dist").rename({"value": "lap_distance_m"}),
            telemetry.fixed_channel("Fuel Level"),
            telemetry.fixed_channel("Ground Speed"),
            {lap.lap_number: lap for lap in telemetry.lap_intervals()},
        )

    def lap_anchors(self, lap_number: int) -> pl.DataFrame:
        lap = self.intervals[lap_number]
        return distance_anchors(
            self.distance.filter(
                (pl.col("ts") >= lap.start_ts) & (pl.col("ts") < lap.end_ts)
            )
        )

    def outcome(self, lap_number: int, start_m: float, end_m: float) -> dict:
        if end_m <= start_m:
            raise ValueError("fixed-distance outcome must not wrap the lap")
        anchors = self.lap_anchors(lap_number)
        start_ts = crossing_time(anchors, start_m)
        end_ts = crossing_time(anchors, end_m)
        fuel_ts = self.fuel["ts"].to_numpy()
        fuel_values = self.fuel["value"].to_numpy()
        speed_ts = self.speed["ts"].to_numpy()
        speed_values = self.speed["value"].to_numpy()
        if start_ts < fuel_ts[0] or end_ts > fuel_ts[-1]:
            raise ValueError("fuel channel does not cover outcome")
        return {
            "elapsed_time_s": end_ts - start_ts,
            "fuel_used_l": float(
                np.interp(start_ts, fuel_ts, fuel_values)
                - np.interp(end_ts, fuel_ts, fuel_values)
            ),
            "entry_speed_kph": float(np.interp(start_ts, speed_ts, speed_values)),
            "exit_speed_kph": float(np.interp(end_ts, speed_ts, speed_values)),
            "start_ts": start_ts,
            "end_ts": end_ts,
            "maximum_distance_update_interval_s": float(anchors["ts"].diff().max()),
        }
