"""Unit tests for multimodal video intelligence pipeline."""

from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from src.analyzer import VideoAnalyzer, VideoAnalysisResult


@pytest.fixture
def analyzer(tmp_path: Path):
    return VideoAnalyzer(output_dir=tmp_path / "analysis_output")


def test_calculate_aspect_ratio():
    """Verify common video aspect ratio computations."""
    assert VideoAnalyzer.calculate_aspect_ratio(1920, 1080) == "16:9"
    assert VideoAnalyzer.calculate_aspect_ratio(1080, 1920) == "9:16"
    assert VideoAnalyzer.calculate_aspect_ratio(1080, 1080) == "1:1"
    assert VideoAnalyzer.calculate_aspect_ratio(1080, 1350) == "4:5"
    assert VideoAnalyzer.calculate_aspect_ratio(1280, 960) == "4:3"
    assert VideoAnalyzer.calculate_aspect_ratio(0, 0) == "unknown"


def test_analyze_video_mocked(analyzer: VideoAnalyzer, tmp_path: Path):
    """Verify end-to-end video analysis and JSON export with mocked ffprobe."""
    dummy_video = tmp_path / "sample.mp4"
    dummy_video.write_bytes(b"dummy video binary data")

    mock_probe = {
        "format": {
            "duration": "14.50",
            "bit_rate": "2500000",
        },
        "streams": [
            {
                "codec_type": "video",
                "width": 1080,
                "height": 1920,
                "codec_name": "h264",
                "r_frame_rate": "30/1",
            },
            {
                "codec_type": "audio",
                "codec_name": "aac",
            },
        ],
    }

    with patch.object(analyzer, "probe_media", return_value=mock_probe):
        with patch.object(analyzer, "extract_uniform_keyframes", return_value=[]):
            with patch.object(
                analyzer,
                "transcribe_audio",
                return_value=([{"start": 0.0, "end": 2.5, "text": "Hello world"}], "Hello world"),
            ):
                result = analyzer.analyze_video(dummy_video)

                assert result.duration_seconds == 14.50
                assert result.resolution == "1080x1920"
                assert result.aspect_ratio == "9:16"
                assert result.video_codec == "h264"
                assert result.has_audio is True
                assert result.audio_codec == "aac"
                assert result.framerate == 30.0
                assert result.full_transcript == "Hello world"

                # Check JSON metadata file was written
                json_file = analyzer.output_dir / "sample.analysis.json"
                assert json_file.exists()


def test_silent_video_graceful_handling(analyzer: VideoAnalyzer, tmp_path: Path):
    """Verify video without audio streams skips transcription without error."""
    dummy_video = tmp_path / "silent.mp4"
    dummy_video.write_bytes(b"silent video data")

    mock_probe_silent = {
        "format": {"duration": "5.0", "bit_rate": "1000000"},
        "streams": [
            {
                "codec_type": "video",
                "width": 1920,
                "height": 1080,
                "codec_name": "h264",
                "r_frame_rate": "60/1",
            }
        ],
    }

    with patch.object(analyzer, "probe_media", return_value=mock_probe_silent):
        with patch.object(analyzer, "extract_uniform_keyframes", return_value=[]):
            result = analyzer.analyze_video(dummy_video)
            assert result.has_audio is False
            assert result.audio_codec is None
            assert result.transcript == []
            assert result.full_transcript == ""
