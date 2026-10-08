"""Tests for MappingConfig + SignalMapper: routing, thresholds, gating, rate limits."""

from __future__ import annotations

from audioviz_bridge.mapper import MappingConfig, SignalMapper

from .helpers import FakeLink, make_frame, write_config


def test_scale_maps_unit_to_range():
    assert SignalMapper._scale(0.0, (0.0, 1.0)) == 0.0
    assert SignalMapper._scale(1.0, (0.0, 1.0)) == 1.0
    assert abs(SignalMapper._scale(0.5, (0.0, 10.0)) - 5.0) < 1e-9
    assert SignalMapper._scale(2.0, (0.0, 1.0)) == 1.0
    assert SignalMapper._scale(-1.0, (0.0, 1.0)) == 0.0


def test_config_loads_routes(tmp_path):
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
    confidence_threshold: 0.5
""",
    )
    cfg = MappingConfig(path)
    routes = cfg.load()
    assert len(routes) == 2
    assert routes[0].name == "bass"
    assert routes[0].range == (0.0, 1.0)
    assert routes[1].confidence_threshold == 0.5


def test_config_osc_address_is_optional(tmp_path):
    path = write_config(
        tmp_path,
        """
signals:
  - name: midi_only
    source: bass
    midi_cc: 1
""",
    )
    cfg = MappingConfig(path)
    routes = cfg.load()
    assert len(routes) == 1
    assert routes[0].osc_address == ""
    assert routes[0].midi_cc == 1


def test_config_reload_callback(tmp_path):
    path = write_config(
        tmp_path,
        """
signals:
  - name: bass
    source: bass
    osc_address: /bass
""",
    )
    cfg = MappingConfig(path)
    cfg.load()
    events: list[int] = []
    cfg.on_reload(lambda routes: events.append(len(routes)))
    cfg.load()
    assert events == [1]


def test_mapper_trigger_on_onset_filters_non_onset_frames(tmp_path):
    path = write_config(
        tmp_path,
        """
signals:
  - name: kick
    source: onset
    osc_address: /kick
    trigger_on: onset
""",
    )
    cfg = MappingConfig(path)
    cfg.load()
    mapper = SignalMapper(cfg)

    quiet = make_frame(onset_strength=0.5, onset_detected=False)
    hit = make_frame(onset_strength=0.5, onset_detected=True)

    assert mapper.evaluate(quiet) == []
    assert len(mapper.evaluate(hit)) == 1


def test_mapper_confidence_threshold(tmp_path):
    path = write_config(
        tmp_path,
        """
signals:
  - name: onset_signal
    source: onset
    osc_address: /onset
    confidence_threshold: 0.6
""",
    )
    cfg = MappingConfig(path)
    cfg.load()
    mapper = SignalMapper(cfg)

    low = make_frame(onset_strength=0.3)
    high = make_frame(onset_strength=0.8)
    assert mapper.evaluate(low) == []
    assert len(mapper.evaluate(high)) == 1


def test_mapper_gate_source_blocks_when_gate_closed(tmp_path):
    path = write_config(
        tmp_path,
        """
signals:
  - name: kick
    source: onset
    osc_address: /kick
    trigger_on: onset
    gate_source: bass
    gate_threshold: 0.5
""",
    )
    cfg = MappingConfig(path)
    cfg.load()
    mapper = SignalMapper(cfg)

    gate_closed = make_frame(onset_strength=0.9, onset_detected=True, bass_energy=0.3)
    gate_open = make_frame(onset_strength=0.9, onset_detected=True, bass_energy=0.7)
    assert mapper.evaluate(gate_closed) == []
    assert len(mapper.evaluate(gate_open)) == 1


def test_mapper_min_interval_rate_limits(tmp_path):
    path = write_config(
        tmp_path,
        """
signals:
  - name: bass
    source: bass
    osc_address: /bass
    min_interval: 10.0
""",
    )
    cfg = MappingConfig(path)
    cfg.load()
    mapper = SignalMapper(cfg)

    frame = make_frame(bass_energy=0.5)
    assert len(mapper.evaluate(frame)) == 1
    assert mapper.evaluate(frame) == []


def test_mapper_scales_to_custom_range(tmp_path):
    path = write_config(
        tmp_path,
        """
signals:
  - name: bass
    source: bass
    osc_address: /bass
    range: [0.5, 1.0]
""",
    )
    cfg = MappingConfig(path)
    cfg.load()
    mapper = SignalMapper(cfg)

    zero = make_frame(bass_energy=0.0)
    full = make_frame(bass_energy=1.0)

    _, low = mapper.evaluate(zero)[0]
    _, high = mapper.evaluate(full)[0]
    assert abs(low - 0.5) < 1e-9
    assert abs(high - 1.0) < 1e-9


def test_mapper_beat_trigger_uses_link(tmp_path):
    path = write_config(
        tmp_path,
        """
signals:
  - name: beat
    source: beat
    osc_address: /beat
    trigger_on: beat
""",
    )
    cfg = MappingConfig(path)
    cfg.load()
    link = FakeLink(pulse=0.5)
    mapper = SignalMapper(cfg, link=link)

    frame = make_frame()
    result = mapper.evaluate(frame)
    assert len(result) == 1
    assert result[0][1] == 0.5


def test_mapper_beat_trigger_skips_zero_pulse(tmp_path):
    path = write_config(
        tmp_path,
        """
signals:
  - name: beat
    source: beat
    osc_address: /beat
    trigger_on: beat
""",
    )
    cfg = MappingConfig(path)
    cfg.load()
    link = FakeLink(pulse=0.0)
    mapper = SignalMapper(cfg, link=link)

    assert mapper.evaluate(make_frame()) == []


def test_mapper_midi_route_has_no_osc_address(tmp_path):
    path = write_config(
        tmp_path,
        """
signals:
  - name: bass_cc
    source: bass
    osc_address: ""
    midi_cc: 1
    midi_channel: 0
""",
    )
    cfg = MappingConfig(path)
    cfg.load()
    mapper = SignalMapper(cfg)
    result = mapper.evaluate(make_frame(bass_energy=0.5))
    assert len(result) == 1
    route, value = result[0]
    assert route.osc_address == ""
    assert route.midi_cc == 1
    assert 0.0 <= value <= 1.0
