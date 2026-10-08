"""Integration tests for BridgeEngine with the simulate source."""

from __future__ import annotations

import time

from audioviz_bridge.engine import BridgeEngine
from audioviz_bridge.output import NullOutput

from .helpers import RecordingBackend, write_config


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
    """3 秒静音后停止入队，真实音频回来时恢复。"""
    from audioviz_bridge.analyzer import AnalysisFrame

    engine = _make_engine(tmp_path, RecordingBackend())

    clock = {"t": 0.0}
    monkeypatch.setattr("audioviz_bridge.engine.time.monotonic", lambda: clock["t"])

    loud = AnalysisFrame(timestamp=0.0, rms=0.5, bass_energy=0.5)
    silent = AnalysisFrame(timestamp=0.0, rms=0.0, bass_energy=0.0)

    engine._on_frame(loud)
    assert engine._queue.qsize() == 1

    # 静音超过 3 秒 -> 不再入队
    clock["t"] = 10.0
    engine._on_frame(silent)
    assert engine._queue.qsize() == 1

    # 音频恢复 -> 恢复入队
    engine._on_frame(loud)
    assert engine._queue.qsize() == 2


def test_engine_sender_thread_drains_queue(tmp_path):
    """sender 线程消费队列，把消息发到后端（不依赖模拟源的时序）。"""
    import threading

    from audioviz_bridge.analyzer import AnalysisFrame

    rec = RecordingBackend()
    engine = _make_engine(tmp_path, rec)

    worker = threading.Thread(target=engine._send_loop, daemon=True)
    worker.start()

    engine._on_frame(AnalysisFrame(timestamp=0.0, rms=0.5, bass_energy=0.5))
    engine._queue.put(None)  # 哨兵：让 worker 处理完这条后退出
    worker.join(timeout=1.0)

    assert [addr for addr, _ in rec.osc] == ["/bass"]
