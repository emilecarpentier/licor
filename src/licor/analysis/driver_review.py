from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

import polars as pl
from pydantic import BaseModel, Field


ReviewStatus = Literal["draft", "driver_reviewed"]


class ZoneAnnotation(BaseModel):
    zone_id: str
    signal_tags: list[str] = Field(default_factory=list)
    notes: str = ""


class ZonePassExclusion(BaseModel):
    lap_number: int
    zone_id: str
    reason: str
    notes: str = ""


class DriverZoneReview(BaseModel):
    schema_version: int = 1
    dataset_id: str
    track_name: str
    car_class: str
    review_status: ReviewStatus = "draft"
    notes: str = ""
    zone_annotations: list[ZoneAnnotation] = Field(default_factory=list)
    zone_pass_exclusions: list[ZonePassExclusion] = Field(default_factory=list)

    def exclusion_frame(self) -> pl.DataFrame:
        if not self.zone_pass_exclusions:
            return _empty_exclusion_frame()
        return pl.DataFrame(
            [exclusion.model_dump() for exclusion in self.zone_pass_exclusions],
            schema=_EXCLUSION_SCHEMA,
            strict=False,
        )

    def annotation_frame(self) -> pl.DataFrame:
        if not self.zone_annotations:
            return _empty_annotation_frame()
        return pl.DataFrame(
            [annotation.model_dump() for annotation in self.zone_annotations],
            schema=_ANNOTATION_SCHEMA,
            strict=False,
        )


def load_driver_zone_review(path: str | Path) -> DriverZoneReview:
    with Path(path).open(encoding="utf-8") as file:
        return DriverZoneReview.model_validate(json.load(file))


def apply_zone_pass_review(
    zone_passes: pl.DataFrame,
    review: DriverZoneReview,
    *,
    excluded_validity_label: str = "driver_excluded",
) -> pl.DataFrame:
    """Apply driver review exclusions and zone-level signal tags to zone passes."""

    if zone_passes.is_empty():
        return zone_passes

    reviewed = zone_passes
    exclusions = review.exclusion_frame()
    if not exclusions.is_empty():
        exclusions = exclusions.rename(
            {
                "reason": "driver_review_exclusion_reason",
                "notes": "driver_review_exclusion_notes",
            }
        )
        reviewed = reviewed.join(
            exclusions,
            on=["lap_number", "zone_id"],
            how="left",
        ).with_columns(
            pl.when(pl.col("driver_review_exclusion_reason").is_not_null())
            .then(pl.lit(excluded_validity_label))
            .otherwise(pl.col("validity_label"))
            .alias("validity_label"),
            pl.coalesce([pl.col("driver_review_exclusion_reason"), pl.lit("")]).alias(
                "driver_review_exclusion_reason"
            ),
            pl.coalesce([pl.col("driver_review_exclusion_notes"), pl.lit("")]).alias(
                "driver_review_exclusion_notes"
            ),
        )
    else:
        reviewed = reviewed.with_columns(
            pl.lit("").alias("driver_review_exclusion_reason"),
            pl.lit("").alias("driver_review_exclusion_notes"),
        )

    annotations = review.annotation_frame()
    if not annotations.is_empty():
        annotations = annotations.rename(
            {
                "signal_tags": "driver_review_signal_tags",
                "notes": "driver_review_zone_notes",
            }
        )
        reviewed = reviewed.join(annotations, on="zone_id", how="left").with_columns(
            pl.col("driver_review_signal_tags").fill_null([]).alias(
                "driver_review_signal_tags"
            ),
            pl.coalesce([pl.col("driver_review_zone_notes"), pl.lit("")]).alias(
                "driver_review_zone_notes"
            ),
        )
    else:
        reviewed = reviewed.with_columns(
            pl.lit([]).alias("driver_review_signal_tags"),
            pl.lit("").alias("driver_review_zone_notes"),
        )

    return reviewed.drop(
        [
            column
            for column in ("reason", "notes_right", "signal_tags")
            if column in reviewed.columns
        ]
    )


def _empty_exclusion_frame() -> pl.DataFrame:
    return pl.DataFrame(schema=_EXCLUSION_SCHEMA)


def _empty_annotation_frame() -> pl.DataFrame:
    return pl.DataFrame(schema=_ANNOTATION_SCHEMA)


_EXCLUSION_SCHEMA = {
    "lap_number": pl.Int64,
    "zone_id": pl.String,
    "reason": pl.String,
    "notes": pl.String,
}

_ANNOTATION_SCHEMA = {
    "zone_id": pl.String,
    "signal_tags": pl.List(pl.String),
    "notes": pl.String,
}
