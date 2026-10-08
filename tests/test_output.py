"""Tests for output backends: isolation, null behavior."""

from __future__ import annotations

from audioviz_bridge.output import MultiOutput, NullOutput

from .helpers import ExplodingBackend, RecordingBackend


def test_null_output_is_silent():
    out = NullOutput()
    out.send_osc("/x", 0.5)
    out.send_midi_cc(0, 1, 0.5)
    out.close()


def test_multi_output_fans_out_to_all_backends():
    a = RecordingBackend()
    b = RecordingBackend()
    multi = MultiOutput([a, b])
    multi.send_osc("/bass", 0.7)
    multi.send_midi_cc(0, 1, 0.4)
    assert a.osc == [("/bass", 0.7)]
    assert b.osc == [("/bass", 0.7)]
    assert a.midi == [(0, 1, 0.4)]
    assert b.midi == [(0, 1, 0.4)]


def test_multi_output_isolates_backend_failures():
    exploding = ExplodingBackend()
    recording = RecordingBackend()
    multi = MultiOutput([exploding, recording])

    # 不应抛异常
    multi.send_osc("/x", 0.5)
    multi.send_midi_cc(0, 1, 0.5)
    multi.close()

    assert recording.osc == [("/x", 0.5)]
    assert recording.midi == [(0, 1, 0.5)]


def test_multi_output_with_only_exploding_backend_does_not_raise():
    multi = MultiOutput([ExplodingBackend()])
    multi.send_osc("/x", 0.5)
    multi.send_midi_cc(0, 1, 0.5)
    multi.close()
