from __future__ import annotations

from pathlib import Path

import plotly.graph_objects as go
import polars as pl
from plotly.subplots import make_subplots


STATUS_COLORS = {
    "model_ready": "#2563eb",
    "diagnostic_only": "#d97706",
    "low_data": "#9333ea",
    "review_excluded": "#6b7280",
}


def create_zone_model_report_figure(
    zone_models: pl.DataFrame,
    *,
    title: str,
) -> go.Figure:
    """Create a faceted Plotly report for fitted zone model curves."""

    if zone_models.is_empty():
        figure = go.Figure()
        figure.update_layout(title=title, template="plotly_white")
        return figure

    zones = list(
        zone_models.select("zone_id", "display_label")
        .unique(subset=["zone_id"], keep="first")
        .sort("zone_id")
        .iter_rows(named=True)
    )
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
        status = str(model["model_status"][0])
        color = STATUS_COLORS.get(status, "#111827")

        _add_model_trace(
            figure,
            model,
            metric_column="predicted_fuel_saved_l",
            name=f"{status} model",
            color=color,
            row=row_index,
            col=1,
            shown_legends=shown_legends,
        )
        _add_model_trace(
            figure,
            model,
            metric_column="predicted_time_lost_s",
            name=f"{status} model",
            color=color,
            row=row_index,
            col=2,
            shown_legends=shown_legends,
            showlegend_override=False,
        )
        _add_model_trace(
            figure,
            model.filter(pl.col("predicted_fuel_saved_per_second_lps").is_not_null()),
            metric_column="predicted_fuel_saved_per_second_lps",
            name=f"{status} usable ratio",
            color=color,
            row=row_index,
            col=3,
            shown_legends=shown_legends,
            line_dash="dash",
        )

    figure.update_layout(
        title=title,
        template="plotly_white",
        height=max(420, 260 * len(zones)),
        legend_title_text="model item",
        hovermode="closest",
    )
    figure.update_xaxes(title_text="LICO distance before brake (m)")
    figure.update_yaxes(title_text="fuel saved (L)", col=1)
    figure.update_yaxes(title_text="time lost (s)", col=2)
    figure.update_yaxes(title_text="fuel saved / second (L/s)", col=3)
    return figure


def write_zone_model_report_html(figure: go.Figure, path: str | Path) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure.write_html(output_path, include_plotlyjs="cdn")
    return output_path


def _add_model_trace(
    figure: go.Figure,
    model: pl.DataFrame,
    *,
    metric_column: str,
    name: str,
    color: str,
    row: int,
    col: int,
    shown_legends: set[str],
    line_dash: str | None = None,
    showlegend_override: bool | None = None,
) -> None:
    if model.is_empty():
        return

    showlegend = name not in shown_legends if showlegend_override is None else showlegend_override
    shown_legends.add(name)
    figure.add_trace(
        go.Scatter(
            x=model["lico_distance_m"].to_list(),
            y=model[metric_column].to_list(),
            mode="lines+markers",
            name=name,
            legendgroup=name,
            showlegend=showlegend,
            line={"color": color, "width": 2, "dash": line_dash},
            marker={"color": color, "size": 5},
            customdata=_model_customdata(model),
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


def _model_customdata(model: pl.DataFrame) -> list[list[object]]:
    return [
        [
            row["display_label"],
            row["model_status"],
            _format_quality_flags(row["quality_flags"]),
        ]
        for row in model.iter_rows(named=True)
    ]


def _format_quality_flags(flags: object) -> str:
    if flags is None:
        return ""
    if isinstance(flags, str):
        return flags
    return "|".join(str(flag) for flag in flags)
