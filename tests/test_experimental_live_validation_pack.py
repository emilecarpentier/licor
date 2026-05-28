from pathlib import Path

import json
import polars as pl

from licor.analysis.experimental_live_validation_pack import (
    ExperimentalLiveValidationPackConfig,
    build_live_validation_lap_notes_template,
    build_live_validation_run_metadata_template,
    build_live_validation_zone_signoff_template,
    write_experimental_live_validation_pack,
)


def test_builds_live_validation_run_metadata_template():
    metadata = build_live_validation_run_metadata_template(
        _plan(),
        config=ExperimentalLiveValidationPackConfig(
            variant_key="selected_zones_v1",
            recommended_run_nickname="recommendation_execution_selected_01",
            planned_lico_profile_id="spa_exp_live_candidate_selected_v1",
            planned_lico_profile_description="Selected candidate.",
            warmup_lap_count=2,
            scored_lap_count=3,
            pack_status="candidate",
            status_summary="Candidate pack.",
            operator_mode="adaptive_guarded_operator_preview",
        ),
    )

    assert metadata["collection_design"] == "recommendation_execution"
    assert metadata["audio_cue_plan_id"] == "plan_selected_v1"
    assert metadata["target_zones"] == ["spa_t01", "spa_t18"]


def test_builds_live_validation_lap_notes_template():
    notes = build_live_validation_lap_notes_template(
        _plan(),
        config=ExperimentalLiveValidationPackConfig(
            variant_key="selected_zones_v1",
            recommended_run_nickname="recommendation_execution_selected_01",
            planned_lico_profile_id="spa_exp_live_candidate_selected_v1",
            planned_lico_profile_description="Selected candidate.",
            warmup_lap_count=2,
            scored_lap_count=3,
            pack_status="candidate",
            status_summary="Candidate pack.",
        ),
    )

    assert notes.height == 5
    assert notes.select("lap_index", "lap_role", "scored").rows() == [
        (1, "warmup", False),
        (2, "warmup", False),
        (3, "scored", True),
        (4, "scored", True),
        (5, "scored", True),
    ]
    assert notes.row(0, named=True)["t14"] == "n/a"


def test_builds_live_validation_zone_signoff_template():
    signoff = build_live_validation_zone_signoff_template(_plan())

    assert signoff.select("zone_id", "pre_drive_signoff", "post_run_status").rows() == [
        ("spa_t01", "", ""),
        ("spa_t18", "", ""),
    ]


def test_writes_live_validation_pack(tmp_path: Path):
    plan_path = tmp_path / "plan.csv"
    _plan().write_csv(plan_path)

    pack_dir = write_experimental_live_validation_pack(
        plan_path,
        config=ExperimentalLiveValidationPackConfig(
            variant_key="selected_zones_v1",
            recommended_run_nickname="recommendation_execution_selected_01",
            planned_lico_profile_id="spa_exp_live_candidate_selected_v1",
            planned_lico_profile_description="Selected candidate.",
            warmup_lap_count=2,
            scored_lap_count=3,
            pack_status="candidate",
            status_summary="Candidate pack.",
            operator_mode="adaptive_guarded_operator_preview",
            source_run_id="recommendation_execution_selected_latency_v2_02",
            source_plan_id="plan_baseline_v2",
            source_current_lap_number=8,
            source_next_lap_number=9,
        ),
        output_dir=tmp_path / "packs",
        protocol_doc_path=tmp_path / "protocol.md",
        replay_validation_report_path=tmp_path / "replay.html",
        replanner_validation_report_path=tmp_path / "replanner.html",
    )

    assert (pack_dir / "plan.csv").exists()
    assert (pack_dir / "lap_notes_template.csv").exists()
    assert (pack_dir / "zone_signoff_template.csv").exists()
    assert (pack_dir / "run_metadata_template.json").exists()
    assert (pack_dir / "README.md").exists()
    manifest = json.loads((pack_dir / "pack_manifest.json").read_text(encoding="utf-8"))
    assert manifest["plan_id"] == "plan_selected_v1"
    assert manifest["variant_key"] == "selected_zones_v1"
    assert manifest["pack_status"] == "candidate"
    assert manifest["status_summary"] == "Candidate pack."
    assert manifest["operator_mode"] == "adaptive_guarded_operator_preview"
    assert manifest["source_reference"]["source_run_id"] == "recommendation_execution_selected_latency_v2_02"
    assert manifest["source_reference"]["source_current_lap_number"] == 8
    assert manifest["plan_sha256"]
    readme = (pack_dir / "README.md").read_text(encoding="utf-8")
    assert "scripts/run_lmu_live_cues.py --bench-beep-only" in readme
    assert "source_run_id" in readme


def _plan() -> pl.DataFrame:
    return pl.DataFrame(
        [
            {
                "schema_version": 1,
                "plan_id": "plan_selected_v1",
                "track_name": "Spa-Francorchamps",
                "car_class": "LMP2",
                "race_context_id": "ctx",
                "zone_id": "spa_t01",
                "display_label": "T01",
                "brake_reference_m": 133.0,
                "selected_lico_distance_m": 70.0,
                "planned_lift_start_m": 63.0,
                "cue_distance_m": 63.0,
                "cue_tolerance_m": 5.0,
                "track_length_m": 7000.0,
                "minimum_confidence_label": "experimental_candidate",
                "expected_fuel_saved_l": 0.03,
                "expected_time_lost_s": 0.14,
                "plan_status": "target_met",
                "source_model_status": "model_ready",
                "source_quality_flags": "",
                "strategy_role": "",
                "notes": "candidate",
            },
            {
                "schema_version": 1,
                "plan_id": "plan_selected_v1",
                "track_name": "Spa-Francorchamps",
                "car_class": "LMP2",
                "race_context_id": "ctx",
                "zone_id": "spa_t18",
                "display_label": "T18",
                "brake_reference_m": 6438.0,
                "selected_lico_distance_m": 132.0,
                "planned_lift_start_m": 6306.0,
                "cue_distance_m": 6306.0,
                "cue_tolerance_m": 5.0,
                "track_length_m": 7000.0,
                "minimum_confidence_label": "experimental_candidate",
                "expected_fuel_saved_l": 0.05,
                "expected_time_lost_s": 0.24,
                "plan_status": "target_met",
                "source_model_status": "model_ready",
                "source_quality_flags": "",
                "strategy_role": "",
                "notes": "candidate",
            },
        ]
    )
