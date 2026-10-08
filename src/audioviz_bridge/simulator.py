"""Synthetic audio source for testing without hardware.

Generates a kick drum + bass + hi-hat + melody pattern at a fixed BPM,
feeds each block through the same AudioAnalyzer pipeline used in production.
Interface matches AudioAnalyzer: start(callback) / stop().
"""

from __future__ import annotations

import threading
import time

import numpy as np

from .analyzer import AudioAnalyzer, AnalysisFrame


class SyntheticSource:
    """Replaces AudioAnalyzer's device input with generated audio."""

    def __init__(self, analyzer: AudioAnalyzer, bpm: float = 120.0) -> None:
        self.analyzer = analyzer
        self.bpm = bpm
        self.sample_rate = analyzer.sample_rate
        self.block_size = analyzer.block_size
        self._t = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _generate_block(self) -> np.ndarray:
        n = self.block_size
        sr = self.sample_rate
        t = (np.arange(n) + self._t) / sr
        self._t += n

        beat_period = 60.0 / self.bpm
        phase_in_beat = (t % beat_period) / beat_period

        # Kick: 60Hz one per beat
        time_in_beat = t % beat_period
        kick_env = np.exp(-time_in_beat * 15.0)
        kick = 0.8 * kick_env * np.sin(2 * np.pi * 60 * time_in_beat)

        # Bass: 80Hz continuous with slow amplitude modulation
        bass = 0.3 * np.sin(2 * np.pi * 80 * t) * (0.5 + 0.5 * np.sin(2 * np.pi * 0.5 * t))

        # Hi-hat: noise burst on every half beat
        half_phase = (t % (beat_period / 2)) / (beat_period / 2)
        hat_env = np.exp(-half_phase * 40.0)
        hat = 0.15 * hat_env * np.random.randn(n)

        # Melody: 440Hz sine for mid/treble energy
        melody = 0.15 * np.sin(2 * np.pi * 440 * t)

        return (kick + bass + hat + melody).astype(np.float32)

    def _run(self, callback) -> None:
        interval = self.block_size / self.sample_rate
        next_time = time.monotonic()
        while not self._stop.is_set():
            block = self._generate_block()
            frame = self.analyzer.process_block(block)
            callback(frame)
            next_time += interval
            sleep = next_time - time.monotonic()
            if sleep > 0:
                time.sleep(sleep)
            else:
                next_time = time.monotonic()

    def start(self, callback) -> None:
        self._thread = threading.Thread(target=self._run, args=(callback,), daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()
