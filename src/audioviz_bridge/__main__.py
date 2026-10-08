"""CLI entry point: python -m audioviz_bridge --config mappings.yaml --osc 127.0.0.1:7000"""

from __future__ import annotations

import argparse
import signal
import sys
import time

from .engine import BridgeEngine
from .output import MIDIOutput, MultiOutput, OSCOutput


def parse_target(value: str) -> tuple[str, int]:
    if ":" not in value:
        return value, 7000
    host, port = value.rsplit(":", 1)
    return host, int(port)


def build_output(args) -> MultiOutput | OSCOutput:
    backends = []
    if args.osc:
        host, port = parse_target(args.osc)
        backends.append(OSCOutput(host, port))
    if args.midi:
        try:
            backends.append(MIDIOutput(args.midi_port))
        except Exception as exc:
            print(f"[warn] MIDI output unavailable: {exc}", file=sys.stderr)
    if not backends:
        print("[warn] no output configured; use --osc or --midi", file=sys.stderr)
        from .output import NullOutput

        return NullOutput()
    return MultiOutput(backends)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="audioviz-bridge",
        description="Translate live audio into OSC/MIDI for VJ software.",
    )
    parser.add_argument(
        "--source",
        choices=["device", "simulate"],
        default="device",
        help="Audio source: device (real input) or simulate (synthetic, no hardware needed)",
    )
    parser.add_argument("--bpm", type=float, default=120.0, help="BPM for simulate source")
    parser.add_argument("--config", "-c", required=True, help="Path to mappings.yaml")
    parser.add_argument("--osc", help="OSC target, e.g. 127.0.0.1:7000")
    parser.add_argument("--midi", action="store_true", help="Enable MIDI CC output")
    parser.add_argument(
        "--midi-port",
        default="audioviz-bridge",
        help="Name of the virtual MIDI port (default: audioviz-bridge)",
    )
    parser.add_argument("--device", help="Audio input device index or name")
    parser.add_argument("--sample-rate", type=int, default=48000)
    parser.add_argument("--block-size", type=int, default=1024)
    parser.add_argument("--no-link", action="store_true", help="Disable Ableton Link")
    parser.add_argument("--stats", action="store_true", help="Print stats every 5s")
    args = parser.parse_args(argv)

    output = build_output(args)
    engine = BridgeEngine(
        config_path=args.config,
        output=output,
        device=args.device,
        sample_rate=args.sample_rate,
        block_size=args.block_size,
        enable_link=not args.no_link,
        source=args.source,
        bpm=args.bpm,
    )

    def _shutdown(signum, frame):
        del signum, frame
        engine.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    engine.start()
    print(f"[audioviz-bridge] running. config={args.config} osc={args.osc} midi={args.midi}")

    if args.stats:
        try:
            while True:
                time.sleep(5)
                s = engine.stats
                print(
                    f"[stats] frames={s['frames']} emitted={s['emitted']} "
                    f"link={s['link_enabled']} tempo={s['tempo']:.1f}"
                )
        except KeyboardInterrupt:
            pass
    else:
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass

    engine.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
