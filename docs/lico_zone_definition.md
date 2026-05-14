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
- `name`;
- `start_distance_m`;
- `lico_window_start_m`;
- `brake_reference_m`;
- `end_distance_m`;
- `notes`.

These definitions should be treated as editable driver-reviewed assumptions, not
as permanent truth.

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
