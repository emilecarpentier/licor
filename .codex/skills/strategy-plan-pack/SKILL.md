---
name: strategy-plan-pack
description: Build LICOR strategy outputs from current zone models. Use when Spa models are ready enough to support race-fuel targets, optimizer plans, marginal and sensitivity diagnostics, or exportable live-cue plans and replay-style execution tables.
---

# Strategy Plan Pack

## Overview

Use this skill to rebuild the decision layer above the zone models. Focus on explicit race assumptions, optimizer outputs, diagnostics, and live-cue execution artifacts.

## Source Of Truth

Read `references/source-files.md` before changing any race assumption or interpreting an optimizer output.

## Workflow

1. Confirm prerequisites.
   - Use current zone models, current driver-review state, and explicit race assumptions.
   - Do not silently change lap-count overrides, pit assumptions, or safety margins.

2. Rebuild strategy context.
   - Recompute fuel targets and stop-count comparisons from the latest baseline and pit data.
   - Rebuild conservative and driver-prior plans when both are relevant to the discussion.

3. Rebuild diagnostics.
   - Refresh marginal fuel-time efficiency outputs.
   - Refresh sensitivity scenarios for stricter caps, safety margins, and diagnostic-zone exclusion.
   - Report when the target is unreachable without dipping into weak or diagnostic zones.

4. Rebuild execution artifacts when needed.
   - Export a live-cue plan from the selected strategy plan.
   - If replay data or observed zone passes exist, rebuild replay-style execution rows for planned-versus-observed comparison.

## Guardrails

- Keep strategy priors explicit and editable. Do not bury driver judgments inside ad hoc code.
- Call out when a plan depends on diagnostic-only or weak-confidence zones.
- Keep the race model simple and transparent until empirical cue validation is credible.

## Report Back

Always report:
- race assumptions used
- target fuel saving and whether it is reachable
- plan variant rebuilt
- diagnostics that changed
- whether the project should move to recommendation-execution validation or back to data collection
