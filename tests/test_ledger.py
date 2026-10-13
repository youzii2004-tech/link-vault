"""Tests for the dashboard ledger builder."""

import json
from pathlib import Path

from src.ledger import build_ledger


def _write_analysis(out: Path, file_name: str, with_transcript: bool = True) -> None:
    out.mkdir(parents=True, exist_ok=True)
    data = {
        "file_name": file_name,
        "duration_seconds": 12.0,
        "resolution": "1080x1920",
        "video_codec": "h264",
        "audio_codec": "aac",
        "framerate": 30.0,
        "has_audio": True,
        "transcript": [{"start": 0.0, "end": 1.0, "text": "hi"}] if with_transcript else [],
        "keyframes": [{"timestamp_seconds": 2.0, "image_path": "/x/y/abc_kf_01_2s.jpg"}],
    }
    (out / f"{Path(file_name).stem}.analysis.json").write_text(json.dumps(data))


def test_links_are_matched_to_analysis_by_id_prefix(tmp_path: Path):
    links = tmp_path / "links.json"
    links.write_text(json.dumps([
        {"id": "abc", "platform": "youtube", "canonical_url": "https://youtu.be/1", "media_type": "short"},
        {"id": "def", "platform": "tiktok", "canonical_url": "https://tiktok.com/2", "auth_required": True},
    ]))
    _write_analysis(tmp_path / "out", "abc_title.mp4")

    ledger = build_ledger(links, tmp_path / "out")

    assert [r["id"] for r in ledger] == ["abc", "def"]
    assert ledger[0]["analyzed"] and ledger[0]["codec"] == "h264 / aac"
    assert ledger[0]["keyframes"] == [{"timestamp": 2.0, "file": "abc_kf_01_2s.jpg"}]
    assert ledger[1]["analyzed"] is False and ledger[1]["auth_required"] is True


def test_without_links_file_lists_analyses(tmp_path: Path):
    _write_analysis(tmp_path / "out", "abc_title.mp4")
    ledger = build_ledger(None, tmp_path / "out")
    assert len(ledger) == 1 and ledger[0]["id"] == "abc"


def test_empty_when_nothing_exists(tmp_path: Path):
    assert build_ledger(None, tmp_path / "missing") == []
