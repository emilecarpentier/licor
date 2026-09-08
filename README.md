# LICOR

Lift-and-Coast Optimization for Racing.

LICOR is a telemetry analysis project for Le Mans Ultimate. Its goal is to help endurance sim racing drivers optimize lift-and-coast fuel saving while minimizing lap time loss.

## Current Status

Research prototype with an implemented offline Spa LMP2 pipeline, a static
LMU audio-cue runner, and an initial Paul Ricard transfer bootstrap.

The September 2026 priority is reproducible Paul Ricard pilot preparation and
empirical validation of fuel/time predictions. Static cue timing has initial
Spa validation; predictive accuracy, adaptive benefit, and learned cross-circuit
transfer remain unproven.

Start with [the roadmap](docs/roadmap.md) and
[the restart plan](docs/restart_plan_2026-09.md).

The rebuilt Paul static pack is ready for a prospective pilot; use the
[French run sheet](docs/paul_ricard_static_pilot_run_sheet.md) for preflight and
the 5–7-lap sequence. Its predicted gains still need driving validation.

## MVP

The offline implementation can:

- load telemetry files
- normalize LMU telemetry channels
- calculate fuel used per lap
- detect braking zones
- detect lift-and-coast candidate zones
- compare push and LICO runs
- recommend efficient lift zones

## Not Included Yet

- validated adaptive live recommendations
- validated learned transfer between circuits, drivers, or setups
- race overlay

## Documentation

See:

- `docs/product_spec.md`
- `docs/data_contract.md`
- `docs/architecture.md`
- `docs/lmu_duckdb_format.md`
- `docs/lmu_channels.md`
- `docs/lico_zone_definition.md`
- `docs/race_strategy.md`
- `docs/dataset_log.md`
- `docs/roadmap.md`
- `docs/codex_instructions.md`

## Reference Files

- `config/lmu_telemetry_config.reference.json`: reference copy of the LMU
  telemetry channel/event configuration. It is safe to version because it
  contains signal names and sampling frequencies, not driving data.

## Development

This project uses Python.

Project tools:

- Polars
- DuckDB
- Pydantic
- SciPy
- Plotly
- Streamlit
- Pytest
- Ruff
