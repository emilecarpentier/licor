from __future__ import annotations

from html import escape
from pathlib import Path

import plotly.graph_objects as go
import polars as pl
from plotly.subplots import make_subplots


def create_experimental_live_replay_validation_figure(
    handoff_summary: pl.DataFrame,
    *,
    title: str,
) -> go.Figure:
    figure = make_subplots(
        rows=2,
        cols=2,
        subplot_titles=(
            "Mean cue on-time rate",
            "Median absolute cue error (m)",
            "Mean next-lap fuel error (L)",
            "Mean next-lap time error (s)",
        ),
        horizontal_spacing=0.12,
        vertical_spacing=0.16,
    )
    if handoff_summary.is_empty():
        figure.update_layout(title=title, template="plotly_white")
        return figure

    summary = (
        handoff_summary.group_by(["variant_name", "planning_mode"])
        .agg(
            pl.col("cue_on_time_rate").mean().alias("mean_cue_on_time_rate"),
            pl.col("median_abs_cue_error_m").mean().alias(
                "mean_median_abs_cue_error_m"
            ),
            pl.col("fuel_saved_total_error_l").mean().alias("mean_fuel_saved_error_l"),
            pl.col("time_lost_total_error_s").mean().alias("mean_time_lost_error_s"),
        )
        .with_columns(
            (
                pl.col("variant_name") + pl.lit(" | ") + pl.col("planning_mode")
            ).alias("variant_mode")
        )
        .sort("variant_mode")
    )

    x_values = summary["variant_mode"].to_list()
    figure.add_trace(
        go.Bar(x=x_values, y=summary["mean_cue_on_time_rate"].to_list(), name="on-time"),
        row=1,
        col=1,
    )
    figure.add_trace(
        go.Bar(
            x=x_values,
            y=summary["mean_median_abs_cue_error_m"].to_list(),
            name="median abs cue error",
            showlegend=False,
        ),
        row=1,
        col=2,
    )
    figure.add_trace(
        go.Bar(
            x=x_values,
            y=summary["mean_fuel_saved_error_l"].to_list(),
            name="fuel error",
            showlegend=False,
        ),
        row=2,
        col=1,
    )
    figure.add_trace(
        go.Bar(
            x=x_values,
            y=summary["mean_time_lost_error_s"].to_list(),
            name="time error",
            showlegend=False,
        ),
        row=2,
        col=2,
    )

    figure.update_layout(
        title=title,
        template="plotly_white",
        height=760,
        showlegend=False,
    )
    figure.update_xaxes(title_text="variant | mode", row=2)
    figure.update_xaxes(title_text="variant | mode", row=1)
    figure.update_yaxes(title_text="rate", row=1, col=1)
    figure.update_yaxes(title_text="m", row=1, col=2)
    figure.update_yaxes(title_text="L", row=2, col=1)
    figure.update_yaxes(title_text="s", row=2, col=2)
    return figure


