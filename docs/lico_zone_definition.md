# Lift-And-Coast Zone Definition

This document records the core methodological decision for LICOR: lift-and-coast
should be analyzed by track zones, not primarily by full-lap deltas.

## Core Principle

Full-lap time is useful as a sanity check, but it should not be the main
optimization target for LICOR.

A complete lap mixes too many effects:

- driver adaptation;
- unrelated mistakes;
- fuel mass changes;
- tire and temperature variation;
- different exits in corners unrelated to the tested LICO action;
- natural lap-to-lap rhythm variation.

The model should instead estimate the local cost and benefit of LICO inside
causal track zones.

## Causal Zone Unit

The preferred unit of analysis is:

```text
full-throttle approach
-> optional LICO window
-> braking phase
-> corner or corner complex
-> stabilization point after exit
```

Each zone should contain enough distance after the braking/corner phase to see
whether the LICO action affected the car beyond the braking point. The zone
should not automatically extend to the end of the lap.

LICOR should distinguish two related windows:

- the causal LICO window, from throttle release to brake start;
- the validation window, which may extend through the corner or complex to check
  whether entry speed, minimum speed, rotation, or exit quality degraded.

For simple corners such as Spa T1, the validation end can often be a stable
full-throttle point on the following straight. For complexes such as Les Combes,
that rule can be misleading because the car is still negotiating multiple
corners. In those cases, the end point should be driver-reviewed and used more
as a quality-control boundary than as proof that all local time delta came from
the LICO action.

## Why This Matters

The purpose of LICOR is not to ask:

```text
Did this full LICO lap lose time versus this full push lap?
```

The better question is:

```text
In this specific zone, how much fuel did low/medium/high LICO save, and how much
local time did it cost?
```

The output should eventually look like:

```text
Zone: Les Combes
None:   baseline fuel/time
Low:    fuel saved, time delta
Medium: fuel saved, time delta
High:   fuel saved, time delta
```

Then LICOR can combine the best zone-level choices to meet a fuel target.

## LICO Is A Continuum

The labels `none`, `low`, `medium`, and `high` are experimental collection
conditions. They are not the final decision categories LICOR should optimize.

The final model should not output:

```text
Les Combes = medium LICO
Bus Stop = low LICO
Pouhon = none
```

That would overfit the driver's sample laps and lose too much precision.

Instead, the labels should help create observations across a continuous spectrum
of actual LICO behavior. The model should learn relationships such as:

```text
fuel_saved_l = f(lico_distance_m)
local_time_delta_s = g(lico_distance_m)
corner_quality_delta = h(lico_distance_m)
```

The final recommendation should be continuous, for example:

```text
Les Combes: lift 115 m before the reference brake point
Bus Stop: lift 90 m before the reference brake point
Pouhon: lift 0-15 m, likely not worth meaningful LICO
```

## Continuous LICO Variables

LICOR should extract actual continuous behavior from each zone pass, regardless
of the run label. Useful variables include:

- `lico_start_m`;
- `lico_start_distance_before_brake_m`;
- `lico_duration_s`;
- `lico_distance_m`;
- `throttle_release_rate`;
- `minimum_throttle_pct_before_brake`;
- `average_throttle_pct_before_brake`;
- `brake_start_m`;
- `brake_start_speed_kph`.

For example, two laps both labelled `medium` may still produce different useful
observations:

```text
medium lap A: actual lift distance = 128 m
medium lap B: actual lift distance = 151 m
```

This variation is valuable because it gives the model more points along the
continuous LICO curve.

## LICO Effects To Measure

For each zone pass, LICOR should try to compute:

- fuel used inside the zone;
- elapsed time inside the zone;
- fuel saved versus a comparable push baseline;
- time lost or gained versus a comparable push baseline;
- LICO start distance;
- LICO duration;
- LICO distance;
- throttle profile before braking;
- brake start distance;
- brake start speed;
- brake duration;
- peak brake pressure;
- minimum speed through the corner/complex;
- exit speed at the stabilization point.

## Important Driving Assumption

In theory, LICO should mostly cost time before and during the braking approach.
If the car arrives at the first brake input with lower speed, the driver may be
able to brake later, brake less, or change the braking shape.

Therefore, LICOR should not automatically assign all later lap-time differences
to the LICO action. The zone must end at a meaningful stabilization point where
the car has returned to a comparable state.

However, LICO can still affect the post-braking phase if it changes:

- rotation;
- brake release;
- minimum speed;
- apex timing;
- exit speed;
- the quality of the following straight.

This is why the zone should include the corner/complex exit, not just the
straight-line lift and brake input.

## Initial Zone Boundaries

The first implementation can use manually reviewed zone definitions for Spa.
Each zone should include:

- `zone_id`;
- `turn_numbers`;
- `display_label`;
- `start_distance_m`;
- `lico_window_start_m`;
- `brake_reference_m`;
- `end_distance_m`;
- `lico_eligible`;
- `optimization_role`;
- `validation_end_rule`;
- `review_status`;
- `notes`.

These definitions should be treated as editable driver-reviewed assumptions, not
as permanent truth.

