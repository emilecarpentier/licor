# LICOR

Lift-and-Coast Optimization for Racing.

LICOR is a telemetry analysis project for Le Mans Ultimate. Its goal is to help endurance sim racing drivers optimize lift-and-coast fuel saving while minimizing lap time loss.

## Current Status

Early prototype.

The current focus is offline telemetry analysis for:

- Le Mans Ultimate
- LMP2
- Spa
- recorded telemetry files

## MVP

The first version will:

- load telemetry files
- normalize LMU telemetry channels
- calculate fuel used per lap
- detect braking zones
- detect lift-and-coast candidate zones
- compare push and LICO runs
- recommend efficient lift zones

## Not Included Yet

- live telemetry
- audio cues
- machine learning
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

Planned core tools:

- Polars
- DuckDB
- Pydantic
- SciPy
- Plotly
- Streamlit
- Pytest
- Ruff
