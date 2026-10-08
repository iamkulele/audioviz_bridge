"""Tests for AudioAnalyzer: band energy, normalization, onset detection, smoothing."""

from __future__ import annotations

import numpy as np

from audioviz_bridge.analyzer import AudioAnalyzer

from .helpers import silent_block, sine_block


def test_analyzer_outputs_bounded_values():
    analyzer = AudioAnalyzer(sample_rate=48000, block_size=1024)
    huge = np.ones(1024, dtype=np.float32) * 10.0
    frame = analyzer.process_block(huge)
    assert 0.0 <= frame.rms <= 1.0
    assert 0.0 <= frame.bass_energy <= 1.0
    assert 0.0 <= frame.mid_energy <= 1.0
    assert 0.0 <= frame.treble_energy <= 1.0


def test_analyzer_silence_produces_near_zero():
    analyzer = AudioAnalyzer(sample_rate=48000, block_size=1024)
    frame = analyzer.process_block(silent_block())
    assert frame.rms < 1e-6
    assert frame.bass_energy < 1e-6
    assert frame.treble_energy < 1e-6
    assert not frame.onset_detected


def test_analyzer_low_freq_favors_bass_band():
    analyzer = AudioAnalyzer(sample_rate=48000, block_size=1024)
    frame = analyzer.process_block(sine_block(100.0))
    assert frame.bass_energy > frame.mid_energy
    assert frame.bass_energy > frame.treble_energy


def test_analyzer_high_freq_favors_treble_band():
    analyzer = AudioAnalyzer(sample_rate=48000, block_size=1024)
    frame = analyzer.process_block(sine_block(4000.0))
    assert frame.treble_energy > frame.bass_energy


def test_analyzer_stereo_input_is_averaged():
    analyzer = AudioAnalyzer(sample_rate=48000, block_size=1024)
    stereo = np.random.default_rng(0).standard_normal((1024, 2)).astype(np.float32) * 0.1
    frame = analyzer.process_block(stereo)
    assert 0.0 <= frame.rms <= 1.0


def test_analyzer_pads_short_blocks():
    analyzer = AudioAnalyzer(sample_rate=48000, block_size=1024)
    short = np.ones(256, dtype=np.float32) * 0.5
    frame = analyzer.process_block(short)
    assert 0.0 <= frame.rms <= 1.0


def test_analyzer_onset_detection_on_sudden_burst():
    analyzer = AudioAnalyzer(sample_rate=48000, block_size=1024)
    # 建立静音历史
    for _ in range(12):
        analyzer.process_block(silent_block())
    # 突然一个强低频信号
    frame = analyzer.process_block(sine_block(60.0, amplitude=0.9))
    assert frame.onset_detected
    assert frame.onset_strength > 0.0


def test_analyzer_no_onset_on_steady_signal():
    """规律信号不应持续触发 onset，验证中位数+MAD 阈值有效。"""
    analyzer = AudioAnalyzer(sample_rate=48000, block_size=1024)
    block = sine_block(60.0, amplitude=0.7)
    detections = 0
    for _ in range(60):
        frame = analyzer.process_block(block)
        if frame.onset_detected:
            detections += 1
    # 稳态信号最多只应有开局的一两次“假阳性”
    assert detections <= 2


def test_analyzer_smoothing_accumulates():
    analyzer = AudioAnalyzer(sample_rate=48000, block_size=1024, smoothing=0.5)
    for _ in range(5):
        analyzer.process_block(silent_block())
    loud = np.ones(1024, dtype=np.float32) * 0.5
    first = analyzer.process_block(loud)
    second = analyzer.process_block(loud)
    assert second.rms > first.rms


def test_analyzer_respects_custom_onset_history():
    analyzer = AudioAnalyzer(sample_rate=48000, block_size=1024, onset_history=8)
    for _ in range(20):
        analyzer.process_block(silent_block())
    assert len(analyzer._flux_history) <= 8
