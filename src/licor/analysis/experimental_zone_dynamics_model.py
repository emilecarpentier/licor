from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import polars as pl


@dataclass(frozen=True)
class ExperimentalZoneDynamicsModelConfig:
    target_column: str = "time_lost_vs_baseline_s"
    direct_feature_columns: tuple[str, ...] = ("lico_distance_before_brake_m",)
    dynamics_feature_columns: tuple[str, ...] = (
        "lico_distance_before_brake_m",
        "brake_start_delta_vs_baseline_m",
        "brake_start_speed_delta_vs_baseline_kph",
        "apex_speed_delta_vs_baseline_kph",
        "exit_speed_delta_vs_baseline_kph",
        "carcass_temp_zone_start_delta_vs_baseline_c",
        "stint_index",
    )
    min_training_rows: int = 6
    ridge_alpha: float = 1e-6
    improvement_threshold_r2: float = 0.05


def compare_zone_dynamics_models(
    zone_dynamics: pl.DataFrame,
    *,
    config: ExperimentalZoneDynamicsModelConfig | None = None,
) -> pl.DataFrame:
    """Compare a direct 1D time model with an experimental dynamics-aware model."""

    model_config = config or ExperimentalZoneDynamicsModelConfig()
    if zone_dynamics.is_empty():
        return _empty_zone_dynamics_model_comparison_frame()

    _require_columns(zone_dynamics, {"zone_id", "display_label", model_config.target_column})

    rows = []
    for zone_id in sorted(zone_dynamics["zone_id"].unique().to_list()):
        zone_frame = zone_dynamics.filter(pl.col("zone_id") == zone_id)
        display_label = str(zone_frame["display_label"][0])
        rows.append(
            _comparison_row(
                zone_id=zone_id,
                display_label=display_label,
                zone_frame=zone_frame,
                config=model_config,
            )
        )

    return pl.DataFrame(rows, schema=_MODEL_COMPARISON_SCHEMA, strict=False).select(
        _MODEL_COMPARISON_COLUMNS
    )


def score_zone_dynamics_models(
    zone_dynamics: pl.DataFrame,
    *,
    config: ExperimentalZoneDynamicsModelConfig | None = None,
) -> pl.DataFrame:
    """Return per-row direct and dynamics-model predictions for diagnostic review."""

    model_config = config or ExperimentalZoneDynamicsModelConfig()
    if zone_dynamics.is_empty():
        return _empty_zone_dynamics_model_score_frame()

    _require_columns(
        zone_dynamics,
        {
            "zone_id",
            "display_label",
            "run_id",
            "lap_number",
            model_config.target_column,
        },
    )

    rows: list[dict[str, object]] = []
    for zone_id in sorted(zone_dynamics["zone_id"].unique().to_list()):
        zone_frame = zone_dynamics.filter(pl.col("zone_id") == zone_id)
        display_label = str(zone_frame["display_label"][0])
        direct_features = _available_features(zone_frame, model_config.direct_feature_columns)
        dynamics_features = _available_features(zone_frame, model_config.dynamics_feature_columns)
        direct_fit = _fit_model(
            zone_frame,
            feature_columns=direct_features,
            target_column=model_config.target_column,
            config=model_config,
        )
        dynamics_fit = _fit_model(
            zone_frame,
            feature_columns=dynamics_features,
            target_column=model_config.target_column,
            config=model_config,
        )
        score_frame = zone_frame.select(
            "zone_id",
            "display_label",
            "run_id",
            "lap_number",
            pl.col(model_config.target_column).alias("observed_time_lost_vs_baseline_s"),
        )

        direct_predictions = _prediction_series(
            zone_frame,
            fit=direct_fit,
            feature_columns=direct_features,
            alias="direct_predicted_time_lost_vs_baseline_s",
        )
        dynamics_predictions = _prediction_series(
            zone_frame,
            fit=dynamics_fit,
            feature_columns=dynamics_features,
            alias="dynamics_predicted_time_lost_vs_baseline_s",
        )
        score_frame = score_frame.with_columns(direct_predictions, dynamics_predictions).with_columns(
            (
                pl.col("observed_time_lost_vs_baseline_s")
                - pl.col("direct_predicted_time_lost_vs_baseline_s")
            ).alias("direct_residual_time_lost_s"),
            (
                pl.col("observed_time_lost_vs_baseline_s")
                - pl.col("dynamics_predicted_time_lost_vs_baseline_s")
            ).alias("dynamics_residual_time_lost_s"),
            pl.lit("|".join(direct_features)).alias("direct_feature_columns"),
            pl.lit("|".join(dynamics_features)).alias("dynamics_feature_columns"),
            pl.lit(display_label).alias("display_label"),
        )
        rows.extend(score_frame.iter_rows(named=True))

    if not rows:
        return _empty_zone_dynamics_model_score_frame()
    return pl.DataFrame(rows, schema=_MODEL_SCORE_SCHEMA, strict=False).select(_MODEL_SCORE_COLUMNS)


