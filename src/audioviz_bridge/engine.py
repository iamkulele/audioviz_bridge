"""Bridge engine: wires analyzer, link, mapper and outputs together."""

from __future__ import annotations

import threading
import time
from typing import Optional

from .analyzer import AnalysisFrame, AudioAnalyzer
from .link_sync import LinkClock
from .mapper import MappingConfig, SignalMapper, SignalRoute
from .output import MultiOutput, NullOutput, OutputBackend


class BridgeEngine:
    """Headless bridge process.

    Start it, point it at a mappings.yaml, and it will translate live audio
    into OSC/MIDI messages for downstream VJ software. If anything goes wrong,
    it silently stops emitting rather than flooding the target.
    """

    SILENCE_TIMEOUT = 3.0  # seconds without audio -> stop emitting
    SILENCE_RMS = 0.005    # normalized RMS below which a frame counts as silent

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

        self._last_signal = time.monotonic()
        self._frames = 0
        self._emitted = 0
        self._lock = threading.Lock()

        # Single-slot mailbox: the audio callback drops the latest batch of
        # outgoing messages here, and the sender thread ships them. Overwriting
        # the slot means "latest wins" — stale messages are dropped instead of
        # queued, so worst-case latency stays at one frame rather than growing
        # into a backlog.
        self._cond = threading.Condition()
        self._batch: list[tuple[SignalRoute, float]] = []
        self._stopping = False
        self._worker: threading.Thread | None = None

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
            # Gate on energy, not frame arrival: a muted mic or a disconnected
            # interface keeps the stream alive while delivering silence, so
            # "no audio" means "no energy", and we'd otherwise keep flooding
            # downstream with near-zero values.
            if frame.rms > self.SILENCE_RMS:
                self._last_signal = now
            silenced = (now - self._last_signal) > self.SILENCE_TIMEOUT

        if silenced:
            return

        # Evaluate in the callback (cheap); ship the actual I/O to the sender thread.
        batch = list(self.mapper.evaluate(frame))
        if not batch:
            return
        with self._cond:
            self._batch = batch  # latest wins
            self._cond.notify()

    def _send_batch(self, batch: list[tuple[SignalRoute, float]]) -> None:
        for route, value in batch:
            try:
                if route.osc_address:
                    self.output.send_osc(route.osc_address, value)
                if route.midi_cc is not None:
                    self.output.send_midi_cc(route.midi_channel, route.midi_cc, value)
            except Exception:
                pass
        with self._lock:
            self._emitted += len(batch)

    def _send_loop(self) -> None:
        """Wait for the latest batch and emit it; runs in the sender thread."""
        while True:
            with self._cond:
                while not self._batch and not self._stopping:
                    self._cond.wait()
                if self._stopping and not self._batch:
                    return
                batch, self._batch = self._batch, []
            self._send_batch(batch)

    def start(self) -> None:
        self.config.start_watching()
        with self._cond:
            self._stopping = False
            self._batch = []
        self._worker = threading.Thread(
            target=self._send_loop, daemon=True, name="audioviz-sender"
        )
        self._worker.start()
        self.source.start(self._on_frame)

    def stop(self) -> None:
        self.source.stop()
        self.config.stop_watching()
        # Stop producers first, then let the sender drain the last batch and exit.
        with self._cond:
            self._stopping = True
            self._cond.notify()
        if self._worker is not None:
            self._worker.join(timeout=2.0)
            self._worker = None
        self.link.disable()
        self.output.close()
