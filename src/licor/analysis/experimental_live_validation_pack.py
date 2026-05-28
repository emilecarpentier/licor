from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

import polars as pl

from licor.analysis import load_live_cue_plan


@dataclass(frozen=True)
class ExperimentalLiveValidationPackConfig:
    variant_key: str
    recommended_run_nickname: str
    planned_lico_profile_id: str
    planned_lico_profile_description: str
    scored_lap_count: int
    warmup_lap_count: int
    include_t14: bool = False
    pack_status: str = "candidate"
    status_summary: str = ""
    collection_protocol_id: str = "spa_lmp2_v2_collection_protocol"
    collection_session_id: str = "recommendation_execution"
    collection_design: str = "recommendation_execution"
    operator_mode: str = "static_live_validation"
    source_run_id: str = ""
    source_plan_id: str = ""
    source_current_lap_number: int | None = None
    source_next_lap_number: int | None = None


def write_experimental_live_validation_pack(
    plan_csv_path: str | Path,
    *,
    config: ExperimentalLiveValidationPackConfig,
    output_dir: str | Path,
    protocol_doc_path: str | Path,
    replay_validation_report_path: str | Path,
    replanner_validation_report_path: str | Path,
) -> Path:
    plan_path = Path(plan_csv_path)
    plan = load_live_cue_plan(plan_path)
    if plan.is_empty():
        raise ValueError("live validation pack requires a non-empty plan")

    pack_dir = Path(output_dir) / config.variant_key
    pack_dir.mkdir(parents=True, exist_ok=True)

    copied_plan_path = pack_dir / "plan.csv"
    plan.write_csv(copied_plan_path)

    notes_path = pack_dir / "lap_notes_template.csv"
    build_live_validation_lap_notes_template(
        plan,
        config=config,
    ).write_csv(notes_path)

    zone_signoff_path = pack_dir / "zone_signoff_template.csv"
    build_live_validation_zone_signoff_template(plan).write_csv(zone_signoff_path)

    metadata_path = pack_dir / "run_metadata_template.json"
    metadata_path.write_text(
        json.dumps(
            build_live_validation_run_metadata_template(plan, config=config),
            indent=2,
        ),
        encoding="utf-8",
    )

    readme_path = pack_dir / "README.md"
    readme_path.write_text(
        _pack_readme(
            plan,
            config=config,
            protocol_doc_path=protocol_doc_path,
            notes_path=notes_path,
            zone_signoff_path=zone_signoff_path,
            metadata_path=metadata_path,
            replay_validation_report_path=replay_validation_report_path,
            replanner_validation_report_path=replanner_validation_report_path,
        ),
        encoding="utf-8",
    )

    plan_hash = _sha256_file(copied_plan_path)
    manifest = {
        "pack_id": f"spa_live_validation_{config.variant_key}",
        "variant_key": config.variant_key,
        "recommended_run_nickname": config.recommended_run_nickname,
        "plan_id": str(plan.row(0, named=True)["plan_id"]),
        "plan_sha256": plan_hash,
        "git_commit_sha": _git_head_sha(),
        "pack_status": config.pack_status,
        "status_summary": config.status_summary,
        "collection_protocol_id": config.collection_protocol_id,
        "collection_session_id": config.collection_session_id,
        "collection_design": config.collection_design,
        "operator_mode": config.operator_mode,
        "planned_lico_profile_id": config.planned_lico_profile_id,
        "planned_lico_profile_description": config.planned_lico_profile_description,
        "target_zones": plan["zone_id"].to_list(),
        "source_reference": {
            "source_run_id": config.source_run_id,
            "source_plan_id": config.source_plan_id,
            "source_current_lap_number": config.source_current_lap_number,
            "source_next_lap_number": config.source_next_lap_number,
        },
        "files": {
            "plan_csv": str(copied_plan_path),
            "lap_notes_template_csv": str(notes_path),
            "zone_signoff_template_csv": str(zone_signoff_path),
            "run_metadata_template_json": str(metadata_path),
            "readme_md": str(readme_path),
            "protocol_doc": str(protocol_doc_path),
            "replay_validation_report_html": str(replay_validation_report_path),
            "replanner_validation_report_html": str(replanner_validation_report_path),
        },
    }
    (pack_dir / "pack_manifest.json").write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )

    return pack_dir


def build_live_validation_lap_notes_template(
    plan: pl.DataFrame,
    *,
    config: ExperimentalLiveValidationPackConfig,
) -> pl.DataFrame:
    zone_columns = {
        "spa_t01": "t01",
        "spa_t05_t06": "t05_t06",
        "spa_t08": "t08",
        "spa_t10_t11": "t10_t11",
        "spa_t12_t13": "t12_t13",
        "spa_t14": "t14",
        "spa_t18": "t18",
    }
    selected_zone_ids = set(plan["zone_id"].to_list())
    rows = []
    total_laps = config.warmup_lap_count + config.scored_lap_count
    for lap_index in range(1, total_laps + 1):
        row = {
            "lap_index": lap_index,
            "variant_key": config.variant_key,
            "lap_role": "warmup" if lap_index <= config.warmup_lap_count else "scored",
            "scored": lap_index > config.warmup_lap_count,
            "notes": "",
        }
        for zone_id, column_name in zone_columns.items():
            row[column_name] = "" if zone_id in selected_zone_ids else "n/a"
        rows.append(row)
    return pl.DataFrame(rows)


