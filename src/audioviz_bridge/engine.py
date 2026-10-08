"""Bridge engine: wires analyzer, link, mapper and outputs together."""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Optional

from .analyzer import AudioAnalyzer
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

        # Raw-audio handoff: the audio callback only copies its block into this
        # bounded buffer and returns. A single worker thread drains it and does
        # analysis + mapping + I/O, so the real-time callback never does FFT,
        # heap allocation, or a network syscall. Dropping the oldest block when
        # the worker falls behind is correct: stale audio beats added latency.
        self._audio_cond = threading.Condition()
        self._audio_buffer: deque = deque(maxlen=4)
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

    def _on_audio(self, block) -> None:
        """Publish a raw audio block; runs on the audio callback thread.

        Bounded work only: append + notify. The caller (device callback) has
        already copied the block out of the sound card's buffer.
        """
        with self._audio_cond:
            self._audio_buffer.append(block)  # maxlen drops the oldest
            self._audio_cond.notify()

    def _run(self) -> None:
        """Worker: drain raw audio, analyze, map, and emit."""
        while True:
            with self._audio_cond:
                while not self._audio_buffer and not self._stopping:
                    self._audio_cond.wait()
                if self._stopping and not self._audio_buffer:
                    return
                block = self._audio_buffer.popleft()
            self._process_block(block)

    def _process_block(self, block) -> None:
        frame = self.analyzer.process_block(block)

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

        batch = list(self.mapper.evaluate(frame))
        if not batch:
            return

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

    def start(self) -> None:
        self.config.start_watching()
        with self._audio_cond:
            self._stopping = False
        self._worker = threading.Thread(
            target=self._run, daemon=True, name="audioviz-worker"
        )
        self._worker.start()
        self.source.start(self._on_audio)

    def stop(self) -> None:
        self.source.stop()
        self.config.stop_watching()
        # Stop producers first, then let the worker drain the last block and exit.
        with self._audio_cond:
            self._stopping = True
            self._audio_cond.notify()
        if self._worker is not None:
            self._worker.join(timeout=2.0)
            self._worker = None
        self.link.disable()
        self.output.close()
