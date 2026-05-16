from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class AudioCue:
    plan_id: str
    zone_id: str
    display_label: str
    lap_number: int
    trigger_status: str
    audio_cue_kind: str = "beep"


class AudioCueAdapter(Protocol):
    def emit(self, cue: AudioCue) -> None:
        """Emit one cue notification."""


class NullAudioCueAdapter:
    def emit(self, cue: AudioCue) -> None:
        return None


class RecordingAudioCueAdapter:
    def __init__(self) -> None:
        self.cues: list[AudioCue] = []

    def emit(self, cue: AudioCue) -> None:
        self.cues.append(cue)


@dataclass(frozen=True)
class SystemBeepAudioCueAdapter:
    frequency_hz: int = 1200
    duration_ms: int = 90

    def emit(self, cue: AudioCue) -> None:
        del cue
        try:
            import winsound
        except ImportError:
            print("\a", end="", flush=True)
            return
        winsound.Beep(self.frequency_hz, self.duration_ms)
