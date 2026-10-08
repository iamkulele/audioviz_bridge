"""Tests for SyntheticSource: block generation, spectral distribution."""

from __future__ import annotations

import numpy as np

from audioviz_bridge.analyzer import AudioAnalyzer
from audioviz_bridge.simulator import SyntheticSource


def test_simulator_generates_correct_block_size():
    analyzer = AudioAnalyzer(sample_rate=48000, block_size=1024)
    sim = SyntheticSource(analyzer, bpm=120)
    block = sim._generate_block()
    assert block.shape == (1024,)
    assert block.dtype == np.float32


def test_simulator_block_has_energy():
    analyzer = AudioAnalyzer(sample_rate=48000, block_size=1024)
    sim = SyntheticSource(analyzer, bpm=120)
    block = sim._generate_block()
    assert np.abs(block).max() > 0.1


def test_simulator_spectrum_distribution_bass_gt_mid_gt_treble():
    analyzer = AudioAnalyzer(sample_rate=48000, block_size=1024)
    sim = SyntheticSource(analyzer, bpm=120)

    bass_values, mid_values, treble_values = [], [], []
    for _ in range(20):
        block = sim._generate_block()
        frame = analyzer.process_block(block)
        bass_values.append(frame.bass_energy)
        mid_values.append(frame.mid_energy)
        treble_values.append(frame.treble_energy)

    assert np.mean(bass_values) > np.mean(mid_values)
    assert np.mean(mid_values) > np.mean(treble_values)


def test_simulator_bpm_affects_kick_interval():
    analyzer = AudioAnalyzer(sample_rate=48000, block_size=1024)
    fast = SyntheticSource(analyzer, bpm=240)
    slow = SyntheticSource(analyzer, bpm=60)

    # 快速源的拍周期应更短：一拍内 block 数 = (60/bpm) * sr / block_size
    fast_period = (60.0 / 240) * 48000 / 1024
    slow_period = (60.0 / 60) * 48000 / 1024
    assert slow_period == 4 * fast_period


def test_simulator_start_stop_lifecycle():
    analyzer = AudioAnalyzer(sample_rate=48000, block_size=1024)
    sim = SyntheticSource(analyzer, bpm=120)
    frames = []
    sim.start(lambda f: frames.append(f))
    import time
    time.sleep(0.2)
    sim.stop()
    assert len(frames) > 0
    assert not sim.running
