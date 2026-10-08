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
