---
name: zone-curve-refit-and-sanity
description: Refit Spa zone curves and validate that the updated cost-benefit surfaces still make sense. Use when new Spa v2 runs have passed intake gates, when track-zone or driver-review updates change `zone_pass` observations, or when the optimizer behavior needs a model-sanity review before new collection or live-cue validation.
---

# Zone Curve Refit And Sanity

## Overview

Use this skill to rebuild the zone-analysis layer after new valid data arrives. Focus on reproducible curve inputs, model flags, telemetry sanity, and whether the updated outputs justify more data collection.

## Source Of Truth

Read `references/source-files.md` before rebuilding models or interpreting a suspicious curve.

## Workflow

1. Gate the refit.
   - Confirm that new runs already passed metadata, readiness, and lap-quality intake.
   - Confirm that track-zone and driver-review files are up to date before rebuilding `zone_pass`.

2. Rebuild curve inputs.
   - Rebuild `zone_pass` observations from the current dataset sidecar, zone table, and driver review.
   - Recompute zone summaries, curve points, and binned curve tables before touching the continuous model layer.

3. Refit the model layer.
   - Rebuild piecewise zone models from the latest binned observations.
   - Preserve the distinction between `model_ready`, `diagnostic_only`, `review_excluded`, and low-data outputs.

4. Run sanity checks.
   - Compare local zone deltas with the full-lap sanity table.
   - Review `zone_start_zero_throttle`, anomalous telemetry windows, and model flags before trusting optimizer changes.
   - Treat full-lap time as a validation layer, not the objective function.

5. Decide what happens next.
   - If model flags remain weak, identify the exact zone and bin gap instead of broadly asking for more data.
   - If the surfaces are credible, hand off to strategy planning or recommendation-execution work.

## Guardrails

- Keep driver-review exclusions and annotations visible in the analysis instead of hiding them with ad hoc filters.
- Put boundary changes in `config/track_zones/` and document the racing assumption.
- Do not jump to heavier ML here. This skill is for transparent curve maintenance and sanity checks.

## Report Back

Always report:
- what was rebuilt
- which zones materially changed
- which quality flags remain
- whether new targeted data is still justified
