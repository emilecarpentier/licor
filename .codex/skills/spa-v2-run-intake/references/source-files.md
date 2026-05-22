# Spa V2 Intake References

## Core docs
- `docs/roadmap.md`: current phase and next incomplete step
- `docs/codex_instructions.md`: project priorities and coding rules
- `docs/dataset_log.md`: collection history and methodology notes
- `docs/data_contract.md`: metadata, readiness, and live-cue contracts

## Config and review files
- `config/datasets/`: dataset sidecars
- `config/collection_protocols/spa_lmp2_v2_protocol.json`: required Spa v2 metadata contract
- `config/driver_reviews/`: lap-zone exclusions and pass annotations
- `config/track_zones/spa_lmp2_zones.draft.json`: current candidate-zone boundaries

## Main functions
- `src/licor/analysis/collection_metadata.py`: `validate_dataset_collection_metadata`
- `src/licor/analysis/processed_artifacts.py`: `build_spa_v2_readiness_artifacts`, `build_spa_v2_quality_artifacts`
- `src/licor/analysis/lap_summary.py`: lap summaries and valid-lap filtering

## Main outputs
- `data/processed/spa_lmp2_zone_passes.csv`
- `data/processed/spa_lmp2_zone_passes.parquet`
- `data/processed/spa_lmp2_v2_zone_data_readiness.csv`
- `data/processed/spa_lmp2_v2_protocol_readiness.csv`
- `data/processed/spa_lmp2_v2_lap_quality_manifest.csv`
