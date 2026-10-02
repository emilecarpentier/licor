"""Align Sebring with historical push-only ratio profiles, without changing targets."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "data/processed/experimental/four_circuit_low_data_v1"
PACK = (
    ROOT
    / "data/processed/experimental/sebring_lmp2_transfer_2026_09/lico_validation_pack_v1"
)
OUTPUT = ROOT / "data/processed/experimental/four_circuit_harmonized_v1"
PUSH_RUN = "sebring_push_20260912_114122"
RATIOS = (0.0, 0.25, 0.5, 1.0, 1.5)
PROFILE_COLUMNS = tuple(
    f"approach_acceleration_ratio_{suffix}_mps2"
    for suffix in ("0_0", "0_25", "0_5", "1_0", "1_5")
)


def record(path: Path) -> dict:
    with path.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    return {"path": str(path.resolve()), "sha256": digest}


def verify_hash(path: Path, expected: str) -> None:
    if record(path)["sha256"] != expected:
        raise ValueError(f"frozen hash mismatch: {path}")


def harmonize(
    rows: pl.DataFrame, events: pl.DataFrame
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Match historical median-at-ratio then linear interpolation, not grid median."""
    for column in ("observation_id", "circuit_id", "zone_id"):
        if rows[column].null_count():
            raise ValueError(f"null response identity: {column}")
    if rows["observation_id"].n_unique() != rows.height:
        raise ValueError("duplicate response observation")
    keys = ["run_id", "lap_number", "zone_id"]
    if events.select(keys).unique().height != events.height:
        raise ValueError("duplicate push event")
    if events.filter(
        (pl.col("run_id") != PUSH_RUN) | ~pl.col("lap_number").is_in(range(8, 13))
    ).height:
        raise ValueError("push event outside frozen prior run/laps")
    supported = events.filter(pl.col("braking_event_quality") == "ready")
    profiles = []
    lookup = {}
    for zone in rows.filter(pl.col("circuit_id") == "sebring")["zone_id"].unique():
        selected = supported.filter(pl.col("zone_id") == zone)
        profile = []
        for ratio, column in zip(RATIOS, PROFILE_COLUMNS):
            values = selected[column].drop_nulls()
            if not values.is_finite().all():
                raise ValueError(f"nonfinite push profile: {zone}/{ratio}")
            if len(values) < 3:
                raise ValueError(f"insufficient push profile support: {zone}/{ratio}")
            value = float(values.median())
            profile.append(value)
            profiles.append(
                {
                    "zone_id": zone,
                    "ratio": ratio,
                    "acceleration_mps2": value,
                    "support": len(values),
                }
            )
        lookup[zone] = profile
    accelerations = []
    planned_accelerations = []
    for row in rows.iter_rows(named=True):
        previous = row["acceleration"]
        if previous is None or not math.isfinite(previous):
            raise ValueError("nonfinite original acceleration")
        action = row["action"]
        if action is None or not math.isfinite(action) or not 0 <= action <= 1.5:
            raise ValueError("action outside finite ratio profile domain")
        accelerations.append(
            float(np.interp(action, RATIOS, lookup[row["zone_id"]]))
            if row["circuit_id"] == "sebring"
            else previous
        )
        planned = row.get("planned_action")
        if row["circuit_id"] == "sebring":
            if planned is None or not math.isfinite(planned) or not 0 <= planned <= 1.5:
                raise ValueError("planned action outside finite ratio profile domain")
            planned_accelerations.append(
                float(np.interp(planned, RATIOS, lookup[row["zone_id"]]))
            )
        else:
            planned_accelerations.append(None)
    result = rows.with_columns(
        pl.col("acceleration").alias("acceleration_previous"),
        pl.Series("acceleration_harmonized", accelerations),
        pl.Series("acceleration", accelerations),
        pl.Series(
            "acceleration_planned_harmonized", planned_accelerations, dtype=pl.Float64
        ),
        pl.when(pl.col("circuit_id") == "sebring")
        .then(pl.lit("in_range_prior_push_profile"))
        .otherwise(pl.lit("not_exported_historical"))
        .alias("planned_acceleration_status"),
    )
    return result, pl.DataFrame(profiles).sort(["zone_id", "ratio"])


def build(output: Path) -> dict:
    if output.exists():
        raise FileExistsError(f"refusing overwrite: {output}")
    canonical = INPUT / "canonical_response_rows.csv"
    source_manifest = INPUT / "manifest.json"
    pack_manifest = PACK / "pack_manifest.json"
    events_path = PACK / "physical_events.csv"
    manifest = json.loads(source_manifest.read_text())
    artifact = next(
        item
        for item in manifest["artifacts"]
        if Path(item["path"]).name == canonical.name
    )
    verify_hash(canonical, artifact["sha256"])
    frozen = json.loads(pack_manifest.read_text())
    verify_hash(events_path, frozen["artifacts"][events_path.name])
    result, profiles = harmonize(pl.read_csv(canonical), pl.read_csv(events_path))
    output.mkdir(parents=True)
    result.write_csv(output / "canonical_response_rows.csv")
    profiles.write_csv(output / "sebring_ratio_profiles.csv")
    metadata = {
        "artifact_id": "four_circuit_harmonized_v1",
        "status": "retrospective_development_inputs_not_live_model",
        "method": "Per-zone medians of prior-push per-lap acceleration at ratios 0,.25,.5,1,1.5, then linear interpolation at executed action; no clipping. Historical three-circuit values unchanged.",
        "acceleration_window": "Existing common extractor: 1s window ending 0.2s before point; correlation-validated longitudinal sensor median, speed-regression fallback.",
        "limitations": [
            "Sparse profile remains an approximation, not a dense physical response curve.",
            "Executed action is retrospective. Outcome targets and qualification remain unchanged.",
            "Harmonization does not fix cross-circuit outcome-window or run-quality differences.",
        ],
        "rows": result.height,
        "sebring_rows": result.filter(pl.col("circuit_id") == "sebring").height,
        "sources": [
            record(path)
            for path in (
                canonical,
                source_manifest,
                events_path,
                pack_manifest,
                Path(__file__),
            )
        ],
        "artifacts": [record(path) for path in sorted(output.glob("*.csv"))],
    }
    (output / "manifest.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    return metadata


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT)
    print(json.dumps(build(parser.parse_args().output_dir), indent=2))
