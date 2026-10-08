"""YAML-driven mapping from analysis signals to OSC/MIDI messages."""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import yaml

from .analyzer import AnalysisFrame
from .link_sync import LinkClock


@dataclass
class SignalRoute:
    name: str
    source: str
    osc_address: str
    range: tuple[float, float] = (0.0, 1.0)
    trigger_on: Optional[str] = None
    confidence_threshold: float = 0.0
    gate_source: Optional[str] = None
    gate_threshold: float = 0.0
    min_interval: float = 0.0
    midi_cc: Optional[int] = None
    midi_channel: int = 0

    _last_sent: float = field(default=0.0, repr=False)


class MappingConfig:
    """Loads mappings.yaml and watches it for changes."""

    def __init__(self, path: str, reload_interval: float = 1.0) -> None:
        self.path = os.path.abspath(path)
        self.reload_interval = reload_interval
        self._routes: list[SignalRoute] = []
        self._mtime: float = 0.0
        self._lock = threading.Lock()
        self._on_reload: list[Callable[[list[SignalRoute]], None]] = []
        self._watch_thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    @property
    def routes(self) -> list[SignalRoute]:
        with self._lock:
            return list(self._routes)

    def on_reload(self, cb: Callable[[list[SignalRoute]], None]) -> None:
        self._on_reload.append(cb)

    def load(self) -> list[SignalRoute]:
        with open(self.path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        routes: list[SignalRoute] = []
        for item in data.get("signals", []):
            rng = item.get("range", [0.0, 1.0])
            routes.append(
                SignalRoute(
                    name=item["name"],
                    source=item["source"],
                    osc_address=item.get("osc_address", ""),
                    range=(float(rng[0]), float(rng[1])),
                    trigger_on=item.get("trigger_on"),
                    confidence_threshold=float(item.get("confidence_threshold", 0.0)),
                    gate_source=item.get("gate_source"),
                    gate_threshold=float(item.get("gate_threshold", 0.0)),
                    min_interval=float(item.get("min_interval", 0.0)),
                    midi_cc=item.get("midi_cc"),
                    midi_channel=int(item.get("midi_channel", 0)),
                )
            )

        with self._lock:
            self._routes = routes
        for cb in self._on_reload:
            cb(routes)
        return routes

    def start_watching(self) -> None:
        if self._watch_thread is not None:
            return

        def _watch():
            while not self._stop.is_set():
                try:
                    mtime = os.path.getmtime(self.path)
                    if mtime != self._mtime:
                        self._mtime = mtime
                        self.load()
                except FileNotFoundError:
                    pass
                except Exception:
                    pass
                self._stop.wait(self.reload_interval)

        self._watch_thread = threading.Thread(target=_watch, daemon=True)
        self._watch_thread.start()

    def stop_watching(self) -> None:
        self._stop.set()
        if self._watch_thread is not None:
            self._watch_thread.join(timeout=2.0)
            self._watch_thread = None


class SignalMapper:
    """Turns AnalysisFrame + LinkClock state into outgoing messages."""

    def __init__(
        self,
        config: MappingConfig,
        link: Optional[LinkClock] = None,
    ) -> None:
        self.config = config
        self.link = link or LinkClock()

    @staticmethod
    def _scale(value: float, rng: tuple[float, float]) -> float:
        lo, hi = rng
        return lo + (hi - lo) * max(0.0, min(1.0, value))

    def _read_source(self, source: str, frame: AnalysisFrame) -> float:
        if source == "beat" or source == "beat_pulse":
            return self.link.beat_pulse()
        if source == "rms":
            return frame.rms
        if source == "bass":
            return frame.bass_energy
        if source == "mid":
            return frame.mid_energy
        if source == "treble":
            return frame.treble_energy
        if source == "onset":
            return frame.onset_strength
        return 0.0

    def evaluate(self, frame: AnalysisFrame) -> list[tuple[SignalRoute, float]]:
        """Return list of (route, scaled_value) ready to be emitted."""
        now = time.monotonic()
        outgoing: list[tuple[SignalRoute, float]] = []

        for route in self.config.routes:
            value = self._read_source(route.source, frame)

            if route.trigger_on == "onset" and not frame.onset_detected:
                continue
            if route.trigger_on == "beat" and value <= 0.0:
                continue

            if route.confidence_threshold > 0.0 and value < route.confidence_threshold:
                continue

            if route.gate_source:
                gate_value = self._read_source(route.gate_source, frame)
                if gate_value < route.gate_threshold:
                    continue

            if route.min_interval > 0.0 and (now - route._last_sent) < route.min_interval:
                continue

            route._last_sent = now
            outgoing.append((route, self._scale(value, route.range)))

        return outgoing
