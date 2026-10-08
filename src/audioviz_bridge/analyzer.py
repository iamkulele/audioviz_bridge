"""Real-time audio analysis: FFT band energy, onset detection, RMS."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import sounddevice as sd


@dataclass
class AnalysisFrame:
    """One analysis frame's worth of extracted features."""

    timestamp: float
    rms: float = 0.0
    bass_energy: float = 0.0
    mid_energy: float = 0.0
    treble_energy: float = 0.0
    onset_strength: float = 0.0
    onset_detected: bool = False
    spectral_flux: float = 0.0


class AudioAnalyzer:
    """Captures audio from an input device and extracts features per block.

    Features are normalized to 0.0-1.0 where applicable, so downstream
    mapping can use fixed thresholds. The band-energy references below are
    calibration points for a typical line-level input; they scale with source
    gain, so retune them if the gain changes materially.
    """

    BASS_RANGE = (20.0, 250.0)
    MID_RANGE = (250.0, 2000.0)
    TREBLE_RANGE = (2000.0, 8000.0)

    # References for _normalize: the band-energy magnitude that maps to ~63%
    # (1 - 1/e) of full scale. Tuned for a line-level input; not gain-invariant.
    BASS_REFERENCE = 0.05
    MID_REFERENCE = 0.02
    TREBLE_REFERENCE = 0.01

    def __init__(
        self,
        sample_rate: int = 48000,
        block_size: int = 1024,
        device: Optional[int | str] = None,
        channels: int = 1,
        onset_threshold: float = 1.5,
        onset_history: int = 43,
        smoothing: float = 0.6,
    ) -> None:
        self.sample_rate = sample_rate
        self.block_size = block_size
        self.device = device
        self.channels = channels

        self.onset_threshold = onset_threshold
        self.onset_history = onset_history
        self.smoothing = smoothing

        self._window = np.hanning(block_size).astype(np.float32)
        self._freqs = np.fft.rfftfreq(block_size, d=1.0 / sample_rate)

        self._prev_spectrum: Optional[np.ndarray] = None
        self._flux_history: list[float] = []
        self._smoothed = AnalysisFrame(timestamp=0.0)

        self._band_masks = {
            "bass": self._band_mask(*self.BASS_RANGE),
            "mid": self._band_mask(*self.MID_RANGE),
            "treble": self._band_mask(*self.TREBLE_RANGE),
        }

        self._stream: Optional[sd.InputStream] = None
        self._running = False

    def _band_mask(self, low: float, high: float) -> np.ndarray:
        return (self._freqs >= low) & (self._freqs < high)

    def _band_energy(self, spectrum: np.ndarray, band: str) -> float:
        mask = self._band_masks[band]
        if not mask.any():
            return 0.0
        energy = float(np.mean(spectrum[mask]))
        return energy

    @staticmethod
    def _normalize(value: float, reference: float = 1.0) -> float:
        """Soft normalization into 0..1 using a smooth curve."""
        if value <= 0.0:
            return 0.0
        return float(1.0 - np.exp(-value / max(reference, 1e-9)))

    def process_block(self, block: np.ndarray) -> AnalysisFrame:
        """Analyze a single block of mono audio samples."""
        if block.ndim > 1:
            block = block.mean(axis=1)
        block = block.astype(np.float32)

        if block.size > self.block_size:
            block = block[: self.block_size]
        elif block.size < self.block_size:
            block = np.pad(block, (0, self.block_size - block.size))

        windowed = block * self._window
        spectrum = np.abs(np.fft.rfft(windowed)) / self.block_size

        rms = float(np.sqrt(np.mean(block**2)))

        bass = self._band_energy(spectrum, "bass")
        mid = self._band_energy(spectrum, "mid")
        treble = self._band_energy(spectrum, "treble")

        # Spectral flux: half-wave rectified difference between consecutive spectra.
        if self._prev_spectrum is None:
            flux = 0.0
        else:
            diff = spectrum - self._prev_spectrum
            flux = float(np.sum(np.maximum(diff, 0.0)))
        self._prev_spectrum = spectrum

        self._flux_history.append(flux)
        if len(self._flux_history) > self.onset_history:
            self._flux_history.pop(0)

        onset_detected = False
        onset_strength = 0.0
        if len(self._flux_history) >= 8:
            arr = np.array(self._flux_history, dtype=np.float64)
            median = float(np.median(arr))
            mad = float(np.median(np.abs(arr - median)))
            scaled_mad = mad * 1.4826 + 1e-9   # 1.4826 让 MAD 与标准差可比
            threshold = median + self.onset_threshold * scaled_mad
            if flux > threshold:
                onset_detected = True
                onset_strength = self._normalize(
                    flux - threshold, reference=max(threshold, 1e-6) * 1.5
                )

        frame = AnalysisFrame(
            timestamp=time.monotonic(),
            rms=self._normalize(rms),
            bass_energy=self._normalize(bass, reference=self.BASS_REFERENCE),
            mid_energy=self._normalize(mid, reference=self.MID_REFERENCE),
            treble_energy=self._normalize(treble, reference=self.TREBLE_REFERENCE),
            onset_strength=onset_strength,
            onset_detected=onset_detected,
            spectral_flux=flux,
        )

        # Exponential smoothing for continuous signals; onsets stay sharp.
        a = self.smoothing
        self._smoothed = AnalysisFrame(
            timestamp=frame.timestamp,
            rms=a * self._smoothed.rms + (1 - a) * frame.rms,
            bass_energy=a * self._smoothed.bass_energy + (1 - a) * frame.bass_energy,
            mid_energy=a * self._smoothed.mid_energy + (1 - a) * frame.mid_energy,
            treble_energy=a * self._smoothed.treble_energy + (1 - a) * frame.treble_energy,
            onset_strength=frame.onset_strength,
            onset_detected=frame.onset_detected,
            spectral_flux=frame.spectral_flux,
        )
        return self._smoothed

    def start(self, callback) -> None:
        """Start capturing audio; callback receives each raw audio block.

        Analysis is intentionally NOT done here: this runs on PortAudio's
        real-time thread, which must return within one block period. The block
        is copied out and handed off; the consumer runs process_block() on its
        own thread.
        """
        if self._running:
            return

        def _sd_callback(indata, frames, time_info, status):
            del frames, time_info
            if status:
                pass  # status is informational; bridge stays silent
            callback(indata.copy())

        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            blocksize=self.block_size,
            device=self.device,
            channels=self.channels,
            callback=_sd_callback,
        )
        self._stream.start()
        self._running = True

    def stop(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        self._running = False

    @property
    def running(self) -> bool:
        return self._running