def _comparison_row(
    *,
    zone_id: str,
    display_label: str,
    zone_frame: pl.DataFrame,
    config: ExperimentalZoneDynamicsModelConfig,
) -> dict[str, object]:
    direct_features = _available_features(zone_frame, config.direct_feature_columns)
    dynamics_features = _available_features(zone_frame, config.dynamics_feature_columns)
    direct_fit = _fit_model(
        zone_frame,
        feature_columns=direct_features,
        target_column=config.target_column,
        config=config,
    )
    dynamics_fit = _fit_model(
        zone_frame,
        feature_columns=dynamics_features,
        target_column=config.target_column,
        config=config,
    )

    status = _status(direct_fit, dynamics_fit)
    recommendation = _recommendation(direct_fit, dynamics_fit, config=config)
    return {
        "zone_id": zone_id,
        "display_label": display_label,
        "training_row_count": int(zone_frame.height),
        "direct_row_count": direct_fit.row_count,
        "dynamics_row_count": dynamics_fit.row_count,
        "direct_feature_columns": "|".join(direct_features),
        "dynamics_feature_columns": "|".join(dynamics_features),
        "direct_r2": direct_fit.r2,
        "direct_mae_s": direct_fit.mae,
        "direct_rmse_s": direct_fit.rmse,
        "dynamics_r2": dynamics_fit.r2,
        "dynamics_mae_s": dynamics_fit.mae,
        "dynamics_rmse_s": dynamics_fit.rmse,
        "r2_improvement": _difference(dynamics_fit.r2, direct_fit.r2),
        "mae_improvement_s": _difference(direct_fit.mae, dynamics_fit.mae),
        "status": status,
        "recommendation": recommendation,
    }


@dataclass(frozen=True)
class _FitResult:
    row_count: int
    prediction_mask: np.ndarray
    predictions: np.ndarray | None
    r2: float | None
    mae: float | None
    rmse: float | None


def _fit_model(
    frame: pl.DataFrame,
    *,
    feature_columns: tuple[str, ...],
    target_column: str,
    config: ExperimentalZoneDynamicsModelConfig,
) -> _FitResult:
    if not feature_columns:
        return _FitResult(
            row_count=0,
            prediction_mask=np.zeros(frame.height, dtype=bool),
            predictions=None,
            r2=None,
            mae=None,
            rmse=None,
        )

    subset = frame.select(*feature_columns, target_column).to_pandas()
    mask = subset.notnull().all(axis=1).to_numpy(dtype=bool)
    row_count = int(mask.sum())
    if row_count < max(config.min_training_rows, len(feature_columns) + 2):
        return _FitResult(
            row_count=row_count,
            prediction_mask=mask,
            predictions=None,
            r2=None,
            mae=None,
            rmse=None,
        )

    matrix = subset.loc[mask, list(feature_columns)].to_numpy(dtype=float)
    target = subset.loc[mask, target_column].to_numpy(dtype=float)
    design = np.column_stack([np.ones(len(matrix)), matrix])
    regularizer = np.eye(design.shape[1]) * config.ridge_alpha
    regularizer[0, 0] = 0.0
    coeffs = np.linalg.solve(design.T @ design + regularizer, design.T @ target)
    predictions = design @ coeffs
    residuals = target - predictions
    baseline = target - target.mean()
    total_sum_squares = float(np.square(baseline).sum())
    residual_sum_squares = float(np.square(residuals).sum())
    r2 = 1.0 - residual_sum_squares / total_sum_squares if total_sum_squares > 0 else None
    mae = float(np.abs(residuals).mean())
    rmse = float(np.sqrt(np.square(residuals).mean()))
    return _FitResult(
        row_count=row_count,
        prediction_mask=mask,
        predictions=predictions,
        r2=r2,
        mae=mae,
        rmse=rmse,
    )


def _prediction_series(
    frame: pl.DataFrame,
    *,
    fit: _FitResult,
    feature_columns: tuple[str, ...],
    alias: str,
) -> pl.Series:
    values: list[float | None] = [None] * frame.height
    if fit.predictions is not None:
        prediction_values = iter(fit.predictions.tolist())
        for index, include_row in enumerate(fit.prediction_mask.tolist()):
            if include_row:
                values[index] = float(next(prediction_values))
    return pl.Series(alias, values, dtype=pl.Float64)


