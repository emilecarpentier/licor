from __future__ import annotations

from html import escape
from pathlib import Path

import plotly.graph_objects as go
import polars as pl
from plotly.subplots import make_subplots


def create_experimental_lap_replanner_report_figure(
    lap_summary: pl.DataFrame,
    *,
    title: str,
) -> go.Figure:
    """Visualize lap-by-lap replanning state across scenarios and planning modes."""

    figure = make_subplots(
        rows=2,
        cols=2,
        subplot_titles=(
            "Remaining fuel target",
            "Next-lap fuel target",
            "Cumulative fuel saved",
            "Cumulative time lost",
        ),
        horizontal_spacing=0.1,
        vertical_spacing=0.16,
    )
    if lap_summary.is_empty():
        figure.update_layout(title=title, template="plotly_white")
        return figure

    shown = set()
    for scenario_id in sorted(lap_summary["scenario_id"].unique().to_list()):
        for planning_mode in sorted(
            lap_summary.filter(pl.col("scenario_id") == scenario_id)["planning_mode"]
            .unique()
            .to_list()
        ):
            frame = lap_summary.filter(
                (pl.col("scenario_id") == scenario_id)
                & (pl.col("planning_mode") == planning_mode)
            ).sort("lap_number")
            trace_name = f"{scenario_id} | {planning_mode}"
            showlegend = trace_name not in shown
            shown.add(trace_name)
            _add_trace(
                figure,
                frame,
                trace_name=trace_name,
                y_column="fuel_target_remaining_after_l",
                row=1,
                col=1,
                showlegend=showlegend,
            )
            _add_trace(
                figure,
                frame,
                trace_name=trace_name,
                y_column="next_lap_target_fuel_saved_l",
                row=1,
                col=2,
                showlegend=False,
            )
            _add_trace(
                figure,
                frame,
                trace_name=trace_name,
                y_column="cumulative_fuel_saved_l",
                row=2,
                col=1,
                showlegend=False,
            )
            _add_trace(
                figure,
                frame,
                trace_name=trace_name,
                y_column="cumulative_time_lost_s",
                row=2,
                col=2,
                showlegend=False,
            )

    figure.update_layout(
        title=title,
        template="plotly_white",
        height=760,
        hovermode="x unified",
        legend_title_text="scenario | mode",
    )
    figure.update_xaxes(title_text="lap number", row=2)
    figure.update_xaxes(title_text="lap number", row=1)
    figure.update_yaxes(title_text="L", row=1, col=1)
    figure.update_yaxes(title_text="L/lap", row=1, col=2)
    figure.update_yaxes(title_text="L", row=2, col=1)
    figure.update_yaxes(title_text="s", row=2, col=2)
    return figure


def write_experimental_lap_replanner_report_html(
    figure: go.Figure,
    path: str | Path,
) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure.write_html(output_path, include_plotlyjs="cdn")
    return output_path