The current editable draft lives at
`config/track_zones/spa_lmp2_zones.draft.json`. Distances intentionally remain
blank until reviewed by the driver. This keeps the analysis honest: code can
validate completeness, but it should not guess causal boundaries.

For generalization to future circuits, zone identifiers should be based on
generally known turn numbers rather than local corner names. Corner names can be
kept in notes for driver review, but they should not drive the analysis.

LICO eligibility should be binary. The table can exclude structural
non-candidates, such as a second chicane brake pressure that cannot reasonably be
used for lift-and-coast. It should not encode intensity-specific judgments such
as "heavy LICO is bad here"; the later cost/benefit model should learn that from
continuous lift distance and local time/fuel outcomes.

For the first Spa proposal pass:

- `brake_reference_m` is proposed from the earliest observed brake start in the
  clean full-push laps;
- `lico_window_start_m` is proposed from the earliest high-LICO lift start minus
  `30 m`;
- `end_distance_m` stays manual because the user wants to validate zone endings
  visually on a circuit map.

The current validation report can display a true XY circuit map only when XY/GPS
coordinates are available. The observed LMU DuckDB files do not include such
coordinates, so LICOR currently generates a distance-strip view from lap distance
and path-lateral telemetry. This is still useful for checking ordering and
relative boundaries, but final map validation will need either an external track
map or a telemetry source with coordinates.

LICOR now also supports a top-down Spa validation report using a local
OpenStreetMap-derived GeoJSON trace. This report overlays proposed zone starts,
conservative full-push brake references, and median `none` brake points. Because
the trace is external to LMU, it is scaled to the observed telemetry lap length
and should be checked for start/finish offset before finalizing distances.

The top-down report can generate offset variants. A negative offset moves LMU
distance markers earlier on the OSM trace and is the expected correction when
brake markers appear after corner apexes.

Initial `validation_end` markers are generated only as visual proposals. The
default rule places a zone end shortly before the next zone start while enforcing
a minimum distance after the brake reference. These markers must be reviewed by
the driver before they are copied into the editable zone table.

Driver review notes from the first start/end top-down map:

- T01 automatic end was much too far and should be shortened before Phase 3.
- T05-T06 end should be between T6 and T7 to avoid pulling poor T7 execution into
  the Les Combes zone.
- T08 automatic end looked acceptable.
- T09 automatic end was too far; T10-T11 also needs a fallback zone start marker
  because no high-LICO start was detected there.
- T10-T11 and T12-T13 automatic ends looked acceptable.
- T14 end should be just after T15.
- T18 end was too early and should include the first Bus Stop rotation.

The second review accepted all short-end candidates except T18, which was moved
15 m later. Driver-reviewed candidate zones are now written to
`config/track_zones/spa_lmp2_zones.draft.json`; T19 remains a validation-only
non-candidate.

## Current Detection Heuristic

The current code detects braking references before manually reviewed Spa zones
exist. It treats `Brake Pos >= 5%` as brake active, filters very short segments,
and only merges very small brake-input chatter. Deliberate separate brake
pressures, including the two Bus Stop pressures, should remain separate detected
zones.

LICO detection then looks backward from each brake start. It starts the LICO
window when throttle first leaves full throttle, but only validates the event as
LICO when there is a genuine zero-input coast phase before the brake input. The
output records continuous variables such as lift start distance, lift distance
before brake, duration, distance, minimum throttle, average throttle, and release
rate.

These detected zones are candidates, not final causal track zones. The next
driver-review step should map them to named Spa zones and choose where each zone
should end after the corner or complex.

## Example Zone Observation

Each pass through a zone should eventually produce an observation like:

```text
file_name
run_id
lap_number
zone_id
lico_intensity
fuel_used_l
elapsed_time_s
fuel_delta_l
time_delta_s
lico_start_m
lico_duration_s
lico_distance_m
brake_start_m
brake_start_speed_kph
min_speed_kph
exit_speed_kph
validity_label
notes
```

## Role Of Full-Lap Metrics

Full-lap metrics should still be reported because they are useful for:

- checking whether a run is generally plausible;
- filtering obvious adaptation laps or invalid laps;
- monitoring fuel mass effects;
- validating that zone-level recommendations make sense globally.

But full-lap metrics should not be the main objective function for LICO
optimization.

## Optimization Framing

Once zone-level effects are estimated, LICOR should choose a combination of LICO
actions by solving:

```text
minimize total local time loss
subject to total fuel saved >= target fuel saving
```

This makes the project closer to zone-level cost-benefit optimization than
full-lap imitation.

## Candidate Modeling Approaches

The first MVP can use transparent interpolation or simple smooth curves by zone.
Later versions can use more formal continuous models:

- splines or generalized additive models for interpretable smooth curves;
- Gaussian processes to model uncertainty and suggest useful new test points;
- hierarchical Bayesian models to share learning across zones and circuits.

Black-box classification of `none`, `low`, `medium`, and `high` should be
avoided. Those labels describe how the data was collected, not what the final
optimizer should choose.
