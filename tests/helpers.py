"""Shared test helpers."""

from __future__ import annotations

import numpy as np

from audioviz_bridge.analyzer import AnalysisFrame
from audioviz_bridge.link_sync import LinkState


def make_frame(**kwargs) -> AnalysisFrame:
    """Build an AnalysisFrame with sensible defaults for tests."""
    kwargs.setdefault("timestamp", 0.0)
    return AnalysisFrame(**kwargs)


def sine_block(freq: float, amplitude: float = 0.5, sample_rate: int = 48000, size: int = 1024) -> np.ndarray:
    t = np.arange(size) / sample_rate
    return (amplitude * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def silent_block(size: int = 1024) -> np.ndarray:
    return np.zeros(size, dtype=np.float32)


class FakeLink:
    """Stand-in for LinkClock: fixed tempo, deterministic beat pulse."""

    def __init__(self, pulse: float = 0.5, tempo: float = 120.0, available: bool = False) -> None:
        self._pulse = pulse
        self._state = LinkState(available=available, enabled=available, tempo=tempo)

    @property
    def state(self) -> LinkState:
        return LinkState(**self._state.__dict__)

    def enable(self) -> bool:
        self._state.enabled = self._state.available
        return self._state.enabled

    def disable(self) -> None:
        self._state.enabled = False

    def poll(self) -> LinkState:
        return self.state

    def beat_pulse(self) -> float:
        return self._pulse


class RecordingBackend:
    """Captures OSC/MIDI messages for assertions."""

    def __init__(self) -> None:
        self.osc: list[tuple[str, float]] = []
        self.midi: list[tuple[int, int, float]] = []

    def send_osc(self, address: str, value: float) -> None:
        self.osc.append((address, value))

    def send_midi_cc(self, channel: int, cc: int, value: float) -> None:
        self.midi.append((channel, cc, value))

    def close(self) -> None:
        pass


class ExplodingBackend:
    """Raises on every call to verify failure isolation."""

    def send_osc(self, address: str, value: float) -> None:
        raise RuntimeError("boom")

    def send_midi_cc(self, channel: int, cc: int, value: float) -> None:
        raise RuntimeError("boom")

    def close(self) -> None:
        raise RuntimeError("boom")


def write_config(tmp_path, content: str) -> str:
    path = tmp_path / "mappings.yaml"
    path.write_text(content, encoding="utf-8")
    return str(path)
