---
name: spa-v2-run-intake
description: Intake new Spa v2 LMU telemetry runs into LICOR. Use when new `.duckdb` files arrive, when controlled-random, targeted-zone, or recommendation-execution runs need dataset metadata, when impacts or lap-zone exclusions must be reviewed, or when Spa readiness and lap-quality artifacts must be rebuilt before refitting curves.
---

# Spa V2 Run Intake

## Overview

Use this skill to move from raw Spa `.duckdb` files to metadata-validated runs and refreshed Spa v2 readiness outputs. Keep the work focused on intake, review decisions, and artifact refresh, not on refitting models.

## Source Of Truth

Read `references/source-files.md` before editing metadata or rebuilding artifacts.

## Workflow

1. Inventory the new runs.
   - Identify the new `.duckdb` files and their intended collection design.
   - Inspect lap summaries before touching dataset sidecars.
   - Check for impacts, in-pits laps, suspicious lap times, and obvious driver-reported incidents.

2. Capture review decisions explicitly.
   - Put lap-zone exclusions or pass annotations in `config/driver_reviews/`.
   - If credible laps repeatedly start a zone at `0%` throttle, flag a boundary review instead of dropping the data.
   - Never silently rewrite lap numbering to match driver memory; document the telemetry mapping.

3. Update the dataset sidecar.
   - Add or update the run in `config/datasets/`.
   - Fill `collection_protocol_id`, `collection_session_id`, `collection_design`, `target_zones`, `planned_lico_profile_id`, `execution_quality`, `labels_quality`, and `driver_notes` when applicable.

4. Validate metadata before processing.
   - Use `validate_dataset_collection_metadata(...)` against `config/collection_protocols/spa_lmp2_v2_protocol.json`.
   - Stop and report the flags if metadata is missing, inconsistent, or not in protocol.

5. Rebuild intake artifacts.
   - Use `build_spa_v2_readiness_artifacts(...)` for zone-pass and readiness outputs.
   - Use `build_spa_v2_quality_artifacts(...)` for the lap-quality manifest.
   - Keep this skill scoped to intake and quality gates. Do not refit curves here unless the user explicitly asks.

## Report Back

Always report:
- files added or updated
- laps or zones excluded and why
- metadata flags found or cleared
- artifacts rebuilt
- what downstream step is now unblocked
