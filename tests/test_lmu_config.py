import json

from licor.ingestion import load_lmu_telemetry_config


def test_loads_lmu_telemetry_config_and_validates_inventory(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "Channels": {
                    "Brake Pos": {"Frequency": 50, "Name": "Brake Pos"},
                    "Fuel Level": {"Frequency": 20, "Name": "Fuel Level"},
                },
                "Events": {
                    "Lap": {"Name": "Lap"},
                    "In Pits": {"Name": "In Pits"},
                },
            }
        ),
        encoding="utf-8",
    )

    config = load_lmu_telemetry_config(config_path)

    assert config.channel_names == {"Brake Pos", "Fuel Level"}
    assert config.event_names == {"Lap", "In Pits"}
    assert config.missing_channels({"Brake Pos"}) == {"Fuel Level"}
    assert config.missing_events({"Lap"}) == {"In Pits"}

    mismatches = config.frequency_mismatches(
        {"Brake Pos": 100, "Fuel Level": 20}
    )
    assert len(mismatches) == 1
    assert mismatches[0].channel_name == "Brake Pos"
    assert mismatches[0].expected_hz == 50
    assert mismatches[0].observed_hz == 100
