# LICOR Roadmap

Use this roadmap as the main handoff document for future Codex sessions. Start
new work from the first incomplete phase, keep edits small, and update this file
when a phase changes meaningfully.

## Phase 0: Project Foundation

Status: complete.

- [x] Document the LMU DuckDB telemetry format.
- [x] Add the LMU telemetry reference config to the repo.
- [x] Implement read-only DuckDB ingestion.
- [x] Add a loader for the LMU telemetry reference config.
- [x] Validate observed DuckDB channels/events against the reference config.
- [x] Reconstruct timestamps for fixed-frequency channels.
- [x] Add tests with synthetic DuckDB files.
- [x] Define the normalized LICOR telemetry schema.

## Phase 1: First Controlled Spa Dataset

Status: lap summary pipeline complete.

- [x] Keep raw telemetry files outside Git.
- [x] Add a dataset log for controlled runs.
- [x] Convert `docs/dataset_log.md` into a machine-readable label file if needed.
- [x] Load multiple LMU telemetry files from a local folder.
- [x] Extract lap intervals and filter out-laps/warm-up laps.
- [x] Produce a lap summary table with fuel usage and basic validation metrics.
- [x] Add tests for lap summary and valid-lap filtering.

Recommended next Codex task:

```text
Review the driver-prior Spa 48-lap candidate plan visually and decide which
diagnostic zones should graduate into optimization recommendations or receive
targeted telemetry collection.
```

## Phase 2: Braking And LICO Detection

- [x] Detect braking zones from `Brake Pos`.
- [x] Merge nearby braking segments into meaningful corners/zones.
- [x] Keep distinct Bus Stop-style brake presses as separate detected zones.
- [x] Define driver-reviewed Spa LICO candidate zones around approach, LICO,
  braking, corner/complex, and exit stabilization phases.
- [x] Detect throttle lift before braking zones.
- [x] Associate candidate LICO zones with lap distance and braking point.
- [x] Add tests for brake segment detection and segment merging.

Phase 2 closeout note:

```text
Driver-reviewed candidate zones are complete for Phase 3. Spa T19 remains an
incomplete validation-only non-candidate for the second Bus Stop brake pressure;
it is intentionally excluded from the current optimization pipeline.
```

Implementation note:

- [x] Add an editable track-zone config schema and draft Spa zone file.
- [x] Add tests for track-zone loading and validation.
- [x] Add proposal logic for brake references and LICO window starts.
- [x] Build a zone-boundary visualization workflow for driver validation.
- [x] Add a Spa top-down map workflow from a local OpenStreetMap-derived trace.
- [x] Driver-review top-down alignment, zone starts, brake references, and
  validation endings for LICO candidate zones.
- [ ] Decide whether to add complete validation-only boundaries for Spa T19.

## Phase 3: Cost/Benefit Analysis

- [x] Compare push and LICO behavior by track zone.
- [x] Estimate fuel saved and local time lost by zone.
- [x] Convert `none`, `low`, `medium`, and `high` collection labels into continuous
  telemetry measurements such as lift distance and lift duration.
- [x] Fit initial smooth zone-level cost/benefit curves.
- [x] Rank zones by fuel saved per second lost.
- [x] Let the driver review and correct zone interpretation.
- [x] Treat full-lap deltas as sanity checks, not objective functions.

Implementation note:

- [x] Add a first `zone_pass` extraction table from driver-reviewed track zones.
- [x] Add synthetic tests for push, LICO, skipped zones, and incomplete zone
  coverage.
- [x] Add a first zone-level cost summary from `zone_pass` observations.
- [x] Add descriptive zone curve points and distance-binned curve tables before
  fitting a formal continuous model.
- [x] Add driver review annotations for lap-zone exclusions and zone signal tags.
- [x] Add targeted throttle/brake/speed zone telemetry reports for curve
  anomalies.
- [x] Add zone-start zero-throttle diagnostics and apply the T08 driver-reviewed
  start adjustment.
- [x] Make zone-pass LICO start robust to isolated throttle artifacts before the
  true zero-input coast phase.
- [x] Add first piecewise-linear zone models from binned curve observations.
- [x] Add a full-lap sanity table comparing global lap deltas with summed
  observed zone deltas.

## Phase 4: Pit Stops And Race Strategy

- [x] Load dedicated pit stop telemetry files.
- [x] Detect pit entry, pit exit, speed limiter on/off, stationary time, and refill
  windows.
- [x] Estimate observed refill rate and pit lane commitment time.
- [x] Compare telemetry-derived refill rate with configurable LMU/rules values.
- [x] Compare full-push stop count versus LICO-enabled stop count for a race length.
- [x] Compute the fuel saving target required to avoid an extra stop.

Implementation note:

- [x] Add a first `pit_stop_observation` extraction table from dedicated pit stop
  telemetry.
- [x] Add synthetic tests for pit state intervals, limiter windows, stationary
  windows, refill windows, missing refill handling, and initial out-lap pit
  state filtering.
- [x] Add first race-strategy helpers for race lap count, stop count, fuel-saving
  targets, and full-push versus LICO scenario comparisons.
- [x] Generate first Spa strategy CSVs from observed full-lap fuel deltas and
  measured pit/refill telemetry.
- [x] Add a race-lap override for championship-observed distances such as the
  Spa ELMS split result of 48 laps.
- [x] Add a first conservative zone-level optimizer that uses only `model_ready`
  points and reports when the fuel target is unreachable.
- [x] Add editable driver strategy priors and a driver-prior optimizer mode for
  feasible-but-diagnostic LICO zones.
- [x] Generate Spa conservative and driver-prior zone-level plans for the
  48-lap one-stop fuel target.

## Phase 5: Reports And App

- [ ] Generate Plotly charts for speed, throttle, brake, fuel, and lap distance.
- [x] Generate zone-level comparison reports.
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
