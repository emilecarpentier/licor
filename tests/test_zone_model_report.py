from pathlib import Path

import polars as pl

from licor.reports import (
    create_zone_model_report_figure,
    write_zone_model_report_html,
)


def test_creates_zone_model_report_with_fuel_time_and_ratio_traces():
    model = pl.DataFrame(
        [
            _model_row("spa_t01", "T01", 0.0, 0.0, 0.0, None),
            _model_row("spa_t01", "T01", 50.0, 0.04, 0.10, 0.4),
            _model_row("spa_t01", "T01", 100.0, 0.07, 0.20, 0.35),
        ]
    )

    figure = create_zone_model_report_figure(model, title="Synthetic model")

    assert len(figure.data) == 3
    assert figure.layout.title.text == "Synthetic model"


def test_writes_zone_model_report_html(tmp_path: Path):
    figure = create_zone_model_report_figure(pl.DataFrame(), title="Empty")

    path = write_zone_model_report_html(figure, tmp_path / "model.html")

    assert path.exists()
    assert path.read_text(encoding="utf-8").startswith("<html>")


def _model_row(
    zone_id: str,
    display_label: str,
    distance_m: float,
    fuel_saved_l: float,
    time_lost_s: float,
    ratio_lps: float | None,
) -> dict[str, object]:
    return {
        "zone_id": zone_id,
        "display_label": display_label,
        "lico_distance_m": distance_m,
        "predicted_fuel_saved_l": fuel_saved_l,
        "predicted_time_lost_s": time_lost_s,
        "predicted_fuel_saved_per_second_lps": ratio_lps,
        "is_extrapolated": False,
        "model_status": "model_ready",
        "quality_flags": ["clean_signal"],
        "source_bin_count": 3,
        "nonzero_source_bin_count": 2,
        "observed_max_lico_distance_m": 100.0,
    }
