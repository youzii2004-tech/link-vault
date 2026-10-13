"""Merge ingested links with analysis output into the ledger shown by the dashboard."""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional


def _load_json(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_ledger(links_file: Optional[Path], analysis_dir: Path) -> List[Dict[str, Any]]:
    """Return one record per link (or per analysis file when no links file is given).

    Analysis files are matched to links by the ``<link id>_`` filename prefix the
    downloader uses. Keyframes are exposed as file names under ``analysis_dir/keyframes``.
    """
    analyses: List[Dict[str, Any]] = []
    if analysis_dir.is_dir():
        for p in sorted(analysis_dir.glob("*.analysis.json")):
            try:
                analyses.append(_load_json(p))
            except (OSError, ValueError):
                continue

    def find_analysis(link_id: str) -> Optional[Dict[str, Any]]:
        return next((a for a in analyses if a.get("file_name", "").startswith(f"{link_id}_")), None)

    def to_record(base: Dict[str, Any], a: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        rec = {
            "id": base.get("id", ""),
            "platform": base.get("platform", "generic"),
            "canonical_url": base.get("canonical_url", ""),
            "media_type": base.get("media_type", "video"),
            "auth_required": bool(base.get("auth_required", False)),
            "analyzed": a is not None,
        }
        if a:
            rec.update(
                duration=a.get("duration_seconds", 0),
                resolution=a.get("resolution", "unknown"),
                codec=f"{a.get('video_codec', '?')} / {a.get('audio_codec') or 'no audio'}",
                fps=a.get("framerate", 0),
                has_audio=a.get("has_audio", False),
                transcript=a.get("transcript", []),
                keyframes=[
                    {
                        "timestamp": kf.get("timestamp_seconds", 0),
                        "file": Path(kf.get("image_path", "")).name,
                    }
                    for kf in a.get("keyframes", [])
                ],
            )
        return rec

    if links_file and links_file.exists():
        links = [l for l in _load_json(links_file) if isinstance(l, dict)]
        return [to_record(l, find_analysis(l.get("id", "\0"))) for l in links]

    # No links file: show whatever has been analyzed.
    return [
        to_record(
            {"id": a.get("file_name", "").split("_", 1)[0], "canonical_url": a.get("file_name", "")},
            a,
        )
        for a in analyses
    ]