def write_experimental_live_replay_validation_report_html(
    *,
    title: str,
    figure: go.Figure,
    handoff_summary: pl.DataFrame,
    zone_summary: pl.DataFrame,
    validation_rows: pl.DataFrame,
    path: str | Path,
) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    handoff_columns = [
        "variant_name",
        "planning_mode",
        "scenario_id",
        "current_lap_number",
        "next_lap_number",
        "planned_zone_ids",
        "telemetry_available",
        "cue_on_time_rate",
        "median_abs_cue_error_m",
        "executed_zone_count",
        "expected_fuel_saved_total_l",
        "actual_fuel_saved_total_l",
        "fuel_saved_total_error_l",
        "expected_time_lost_total_s",
        "actual_time_lost_total_s",
        "time_lost_total_error_s",
    ]
    zone_columns = [
        "variant_name",
        "planning_mode",
        "display_label",
        "telemetry_available_rate",
        "cue_on_time_rate",
        "median_abs_cue_error_m",
        "zone_execution_rate",
        "mean_expected_fuel_saved_l",
        "mean_actual_fuel_saved_l",
        "mean_fuel_saved_error_l",
        "mean_expected_time_lost_s",
        "mean_actual_time_lost_s",
        "mean_time_lost_error_s",
    ]
    validation_columns = [
        "variant_name",
        "planning_mode",
        "scenario_id",
        "current_lap_number",
        "next_lap_number",
        "display_label",
        "selected_lico_distance_m",
        "next_recommended_range_start_m",
        "next_recommended_range_end_m",
        "telemetry_available",
        "trigger_status",
        "cue_error_m",
        "actual_lift_distance_before_brake_m",
        "actual_distance_before_brake_error_m",
        "actual_fuel_saved_l",
        "fuel_saved_error_l",
        "actual_time_lost_s",
        "time_lost_error_s",
    ]

    figure_html = figure.to_html(full_html=False, include_plotlyjs="cdn")
    handoff_table = _frame_table_html(
        handoff_summary.sort(
            [
                "variant_name",
                "scenario_id",
                "current_lap_number",
            ]
        ),
        columns=handoff_columns,
        max_rows=80,
    )
    zone_table = _frame_table_html(zone_summary, columns=zone_columns, max_rows=40)
    validation_table = _frame_table_html(
        validation_rows.sort(
            [
                "variant_name",
                "scenario_id",
                "current_lap_number",
                "zone_id",
            ]
        ),
        columns=validation_columns,
        max_rows=120,
    )

    html = f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>{escape(title)}</title>
    <style>
      body {{
        font-family: Arial, sans-serif;
        margin: 24px;
        color: #1f2937;
        background: #ffffff;
      }}
      h1, h2 {{
        margin-bottom: 8px;
      }}
      p {{
        max-width: 1100px;
        line-height: 1.45;
      }}
      .section {{
        margin-top: 28px;
      }}
      table {{
        border-collapse: collapse;
        width: 100%;
        margin-top: 12px;
        font-size: 14px;
      }}
      th, td {{
        border: 1px solid #d1d5db;
        padding: 6px 8px;
        text-align: left;
      }}
      th {{
        background: #f3f4f6;
      }}
      .note {{
        color: #4b5563;
        font-size: 14px;
      }}
    </style>
  </head>
  <body>
    <h1>{escape(title)}</h1>
    <p>
      This is the closest offline version of the future live cue loop.
      Each handoff starts from what happened on lap N, turns the adaptive
      recommendation for lap N+1 into a replay-ready live cue plan, replays
      it on the recorded telemetry of lap N+1, then compares that to the
      observed lift-and-coast outcome on lap N+1.
    </p>

    <div class="section">
      <h2>High-Level Replay Validation</h2>
      <p class="note">
        Read this first. The figure compresses four questions:
        are cues firing on time, how large is the cue timing error,
        and how far the next-lap fuel/time outcome lands from the expectation.
      </p>
      {figure_html}
    </div>

    <div class="section">
      <h2>Lap-to-Lap Handoff Summary</h2>
      <p class="note">
        One row equals one concrete handoff: lap N observed, lap N+1 recommended,
        lap N+1 replayed when telemetry is available, then compared to the
        observed next-lap LICO outcome only when a lift is actually observed.
      </p>
      {handoff_table}
    </div>

    <div class="section">
      <h2>Zone Summary</h2>
      <p class="note">
        This is the compact per-zone view of the adaptive replay loop.
      </p>
      {zone_table}
    </div>

    <div class="section">
      <h2>Detailed Validation Rows</h2>
      <p class="note">
        Use this table when you want to inspect a specific zone recommendation
        and compare the recommended distance to what was actually observed.
      </p>
      {validation_table}
    </div>
  </body>
</html>
"""
    output_path.write_text(html, encoding="utf-8")
    return output_path


def _frame_table_html(
    frame: pl.DataFrame,
    *,
    columns: list[str],
    max_rows: int,
) -> str:
    if frame.is_empty():
        return '<p class="note">No rows available.</p>'
    selected_columns = [column for column in columns if column in frame.columns]
    table_frame = frame.select(selected_columns).head(max_rows)
    return table_frame.to_pandas().to_html(index=False, border=0)
