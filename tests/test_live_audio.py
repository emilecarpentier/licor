import sys
from types import SimpleNamespace

from licor.live import audio


def test_system_beep_starts_in_background(monkeypatch):
    started = []
    fake_winsound = SimpleNamespace(Beep=lambda frequency, duration: None)

    class FakeThread:
        def __init__(self, **kwargs):
            assert kwargs["target"] is audio._background_windows_beep
            assert kwargs["args"] == (fake_winsound, 1200, 90)
            assert kwargs["daemon"] is False
            assert kwargs["name"] == "licor-system-beep"

        def start(self):
            started.append(True)

    monkeypatch.setitem(sys.modules, "winsound", fake_winsound)
    monkeypatch.setattr(audio, "Thread", FakeThread)

    audio.SystemBeepAudioCueAdapter().emit(None)

    assert started == [True]


def test_blocking_system_beep_confirms_diagnostic_call(monkeypatch):
    calls = []
    fake_winsound = SimpleNamespace(
        Beep=lambda frequency, duration: calls.append((frequency, duration))
    )
    monkeypatch.setitem(sys.modules, "winsound", fake_winsound)

    audio.SystemBeepAudioCueAdapter(blocking=True).emit(None)

    assert calls == [(1200, 90)]
