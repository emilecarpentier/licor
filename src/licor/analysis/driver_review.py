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
    run_id: str = ""
    reason: str
    notes: str = ""


class ZonePassAnnotation(BaseModel):
    lap_number: int
    zone_id: str
    run_id: str = ""
    review_tags: list[str] = Field(default_factory=list)
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
    zone_pass_annotations: list[ZonePassAnnotation] = Field(default_factory=list)

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

    def pass_annotation_frame(self) -> pl.DataFrame:
        if not self.zone_pass_annotations:
            return _empty_pass_annotation_frame()
        return pl.DataFrame(
            [annotation.model_dump() for annotation in self.zone_pass_annotations],
            schema=_PASS_ANNOTATION_SCHEMA,
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
        reviewed = _apply_exclusions(
            reviewed,
            exclusions,
            excluded_validity_label=excluded_validity_label,
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

    pass_annotations = review.pass_annotation_frame()
    if not pass_annotations.is_empty():
        pass_annotations = pass_annotations.rename(
            {
                "review_tags": "driver_review_pass_tags",
                "notes": "driver_review_pass_notes",
            }
        )
        run_specific = pass_annotations.filter(pl.col("run_id") != "")
        run_agnostic = pass_annotations.filter(pl.col("run_id") == "").drop("run_id")
        if not run_specific.is_empty() and "run_id" in reviewed.columns:
            reviewed = reviewed.join(
                run_specific,
                on=["run_id", "lap_number", "zone_id"],
                how="left",
            )
        if not run_agnostic.is_empty():
            reviewed = reviewed.join(
                run_agnostic,
                on=["lap_number", "zone_id"],
                how="left",
                suffix="_generic",
            )
        reviewed = _coalesce_pass_annotation_columns(reviewed)
    else:
        reviewed = reviewed.with_columns(
            pl.lit([]).alias("driver_review_pass_tags"),
            pl.lit("").alias("driver_review_pass_notes"),
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


def _empty_pass_annotation_frame() -> pl.DataFrame:
    return pl.DataFrame(schema=_PASS_ANNOTATION_SCHEMA)


def _apply_exclusions(
    zone_passes: pl.DataFrame,
    exclusions: pl.DataFrame,
    *,
    excluded_validity_label: str,
) -> pl.DataFrame:
    reviewed = zone_passes
    run_specific = exclusions.filter(pl.col("run_id") != "")
    run_agnostic = exclusions.filter(pl.col("run_id") == "").drop("run_id")
    if not run_specific.is_empty() and "run_id" in reviewed.columns:
        reviewed = reviewed.join(
            run_specific,
            on=["run_id", "lap_number", "zone_id"],
            how="left",
        )
    if not run_agnostic.is_empty():
        reviewed = reviewed.join(
            run_agnostic,
            on=["lap_number", "zone_id"],
            how="left",
            suffix="_generic",
        )
    reviewed = _coalesce_exclusion_columns(reviewed)
    return reviewed.with_columns(
        pl.when(pl.col("driver_review_exclusion_reason") != "")
        .then(pl.lit(excluded_validity_label))
        .otherwise(pl.col("validity_label"))
        .alias("validity_label")
    )


def _coalesce_exclusion_columns(frame: pl.DataFrame) -> pl.DataFrame:
    reason_columns = [
        column
        for column in (
            "driver_review_exclusion_reason",
            "driver_review_exclusion_reason_generic",
        )
        if column in frame.columns
    ]
    note_columns = [
        column
        for column in (
            "driver_review_exclusion_notes",
            "driver_review_exclusion_notes_generic",
        )
        if column in frame.columns
    ]
    if reason_columns:
        frame = frame.with_columns(
            pl.coalesce([pl.col(column) for column in reason_columns] + [pl.lit("")]).alias(
                "driver_review_exclusion_reason"
            )
        )
    else:
        frame = frame.with_columns(pl.lit("").alias("driver_review_exclusion_reason"))
    if note_columns:
        frame = frame.with_columns(
            pl.coalesce([pl.col(column) for column in note_columns] + [pl.lit("")]).alias(
                "driver_review_exclusion_notes"
            )
        )
    else:
        frame = frame.with_columns(pl.lit("").alias("driver_review_exclusion_notes"))
    return frame.drop(
        [
            column
            for column in (
                "driver_review_exclusion_reason_generic",
                "driver_review_exclusion_notes_generic",
            )
            if column in frame.columns
        ]
    )


def _coalesce_pass_annotation_columns(frame: pl.DataFrame) -> pl.DataFrame:
    tag_columns = [
        column
        for column in ("driver_review_pass_tags", "driver_review_pass_tags_generic")
        if column in frame.columns
    ]
    note_columns = [
        column
        for column in ("driver_review_pass_notes", "driver_review_pass_notes_generic")
        if column in frame.columns
    ]
    if tag_columns:
        frame = frame.with_columns(
            pl.coalesce([pl.col(column) for column in tag_columns] + [pl.lit([])]).alias(
                "driver_review_pass_tags"
            )
        )
    else:
        frame = frame.with_columns(pl.lit([]).alias("driver_review_pass_tags"))
    if note_columns:
        frame = frame.with_columns(
            pl.coalesce([pl.col(column) for column in note_columns] + [pl.lit("")]).alias(
                "driver_review_pass_notes"
            )
        )
    else:
        frame = frame.with_columns(pl.lit("").alias("driver_review_pass_notes"))
    return frame.drop(
        [
            column
            for column in ("driver_review_pass_tags_generic", "driver_review_pass_notes_generic")
            if column in frame.columns
        ]
    )


_EXCLUSION_SCHEMA = {
    "lap_number": pl.Int64,
    "zone_id": pl.String,
    "run_id": pl.String,
    "reason": pl.String,
    "notes": pl.String,
}

_ANNOTATION_SCHEMA = {
    "zone_id": pl.String,
    "signal_tags": pl.List(pl.String),
    "notes": pl.String,
}

_PASS_ANNOTATION_SCHEMA = {
    "lap_number": pl.Int64,
    "zone_id": pl.String,
    "run_id": pl.String,
    "review_tags": pl.List(pl.String),
    "notes": pl.String,
}
