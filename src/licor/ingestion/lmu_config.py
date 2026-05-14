from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class LmuConfiguredChannel:
    key: str
    name: str
    frequency_hz: int


@dataclass(frozen=True)
class LmuConfiguredEvent:
    key: str
    name: str


@dataclass(frozen=True)
class FrequencyMismatch:
    channel_name: str
    expected_hz: int
    observed_hz: int


@dataclass(frozen=True)
class LmuTelemetryConfig:
    channels: dict[str, LmuConfiguredChannel]
    events: dict[str, LmuConfiguredEvent]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LmuTelemetryConfig:
        channels = {
            key: LmuConfiguredChannel(
                key=key,
                name=str(value["Name"]),
                frequency_hz=int(value["Frequency"]),
            )
            for key, value in data.get("Channels", {}).items()
        }
        events = {
            key: LmuConfiguredEvent(key=key, name=str(value["Name"]))
            for key, value in data.get("Events", {}).items()
        }
        return cls(channels=channels, events=events)

    @property
    def channel_names(self) -> set[str]:
        return {channel.name for channel in self.channels.values()}

    @property
    def event_names(self) -> set[str]:
        return {event.name for event in self.events.values()}

    def missing_channels(self, observed_channel_names: set[str]) -> set[str]:
        return self.channel_names - observed_channel_names

    def missing_events(self, observed_event_names: set[str]) -> set[str]:
        return self.event_names - observed_event_names

    def frequency_mismatches(
        self, observed_frequencies_hz: dict[str, int]
    ) -> list[FrequencyMismatch]:
        mismatches: list[FrequencyMismatch] = []
        for channel in self.channels.values():
            observed = observed_frequencies_hz.get(channel.name)
            if observed is not None and observed != channel.frequency_hz:
                mismatches.append(
                    FrequencyMismatch(
                        channel_name=channel.name,
                        expected_hz=channel.frequency_hz,
                        observed_hz=observed,
                    )
                )
        return mismatches


def load_lmu_telemetry_config(path: str | Path) -> LmuTelemetryConfig:
    with Path(path).open(encoding="utf-8") as file:
        data = json.load(file)
    return LmuTelemetryConfig.from_dict(data)