def _available_features(frame: pl.DataFrame, candidates: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(column for column in candidates if column in frame.columns)


def _status(direct_fit: _FitResult, dynamics_fit: _FitResult) -> str:
    if direct_fit.r2 is None and dynamics_fit.r2 is None:
        return "insufficient_data"
    if direct_fit.r2 is not None and dynamics_fit.r2 is None:
        return "direct_only"
    if direct_fit.r2 is None and dynamics_fit.r2 is not None:
        return "dynamics_only"
    return "comparable"


def _recommendation(
    direct_fit: _FitResult,
    dynamics_fit: _FitResult,
    *,
    config: ExperimentalZoneDynamicsModelConfig,
) -> str:
    if direct_fit.r2 is None and dynamics_fit.r2 is None:
        return "collect_more_data"
    if direct_fit.r2 is not None and dynamics_fit.r2 is None:
        return "direct_model_only"
    if direct_fit.r2 is None and dynamics_fit.r2 is not None:
        return "dynamics_model_promising"
    assert direct_fit.r2 is not None
    assert dynamics_fit.r2 is not None
    if dynamics_fit.r2 >= direct_fit.r2 + config.improvement_threshold_r2:
        return "dynamics_explains_more_variance"
    if direct_fit.r2 > dynamics_fit.r2 + config.improvement_threshold_r2:
        return "direct_model_still_stronger"
    return "no_material_difference"


def _difference(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return left - right


def _require_columns(frame: pl.DataFrame, required: set[str]) -> None:
    missing = sorted(required - set(frame.columns))
    if missing:
        missing_text = ", ".join(missing)
        raise ValueError(f"experimental zone dynamics data is missing required columns: {missing_text}")


_MODEL_COMPARISON_COLUMNS = [
    "zone_id",
    "display_label",
    "training_row_count",
    "direct_row_count",
    "dynamics_row_count",
    "direct_feature_columns",
    "dynamics_feature_columns",
    "direct_r2",
    "direct_mae_s",
    "direct_rmse_s",
    "dynamics_r2",
    "dynamics_mae_s",
    "dynamics_rmse_s",
    "r2_improvement",
    "mae_improvement_s",
    "status",
    "recommendation",
]

_MODEL_COMPARISON_SCHEMA = {
    "zone_id": pl.String,
    "display_label": pl.String,
    "training_row_count": pl.Int64,
    "direct_row_count": pl.Int64,
    "dynamics_row_count": pl.Int64,
    "direct_feature_columns": pl.String,
    "dynamics_feature_columns": pl.String,
    "direct_r2": pl.Float64,
    "direct_mae_s": pl.Float64,
    "direct_rmse_s": pl.Float64,
    "dynamics_r2": pl.Float64,
    "dynamics_mae_s": pl.Float64,
    "dynamics_rmse_s": pl.Float64,
    "r2_improvement": pl.Float64,
    "mae_improvement_s": pl.Float64,
    "status": pl.String,
    "recommendation": pl.String,
}

_MODEL_SCORE_COLUMNS = [
    "zone_id",
    "display_label",
    "run_id",
    "lap_number",
    "observed_time_lost_vs_baseline_s",
    "direct_predicted_time_lost_vs_baseline_s",
    "dynamics_predicted_time_lost_vs_baseline_s",
    "direct_residual_time_lost_s",
    "dynamics_residual_time_lost_s",
    "direct_feature_columns",
    "dynamics_feature_columns",
]

_MODEL_SCORE_SCHEMA = {
    "zone_id": pl.String,
    "display_label": pl.String,
    "run_id": pl.String,
    "lap_number": pl.Int64,
    "observed_time_lost_vs_baseline_s": pl.Float64,
    "direct_predicted_time_lost_vs_baseline_s": pl.Float64,
    "dynamics_predicted_time_lost_vs_baseline_s": pl.Float64,
    "direct_residual_time_lost_s": pl.Float64,
    "dynamics_residual_time_lost_s": pl.Float64,
    "direct_feature_columns": pl.String,
    "dynamics_feature_columns": pl.String,
}


def _empty_zone_dynamics_model_comparison_frame() -> pl.DataFrame:
    return pl.DataFrame(schema=_MODEL_COMPARISON_SCHEMA)


def _empty_zone_dynamics_model_score_frame() -> pl.DataFrame:
    return pl.DataFrame(schema=_MODEL_SCORE_SCHEMA)
