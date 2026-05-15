from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

import polars as pl
from pydantic import BaseModel, Field, field_validator, model_validator


StrategyRole = Literal["preferred", "usable", "limited", "excluded"]


class ZoneStrategyPrior(BaseModel):
    zone_id: str
    display_label: str = ""
    feasibility_score: int = Field(ge=0, le=5)
    strategy_role: StrategyRole
    allow_diagnostic_model: bool = False
    max_lico_distance_m: float | None = Field(default=None, gt=0.0)
    notes: str = ""

    @field_validator("strategy_role")
    @classmethod
    def excluded_role_must_match_zero_score(
        cls,
        strategy_role: StrategyRole,
        info,
    ) -> StrategyRole:
        feasibility_score = info.data.get("feasibility_score")
        if feasibility_score == 0 and strategy_role != "excluded":
            raise ValueError("0/5 feasibility zones must use strategy_role='excluded'")
        return strategy_role


class StrategyPriorTable(BaseModel):
    schema_version: int = 1
    dataset_id: str
    track_name: str
    car_class: str
    notes: str = ""
    zones: list[ZoneStrategyPrior] = Field(default_factory=list)

    @model_validator(mode="after")
    def zone_ids_must_be_unique(self) -> StrategyPriorTable:
        zone_ids = [zone.zone_id for zone in self.zones]
        if len(zone_ids) != len(set(zone_ids)):
            raise ValueError("zone strategy prior zone_id values must be unique")
        return self

    def to_frame(self) -> pl.DataFrame:
        if not self.zones:
            return _empty_strategy_prior_frame()
        return pl.DataFrame(
            [zone.model_dump() for zone in self.zones],
            schema=_STRATEGY_PRIOR_SCHEMA,
            strict=False,
        ).select(_STRATEGY_PRIOR_COLUMNS)


def load_strategy_prior_table(path: str | Path) -> StrategyPriorTable:
    with Path(path).open(encoding="utf-8") as file:
        return StrategyPriorTable.model_validate(json.load(file))


def _empty_strategy_prior_frame() -> pl.DataFrame:
    return pl.DataFrame(schema=_STRATEGY_PRIOR_SCHEMA)


_STRATEGY_PRIOR_COLUMNS = [
    "zone_id",
    "display_label",
    "feasibility_score",
    "strategy_role",
    "allow_diagnostic_model",
    "max_lico_distance_m",
    "notes",
]

_STRATEGY_PRIOR_SCHEMA = {
    "zone_id": pl.String,
    "display_label": pl.String,
    "feasibility_score": pl.Int64,
    "strategy_role": pl.String,
    "allow_diagnostic_model": pl.Boolean,
    "max_lico_distance_m": pl.Float64,
    "notes": pl.String,
}
