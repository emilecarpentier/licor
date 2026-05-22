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
Update the Spa learning loop: add marginal/sensitivity diagnostics, define a
new controlled-random and targeted data collection protocol, then prepare a
minimal live audio-cue validation path.
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

Status: re-scoped. Reports remain next; Streamlit should wait until the
recommendation loop is credible.

- [x] Add marginal fuel/time efficiency diagnostics for each zone model.
- [x] Add sensitivity reports for optimizer plans, including best-ratio caps,
  stricter driver caps, diagnostic-zone exclusion, and fuel safety margins.
- [x] Define a Spa v2 data collection protocol with controlled-random LICO,
  targeted zone variation, and recommendation-execution runs.
- [x] Add Spa v2 data-readiness summaries for zone coverage and protocol
  coverage before refitting curves.
- [x] Persist current Spa zone-pass and Spa v2 readiness CSV/parquet artifacts.
- [x] Add a Spa v2 run-metadata ingestion contract and validation layer so
  future non-labelled runs can link to collection protocols before telemetry
  processing.
- [x] Add a run/lap quality manifest v2 to gate future collection laps before
  zone readiness and curve updates.
- [x] Use four Spa v2 controlled-random runs as the first post-v1 coverage gate
  before deciding whether targeted-zone collection is still necessary.
- [x] Add an exportable LICO plan format suitable for live cues.
- [x] Add a replay-style execution schema for planned-versus-observed live cue
  validation.
- [x] Build a minimal live-cue trigger/logging prototype that consumes an
  exported plan and logs cue timing accuracy.
- [x] Add an injectable replay/audio wrapper around the tested live-cue runner.
- [ ] Validate the real audio adapter against LMU telemetry during a driving
  session.
- [x] Generate Plotly charts for speed, throttle, brake, fuel, and lap distance.
- [x] Generate zone-level comparison reports.
- [ ] Build a simple Streamlit dashboard around the tested analysis functions
  after offline reports and live-cue validation are useful.
- [ ] Keep analysis logic out of the app layer.

## Phase 6: Modeling And Generalization

- [ ] Use Spa as the first calibration and methodology dataset.
- [ ] Replace first piecewise curves with robust continuous models once Spa v2
  data is available.
- [ ] Model uncertainty so recommendations can distinguish high-confidence
  zones from extrapolated or weakly supported zones.
- [ ] Learn reusable zone priors from Spa, such as relationships between
  approach speed, braking severity, straight length, corner type, LICO distance,
  fuel saved, and local time lost.
- [ ] Add automatic candidate-zone proposal for new circuits from mostly push
  laps, using braking events, approach geometry/proxies, and reusable priors.
- [ ] Test the pipeline on another circuit with a small calibration budget:
  mostly push laps plus a limited number of varied LICO laps, not a full manual
  50-lap rebuild.
- [ ] Keep a manual review fallback for zones whose telemetry shape is outside
  the Spa-learned distribution.
- [ ] Add lightweight statistical models only after transparent heuristic
  outputs are credible.
- [ ] Prefer continuous models such as splines, Gaussian processes, or hierarchical
  Bayesian models over classification of LICO intensity labels.

## Current Data Readiness

The current local dataset is enough to start implementation:

- `none`: push baseline;
- `low`: low LICO sample;
- `medium`: medium LICO sample;
- `high`: high LICO sample;
- `pitstop`: pit/refill sample;
- `baseline` refresh: two metadata-linked Spa v2 push-baseline runs;
- `controlled_random`: four metadata-linked Spa v2 runs.

The first reproducible Spa pipeline now exists. Future Spa data should move away
from broad `none`/`low`/`medium`/`high` labels and toward:

- controlled-random LICO runs that vary lift distances across zones to fill the
  continuous curve;
- targeted zone runs that break correlations between zones, but only after
  post-refit diagnostics show that controlled-random coverage is still
  insufficient;
- recommendation-execution runs once an audio cue can tell the driver where to
  lift and log whether the plan was followed.

Recommended next step after integrating the first four Spa v2 controlled-random runs:

```text
Refit the zone curves and optimizer plans from the integrated Spa v2 dataset,
audit which zones remain noisy or weakly supported, and then decide whether a
small targeted-zone pass is still worth the time before moving to
recommendation-execution validation.
```
