import numpy as np

from audioviz_bridge.analyzer import AudioAnalyzer
from audioviz_bridge.mapper import MappingConfig, SignalMapper


def test_package_exposes_public_api():
    """顶层包应能直接导入公开 API(而非空的 __init__ / 孤儿 init.py)。"""
    import audioviz_bridge

    assert audioviz_bridge.__version__ == "0.1.0"
    from audioviz_bridge import AudioAnalyzer, BridgeEngine, SignalMapper  # noqa: F401


def test_analyzer_produces_normalized_frame():
    analyzer = AudioAnalyzer(sample_rate=48000, block_size=1024)
    sine = np.sin(2 * np.pi * 100 * np.arange(1024) / 48000).astype(np.float32)
    frame = analyzer.process_block(sine)
    assert 0.0 <= frame.bass_energy <= 1.0
    assert 0.0 <= frame.rms <= 1.0


def test_mapper_respects_confidence_threshold(tmp_path):
    cfg = tmp_path / "mappings.yaml"
    cfg.write_text(
        """
signals:
  - name: test
    source: onset
    osc_address: /test
    trigger_on: onset
    confidence_threshold: 0.9
""",
        encoding="utf-8",
    )
    mapping = MappingConfig(str(cfg))
    mapping.load()
    mapper = SignalMapper(mapping)
    from audioviz_bridge.analyzer import AnalysisFrame

    low = AnalysisFrame(timestamp=0.0, onset_strength=0.3, onset_detected=True)
    high = AnalysisFrame(timestamp=0.0, onset_strength=0.95, onset_detected=True)
    assert mapper.evaluate(low) == []
    assert len(mapper.evaluate(high)) == 1