def create_experimental_zone_execution_calibration_figure(
    zone_summary: pl.DataFrame,
    *,
    title: str,
) -> go.Figure:
    figure = make_subplots(
        rows=2,
        cols=1,
        subplot_titles=(
            "Mean fuel-scale delta versus global execution scale",
            "Mean time-scale delta versus global execution scale",
        ),
        vertical_spacing=0.14,
    )
    if zone_summary.is_empty():
        figure.update_layout(title=title, template="plotly_white")
        return figure

    shown = set()
    for variant_name in sorted(zone_summary["variant_name"].unique().to_list()):
        for planning_mode in sorted(
            zone_summary.filter(pl.col("variant_name") == variant_name)["planning_mode"]
            .unique()
            .to_list()
        ):
            frame = zone_summary.filter(
                (pl.col("variant_name") == variant_name)
                & (pl.col("planning_mode") == planning_mode)
            ).sort("zone_id")
            trace_name = f"{variant_name} | {planning_mode}"
            showlegend = trace_name not in shown
            shown.add(trace_name)
            customdata = list(
                zip(
                    frame["sample_count"].to_list(),
                    frame["relieved_fuel_count"].to_list(),
                    frame["penalized_fuel_count"].to_list(),
                    frame["mean_support_rows"].to_list(),
                    frame["execution_rate"].to_list(),
                )
            )
            x_values = _display_labels(frame)
            figure.add_trace(
                go.Bar(
                    x=x_values,
                    y=frame["mean_fuel_scale_delta_vs_global"].to_list(),
                    name=trace_name,
                    legendgroup=trace_name,
                    showlegend=showlegend,
                    customdata=customdata,
                    hovertemplate=(
                        "zone=%{x}<br>"
                        "fuel delta=%{y:.4f}<br>"
                        "samples=%{customdata[0]}<br>"
                        "relieved count=%{customdata[1]}<br>"
                        "penalized count=%{customdata[2]}<br>"
                        "mean support rows=%{customdata[3]:.2f}<br>"
                        "execution rate=%{customdata[4]:.2f}<extra></extra>"
                    ),
                ),
                row=1,
                col=1,
            )
            figure.add_trace(
                go.Bar(
                    x=x_values,
                    y=frame["mean_time_scale_delta_vs_global"].to_list(),
                    name=trace_name,
                    legendgroup=trace_name,
                    showlegend=False,
                    customdata=customdata,
                    hovertemplate=(
                        "zone=%{x}<br>"
                        "time delta=%{y:.4f}<br>"
                        "samples=%{customdata[0]}<br>"
                        "relieved count=%{customdata[1]}<br>"
                        "penalized count=%{customdata[2]}<br>"
                        "mean support rows=%{customdata[3]:.2f}<br>"
                        "execution rate=%{customdata[4]:.2f}<extra></extra>"
                    ),
                ),
                row=2,
                col=1,
            )

    figure.update_layout(
        title=title,
        template="plotly_white",
        height=840,
        barmode="group",
        legend_title_text="variant | mode",
    )
    figure.update_xaxes(title_text="zone", row=2, col=1)
    figure.update_yaxes(title_text="delta scale", row=1, col=1)
    figure.update_yaxes(title_text="delta scale", row=2, col=1)
    return figure


