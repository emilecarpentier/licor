# Codex And ChatGPT Instructions

## Project Direction

LICOR is currently an offline telemetry analysis project. Prioritize a reliable
offline pipeline before adding live telemetry, audio cues, overlays, or machine
learning.

The project's first target is:

- Le Mans Ultimate;
- LMP2;
- Spa;
- recorded telemetry files;
- controlled sessions produced by an expert driver.

## Collaboration Style

The user is a master's student in economics and a high-level esport driver, not
a software engineer. Explain technical tradeoffs clearly, avoid unnecessary
engineering complexity, and keep the implementation path professional but
approachable.

The user has deep driving, racing, and vehicle dynamics knowledge. Do not treat
LICOR as a black-box automation project. The goal is to convert expert driving
intuition into explicit, testable rules and metrics.

## Development Priorities

When adding code, prefer this order:

1. data contracts and normalized column names;
2. telemetry ingestion;
3. preprocessing and lap validation;
4. fuel usage and lap summaries;
5. braking zone detection;
6. driver-reviewed track zone definitions;
7. lift-and-coast candidate detection inside zones;
8. push versus LICO comparison by zone;
9. zone-level optimization;
10. pit stop/refill analysis;
11. race strategy optimization;
12. reports and plots;
13. Streamlit dashboard;
14. live features.

## Technical Preferences

- Use Polars for tabular telemetry transformations.
- Use Pydantic for explicit data contracts or configuration models when useful.
- Use DuckDB only when persistent analytical storage is actually needed.
- Use Plotly for interactive charts.
- Use Streamlit only after the core analysis functions work.
- Use Pytest for small, focused tests.
- Use Ruff for formatting and lint checks.

## Coding Rules

- Keep analysis logic out of the Streamlit app.
- Prefer pure functions for telemetry calculations.
- Add tests for every non-trivial metric or detection rule.
- Keep thresholds configurable rather than hard-coded deep inside functions.
- Keep raw telemetry files out of Git.
- Keep `config/lmu_telemetry_config.reference.json` in Git as the expected LMU
  signal inventory.
- Treat full-lap time as a validation/sanity metric, not the primary objective
  for LICO optimization.
- Optimize LICO from zone-level cost/benefit estimates: fuel saved inside a
  causal zone versus local time lost inside that same zone.
- Treat `none`, `low`, `medium`, and `high` as data collection labels, not
  output classes. The final optimizer should choose continuous lift distances or
  durations by zone.
- Evaluate fuel saving in race-strategy terms: avoided pit stops can matter more
  than isolated lap-time deltas.
- Keep pit stop telemetry separate from LICO calibration telemetry, but use it to
  estimate pit loss, refill duration, and refill rate.
- Do not add machine learning until transparent heuristics have been validated.
- Do not expand to other cars or tracks until the Spa LMP2 workflow is useful.

## Documentation Rules

Update documentation when changing:

- the expected telemetry schema;
- the definition of a valid lap;
- the definition of a braking zone;
- the definition of a lift-and-coast zone;
- the definition of a causal track zone;
- any metric used to rank recommendations;
- the MVP scope.

If a coding decision depends on racing assumptions, document the assumption and
flag it for driver review.

## Preferred Output From Codex

For each meaningful change, Codex should report:

- what changed;
- what assumptions were made;
- how it was tested;
- what remains uncertain.

When possible, include exact commands to reproduce checks, such as:

```powershell
uv run pytest
uv run ruff check .
```
