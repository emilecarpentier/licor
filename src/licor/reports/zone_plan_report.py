from __future__ import annotations

from pathlib import Path
from typing import Any

import plotly.graph_objects as go
import polars as pl
from plotly.subplots import make_subplots

from licor.reports.zone_model_report import STATUS_COLORS


PLAN_SELECTED_COLOR = "#16a34a"
PLAN_ZERO_COLOR = "#6b7280"


def create_zone_plan_report_figure(
    zone_models: pl.DataFrame,
    zone_plan: pl.DataFrame,
    *,
    title: str,
) -> go.Figure:
    """Create a faceted report showing selected optimizer points on model curves."""

    zones = _zone_rows(zone_models, zone_plan)
    if not zones:
        figure = go.Figure()
        figure.update_layout(title=title, template="plotly_white")
        return figure

    subplot_titles = []
    for zone in zones:
        label = str(zone["display_label"])
        subplot_titles.extend([f"{label} fuel", f"{label} time", f"{label} ratio"])

    figure = make_subplots(
        rows=len(zones),
        cols=3,
        subplot_titles=subplot_titles,
        horizontal_spacing=0.06,
        vertical_spacing=min(0.08, 0.65 / len(zones)),
    )

    shown_legends: set[str] = set()
    for row_index, zone in enumerate(zones, start=1):
        zone_id = str(zone["zone_id"])
        model = zone_models.filter(pl.col("zone_id") == zone_id).sort("lico_distance_m")
        plan = zone_plan.filter(pl.col("zone_id") == zone_id)

        _add_model_traces(
            figure,
            model,
            row=row_index,
            shown_legends=shown_legends,
        )
        _add_plan_marker_traces(
            figure,
            plan,
            row=row_index,
            shown_legends=shown_legends,
        )

    figure.update_layout(
        title=title,
        template="plotly_white",
        height=max(420, 260 * len(zones)),
        legend_title_text="plan item",
        hovermode="closest",
    )
    figure.update_xaxes(title_text="LICO distance before brake (m)")
    figure.update_yaxes(title_text="fuel saved (L)", col=1)
    figure.update_yaxes(title_text="time lost (s)", col=2)
    figure.update_yaxes(title_text="fuel saved / second (L/s)", col=3)
    return figure


def write_zone_plan_report_html(figure: go.Figure, path: str | Path) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure.write_html(output_path, include_plotlyjs="cdn")
    return output_path


def _zone_rows(zone_models: pl.DataFrame, zone_plan: pl.DataFrame) -> list[dict[str, Any]]:
    frames = []
    for frame in (zone_plan, zone_models):
        if not frame.is_empty():
            frames.append(frame.select("zone_id", "display_label"))
    if not frames:
        return []
    return list(
        pl.concat(frames)
        .unique(subset=["zone_id"], keep="first")
        .sort("zone_id")
        .iter_rows(named=True)
    )


def _add_model_traces(
    figure: go.Figure,
    model: pl.DataFrame,
    *,
    row: int,
    shown_legends: set[str],
) -> None:
    if model.is_empty():
        return

    status = str(model["model_status"][0])
    color = STATUS_COLORS.get(status, "#111827")
    for metric_column, col, line_dash, legend_suffix in (
        ("predicted_fuel_saved_l", 1, None, "model"),
        ("predicted_time_lost_s", 2, None, "model"),
        ("predicted_fuel_saved_per_second_lps", 3, "dash", "usable ratio"),
    ):
        metric_model = model
        if metric_column == "predicted_fuel_saved_per_second_lps":
            metric_model = model.filter(pl.col(metric_column).is_not_null())
        if metric_model.is_empty():
            continue

        name = f"{status} {legend_suffix}"
        showlegend = name not in shown_legends
        shown_legends.add(name)
        figure.add_trace(
            go.Scatter(
                x=metric_model["lico_distance_m"].to_list(),
                y=metric_model[metric_column].to_list(),
                mode="lines+markers",
                name=name,
                legendgroup=name,
                showlegend=showlegend,
                line={"color": color, "width": 2, "dash": line_dash},
                marker={"color": color, "size": 5},
                customdata=_model_customdata(metric_model),
                hovertemplate=(
                    "zone=%{customdata[0]}<br>"
                    "status=%{customdata[1]}<br>"
                    "flags=%{customdata[2]}<br>"
                    "LICO=%{x:.1f} m<br>"
                    "%{y:.4f}<extra></extra>"
                ),
            ),
            row=row,
            col=col,
        )


