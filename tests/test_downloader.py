"""Unit tests for media downloader and authentication engine."""

from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from src.downloader import MediaDownloader, DownloadResult
from src.parser import ParsedLink


@pytest.fixture
def downloader(tmp_path: Path):
    return MediaDownloader(download_dir=tmp_path / "downloads", max_workers=2)


def test_sanitize_filename():
    """Verify dangerous path characters and whitespace are securely stripped."""
    dangerous = 'test/video: "my super*cool?video" <1080p>|final.mp4'
    safe = MediaDownloader.sanitize_filename(dangerous)
    assert "/" not in safe
    assert ":" not in safe
    assert '"' not in safe
    assert "*" not in safe
    assert "?" not in safe
    assert "<" not in safe
    assert ">" not in safe
    assert "|" not in safe
    assert safe == "testvideo_my_supercoolvideo_1080pfinal.mp4"


def test_validate_cookies_file(tmp_path: Path, downloader: MediaDownloader):
    """Verify Netscape HTTP cookie format detection."""
    valid_cookie_file = tmp_path / "valid_cookies.txt"
    valid_cookie_file.write_text(
        "# Netscape HTTP Cookie File\n"
        ".instagram.com\tTRUE\t/\tTRUE\t1798765432\tsessionid\tdummy\n",
        encoding="utf-8",
    )
    assert downloader.validate_cookies_file(valid_cookie_file) is True

    invalid_cookie_file = tmp_path / "corrupt_cookies.txt"
    invalid_cookie_file.write_text("random json or key-value data", encoding="utf-8")
    assert downloader.validate_cookies_file(invalid_cookie_file) is False

    assert downloader.validate_cookies_file(tmp_path / "does_not_exist.txt") is False


def test_download_batch_execution(downloader: MediaDownloader):
    """Verify batch worker pool dispatches and aggregates results."""
    mock_link1 = ParsedLink(
        id="hash01",
        raw_url="https://youtube.com/watch?v=1",
        canonical_url="https://youtube.com/watch?v=1",
        platform="youtube",
        media_type="video",
        auth_required=False,
    )
    mock_link2 = ParsedLink(
        id="hash02",
        raw_url="https://instagram.com/reel/2",
        canonical_url="https://instagram.com/reel/2",
        platform="instagram",
        media_type="reel",
        auth_required=True,
    )

    with patch.object(downloader, "download_link") as mock_dl:
        mock_dl.side_effect = [
            DownloadResult(link_id="hash01", url="https://youtube.com/watch?v=1", platform="youtube", success=True),
            DownloadResult(link_id="hash02", url="https://instagram.com/reel/2", platform="instagram", success=False, error="Auth required"),
        ]

        results = downloader.download_batch([mock_link1, mock_link2])
        assert len(results) == 2
        success_count = sum(1 for r in results if r.success)
        assert success_count == 1
