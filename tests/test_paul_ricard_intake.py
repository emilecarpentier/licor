import json
import runpy
from pathlib import Path

import polars as pl
import pytest

from licor.analysis.collection_metadata import validate_dataset_collection_metadata
from licor.analysis.driver_review import apply_zone_pass_review, load_driver_zone_review
from licor.analysis.lap_summary import load_dataset_lap_labels

MODULE = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "scripts/build_paul_ricard_intake.py")
)
DATASET_FILE = MODULE["DATASET_FILE"]
PROJECT_ROOT = MODULE["PROJECT_ROOT"]
PROTOCOL_FILE = MODULE["PROTOCOL_FILE"]
REVIEW_FILE = MODULE["REVIEW_FILE"]
_sha256 = MODULE["_sha256"]
build_intake = MODULE["build_intake"]
select_modeling_passes = MODULE["select_modeling_passes"]
verify_intake_manifest = MODULE["verify_intake_manifest"]


def test_retrospective_metadata_keeps_original_laps_and_review_scope():
    labels = load_dataset_lap_labels(PROJECT_ROOT / DATASET_FILE)
    metadata = validate_dataset_collection_metadata(
        labels, PROJECT_ROOT / PROTOCOL_FILE
    )
    assert metadata["metadata_status"].to_list() == ["ready"] * 4
    second_baseline = labels.runs[1]
    assert second_baseline.valid_laps == {9, 10, 11}
    assert second_baseline.borderline_laps == {13}
    assert second_baseline.context_laps == {14}
    assert second_baseline.excluded_laps == {8, 12}
    assert labels.runs[3].valid_laps == set(range(10, 18))


def test_modeling_gate_preserves_zone_only_exclusion_and_other_lap13_zones():
    frame = pl.DataFrame(
        {
            "run_id": ["paul_ricard_baseline_push_02"] * 5,
            "lap_number": [13, 13, 12, 14, 13],
            "zone_id": ["pr_t03", "pr_t14", "pr_t14", "pr_t14", "pr_t15"],
            "validity_label": ["valid"] * 5,
            "zone_modeling_lap_eligible": [True, True, False, False, True],
            "optimization_role": ["candidate"] * 4 + ["excluded"],
            "lico_eligible": [True] * 4 + [False],
            "review_status": ["driver_reviewed"] * 5,
        }
    )
    reviewed = apply_zone_pass_review(
        frame, load_driver_zone_review(PROJECT_ROOT / REVIEW_FILE)
    )
    selected = select_modeling_passes(reviewed)
    assert selected.select("zone_id", "validity_label").rows() == [
        ("pr_t03", "driver_excluded"),
        ("pr_t14", "valid"),
    ]
    assert reviewed.height == 5


@pytest.mark.parametrize("changed", ["raw", "metadata_validation.csv"])
def test_manifest_rejects_changed_input_or_output(tmp_path: Path, changed: str):
    (tmp_path / "raw").write_bytes(b"original raw")
    output = tmp_path / "output"
    output.mkdir()
    pl.DataFrame({"metadata_status": ["ready"]}).write_csv(
        output / "metadata_validation.csv"
    )
    manifest = {
        "schema_version": 1,
        "metadata_valid": True,
        "source_sha256": {"raw": _sha256(tmp_path / "raw")},
        "artifact_sha256": {
            "metadata_validation.csv": _sha256(output / "metadata_validation.csv")
        },
    }
    (output / "intake_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert verify_intake_manifest(output, tmp_path) == manifest
    target = tmp_path / "raw" if changed == "raw" else output / changed
    target.write_bytes(b"changed")
    with pytest.raises(ValueError, match="Stale intake input/output"):
        verify_intake_manifest(output, tmp_path)


@pytest.mark.skipif(
    not all(
        (PROJECT_ROOT / run.file).is_file()
        for run in load_dataset_lap_labels(PROJECT_ROOT / DATASET_FILE).runs
    ),
    reason="Optional local real-telemetry integration check requires the four raw Paul files",
)
def test_raw_intake_reproduces_inventory_and_explicit_exclusions(tmp_path: Path):
    output = tmp_path / "intake"
    build_intake(output_dir=output)
    manifest = verify_intake_manifest(output)
    assert manifest["counts"] == {
        "complete_laps": 31,
        "modeling_laps": 25,
        "clean_whole_lap_baseline": 9,
        "modeling_passes": 150,
        "driver_excluded_passes": 1,
    }
    passes = pl.read_csv(output / "zone_passes_modeling.csv")
    excluded = passes.filter(pl.col("validity_label") == "driver_excluded")
    assert excluded.select("run_id", "lap_number", "zone_id").rows() == [
        ("paul_ricard_baseline_push_02", 13, "pr_t03")
    ]
    all_passes = pl.read_csv(output / "zone_passes_all.csv")
    assert all_passes.height == 31 * 9
    assert all_passes.filter(pl.col("zone_start_zero_throttle")).height > 0
    baseline = pl.read_csv(output / "baseline_summary.csv").filter(
        pl.col("recommended_review_action") == "candidate_clean"
    )
    assert baseline["fuel_used_l"].mean() == pytest.approx(2.7763146, abs=1e-6)