def _add_plan_marker_traces(
    figure: go.Figure,
    plan: pl.DataFrame,
    *,
    row: int,
    shown_legends: set[str],
) -> None:
    if plan.is_empty():
        return

    plan_row = plan.row(0, named=True)
    is_selected = bool(plan_row["is_selected_for_lico"])
    color = PLAN_SELECTED_COLOR if is_selected else PLAN_ZERO_COLOR
    legend_name = "selected plan point" if is_selected else "zero-LICO plan point"
    showlegend = legend_name not in shown_legends
    shown_legends.add(legend_name)

    distance_m = float(plan_row["selected_lico_distance_m"])
    fuel_saved_l = float(plan_row["predicted_fuel_saved_l"])
    time_lost_s = float(plan_row["predicted_time_lost_s"])
    ratio_lps = fuel_saved_l / time_lost_s if time_lost_s > 0.0 else None
    customdata = [_plan_customdata(plan_row)]

    for y_value, col, show_marker in (
        (fuel_saved_l, 1, True),
        (time_lost_s, 2, True),
        (ratio_lps, 3, ratio_lps is not None),
    ):
        if not show_marker:
            continue
        figure.add_trace(
            go.Scatter(
                x=[distance_m],
                y=[y_value],
                mode="markers",
                name=legend_name,
                legendgroup=legend_name,
                showlegend=showlegend,
                marker={
                    "color": color,
                    "size": 12,
                    "symbol": "diamond",
                    "line": {"color": "#111827", "width": 1},
                },
                customdata=customdata,
                hovertemplate=(
                    "zone=%{customdata[0]}<br>"
                    "selected=%{customdata[1]}<br>"
                    "role=%{customdata[2]}<br>"
                    "status=%{customdata[3]}<br>"
                    "LICO=%{x:.1f} m<br>"
                    "fuel=%{customdata[4]:.4f} L<br>"
                    "time=%{customdata[5]:.4f} s<br>"
                    "total fuel=%{customdata[6]:.4f} L/lap<br>"
                    "total time=%{customdata[7]:.4f} s/lap<br>"
                    "surplus=%{customdata[8]:.4f} L/lap<br>"
                    "flags=%{customdata[9]}<extra></extra>"
                ),
            ),
            row=row,
            col=col,
        )
        showlegend = False


def _model_customdata(model: pl.DataFrame) -> list[list[object]]:
    return [
        [
            row["display_label"],
            row["model_status"],
            _format_quality_flags(row["quality_flags"]),
        ]
        for row in model.iter_rows(named=True)
    ]


def _plan_customdata(plan_row: dict[str, Any]) -> list[object]:
    return [
        plan_row["display_label"],
        plan_row["is_selected_for_lico"],
        plan_row.get("strategy_role", ""),
        plan_row["model_status"],
        plan_row["predicted_fuel_saved_l"],
        plan_row["predicted_time_lost_s"],
        plan_row["total_predicted_fuel_saved_l"],
        plan_row["total_predicted_time_lost_s"],
        plan_row["fuel_surplus_l"],
        _format_quality_flags(plan_row.get("quality_flags")),
    ]


def _format_quality_flags(flags: object) -> str:
    if flags is None:
        return ""
    if isinstance(flags, str):
        return flags
    return "|".join(str(flag) for flag in flags)
