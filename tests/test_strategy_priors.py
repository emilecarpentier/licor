import json

import pytest
from pydantic import ValidationError

from licor.analysis import load_strategy_prior_table


def test_loads_strategy_priors_to_frame(tmp_path):
    path = tmp_path / "priors.json"
    path.write_text(
        json.dumps(
            {
                "dataset_id": "synthetic",
                "track_name": "Synthetic Spa",
                "car_class": "LMP2_TEST",
                "zones": [
                    {
                        "zone_id": "spa_t05_t06",
                        "display_label": "T05-T06",
                        "feasibility_score": 5,
                        "strategy_role": "preferred",
                    },
                    {
                        "zone_id": "spa_t09",
                        "display_label": "T09",
                        "feasibility_score": 0,
                        "strategy_role": "excluded",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    priors = load_strategy_prior_table(path)
    frame = priors.to_frame()

    assert frame.select("zone_id", "feasibility_score", "strategy_role").rows() == [
        ("spa_t05_t06", 5, "preferred"),
        ("spa_t09", 0, "excluded"),
    ]


def test_rejects_zero_rating_without_excluded_role(tmp_path):
    path = tmp_path / "priors.json"
    path.write_text(
        json.dumps(
            {
                "dataset_id": "synthetic",
                "track_name": "Synthetic Spa",
                "car_class": "LMP2_TEST",
                "zones": [
                    {
                        "zone_id": "spa_t09",
                        "feasibility_score": 0,
                        "strategy_role": "usable",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError):
        load_strategy_prior_table(path)


def test_rejects_duplicate_zone_ids(tmp_path):
    path = tmp_path / "priors.json"
    path.write_text(
        json.dumps(
            {
                "dataset_id": "synthetic",
                "track_name": "Synthetic Spa",
                "car_class": "LMP2_TEST",
                "zones": [
                    {
                        "zone_id": "spa_t18",
                        "feasibility_score": 5,
                        "strategy_role": "preferred",
                    },
                    {
                        "zone_id": "spa_t18",
                        "feasibility_score": 4,
                        "strategy_role": "usable",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError):
        load_strategy_prior_table(path)
