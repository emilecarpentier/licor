from __future__ import annotations

from dataclasses import dataclass
from threading import Thread
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
    blocking: bool = False

    def emit(self, cue: AudioCue) -> None:
        del cue
        try:
            import winsound
        except ImportError:
            print("\a", end="", flush=True)
            return
        if self.blocking:
            winsound.Beep(self.frequency_hz, self.duration_ms)
            return
        Thread(
            target=_background_windows_beep,
            args=(winsound, self.frequency_hz, self.duration_ms),
            daemon=False,
            name="licor-system-beep",
        ).start()


def _background_windows_beep(winsound, frequency_hz: int, duration_ms: int) -> None:
    try:
        winsound.Beep(frequency_hz, duration_ms)
    except Exception as error:  # pragma: no cover - hardware/driver dependent
        print(f"LICOR system beep failed: {error}", flush=True)
        print("\a", end="", flush=True)
