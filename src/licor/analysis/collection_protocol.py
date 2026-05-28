from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

import polars as pl
from pydantic import BaseModel, Field, model_validator


CollectionDesign = Literal[
    "baseline",
    "controlled_random",
    "targeted_zone",
    "recommendation_execution",
    "pitstop_validation",
]


class CollectionProtocolSession(BaseModel):
    session_id: str
    collection_design: CollectionDesign
    objective: str
    target_zones: tuple[str, ...] = Field(default_factory=tuple)
    target_zones_source: str = ""
    minimum_clean_laps: int = Field(default=1, ge=0)
    lico_variation_guidance: str = ""
    execution_quality_notes: str = ""
    notes: str = ""

    @model_validator(mode="before")
    @classmethod
    def normalize_collection_design_entry(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        normalized = dict(data)
        if "objective" not in normalized and "purpose" in normalized:
            normalized["objective"] = normalized["purpose"]
        if "session_id" not in normalized and "collection_design" in normalized:
            normalized["session_id"] = normalized["collection_design"]
        if normalized.get("collection_design") == "pit_stop_validation":
            normalized["collection_design"] = "pitstop_validation"
        if "target_zones" not in normalized and "target_groups" in normalized:
            normalized["target_zones"] = _flatten_target_groups(normalized["target_groups"])
        if isinstance(normalized.get("target_zones"), str):
            normalized["target_zones_source"] = normalized["target_zones"]
            normalized["target_zones"] = []
        if "minimum_clean_laps" not in normalized and "suggested_valid_laps" in normalized:
            normalized["minimum_clean_laps"] = _minimum_lap_count(
                normalized["suggested_valid_laps"]
            )
        if "lico_variation_guidance" not in normalized and "constraints" in normalized:
            normalized["lico_variation_guidance"] = " ".join(normalized["constraints"])
        if (
            "execution_quality_notes" not in normalized
            and "primary_quality_checks" in normalized
        ):
            normalized["execution_quality_notes"] = " ".join(
                normalized["primary_quality_checks"]
            )
        return normalized

    @model_validator(mode="after")
    def targeted_sessions_need_targets(self) -> CollectionProtocolSession:
        if self.collection_design == "targeted_zone" and not self.target_zones:
            raise ValueError("targeted_zone sessions require at least one target zone")
        return self


class CollectionProtocol(BaseModel):
    schema_version: int = 1
    protocol_id: str
    dataset_id: str
    track_name: str
    car_class: str
    purpose: str
    required_run_metadata: tuple[str, ...] = Field(default_factory=tuple)
    sessions: list[CollectionProtocolSession] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def normalize_protocol_shape(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        normalized = dict(data)
        if "schema_version" not in normalized and "protocol_version" in normalized:
            normalized["schema_version"] = normalized["protocol_version"]
        if "track_name" not in normalized and "track" in normalized:
            normalized["track_name"] = normalized["track"]
        if "dataset_id" not in normalized and "source_dataset_id" in normalized:
            normalized["dataset_id"] = normalized["source_dataset_id"]
        if "purpose" not in normalized and "objectives" in normalized:
            normalized["purpose"] = " ".join(str(item) for item in normalized["objectives"])
        if "sessions" not in normalized and "collection_designs" in normalized:
            normalized["sessions"] = normalized["collection_designs"]
        return normalized

    @model_validator(mode="after")
    def session_ids_must_be_unique(self) -> CollectionProtocol:
        session_ids = [session.session_id for session in self.sessions]
        if len(session_ids) != len(set(session_ids)):
            raise ValueError("collection protocol session_id values must be unique")
        return self

    def to_frame(self) -> pl.DataFrame:
        if not self.sessions:
            return _empty_collection_protocol_frame()
        return pl.DataFrame(
            [
                {
                    **session.model_dump(),
                    "protocol_id": self.protocol_id,
                    "dataset_id": self.dataset_id,
                    "track_name": self.track_name,
                    "car_class": self.car_class,
                }
                for session in self.sessions
            ],
            schema=_COLLECTION_PROTOCOL_SCHEMA,
            strict=False,
        ).select(_COLLECTION_PROTOCOL_COLUMNS)


def load_collection_protocol(path: str | Path) -> CollectionProtocol:
    with Path(path).open(encoding="utf-8") as file:
        return CollectionProtocol.model_validate(json.load(file))


def _empty_collection_protocol_frame() -> pl.DataFrame:
    return pl.DataFrame(schema=_COLLECTION_PROTOCOL_SCHEMA)


def _flatten_target_groups(target_groups: object) -> list[str]:
    flattened = []
    if not isinstance(target_groups, list):
        return flattened
    for group in target_groups:
        if isinstance(group, list):
            flattened.extend(str(zone_id) for zone_id in group)
        elif isinstance(group, str):
            flattened.append(group)
    return flattened


def _minimum_lap_count(value: object) -> int:
    text = str(value)
    digits = []
    for character in text:
        if character.isdigit():
            digits.append(character)
        elif digits:
            break
    return int("".join(digits)) if digits else 0


_COLLECTION_PROTOCOL_COLUMNS = [
    "protocol_id",
    "dataset_id",
    "track_name",
    "car_class",
    "session_id",
    "collection_design",
    "objective",
    "target_zones",
    "target_zones_source",
    "minimum_clean_laps",
    "lico_variation_guidance",
    "execution_quality_notes",
    "notes",
]

_COLLECTION_PROTOCOL_SCHEMA = {
    "protocol_id": pl.String,
    "dataset_id": pl.String,
    "track_name": pl.String,
    "car_class": pl.String,
    "session_id": pl.String,
    "collection_design": pl.String,
    "objective": pl.String,
    "target_zones": pl.List(pl.String),
    "target_zones_source": pl.String,
    "minimum_clean_laps": pl.Int64,
    "lico_variation_guidance": pl.String,
    "execution_quality_notes": pl.String,
    "notes": pl.String,
}