def write_experimental_lap_replanner_validation_report_html(
    *,
    title: str,
    replanner_figure: go.Figure,
    calibration_figure: go.Figure,
    zone_summary: pl.DataFrame,
    live_transition_preview: pl.DataFrame,
    path: str | Path,
) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    zone_columns = [
        "variant_name",
        "planning_mode",
        "display_label",
        "mean_fuel_scale_delta_vs_global",
        "mean_time_scale_delta_vs_global",
        "relieved_fuel_count",
        "penalized_fuel_count",
        "mean_support_rows",
        "execution_rate",
    ]
    transition_columns = [
        "variant_name",
        "planning_mode",
        "scenario_id",
        "current_lap_number",
        "next_lap_number",
        "next_zone_id",
        "next_selected_lico_distance_m",
        "next_applied_driver_fuel_execution_scale",
        "next_applied_driver_time_execution_scale",
        "next_applied_zone_execution_support_rows",
        "next_lap_target_fuel_saved_l",
    ]

    replanner_html = replanner_figure.to_html(
        full_html=False,
        include_plotlyjs="cdn",
    )
    calibration_html = calibration_figure.to_html(
        full_html=False,
        include_plotlyjs=False,
    )
    zone_table_html = _frame_table_html(zone_summary, columns=zone_columns, max_rows=40)
    transition_table_html = _frame_table_html(
        live_transition_preview,
        columns=transition_columns,
        max_rows=60,
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
      This validation view is meant to answer two practical questions:
      how the adaptive replanner changed after recent driver execution,
      and what the next-lap handoff would look like for a live cue loop.
    </p>

    <div class="section">
      <h2>Lap-by-Lap Replanning State</h2>
      <p class="note">
        Read this first for the big picture: remaining target, next-lap demand,
        cumulative fuel saved, and cumulative local time cost.
      </p>
      {replanner_html}
    </div>

    <div class="section">
      <h2>Zone Execution Calibration</h2>
      <p class="note">
        Positive deltas mean the zone-specific memory relaxed the global
        calibration for that zone. Negative deltas mean the zone was penalized
        relative to the global driver scale.
      </p>
      {calibration_html}
      {zone_table_html}
    </div>

    <div class="section">
      <h2>Next-Lap Live Handoff Preview</h2>
      <p class="note">
        Each row below shows what the replanner would hand to a live cue layer
        for the next lap: target, zone, selected distance, and the calibration
        actually applied to that zone.
      </p>
      {transition_table_html}
    </div>
  </body>
</html>
"""
    output_path.write_text(html, encoding="utf-8")
    return output_path


def create_experimental_shadow_adaptive_summary_figure(
    handoff_summary: pl.DataFrame,
    zone_summary: pl.DataFrame,
    *,
    title: str,
) -> go.Figure:
    figure = make_subplots(
        rows=2,
        cols=2,
        subplot_titles=(
            "Changed zones per handoff",
            "Mean absolute distance delta per handoff (m)",
            "Mean distance delta by zone (m)",
            "Expected fuel delta per handoff (L)",
        ),
        horizontal_spacing=0.12,
        vertical_spacing=0.16,
    )
    if handoff_summary.is_empty() and zone_summary.is_empty():
        figure.update_layout(title=title, template="plotly_white")
        return figure

    if not handoff_summary.is_empty():
        x_values = [
            f"{row['run_id']} | {int(row['current_lap_number'])}->{int(row['next_lap_number'])}"
            for row in handoff_summary.iter_rows(named=True)
        ]
        customdata = list(
            zip(
                handoff_summary["changed_zone_ids"].to_list(),
                handoff_summary["adaptive_driver_fuel_execution_scale"].to_list(),
                handoff_summary["adaptive_driver_time_execution_scale"].to_list(),
            )
        )
        figure.add_trace(
            go.Bar(
                x=x_values,
                y=handoff_summary["changed_zone_count"].to_list(),
                name="changed zones",
                customdata=customdata,
                hovertemplate=(
                    "handoff=%{x}<br>"
                    "changed zones=%{y}<br>"
                    "zone ids=%{customdata[0]}<br>"
                    "fuel scale=%{customdata[1]:.3f}<br>"
                    "time scale=%{customdata[2]:.3f}<extra></extra>"
                ),
            ),
            row=1,
            col=1,
        )
        figure.add_trace(
            go.Bar(
                x=x_values,
                y=handoff_summary["mean_abs_distance_delta_m"].to_list(),
                name="mean abs distance delta",
                showlegend=False,
                hovertemplate="handoff=%{x}<br>mean abs delta=%{y:.3f} m<extra></extra>",
            ),
            row=1,
            col=2,
        )
        figure.add_trace(
            go.Bar(
                x=x_values,
                y=handoff_summary["expected_fuel_saved_delta_l"].to_list(),
                name="fuel delta",
                showlegend=False,
                hovertemplate="handoff=%{x}<br>fuel delta=%{y:.4f} L<extra></extra>",
            ),
            row=2,
            col=2,
        )

    if not zone_summary.is_empty():
        figure.add_trace(
            go.Bar(
                x=_display_labels(zone_summary),
                y=zone_summary["mean_distance_delta_m"].to_list(),
                name="zone mean distance delta",
                showlegend=False,
                hovertemplate="zone=%{x}<br>mean delta=%{y:.3f} m<extra></extra>",
            ),
            row=2,
            col=1,
        )

    figure.update_layout(
        title=title,
        template="plotly_white",
        height=780,
        showlegend=False,
    )
    figure.update_yaxes(title_text="count", row=1, col=1)
    figure.update_yaxes(title_text="m", row=1, col=2)
    figure.update_yaxes(title_text="m", row=2, col=1)
    figure.update_yaxes(title_text="L", row=2, col=2)
    return figure


def write_experimental_shadow_adaptive_report_html(
    *,
    title: str,
    replanner_figure: go.Figure,
    shadow_figure: go.Figure,
    handoff_summary: pl.DataFrame,
    zone_summary: pl.DataFrame,
    transition_comparison: pl.DataFrame,
    live_transition_preview: pl.DataFrame,
    replay_handoff_summary: pl.DataFrame,
    replay_zone_summary: pl.DataFrame,
    path: str | Path,
) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    handoff_columns = [
        "run_id",
        "current_lap_number",
        "next_lap_number",
        "next_lap_target_fuel_saved_l",
        "static_zone_count",
        "adaptive_zone_count",
        "changed_zone_count",
        "added_zone_count",
        "removed_zone_count",
        "mean_abs_distance_delta_m",
        "expected_fuel_saved_delta_l",
        "expected_time_lost_delta_s",
        "changed_zone_ids",
    ]
    zone_columns = [
        "display_label",
        "sample_count",
        "changed_count",
        "added_count",
        "removed_count",
        "mean_distance_delta_m",
        "mean_abs_distance_delta_m",
        "mean_expected_fuel_saved_delta_l",
        "mean_expected_time_lost_delta_s",
    ]
    comparison_columns = [
        "run_id",
        "current_lap_number",
        "next_lap_number",
        "display_label",
        "change_type",
        "static_selected_lico_distance_m",
        "adaptive_selected_lico_distance_m",
        "distance_delta_m",
        "static_expected_fuel_saved_l",
        "adaptive_expected_fuel_saved_l",
        "expected_fuel_saved_delta_l",
        "static_expected_time_lost_s",
        "adaptive_expected_time_lost_s",
        "expected_time_lost_delta_s",
    ]
    preview_columns = [
        "current_lap_number",
        "next_lap_number",
        "next_zone_id",
        "next_selected_lico_distance_m",
        "next_applied_driver_fuel_execution_scale",
        "next_applied_driver_time_execution_scale",
        "next_applied_zone_execution_support_rows",
        "next_lap_target_fuel_saved_l",
    ]
    replay_columns = [
        "run_id",
        "current_lap_number",
        "next_lap_number",
        "planned_zone_ids",
        "cue_on_time_rate",
        "median_abs_cue_error_m",
        "expected_fuel_saved_total_l",
        "actual_fuel_saved_total_l",
        "fuel_saved_total_error_l",
        "expected_time_lost_total_s",
        "actual_time_lost_total_s",
        "time_lost_total_error_s",
    ]

    replanner_html = replanner_figure.to_html(full_html=False, include_plotlyjs="cdn")
    shadow_html = shadow_figure.to_html(full_html=False, include_plotlyjs=False)
    handoff_table = _frame_table_html(handoff_summary, columns=handoff_columns, max_rows=40)
    zone_table = _frame_table_html(zone_summary, columns=zone_columns, max_rows=30)
    comparison_table = _frame_table_html(
        transition_comparison.sort(
            ["run_id", "current_lap_number", "next_lap_number", "zone_id"]
        ),
        columns=comparison_columns,
        max_rows=80,
    )
    preview_table = _frame_table_html(
        live_transition_preview.filter(pl.col("planning_mode") == "adaptive").sort(
            ["scenario_id", "current_lap_number", "next_zone_id"]
        ),
        columns=preview_columns,
        max_rows=80,
    )
    replay_handoff_table = _frame_table_html(
        replay_handoff_summary.sort(["run_id", "current_lap_number", "next_lap_number"]),
        columns=replay_columns,
        max_rows=40,
    )
    replay_zone_table = _frame_table_html(
        replay_zone_summary,
        columns=[
            "display_label",
            "sample_count",
            "cue_on_time_rate",
            "median_abs_cue_error_m",
            "zone_execution_rate",
            "mean_fuel_saved_error_l",
            "mean_time_lost_error_s",
        ],
        max_rows=30,
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
        max-width: 1120px;
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
      This shadow view keeps the live baseline in charge and asks a quieter
      question: after lap N was actually driven, what would the adaptive
      controller have changed for lap N+1, and would those changes have stayed
      small enough to be readable for the driver?
    </p>

    <div class="section">
      <h2>Observed Baseline Session State</h2>
      <p class="note">
        This is the lap-by-lap replanner view restricted to the real static live
        baseline session used as shadow input.
      </p>
      {replanner_html}
    </div>

    <div class="section">
      <h2>Static vs Shadow Adaptive Delta</h2>
      <p class="note">
        Read this first when judging controller stability. It shows how many
        zones changed, how far those distance edits moved, and whether the
        shadow controller was trying to add or remove meaningful fuel demand.
      </p>
      {shadow_html}
      {handoff_table}
      {zone_table}
    </div>

    <div class="section">
      <h2>Detailed Static vs Adaptive Changes</h2>
      <p class="note">
        One row equals one zone on one handoff. Compare the frozen static
        distance to the shadow adaptive distance directly.
      </p>
      {comparison_table}
    </div>

    <div class="section">
      <h2>Adaptive Next-Lap Preview</h2>
      <p class="note">
        This is the exact next-lap adaptive handoff that would be ready for a
        future live bridge once the shadow controller is trusted enough.
      </p>
      {preview_table}
    </div>

    <div class="section">
      <h2>Replay Check On The Actual Next Lap</h2>
      <p class="note">
        This remains offline: the shadow adaptive next-lap plan is replayed on
        the recorded telemetry of the actual next lap, then compared to what the
        driver really did.
      </p>
      {replay_handoff_table}
      {replay_zone_table}
    </div>
  </body>
</html>
"""
    output_path.write_text(html, encoding="utf-8")
    return output_path


def write_experimental_guarded_adaptive_handoff_report_html(
    *,
    title: str,
    summary: pl.DataFrame,
    detail: pl.DataFrame,
    guarded_live_transition_preview: pl.DataFrame,
    guarded_live_plan: pl.DataFrame,
    guarded_replay_handoff_summary: pl.DataFrame,
    path: str | Path,
) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    summary_table = _frame_table_html(
        summary,
        columns=[
            "run_id",
            "current_lap_number",
            "next_lap_number",
            "next_lap_target_fuel_saved_l",
            "raw_changed_zone_count",
            "guarded_changed_zone_count",
            "clamped_zone_count",
            "blocked_zone_count",
            "guarded_zone_count",
            "mean_guarded_abs_distance_delta_m",
            "guarded_expected_fuel_saved_total_l",
            "guarded_expected_time_lost_total_s",
            "target_met_after_guardrails",
            "guardrail_reasons",
        ],
        max_rows=40,
    )
    detail_table = _frame_table_html(
        detail.sort(["run_id", "current_lap_number", "next_lap_number", "zone_id"]),
        columns=[
            "run_id",
            "current_lap_number",
            "next_lap_number",
            "display_label",
            "support_rows",
            "static_selected_lico_distance_m",
            "raw_adaptive_selected_lico_distance_m",
            "guarded_selected_lico_distance_m",
            "raw_distance_delta_m",
            "guarded_distance_delta_m",
            "guardrail_reason",
            "keep_in_guarded_plan",
            "static_expected_fuel_saved_l",
            "raw_adaptive_expected_fuel_saved_l",
            "guarded_expected_fuel_saved_l",
            "static_expected_time_lost_s",
            "raw_adaptive_expected_time_lost_s",
            "guarded_expected_time_lost_s",
        ],
        max_rows=80,
    )
    preview_table = _frame_table_html(
        guarded_live_transition_preview.sort(
            ["scenario_id", "current_lap_number", "next_lap_number", "next_zone_id"]
        ),
        columns=[
            "current_lap_number",
            "next_lap_number",
            "next_zone_id",
            "next_selected_lico_distance_m",
            "next_expected_fuel_saved_by_zone_l",
            "next_expected_time_lost_by_zone_s",
            "next_lap_target_fuel_saved_l",
            "next_lap_expected_fuel_saved_l",
            "next_lap_expected_time_lost_s",
        ],
        max_rows=80,
    )
    live_plan_table = _frame_table_html(
        guarded_live_plan.sort(["current_lap_number", "next_lap_number", "zone_id"]),
        columns=[
            "plan_id",
            "run_id",
            "current_lap_number",
            "next_lap_number",
            "display_label",
            "selected_lico_distance_m",
            "planned_lift_start_m",
            "cue_distance_m",
            "expected_fuel_saved_l",
            "expected_time_lost_s",
            "cue_latency_compensation_distance_m",
        ],
        max_rows=80,
    )
    replay_table = _frame_table_html(
        guarded_replay_handoff_summary.sort(["run_id", "current_lap_number", "next_lap_number"]),
        columns=[
            "run_id",
            "current_lap_number",
            "next_lap_number",
            "planned_zone_ids",
            "cue_on_time_rate",
            "median_abs_cue_error_m",
            "expected_fuel_saved_total_l",
            "actual_fuel_saved_total_l",
            "fuel_saved_total_error_l",
            "expected_time_lost_total_s",
            "actual_time_lost_total_s",
            "time_lost_total_error_s",
        ],
        max_rows=40,
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
        color: #111827;
        line-height: 1.5;
      }}
      .section {{
        margin-bottom: 28px;
      }}
      h1, h2 {{
        margin-bottom: 8px;
      }}
      .note {{
        color: #4b5563;
        margin-bottom: 12px;
      }}
      table {{
        border-collapse: collapse;
        width: 100%;
        font-size: 13px;
      }}
      th, td {{
        border: 1px solid #d1d5db;
        padding: 6px 8px;
        text-align: left;
      }}
      th {{
        background: #f3f4f6;
      }}
    </style>
  </head>
  <body>
    <h1>{escape(title)}</h1>
    <p class="note">
      This report turns a raw shadow adaptive recommendation into an
      operator-facing between-laps handoff. Raw adaptive changes are bounded by
      explicit guardrails before a new next-lap live plan is exported.
    </p>

    <div class="section">
      <h2>Guarded Handoff Summary</h2>
      <p class="note">
        This is the compact answer to "did the guardrails keep the handoff
        readable while still meeting the next-lap fuel target?"
      </p>
      {summary_table}
    </div>

    <div class="section">
      <h2>Zone-Level Guardrail Detail</h2>
      <p class="note">
        Compare the static baseline distance, the raw adaptive distance, and the
        guarded distance that would actually be handed to a live operator.
      </p>
      {detail_table}
    </div>

    <div class="section">
      <h2>Guarded Next-Lap Preview</h2>
      <p class="note">
        These rows are the guarded adaptive preview before conversion into the
        live-cue runner plan format.
      </p>
      {preview_table}
    </div>

    <div class="section">
      <h2>Guarded Live Plan Export</h2>
      <p class="note">
        This is the runner-ready plan that could be loaded for the next lap
        after operator confirmation.
      </p>
      {live_plan_table}
    </div>

    <div class="section">
      <h2>Replay Check On The Actual Next Lap</h2>
      <p class="note">
        The guarded plan is replayed on the actual observed next lap so the
        handoff can be judged before any live authority is granted.
      </p>
      {replay_table}
    </div>
  </body>
