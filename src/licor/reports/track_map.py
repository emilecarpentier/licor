from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import polars as pl


EARTH_RADIUS_M = 6_371_000.0


def load_geojson_track_points(
    path: str | Path,
    *,
    target_length_m: float | None = None,
) -> pl.DataFrame:
    feature = _first_linestring_feature(path)
    coordinates = feature["geometry"]["coordinates"]
    points = lonlat_to_local_xy(coordinates)
    points = add_cumulative_distance(points)
    if target_length_m is not None:
        points = scale_lap_distance(points, target_length_m=target_length_m)
    return points


def lonlat_to_local_xy(coordinates: list[list[float]]) -> pl.DataFrame:
    if not coordinates:
        return pl.DataFrame({"lon": [], "lat": [], "x_m": [], "y_m": []})

    lon0 = sum(point[0] for point in coordinates) / len(coordinates)
    lat0 = sum(point[1] for point in coordinates) / len(coordinates)
    lat0_rad = math.radians(lat0)
    rows = []
    for lon, lat in coordinates:
        x_m = math.radians(lon - lon0) * EARTH_RADIUS_M * math.cos(lat0_rad)
        y_m = math.radians(lat - lat0) * EARTH_RADIUS_M
        rows.append({"lon": lon, "lat": lat, "x_m": x_m, "y_m": y_m})
    return pl.DataFrame(rows)


def add_cumulative_distance(points: pl.DataFrame) -> pl.DataFrame:
    if points.is_empty():
        return points.with_columns(pl.lit(None).alias("lap_distance_m"))

    distances = [0.0]
    rows = points.select("x_m", "y_m").iter_rows(named=True)
    previous = next(rows)
    cumulative = 0.0
    for row in rows:
        cumulative += math.hypot(
            float(row["x_m"]) - float(previous["x_m"]),
            float(row["y_m"]) - float(previous["y_m"]),
        )
        distances.append(cumulative)
        previous = row
    return points.with_columns(pl.Series("lap_distance_m", distances))


def scale_lap_distance(points: pl.DataFrame, *, target_length_m: float) -> pl.DataFrame:
    if points.is_empty():
        return points
    source_length = float(points["lap_distance_m"].max())
    if source_length <= 0.0:
        return points
    scale = target_length_m / source_length
    return points.with_columns((pl.col("lap_distance_m") * scale).alias("lap_distance_m"))


def _first_linestring_feature(path: str | Path) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as file:
        data = json.load(file)

    if data["type"] == "Feature":
        features = [data]
    else:
        features = data.get("features", [])
    for feature in features:
        if feature.get("geometry", {}).get("type") == "LineString":
            return feature
    msg = f"No LineString feature found in {path}"
    raise ValueError(msg)
