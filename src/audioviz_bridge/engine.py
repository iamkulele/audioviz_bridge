"""Bridge engine: wires analyzer, link, mapper and outputs together."""

from __future__ import annotations

import queue
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

        # Outgoing messages are handed to a dedicated sender thread so the
        # audio callback never does network I/O (UDP send) in its own thread.
        self._queue: queue.Queue[tuple[SignalRoute, float] | None] = queue.Queue(
            maxsize=64
        )
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
        for route, value in self.mapper.evaluate(frame):
            self._enqueue(route, value)

    def _enqueue(self, route: SignalRoute, value: float) -> None:
        try:
            self._queue.put_nowait((route, value))
        except queue.Full:
            # Backpressure: the backend can't keep up. Drop the oldest queued
            # message so we emit the freshest value instead of blocking the
            # audio callback or growing the queue without bound.
            try:
                self._queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._queue.put_nowait((route, value))
            except queue.Full:
                pass

    def _send_loop(self) -> None:
        """Drain the queue and emit messages; runs in the sender thread."""
        while True:
            item = self._queue.get()
            if item is None:  # shutdown sentinel
                break
            route, value = item
            try:
                if route.osc_address:
                    self.output.send_osc(route.osc_address, value)
                if route.midi_cc is not None:
                    self.output.send_midi_cc(route.midi_channel, route.midi_cc, value)
            except Exception:
                pass
            with self._lock:
                self._emitted += 1

    def start(self) -> None:
        self.config.start_watching()
        self._worker = threading.Thread(
            target=self._send_loop, daemon=True, name="audioviz-sender"
        )
        self._worker.start()
        self.source.start(self._on_frame)

    def stop(self) -> None:
        self.source.stop()
        self.config.stop_watching()
        # Stop producers first, then signal the worker to drain and exit, then close.
        self._queue.put(None)
        if self._worker is not None:
            self._worker.join(timeout=2.0)
            self._worker = None
        self.link.disable()
        self.output.close()
