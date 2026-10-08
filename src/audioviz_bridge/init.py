"""audioviz-bridge: lightweight audio analysis to OSC/MIDI bridge for live VJ systems."""

__version__ = "0.1.0"

from .analyzer import AudioAnalyzer, AnalysisFrame
from .mapper import MappingConfig, SignalMapper
from .output import OSCOutput, MIDIOutput, MultiOutput
from .engine import BridgeEngine

__all__ = [
    "AudioAnalyzer",
    "AnalysisFrame",
    "MappingConfig",
    "SignalMapper",
    "OSCOutput",
    "MIDIOutput",
    "MultiOutput",
    "BridgeEngine",
]
