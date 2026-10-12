"""Unit tests for universal link parser, classifier, and canonical sanitizer."""

from pathlib import Path
import pytest

from src.parser import LinkParser, ParsedLink


@pytest.fixture
def parser():
    return LinkParser()


def test_url_canonicalization_strips_tracking(parser: LinkParser):
    """Verify that tracking parameters are completely stripped from canonical URLs."""
    raw = "https://www.instagram.com/reel/C3x9abc1234/?utm_source=ig_web_copy_link&igsh=MzRlODBiNWFlZA==&fbclid=IwAR123"
    sanitized = parser.sanitize_url(raw)
    assert sanitized == "https://www.instagram.com/reel/C3x9abc1234"
    assert "utm_source" not in sanitized
    assert "igsh" not in sanitized
    assert "fbclid" not in sanitized


def test_platform_classification_coverage(parser: LinkParser):
    """Verify regex classifier for all supported platforms."""
    fixtures = [
        ("https://www.instagram.com/reel/C3x9abc1234/", "instagram", "reel"),
        ("https://www.tiktok.com/@openai/video/7345678901234567890", "tiktok", "video"),
        ("https://www.youtube.com/shorts/dQw4w9WgXcQ", "youtube", "short"),
        ("https://www.youtube.com/watch?v=aqz-KE-bpKQ", "youtube", "video"),
        ("https://www.facebook.com/reel/1020304050607080", "facebook", "reel"),
        ("https://x.com/OpenAI/status/1758212957864358054", "x", "post"),
        ("https://www.pinterest.com/pin/123456789012345678/", "pinterest", "pin"),
        ("https://www.reddit.com/r/technology/comments/17abcde/discussion/", "reddit", "video"),
        ("https://example.com/videos/sample.mp4", "generic", "video"),
    ]

    for url, expected_plat, expected_type in fixtures:
        link = parser.parse_single_url(url)
        assert link is not None, f"Failed to parse {url}"
        assert link.platform == expected_plat, f"Expected {expected_plat}, got {link.platform} for {url}"
        assert link.media_type == expected_type, f"Expected {expected_type}, got {link.media_type} for {url}"


def test_auth_requirement_flag(parser: LinkParser):
    """Verify platforms requiring authentication are correctly flagged."""
    ig_link = parser.parse_single_url("https://www.instagram.com/p/C_abc123/")
    yt_link = parser.parse_single_url("https://www.youtube.com/watch?v=12345")

    assert ig_link.auth_required is True
    assert yt_link.auth_required is False


def test_parse_unstructured_text(parser: LinkParser):
    """Verify extraction and deduplication from messy clipboard or raw text."""
    text = """
    Check out this awesome demo: https://www.youtube.com/watch?v=demo123&utm_campaign=share
    Also see https://www.tiktok.com/@user/video/123456789 and again
    the same link with extra trackers: https://www.youtube.com/watch?v=demo123&si=xyz123
    """
    results = parser.parse_text(text)
    assert len(results) == 2
    assert results[0].platform == "youtube"
    assert results[1].platform == "tiktok"
    assert results[0].canonical_url == "https://www.youtube.com/watch?v=demo123"


def test_csv_auto_column_detection(parser: LinkParser, tmp_path: Path):
    """Verify CSV parser correctly identifies URL column and preserves row metadata."""
    csv_content = """Title,Target_URL,Category
AI Reel,https://www.instagram.com/reel/C12345/,Tech
OpenAI Update,https://x.com/OpenAI/status/9876543210,News
"""
    csv_file = tmp_path / "test_import.csv"
    csv_file.write_text(csv_content, encoding="utf-8")

    links = parser.parse_csv(csv_file)
    assert len(links) == 2
    assert links[0].platform == "instagram"
    assert links[0].canonical_url == "https://www.instagram.com/reel/C12345"
    assert links[0].metadata.get("Title") == "AI Reel"
    assert links[1].platform == "x"
    assert links[1].metadata.get("Category") == "News"


def test_csv_with_no_header_detects_url_column(parser: LinkParser, tmp_path: Path):
    """Verify heuristic auto-detection works even without an explicit URL column header."""
    csv_content = """Some Note,https://www.youtube.com/watch?v=abc1234,Priority 1
Another Note,https://www.tiktok.com/@test/video/9999999,Priority 2
"""
    csv_file = tmp_path / "raw_no_header.csv"
    csv_file.write_text(csv_content, encoding="utf-8")

    links = parser.parse_csv(csv_file)
    assert len(links) == 2
    assert links[0].platform == "youtube"
    assert links[1].platform == "tiktok"