def build_live_validation_run_metadata_template(
    plan: pl.DataFrame,
    *,
    config: ExperimentalLiveValidationPackConfig,
) -> dict[str, object]:
    first_row = plan.row(0, named=True)
    return {
        "run_id": "<fill_me>",
        "file": "data/<replace_with_duckdb_file>.duckdb",
        "track": str(first_row.get("track_name") or "Spa-Francorchamps"),
        "car_class": str(first_row.get("car_class") or "LMP2_ELMS"),
        "car": "<fill_me>",
        "session_type": "Practice",
        "run_type": "recommendation execution live candidate",
        "collection_label": "recommendation_execution",
        "labels_quality": "unknown",
        "valid_laps": [],
        "borderline_laps": [],
        "context_laps": [],
        "excluded_laps": [],
        "include_in_lap_summary": True,
        "collection_protocol_id": config.collection_protocol_id,
        "collection_session_id": config.collection_session_id,
        "collection_design": config.collection_design,
        "target_zones": plan["zone_id"].to_list(),
        "target_zones_source": "from_exported_plan",
        "planned_lico_profile_id": config.planned_lico_profile_id,
        "planned_lico_profile_description": config.planned_lico_profile_description,
        "audio_cue_plan_id": str(first_row["plan_id"]),
        "execution_quality": "unknown",
        "driver_notes": "",
    }


def build_live_validation_zone_signoff_template(plan: pl.DataFrame) -> pl.DataFrame:
    return plan.select(
        "zone_id",
        "display_label",
        "selected_lico_distance_m",
        "planned_lift_start_m",
    ).with_columns(
        pl.lit("").alias("pre_drive_signoff"),
        pl.lit("").alias("post_run_status"),
        pl.lit("").alias("notes"),
    )


def _pack_readme(
    plan: pl.DataFrame,
    *,
    config: ExperimentalLiveValidationPackConfig,
    protocol_doc_path: str | Path,
    notes_path: Path,
    zone_signoff_path: Path,
    metadata_path: Path,
    replay_validation_report_path: str | Path,
    replanner_validation_report_path: str | Path,
) -> str:
    first_row = plan.row(0, named=True)
    plan_id = str(first_row["plan_id"])
    cue_lines = "\n".join(
        f"- `{row['display_label']}`: `{row['selected_lico_distance_m']:.3f} m` before brake"
        for row in plan.iter_rows(named=True)
    )
    status_summary = config.status_summary or "No additional operator status note."
    source_reference_lines = ""
    if config.source_run_id or config.source_plan_id:
        source_reference_lines = f"""
Source reference:

- `source_run_id`: `{config.source_run_id or 'n/a'}`
- `source_plan_id`: `{config.source_plan_id or 'n/a'}`
- `source_current_lap_number`: `{config.source_current_lap_number if config.source_current_lap_number is not None else 'n/a'}`
- `source_next_lap_number`: `{config.source_next_lap_number if config.source_next_lap_number is not None else 'n/a'}`
"""
    return f"""# Spa Live Validation Pack: {config.variant_key}

Status:

```text
{config.pack_status}
```

Status summary:

```text
{status_summary}
```

Operator mode:

```text
{config.operator_mode}
```

Plan id:

```text
{plan_id}
```

Recommended run nickname:

```text
{config.recommended_run_nickname}
```

Cue summary:

{cue_lines}
{source_reference_lines}

Files in this pack:

- `plan.csv`
- `{notes_path.name}`
- `{zone_signoff_path.name}`
- `{metadata_path.name}`
- `pack_manifest.json`

Reference docs:

- Protocol: `{Path(protocol_doc_path)}`
- Adaptive replay validation: `{Path(replay_validation_report_path)}`
- Replanner validation: `{Path(replanner_validation_report_path)}`

Suggested bench beep command:

```powershell
uv run python scripts/run_lmu_live_cues.py --bench-beep-only
```

Suggested shadow replay command:

```powershell
uv run python scripts/run_live_cue_replay.py --plan "{Path('plan.csv')}" --telemetry "<path-to-telemetry-samples.csv>" --event-log "shadow_replay_events.csv" --run-id "{config.recommended_run_nickname}" --emit-system-beep
```

Metadata reminder:

- `collection_design = recommendation_execution`
- `audio_cue_plan_id = {plan_id}`
- `planned_lico_profile_id = {config.planned_lico_profile_id}`
- preserve raw telemetry, cue logs, and lap notes together
- use one recording for one `plan_id`; do not mix Candidate A and Candidate B in
  the same telemetry file
"""


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_head_sha() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return ""
    return result.stdout.strip()
