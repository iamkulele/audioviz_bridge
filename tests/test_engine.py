"""Integration tests for BridgeEngine with the simulate source."""

from __future__ import annotations

import time

from audioviz_bridge.engine import BridgeEngine
from audioviz_bridge.output import NullOutput

from .helpers import RecordingBackend, silent_block, sine_block, write_config


def _make_engine(tmp_path, output, **kwargs):
    path = write_config(
        tmp_path,
        """
signals:
  - name: bass
    source: bass
    osc_address: /bass
  - name: kick
    source: onset
    osc_address: /kick
    trigger_on: onset
""",
    )
    return BridgeEngine(
        config_path=path,
        output=output,
        source="simulate",
        bpm=120.0,
        **kwargs,
    )


def test_engine_with_simulate_source_emits_frames(tmp_path):
    engine = _make_engine(tmp_path, NullOutput())
    try:
        engine.start()
        time.sleep(0.3)
        stats = engine.stats
    finally:
        engine.stop()

    assert stats["frames"] > 0
    assert stats["emitted"] > 0


def test_engine_emits_to_recording_backend(tmp_path):
    rec = RecordingBackend()
    engine = _make_engine(tmp_path, rec)
    try:
        engine.start()
        time.sleep(0.3)
    finally:
        engine.stop()

    assert len(rec.osc) > 0
    addresses = {address for address, _ in rec.osc}
    assert "/bass" in addresses


def test_engine_stop_is_idempotent(tmp_path):
    engine = _make_engine(tmp_path, NullOutput())
    engine.start()
    time.sleep(0.1)
    engine.stop()
    engine.stop()  # 不应抛异常


def test_engine_stats_shape(tmp_path):
    engine = _make_engine(tmp_path, NullOutput())
    try:
        engine.start()
        time.sleep(0.1)
        stats = engine.stats
    finally:
        engine.stop()

    assert set(stats.keys()) >= {"frames", "emitted", "link_available", "link_enabled", "tempo"}
    assert isinstance(stats["frames"], int)
    assert isinstance(stats["link_available"], bool)


def test_engine_silence_valve_stops_then_resumes(tmp_path, monkeypatch):
    """3 秒静音后停止发送，真实音频回来时恢复。"""
    rec = RecordingBackend()
    engine = _make_engine(tmp_path, rec)

    clock = {"t": 0.0}
    monkeypatch.setattr("audioviz_bridge.engine.time.monotonic", lambda: clock["t"])

    engine._process_block(sine_block(100.0))  # 有能量 -> 发送
    assert [a for a, _ in rec.osc] == ["/bass"]

    # 静音:先喂静音块让平滑衰减到阈值以下，再把时钟拨过 3 秒超时
    for _ in range(20):
        clock["t"] += 0.1
        engine._process_block(silent_block())
    clock["t"] += 10.0

    rec.osc.clear()
    engine._process_block(silent_block())  # 已静音超过 3 秒 -> 不再发送
    assert rec.osc == []

    engine._process_block(sine_block(100.0))  # 音频恢复 -> 重新发送
    assert len(rec.osc) > 0


def test_engine_worker_processes_audio_blocks(tmp_path):
    """worker 消费原始音频块，分析并发送（不依赖模拟源的时序）。"""
    import threading

    rec = RecordingBackend()
    engine = _make_engine(tmp_path, rec)

    worker = threading.Thread(target=engine._run, daemon=True)
    worker.start()

    engine._on_audio(sine_block(100.0))

    # 停掉 worker，让它把最后一个块处理完再退出
    with engine._audio_cond:
        engine._stopping = True
        engine._audio_cond.notify()
    worker.join(timeout=1.0)

    assert [addr for addr, _ in rec.osc] == ["/bass"]
