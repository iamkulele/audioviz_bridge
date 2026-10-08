"""Tests for LinkClock fallback behavior (works with or without aalink)."""

from __future__ import annotations

from audioviz_bridge.link_sync import LinkClock, LinkState


def test_link_state_is_dataclass():
    state = LinkState()
    assert state.available is False
    assert state.enabled is False
    assert state.tempo == 120.0


def test_link_clock_does_not_raise_without_aalink():
    clock = LinkClock()
    state = clock.state
    assert isinstance(state.available, bool)


def test_link_clock_enable_returns_bool():
    clock = LinkClock()
    result = clock.enable()
    assert isinstance(result, bool)


def test_link_clock_beat_pulse_in_range():
    clock = LinkClock()
    for _ in range(5):
        pulse = clock.beat_pulse()
        assert 0.0 <= pulse <= 1.0


def test_link_clock_poll_returns_state():
    clock = LinkClock()
    state = clock.poll()
    assert isinstance(state, LinkState)


def test_link_clock_disable_is_safe():
    clock = LinkClock()
    clock.disable()
    assert clock.state.enabled is False
