# Zone Refit References

## Core docs
- `docs/roadmap.md`
- `docs/dataset_log.md`
- `docs/data_contract.md`

## Analysis modules
- `src/licor/analysis/processed_artifacts.py`: zone-pass and readiness rebuild helpers
- `src/licor/analysis/zone_pass.py`: `zone_pass` extraction
- `src/licor/analysis/zone_curves.py`: curve points and binned observations
- `src/licor/analysis/zone_models.py`: piecewise model layer
- `src/licor/analysis/lap_sanity.py`: full-lap versus summed-zone sanity

## Review and zone files
- `config/track_zones/spa_lmp2_zones.draft.json`
- `config/driver_reviews/spa_lmp2_v2_zone_review_2026-05-21.json`

## Common outputs to inspect
- `data/processed/spa_lmp2_zone_passes.csv`
- zone curve or model HTML reports under `data/processed/`
- `data/processed/spa_lmp2_lap_sanity.csv` when regenerated

## Key interpretation rule
- Use full-lap deltas as a sanity layer only. The causal objective remains zone-level fuel saved versus local time lost.
