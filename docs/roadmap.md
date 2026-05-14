# LICOR Roadmap

Use this roadmap as the main handoff document for future Codex sessions. Start
new work from the first incomplete phase, keep edits small, and update this file
when a phase changes meaningfully.

## Phase 0: Project Foundation

Status: mostly complete.

- [x] Document the LMU DuckDB telemetry format.
- [x] Add the LMU telemetry reference config to the repo.
- [x] Implement read-only DuckDB ingestion.
- [x] Add a loader for the LMU telemetry reference config.
- [x] Validate observed DuckDB channels/events against the reference config.
- [x] Reconstruct timestamps for fixed-frequency channels.
- [x] Add tests with synthetic DuckDB files.
- [x] Define the normalized LICOR telemetry schema.

## Phase 1: First Controlled Spa Dataset

Status: ready to implement.

- [x] Keep raw telemetry files outside Git.
- [x] Add a dataset log for controlled runs.
- [ ] Convert `docs/dataset_log.md` into a machine-readable label file if needed.
- [ ] Load multiple LMU telemetry files from a local folder.
- [ ] Extract lap intervals and filter out-laps/warm-up laps.
- [ ] Produce a lap summary table with fuel usage and basic validation metrics.
- [ ] Add tests for lap summary and valid-lap filtering.

Recommended next Codex task:

```text
Implement the first analysis pipeline: load the local Spa DuckDB files listed in
docs/dataset_log.md, compute lap summaries, apply valid/excluded lap labels, and
write tests for the lap summary logic.
```

## Phase 2: Braking And LICO Detection

- [ ] Detect braking zones from `Brake Pos`.
- [ ] Merge nearby braking segments into meaningful corners/zones.
- [ ] Fix Bus Stop-style split braking detection.
- [ ] Define driver-reviewed Spa track zones around approach, LICO, braking,
  corner/complex, and exit stabilization phases.
- [ ] Detect throttle lift before braking zones.
- [ ] Associate candidate LICO zones with lap distance and braking point.
- [ ] Add tests for brake segment detection and segment merging.

## Phase 3: Cost/Benefit Analysis

- [ ] Compare push and LICO behavior by track zone.
- [ ] Estimate fuel saved and local time lost by zone.
- [ ] Convert `none`, `low`, `medium`, and `high` collection labels into continuous
  telemetry measurements such as lift distance and lift duration.
- [ ] Fit initial smooth zone-level cost/benefit curves.
- [ ] Rank zones by fuel saved per second lost.
- [ ] Let the driver review and correct zone interpretation.
- [ ] Treat full-lap deltas as sanity checks, not objective functions.

## Phase 4: Pit Stops And Race Strategy

- [ ] Load dedicated pit stop telemetry files.
- [ ] Detect pit entry, pit exit, speed limiter on/off, stationary time, and refill
  windows.
- [ ] Estimate observed refill rate and pit lane commitment time.
- [ ] Compare telemetry-derived refill rate with configurable LMU/rules values.
- [ ] Compare full-push stop count versus LICO-enabled stop count for a race length.
- [ ] Compute the fuel saving target required to avoid an extra stop.

## Phase 5: Reports And App

- [ ] Generate Plotly charts for speed, throttle, brake, fuel, and lap distance.
- [ ] Generate zone-level comparison reports.
- [ ] Build a simple Streamlit dashboard around the tested analysis functions.
- [ ] Keep analysis logic out of the app layer.

## Phase 6: Generalization

- [ ] Test the pipeline on another circuit using mostly push laps.
- [ ] Use Spa as the first calibration dataset.
- [ ] Add lightweight statistical models only after heuristic outputs are credible.
- [ ] Prefer continuous models such as splines, Gaussian processes, or hierarchical
  Bayesian models over classification of LICO intensity labels.

## Current Data Readiness

The current local dataset is enough to start implementation:

- `none`: push baseline;
- `low`: low LICO sample;
- `medium`: medium LICO sample;
- `high`: high LICO sample;
- `pitstop`: pit/refill sample.

Do not collect more broad global LICO runs until Phase 1 and Phase 2 produce
reproducible tables. Future data should be targeted by zone.
