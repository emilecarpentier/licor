import json

import polars as pl
import pytest
from pydantic import ValidationError

from licor.analysis.collection_protocol import load_collection_protocol


def test_loads_collection_protocol_to_frame(tmp_path):
    path = tmp_path / "protocol.json"
    path.write_text(
        json.dumps(
            {
                "protocol_id": "synthetic_v2",
                "dataset_id": "synthetic",
                "track_name": "Synthetic Spa",
                "car_class": "LMP2_TEST",
                "purpose": "Synthetic collection protocol.",
                "sessions": [
                    {
                        "session_id": "baseline",
                        "collection_design": "baseline",
                        "objective": "Refresh baseline.",
                        "minimum_clean_laps": 5,
                    },
                    {
                        "session_id": "targeted",
                        "collection_design": "targeted_zone",
                        "objective": "Target one zone.",
                        "target_zones": ["spa_t05_t06"],
                        "minimum_clean_laps": 4,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    protocol = load_collection_protocol(path)
    frame = protocol.to_frame()

    assert frame.select("session_id", "collection_design", "target_zones").rows() == [
        ("baseline", "baseline", []),
        ("targeted", "targeted_zone", ["spa_t05_t06"]),
    ]


def test_loads_spa_v2_protocol_config():
    protocol = load_collection_protocol("config/collection_protocols/spa_lmp2_v2_protocol.json")
    frame = protocol.to_frame()

    assert protocol.protocol_id == "spa_lmp2_v2_collection_protocol"
    assert set(frame["collection_design"].to_list()) == {
        "baseline",
        "controlled_random",
        "targeted_zone",
        "pitstop_validation",
        "recommendation_execution",
    }
    targeted = frame.filter(pl.col("collection_design") == "targeted_zone").row(
        0,
        named=True,
    )
    assert "spa_t05_t06" in targeted["target_zones"]
    recommendation = frame.filter(
        pl.col("collection_design") == "recommendation_execution"
    ).row(0, named=True)
    assert recommendation["target_zones"] == []
    assert recommendation["target_zones_source"] == "from_exported_plan"


def test_normalizes_legacy_pit_stop_collection_design(tmp_path):
    path = tmp_path / "protocol.json"
    path.write_text(
        json.dumps(
            {
                "protocol_id": "synthetic_v2",
                "dataset_id": "synthetic",
                "track_name": "Synthetic Spa",
                "car_class": "LMP2_TEST",
                "purpose": "Synthetic collection protocol.",
                "sessions": [
                    {
                        "session_id": "pit",
                        "collection_design": "pit_stop_validation",
                        "objective": "Legacy spelling.",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    frame = load_collection_protocol(path).to_frame()

    assert frame["collection_design"].to_list() == ["pitstop_validation"]


def test_rejects_targeted_protocol_without_target_zones(tmp_path):
    path = tmp_path / "protocol.json"
    path.write_text(
        json.dumps(
            {
                "protocol_id": "bad",
                "dataset_id": "synthetic",
                "track_name": "Synthetic Spa",
                "car_class": "LMP2_TEST",
                "purpose": "Bad protocol.",
                "sessions": [
                    {
                        "session_id": "targeted",
                        "collection_design": "targeted_zone",
                        "objective": "Missing target.",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError):
        load_collection_protocol(path)


def test_rejects_duplicate_collection_session_ids(tmp_path):
    path = tmp_path / "protocol.json"
    path.write_text(
        json.dumps(
            {
                "protocol_id": "bad",
                "dataset_id": "synthetic",
                "track_name": "Synthetic Spa",
                "car_class": "LMP2_TEST",
                "purpose": "Bad protocol.",
                "sessions": [
                    {
                        "session_id": "baseline",
                        "collection_design": "baseline",
                        "objective": "First.",
                    },
                    {
                        "session_id": "baseline",
                        "collection_design": "baseline",
                        "objective": "Duplicate.",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError):
        load_collection_protocol(path)
