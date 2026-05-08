# Architecture

## Modules

- ingestion: read LMU telemetry files
- preprocessing: clean and align telemetry
- analysis: compute fuel, lap, braking and LICO metrics
- optimization: choose best lift zones for a fuel target
- reports: generate summaries
- app: dashboard
- live: future live telemetry support