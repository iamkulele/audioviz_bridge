"""Optional Ableton Link integration for tempo/beat/phase alignment."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Optional


@dataclass
class LinkState:
    available: bool = False
    enabled: bool = False
    tempo: float = 120.0
    beat: float = 0.0
    phase: float = 0.0
    quantum: float = 4.0
    peers: int = 0


class LinkClock:
    """Wraps aalink if available; otherwise reports unavailable and stays silent."""

    def __init__(self, quantum: float = 4.0) -> None:
        self.quantum = quantum
        self._state = LinkState(quantum=quantum)
        self._link = None
        self._lock = threading.Lock()

        try:
            import aalink  # type: ignore

            self._alink = aalink
        except ImportError:
            self._alink = None
            return

        try:
            self._link = aalink.Link()
            self._state.available = True
        except Exception:
            self._link = None
            self._state.available = False

    @property
    def state(self) -> LinkState:
        with self._lock:
            return LinkState(**self._state.__dict__)

    def enable(self) -> bool:
        if self._link is None:
            return False
        try:
            self._link.enabled = True
            self._state.enabled = True
            return True
        except Exception:
            return False

    def disable(self) -> None:
        if self._link is None:
            return
        try:
            self._link.enabled = False
        except Exception:
            pass
        self._state.enabled = False

    def set_tempo(self, tempo: float) -> None:
        if self._link is None:
            return
        try:
            self._link.tempo = float(tempo)
        except Exception:
            pass

    def poll(self) -> LinkState:
        """Refresh cached state from the Link session."""
        if self._link is None:
            return self.state
        try:
            with self._lock:
                self._state.tempo = float(self._link.tempo)
                self._state.beat = float(self._link.beat)
                self._state.phase = float(self._link.phase)
                self._state.peers = int(self._link.num_peers)
        except Exception:
            pass
        return self.state

    def beat_pulse(self) -> float:
        """Return a 0..1 value that peaks on each beat and decays linearly.

        Uses Link phase when available; otherwise falls back to a monotonic
        clock at the last known tempo.
        """
        st = self.poll()
        if st.available and st.enabled:
            # phase is 0..quantum across the bar; wrap to beat position
            beat_pos = st.beat % 1.0
            return max(0.0, 1.0 - beat_pos)
        # Fallback: internal clock at last tempo
        if st.tempo <= 0:
            return 0.0
        seconds_per_beat = 60.0 / st.tempo
        t = time.monotonic()
        pos = (t % seconds_per_beat) / seconds_per_beat
        return max(0.0, 1.0 - pos)