</html>
"""
    output_path.write_text(html, encoding="utf-8")
    return output_path


def _add_trace(
    figure: go.Figure,
    frame: pl.DataFrame,
    *,
    trace_name: str,
    y_column: str,
    row: int,
    col: int,
    showlegend: bool,
) -> None:
    figure.add_trace(
        go.Scatter(
            x=frame["lap_number"].to_list(),
            y=frame[y_column].to_list(),
            mode="lines+markers",
            name=trace_name,
            showlegend=showlegend,
            customdata=list(
                zip(
                    frame["scenario_event"].to_list(),
                    frame["execution_quality"].to_list(),
                    frame["next_lap_selected_zone_ids"].to_list(),
                    _frame_column_or_default(frame, "fuel_load_band", "").to_list(),
                    _frame_column_or_default(frame, "tire_regime_label", "").to_list(),
                    _frame_column_or_default(frame, "lap_context_label", "").to_list(),
                )
            ),
            hovertemplate=(
                "lap=%{x}<br>"
                "value=%{y:.4f}<br>"
                "event=%{customdata[0]}<br>"
                "quality=%{customdata[1]}<br>"
                "next zones=%{customdata[2]}<br>"
                "fuel band=%{customdata[3]}<br>"
                "tire regime=%{customdata[4]}<br>"
                "context=%{customdata[5]}<extra></extra>"
            ),
        ),
        row=row,
        col=col,
    )


def _frame_column_or_default(
    frame: pl.DataFrame,
    column_name: str,
    default: str,
) -> pl.Series:
    if column_name in frame.columns:
        return frame[column_name]
    return pl.Series([default] * frame.height)


def _display_labels(frame: pl.DataFrame) -> list[str]:
    if "display_label" in frame.columns:
        return [
            str(label) if label is not None and str(label).strip() else str(zone_id)
            for label, zone_id in zip(
                frame["display_label"].to_list(),
                frame["zone_id"].to_list(),
                strict=False,
            )
        ]
    return [str(zone_id) for zone_id in frame["zone_id"].to_list()]


def _frame_table_html(
    frame: pl.DataFrame,
    *,
    columns: list[str],
    max_rows: int,
) -> str:
    if frame.is_empty():
        return "<p class=\"note\">No rows available.</p>"
    selected_columns = [column for column in columns if column in frame.columns]
    table_frame = frame.select(selected_columns).head(max_rows)
    return table_frame.to_pandas().to_html(index=False, border=0)
