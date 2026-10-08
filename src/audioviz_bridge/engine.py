"""Bridge engine: wires analyzer, link, mapper and outputs together."""

from __future__ import annotations

import threading
import time
from typing import Optional

from .analyzer import AnalysisFrame, AudioAnalyzer
from .link_sync import LinkClock
from .mapper import MappingConfig, SignalMapper
from .output import MultiOutput, NullOutput, OutputBackend


class BridgeEngine:
    """Headless bridge process.

    Start it, point it at a mappings.yaml, and it will translate live audio
    into OSC/MIDI messages for downstream VJ software. If anything goes wrong,
    it silently stops emitting rather than flooding the target.
    """

    SILENCE_TIMEOUT = 3.0  # seconds without audio -> stop emitting

    def __init__(
        self,
        config_path: str,
        output: Optional[OutputBackend] = None,
        device: Optional[int | str] = None,
        sample_rate: int = 48000,
        block_size: int = 1024,
        enable_link: bool = True,
        source: str = "device",
        bpm: float = 120.0,
    ) -> None:
        self.config = MappingConfig(config_path)
        self.config.load()

        self.output = output or NullOutput()
        self.link = LinkClock()
        if enable_link and self.link.state.available:
            self.link.enable()

        self.mapper = SignalMapper(self.config, self.link)
        self.analyzer = AudioAnalyzer(
            sample_rate=sample_rate,
            block_size=block_size,
            device=device,
        )

        if source == "simulate":
            from .simulator import SyntheticSource
            self.source = SyntheticSource(self.analyzer, bpm=bpm)
        else:
            self.source = self.analyzer

        self._last_audio = time.monotonic()
        self._frames = 0
        self._emitted = 0
        self._lock = threading.Lock()
        self._stop = threading.Event()

    @property
    def stats(self) -> dict:
        with self._lock:
            return {
                "frames": self._frames,
                "emitted": self._emitted,
                "link_available": self.link.state.available,
                "link_enabled": self.link.state.enabled,
                "tempo": self.link.state.tempo,
            }

    def _on_frame(self, frame: AnalysisFrame) -> None:
        now = time.monotonic()
        with self._lock:
            self._frames += 1
            self._last_audio = now

        for route, value in self.mapper.evaluate(frame):
            if route.osc_address:
                self.output.send_osc(route.osc_address, value)
            if route.midi_cc is not None:
                self.output.send_midi_cc(route.midi_channel, route.midi_cc, value)
            with self._lock:
                self._emitted += 1

    def _watchdog(self) -> None:
        """Stop emitting if audio has gone silent, but keep the process alive."""
        while not self._stop.is_set():
            with self._lock:
                silent = (time.monotonic() - self._last_audio) > self.SILENCE_TIMEOUT
            if silent:
                # Do nothing; mapper already gates on live frames.
                pass
            self._stop.wait(0.5)

    def start(self) -> None:
        self.config.start_watching()
        self.source.start(self._on_frame)
        threading.Thread(target=self._watchdog, daemon=True).start()

    def stop(self) -> None:
        self._stop.set()
        self.source.stop() 
        self.config.stop_watching()
        self.link.disable()
        self.output.close()
