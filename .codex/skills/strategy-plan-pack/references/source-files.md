# Strategy Plan References

## Core docs
- `docs/roadmap.md`
- `docs/race_strategy.md`
- `docs/data_contract.md`

## Analysis modules
- `src/licor/analysis/race_strategy.py`: race-length, stop-count, and fuel-target helpers
- `src/licor/analysis/zone_optimizer.py`: zone-level plan selection
- `src/licor/analysis/zone_plan_diagnostics.py`: marginal efficiency and sensitivity
- `src/licor/analysis/strategy_priors.py`: editable driver priors
- `src/licor/analysis/live_plan.py`: exportable cue plan and replay-style execution rows

## Inputs to keep explicit
- race lap count override
- fuel target per lap
- safety margin
- strategy priors
- zone model status and quality flags

## Typical outputs to inspect
- zone plan CSVs in `data/processed/`
- sensitivity or marginal diagnostics CSVs in `data/processed/`
- live-cue plan CSVs in `data/processed/`
