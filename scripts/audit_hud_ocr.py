"""Score frozen, offline HUD OCR against manual labels; never feed live LICOR."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


RACE_LINE = re.compile(
    r"(?:Tour\s+)?(?P<lap>[0-9]+|I|l)\s*/\s*"
    r"(?P<marker>~|--)?\s*(?P<total>[0-9]+(?:\.[0-9])?)"
)
FUEL_LINE = re.compile(
    r"[0-9O]+\.[0-9O]\s*L\s*\(\s*(?P<laps>[0-9]+\.[0-9])\s+laps\s*\)"
)
RACE_LINE_V2 = re.compile(RACE_LINE.pattern.replace("~|--", "~|--|-"))
FUEL_LINE_V2 = re.compile(r"[^()\r\n]{1,12}\(\s*(?P<laps>[0-9]+\.[0-9])\s+laps\s*\)")
ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / "docs/evidence/bahrain_race_hud_2026-10-01.json"


def parse_hud(row: dict) -> dict:
    """Return isolated numeric candidates, not certified estimates or horizons.

    No digit repair, decimal insertion, carry-forward or future-frame lookahead.
    I/l in the lap slot and -- in the approximation slot remain ambiguous.
    Windows OCR supplies no confidence, so syntax is not a confidence score.
    """
    result = {
        "total_display": None,
        "fuel_laps": None,
        "lap_display": None,
        "estimated": None,
        "race_status": "unreadable",
        "fuel_status": "unreadable",
        "live_authorized": False,
    }
    v2 = row.get("reader") == "windows_ocr_en-US_v2"
    race_pattern = RACE_LINE_V2 if v2 else RACE_LINE
    fuel_pattern = FUEL_LINE_V2 if v2 else FUEL_LINE
    lines = row.get("race_lines", [])
    if any(re.fullmatch(r"Tour(?:\s+.*)?", line.strip()) for line in lines):
        matches = [m for line in lines if (m := race_pattern.fullmatch(line.strip()))]
        if len(matches) == 1:
            match = matches[0]
            total = match["total"]
            # An approximate value with a lost decimal point must be rejected.
            if float(total) > 0 and (not match["marker"] or "." in total):
                result["total_display"] = float(total)
                lap = match["lap"]
                if lap.isascii() and lap.isdigit() and int(lap) > 0:
                    result["lap_display"] = int(lap)
                if match["marker"] not in ("--", "-"):
                    result["estimated"] = match["marker"] == "~"
                result["race_status"] = (
                    "candidate_ambiguous_context"
                    if result["lap_display"] is None or result["estimated"] is None
                    else "candidate"
                )
    fuel = fuel_pattern.fullmatch(row.get("fuel_text", "").strip())
    if fuel:
        result["fuel_laps"] = float(fuel["laps"])
        result["fuel_status"] = "candidate"
    return result


def evaluate(raw: list[dict], reference: list[dict]) -> tuple[list[dict], dict]:
    labels = {r["video_s"]: r for r in reference}
    if len(labels) != len(reference):
        raise ValueError("Duplicate reference timestamps")
    timestamps = [r["video_s"] for r in raw]
    if len(timestamps) != len(set(timestamps)):
        raise ValueError("Duplicate OCR timestamps")
    if set(timestamps) != set(labels):
        raise ValueError("OCR and reference timestamps must match exactly")
    rows = []
    for row in sorted(raw, key=lambda r: r["video_s"]):
        expected = labels[row["video_s"]]
        parsed = parse_hud(row)
        record = {
            **row,
            **parsed,
            "context": expected["context"],
            "split": "development" if row["video_s"] == 35 else "evaluation_same_video",
        }
        for field in ("total_display", "fuel_laps", "lap_display", "estimated"):
            truth = expected[field]
            record[f"expected_{field}"] = truth
            record[f"{field}_result"] = (
                ("correct_absent" if parsed[field] is None else "false_positive")
                if truth is None
                else "missing"
                if parsed[field] is None
                else "correct"
                if parsed[field] == truth
                else "wrong"
            )
        rows.append(record)
    evaluation = [r for r in rows if r["split"] != "development"]
    summary = {"evaluation_frames": len(evaluation), "fields": {}}
    for field in ("total_display", "fuel_laps", "lap_display", "estimated"):
        counts = {
            outcome: sum(r[f"{field}_result"] == outcome for r in evaluation)
            for outcome in (
                "correct",
                "wrong",
                "missing",
                "correct_absent",
                "false_positive",
            )
        }
        summary["fields"][field] = counts
        counts["visible_frames"] = sum(
            r[f"expected_{field}"] is not None for r in evaluation
        )
    summary["both_targets_correct"] = sum(
        r["total_display_result"] == r["fuel_laps_result"] == "correct"
        for r in evaluation
    )
    summary["live_authorized"] = False
    summary["scope"] = (
        "Frozen development on frame35; same-video holdout, not a new-session test"
    )
    return rows, summary


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reference", type=Path, default=REFERENCE)
    args = parser.parse_args()
    raw = [
        json.loads(line) for path in args.raw for line in path.read_text().splitlines()
    ]
    reference = json.loads(args.reference.read_text())
    rows, summary = evaluate(raw, reference["rows"])
    args.output.mkdir(parents=True, exist_ok=False)
    manifest = {
        "video": reference["video"],
        "reference_sha256": digest(args.reference),
        "inputs": {str(path): digest(path) for path in args.raw},
        "scripts_sha256": {
            "audit_hud_ocr.py": digest(Path(__file__)),
            "read_hud_frames.ps1": digest(ROOT / "scripts/read_hud_frames.ps1"),
        },
        "limitations": [
            "One video, one resolution and HUD layout; correlated hand-picked frames.",
            "No low-fuel or multi-digit race-total validation.",
            "No calibrated OCR confidence, frame freshness or live screen acquisition.",
            "Rounded visible numbers, not unrounded native estimators.",
            "No telemetry alignment, race-horizon conversion or live authority.",
        ],
    }
    for name, value in (("rows", rows), ("summary", summary), ("manifest", manifest)):
        (args.output / f"{name}.json").write_text(
            json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
