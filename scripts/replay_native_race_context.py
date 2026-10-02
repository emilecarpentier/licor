"""Replay a native capture without cues, training, or fuel-plan authority."""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from licor.analysis.race_context import replay_race_context


def build(samples_path: Path, output: Path) -> dict:
    payload = samples_path.read_bytes()
    samples = [json.loads(line) for line in payload.splitlines() if line.strip()]
    rows = replay_race_context(samples)
    transitions = []
    for row in rows:
        if not transitions or row["state"] != transitions[-1]["state"]:
            transitions.append(
                {
                    key: row[key]
                    for key in (
                        "capture_elapsed_s",
                        "scoring_elapsed_s",
                        "state",
                        "completed_laps",
                    )
                }
            )
    summary = {
        "mode": "offline_diagnostic_no_cues_no_training",
        "source": str(samples_path.resolve()),
        "source_sha256": hashlib.sha256(payload).hexdigest(),
        "samples": len(rows),
        "hud_total_laps_present": sum(
            row["hud_total_laps"] is not None for row in rows
        ),
        "states": dict(Counter(row["state"] for row in rows)),
        "transitions": transitions,
        "boundaries": [row for row in rows if row["observed_player_boundary"]],
        "limitations": [
            "LICOR point forecast is not the native HUD value or a validated upper horizon.",
            "Constant last observed pace; no pit, traffic, caution or future leader-change model.",
            "First observed crossings have capture/scoring latency; no future interpolation.",
            "No fuel plan is authorized; no clean-lap or executed-action inference.",
        ],
    }
    output.mkdir(parents=True, exist_ok=False)
    (output / "replay.jsonl").write_text(
        "".join(json.dumps(row, allow_nan=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    (output / "manifest.json").write_text(
        json.dumps(summary, indent=2, allow_nan=False), encoding="utf-8"
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build(args.samples, args.output)
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
