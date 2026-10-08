"""OSC and MIDI output backends."""

from __future__ import annotations

from typing import Optional, Protocol

from pythonosc import udp_client  # type: ignore


class OutputBackend(Protocol):
    def send_osc(self, address: str, value: float) -> None: ...
    def send_midi_cc(self, channel: int, cc: int, value: float) -> None: ...
    def close(self) -> None: ...


class NullOutput:
    """Silent backend; used when --dry-run is set."""

    def send_osc(self, address: str, value: float) -> None:
        pass

    def send_midi_cc(self, channel: int, cc: int, value: float) -> None:
        pass

    def close(self) -> None:
        pass


class OSCOutput:
    def __init__(self, host: str = "127.0.0.1", port: int = 7000) -> None:
        self.client = udp_client.SimpleUDPClient(host, port)

    def send_osc(self, address: str, value: float) -> None:
        try:
            self.client.send_message(address, float(value))
        except Exception:
            pass

    def send_midi_cc(self, channel: int, cc: int, value: float) -> None:
        pass

    def close(self) -> None:
        pass


class MIDIOutput:
    """MIDI CC output. Opens a virtual port by default on macOS/Linux."""

    def __init__(self, port_name: str = "audioviz-bridge") -> None:
        import mido  # imported lazily so OSC-only users skip the dependency

        self._mido = mido
        self.port = mido.open_output(port_name, virtual=True)

    def send_osc(self, address: str, value: float) -> None:
        pass

    def send_midi_cc(self, channel: int, cc: int, value: float) -> None:
        try:
            int_value = max(0, min(127, int(round(value * 127))))
            msg = self._mido.Message(
                "control_change",
                channel=max(0, min(15, channel)),
                control=max(0, min(127, cc)),
                value=int_value,
            )
            self.port.send(msg)
        except Exception:
            pass

    def close(self) -> None:
        try:
            self.port.close()
        except Exception:
            pass


class MultiOutput:
    """Fans messages out to multiple backends; failures in one don't stop others."""

    def __init__(self, backends: list[OutputBackend]) -> None:
        self.backends = backends

    def send_osc(self, address: str, value: float) -> None:
        for b in self.backends:
            try:
                b.send_osc(address, value)
            except Exception:
                pass

    def send_midi_cc(self, channel: int, cc: int, value: float) -> None:
        for b in self.backends:
            try:
                b.send_midi_cc(channel, cc, value)
            except Exception:
                pass

    def close(self) -> None:
        for b in self.backends:
            try:
                b.close()
            except Exception:
                pass
