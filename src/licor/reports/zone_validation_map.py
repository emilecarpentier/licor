from __future__ import annotations

from pathlib import Path

import plotly.graph_objects as go
import polars as pl


def build_track_validation_points(
    samples: pl.DataFrame,
    *,
    x_column: str | None = None,
    y_column: str | None = None,
) -> tuple[pl.DataFrame, str]:
    """Return plotting points for a circuit map, or a distance strip fallback."""

    if x_column and y_column and {x_column, y_column}.issubset(samples.columns):
        points = samples.select(
            "lap_distance_m",
            pl.col(x_column).alias("x_m"),
            pl.col(y_column).alias("y_m"),
        )
        return _clean_track_points(points), "xy"

    y_expr = (
        pl.col("path_lateral_m").alias("y_m")
        if "path_lateral_m" in samples.columns
        else pl.lit(0.0).alias("y_m")
    )
    points = samples.select(
        "lap_distance_m",
        pl.col("lap_distance_m").alias("x_m"),
        y_expr,
    )
    return _clean_track_points(points), "distance_strip"


def zone_markers_from_proposals(
    track_points: pl.DataFrame,
    proposals: pl.DataFrame,
    *,
    map_distance_offset_m: float = 0.0,
) -> pl.DataFrame:
    marker_rows = []
    track_length_m = _track_length_m(track_points)
    for row in proposals.iter_rows(named=True):
        for marker_type, distance_column in (
            ("zone_start", "proposed_lico_window_start_m"),
            ("brake_reference", "proposed_brake_reference_m"),
            ("none_median_brake", "push_brake_reference_median_m"),
            ("validation_end", "proposed_end_distance_m"),
        ):
            if distance_column not in proposals.columns or row[distance_column] is None:
                continue
            lap_distance_m = float(row[distance_column])
            map_distance_m = _map_distance(
                lap_distance_m,
                track_length_m=track_length_m,
                map_distance_offset_m=map_distance_offset_m,
            )
            position = interpolate_track_position(track_points, map_distance_m)
            if position is None:
                continue
            marker_rows.append(
                {
                    "zone_id": row["zone_id"],
                    "display_label": row["display_label"],
                    "marker_type": marker_type,
                    "lap_distance_m": lap_distance_m,
                    "map_distance_m": map_distance_m,
                    "x_m": position["x_m"],
                    "y_m": position["y_m"],
                }
            )
    if not marker_rows:
        return pl.DataFrame()
    return pl.DataFrame(marker_rows)


def interpolate_track_position(
    track_points: pl.DataFrame,
    lap_distance_m: float,
) -> dict[str, float] | None:
    if track_points.is_empty():
        return None

    points = track_points.sort("lap_distance_m")
    distances = [float(value) for value in points["lap_distance_m"].to_list()]
    xs = [float(value) for value in points["x_m"].to_list()]
    ys = [float(value) for value in points["y_m"].to_list()]
    if lap_distance_m < distances[0] or lap_distance_m > distances[-1]:
        return None

    for index, distance in enumerate(distances):
        if lap_distance_m == distance:
            return {"x_m": xs[index], "y_m": ys[index]}
        if lap_distance_m < distance:
            previous_distance = distances[index - 1]
            span = distance - previous_distance
            fraction = 0.0 if span == 0 else (lap_distance_m - previous_distance) / span
            return {
                "x_m": xs[index - 1] + (xs[index] - xs[index - 1]) * fraction,
                "y_m": ys[index - 1] + (ys[index] - ys[index - 1]) * fraction,
            }
    return {"x_m": xs[-1], "y_m": ys[-1]}


def create_zone_validation_figure(
    track_points: pl.DataFrame,
    markers: pl.DataFrame,
    *,
    projection: str,
    title: str,
) -> go.Figure:
    figure = go.Figure()
    figure.add_trace(
        go.Scatter(
            x=track_points["x_m"].to_list(),
            y=track_points["y_m"].to_list(),
            mode="lines",
            name="track reference",
            line={"color": "#2f3a4a", "width": 3},
            hovertemplate="distance=%{customdata:.1f} m<extra></extra>",
            customdata=track_points["lap_distance_m"].to_list(),
        )
    )

    for marker_type, color, symbol in (
        ("zone_start", "#2ca25f", "circle"),
        ("brake_reference", "#de2d26", "x"),
        ("none_median_brake", "#756bb1", "cross"),
        ("validation_end", "#3182bd", "diamond"),
    ):
        marker_rows = markers.filter(pl.col("marker_type") == marker_type)
        if marker_rows.is_empty():
            continue
        figure.add_trace(
            go.Scatter(
                x=marker_rows["x_m"].to_list(),
                y=marker_rows["y_m"].to_list(),
                mode="markers+text",
                name=marker_type,
                text=marker_rows["display_label"].to_list(),
                textposition="top center",
                marker={"color": color, "size": 10, "symbol": symbol},
                customdata=_marker_customdata(marker_rows),
                hovertemplate=(
                    "%{customdata[0]}<br>"
                    "%{customdata[1]}<br>"
                    "LMU distance=%{customdata[2]:.1f} m<br>"
                    "map distance=%{customdata[3]:.1f} m<extra></extra>"
                ),
            )
        )

    figure.update_layout(
        title=title,
        xaxis_title="x_m" if projection == "xy" else "lap_distance_m",
        yaxis_title="y_m" if projection == "xy" else "path_lateral_m",
        yaxis={"scaleanchor": "x"} if projection == "xy" else {},
        template="plotly_white",
        legend_title_text="zone marker",
    )
    return figure


def write_zone_validation_html(figure: go.Figure, path: str | Path) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure.write_html(output_path, include_plotlyjs="cdn")
    return output_path


def _clean_track_points(points: pl.DataFrame) -> pl.DataFrame:
    return (
        points.drop_nulls(["lap_distance_m", "x_m", "y_m"])
        .unique(subset=["lap_distance_m"], keep="first")
        .sort("lap_distance_m")
    )


def _marker_customdata(markers: pl.DataFrame) -> list[list[str | float]]:
    return [
        [
            row["display_label"],
            row["marker_type"],
            float(row["lap_distance_m"]),
            float(row["map_distance_m"]) if row.get("map_distance_m") is not None else None,
        ]
        for row in markers.iter_rows(named=True)
    ]


def _track_length_m(track_points: pl.DataFrame) -> float | None:
    if track_points.is_empty() or "lap_distance_m" not in track_points.columns:
        return None
    return float(track_points["lap_distance_m"].max())


def _map_distance(
    lap_distance_m: float,
    *,
    track_length_m: float | None,
    map_distance_offset_m: float,
) -> float:
    if track_length_m is None or track_length_m <= 0:
        return lap_distance_m + map_distance_offset_m
    return (lap_distance_m + map_distance_offset_m) % track_length_m
