# LICOR Project Agent Guide

## Source of truth
- Start with `docs/roadmap.md`, `docs/codex_instructions.md`, `docs/dataset_log.md`, and `docs/data_contract.md`.
- When methodology changes, update the relevant docs in the same turn.

## Project priorities
- Keep the offline recommendation loop credible before adding app polish.
- Use Spa LMP2 as the first calibration dataset and methodology reference.
- Treat full-lap time as a sanity check, not the primary optimization objective.
- Optimize from zone-level fuel saved versus local time lost.
- Treat `none`, `low`, `medium`, and `high` as collection labels, not output classes.

## Workflow defaults
- For new telemetry: inspect lap summaries, impacts, pit-state anomalies, and `zone_start_zero_throttle` before adding runs to a dataset sidecar.
- Preserve lap-zone exclusions and review notes in `config/driver_reviews/` instead of silently dropping rows in analysis code.
- Run `validate_dataset_collection_metadata` before readiness or refit work when new metadata-rich runs are added.
- Before changing zone boundaries, inspect the relevant telemetry or map reports and document the racing assumption.
- Before refitting: rebuild readiness and lap-quality artifacts first, then rebuild zone passes, curves, models, sanity tables, and strategy outputs.

## Key directories
- `config/datasets/`: dataset sidecars
- `config/collection_protocols/`: collection design and session contracts
- `config/track_zones/`: editable driver-reviewed zone boundaries
- `config/driver_reviews/`: exclusions, annotations, and signal tags
- `data/processed/`: reproducible CSV, parquet, and HTML outputs

## Subagent policy
- Use explorer agents for code or doc reconnaissance and report comparison.
- Use worker agents only on disjoint write scopes.
- Keep telemetry interpretation, methodology decisions, and final integration in the main agent.
- Use a reviewer pass before major refits or workflow changes.

## Guardrails
- Do not touch Streamlit unless explicitly asked.
- Keep analysis logic out of app-layer code.
- Prefer pure functions, explicit data contracts, and small focused tests.
- Default verification for meaningful changes: `uv run pytest` and `uv run ruff check .`
