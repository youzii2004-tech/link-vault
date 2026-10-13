"""Integration tests that exercise real binaries and real sockets (no mocks).

* ffmpeg/ffprobe tests run whenever those binaries are on PATH.
* The network test hits a real public URL and is opt-in:
  ``LINKVAULT_NETWORK_TESTS=1 pytest -m network``
"""

from functools import partial
from http.server import HTTPServer, SimpleHTTPRequestHandler
import os
from pathlib import Path
import shutil
import subprocess
import threading

import pytest

from src.analyzer import VideoAnalyzer
from src.config import LinkVaultConfig
from src.downloader import MediaDownloader
from src.parser import LinkParser

needs_ffmpeg = pytest.mark.skipif(
    not (shutil.which("ffmpeg") and shutil.which("ffprobe")),
    reason="ffmpeg/ffprobe not installed",
)


def _make_video(path: Path, with_audio: bool) -> Path:
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", "testsrc=duration=5:size=320x568:rate=15",
    ]
    if with_audio:
        cmd += ["-f", "lavfi", "-i", "sine=frequency=440:duration=5", "-c:a", "aac"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-shortest", str(path)]
    subprocess.run(cmd, check=True)
    return path


@pytest.fixture
def no_transcription_config() -> LinkVaultConfig:
    cfg = LinkVaultConfig()
    cfg.analysis.transcription.enabled = False
    return cfg


@needs_ffmpeg
def test_analyze_real_video_with_audio(tmp_path: Path, no_transcription_config):
    video = _make_video(tmp_path / "with_audio.mp4", with_audio=True)
    analyzer = VideoAnalyzer(no_transcription_config, output_dir=tmp_path / "out")

    result = analyzer.analyze_video(video)

    assert result.width == 320 and result.height == 568
    assert result.aspect_ratio == "9:16"
    assert result.video_codec == "h264"
    assert result.has_audio and result.audio_codec == "aac"
    assert 4.5 < result.duration_seconds < 5.5
    assert len(result.keyframes) == 5
    assert (tmp_path / "out" / "with_audio.analysis.json").exists()


@needs_ffmpeg
def test_analyze_real_silent_video(tmp_path: Path):
    video = _make_video(tmp_path / "silent.mp4", with_audio=False)
    analyzer = VideoAnalyzer(output_dir=tmp_path / "out")

    result = analyzer.analyze_video(video)

    assert result.has_audio is False
    assert result.transcript == []
    assert len(result.keyframes) == 5


@pytest.fixture
def http_server(tmp_path: Path):
    serve_dir = tmp_path / "www"
    serve_dir.mkdir()
    handler = partial(SimpleHTTPRequestHandler, directory=str(serve_dir))
    server = HTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield serve_dir, f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def test_direct_stream_download_over_real_http(tmp_path: Path, http_server):
    serve_dir, base = http_server
    payload = os.urandom(200_000)
    (serve_dir / "clip.mp4").write_bytes(payload)

    link = LinkParser().parse_single_url(f"{base}/clip.mp4?utm_source=x")
    assert link is not None
    downloader = MediaDownloader(download_dir=tmp_path / "dl")

    result = downloader._download_direct_stream(link)

    assert result.success
    assert Path(result.file_path).read_bytes() == payload


@pytest.mark.network
@pytest.mark.skipif(
    os.environ.get("LINKVAULT_NETWORK_TESTS") != "1" or not shutil.which("yt-dlp"),
    reason="set LINKVAULT_NETWORK_TESTS=1 and install yt-dlp to run",
)
def test_download_public_youtube_video(tmp_path: Path):
    """Real yt-dlp download of the first YouTube video ever uploaded (19 s)."""
    link = LinkParser().parse_single_url("https://www.youtube.com/watch?v=jNQXAC9IVRw")
    downloader = MediaDownloader(download_dir=tmp_path / "dl", max_workers=1)

    result = downloader.download_link(link)

    assert result.success, result.error
    assert Path(result.file_path).stat().st_size > 0
