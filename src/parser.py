"""Link Vault Universal Link Parser & Ingestion Engine.

Handles multi-format input (CSV, raw text, clipboard streams), canonical URL
sanitization (tracking parameter stripping), high-precision regex platform classification,
media type estimation, and deduplication.
"""

import csv
import hashlib
import io
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


@dataclass
class ParsedLink:
    """Standardized representation of an ingested and sanitized media link."""

    id: str
    raw_url: str
    canonical_url: str
    platform: str
    media_type: str
    auth_required: bool
    source_type: str = "raw"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert link representation to dictionary."""
        return asdict(self)


# Tracking parameters to strip during canonicalization
TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "igsh",
    "igshid",
    "fbclid",
    "si",
    "feature",
    "ref",
    "ref_src",
    "s",
    "t",
    "context",
    "is_from_webapp",
    "sender_device",
    "share_id",
    "preview",
    "_branch_match_id",
    "mkt_tok",
    "gclid",
    "oc",
}

# Regex for detecting URLs in arbitrary unstructured text
URL_REGEX = re.compile(
    r"https?://(?:www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b(?:[-a-zA-Z0-9()@:%_\+.~#?&//=]*)",
    re.IGNORECASE,
)


class LinkParser:
    """Universal parser for ingesting, sanitizing, and classifying media links."""

    def __init__(self, auth_platforms: Optional[Set[str]] = None):
        # Platforms that typically require session cookies or authenticated profiles
        self.auth_platforms = auth_platforms or {"instagram", "facebook"}

    @staticmethod
    def compute_link_id(canonical_url: str) -> str:
        """Derive a deterministic 12-character hex ID from the canonical URL."""
        return hashlib.sha256(canonical_url.encode("utf-8")).hexdigest()[:12]

    @classmethod
    def sanitize_url(cls, url: str) -> str:
        """Strip tracking parameters, normalize protocol, and clean query strings."""
        url = url.strip()
        if not url:
            return ""

        # Normalize mobile hostnames
        url = re.sub(r"^https?://m\.facebook\.com/", "https://www.facebook.com/", url)
        url = re.sub(r"^https?://mobile\.twitter\.com/", "https://twitter.com/", url)

        parsed = urlparse(url)
        scheme = parsed.scheme.lower() if parsed.scheme in {"http", "https"} else "https"
        netloc = parsed.netloc.lower()

        # Filter query parameters
        filtered_queries = [
            (k, v)
            for k, v in parse_qsl(parsed.query, keep_blank_values=False)
            if k.lower() not in TRACKING_PARAMS
        ]

        new_query = urlencode(filtered_queries)
        clean_path = parsed.path.rstrip("/") if parsed.path not in {"", "/"} else parsed.path

        return urlunparse((scheme, netloc, clean_path, parsed.params, new_query, ""))

    @classmethod
    def classify_platform(cls, url: str) -> str:
        """Identify media platform using exact hostname and domain matching."""
        parsed = urlparse(url)
        host = parsed.netloc.lower()

        def domain_match(domains: List[str]) -> bool:
            return any(host == d or host.endswith("." + d) for d in domains)

        if domain_match(["instagram.com", "instagr.am"]):
            return "instagram"
        if domain_match(["tiktok.com", "vm.tiktok.com", "vt.tiktok.com"]):
            return "tiktok"
        if domain_match(["youtube.com", "youtu.be"]):
            return "youtube"
        if domain_match(["facebook.com", "fb.watch", "fb.com"]):
            return "facebook"
        if domain_match(["twitter.com", "x.com", "t.co"]):
            return "x"
        if domain_match(["pinterest.com", "pin.it"]):
            return "pinterest"
        if domain_match(["reddit.com", "redd.it", "v.redd.it"]):
            return "reddit"

        return "generic"

    @classmethod
    def estimate_media_type(cls, url: str, platform: str) -> str:
        """Infer target media type (reel, short, video, carousel, post, photo)."""
        parsed = urlparse(url)
        path = parsed.path.lower()

        if platform == "instagram":
            if "/reel/" in path or "/reels/" in path:
                return "reel"
            if "/tv/" in path:
                return "video"
            if "/stories/" in path:
                return "story"
            if "/p/" in path:
                return "post"
            return "profile"

        if platform == "tiktok":
            if "/photo/" in path:
                return "photo"
            if "/video/" in path or "/v/" in path or "vm.tiktok.com" in parsed.netloc:
                return "video"
            return "profile"

        if platform == "youtube":
            if "/shorts/" in path:
                return "short"
            if "/watch" in path or "youtu.be" in parsed.netloc or "/embed/" in path:
                return "video"
            return "channel"

        if platform == "facebook":
            if "/reel/" in path or "/reels/" in path:
                return "reel"
            if "/watch" in path or "/videos/" in path or "fb.watch" in parsed.netloc:
                return "video"
            return "post"

        if platform == "x":
            if "/status/" in path:
                return "post"
            return "profile"

        if platform == "pinterest":
            return "pin"

        if platform == "reddit":
            if "v.redd.it" in parsed.netloc or "/comments/" in path:
                return "video"
            return "post"

        # Generic direct extension detection
        if any(path.endswith(ext) for ext in [".mp4", ".webm", ".mkv", ".mov", ".m4v"]):
            return "video"
        if any(path.endswith(ext) for ext in [".jpg", ".jpeg", ".png", ".webp"]):
            return "photo"

        return "media"

    def parse_single_url(
        self,
        raw_url: str,
        source_type: str = "raw",
        extra_meta: Optional[Dict[str, Any]] = None,
    ) -> Optional[ParsedLink]:
        """Sanitize, classify, and construct a ParsedLink entity."""
        raw_clean = raw_url.strip()
        if not raw_clean or not (raw_clean.startswith("http://") or raw_clean.startswith("https://")):
            return None

        canonical = self.sanitize_url(raw_clean)
        if not canonical:
            return None

        platform = self.classify_platform(canonical)
        media_type = self.estimate_media_type(canonical, platform)
        auth_req = platform in self.auth_platforms

        metadata = extra_meta.copy() if extra_meta else {}

        return ParsedLink(
            id=self.compute_link_id(canonical),
            raw_url=raw_clean,
            canonical_url=canonical,
            platform=platform,
            media_type=media_type,
            auth_required=auth_req,
            source_type=source_type,
            metadata=metadata,
        )

    def parse_text(self, text: str) -> List[ParsedLink]:
        """Extract all valid URLs from unstructured bulk text or clipboard contents."""
        found_urls = URL_REGEX.findall(text)
        results: List[ParsedLink] = []
        seen: Set[str] = set()

        for idx, match in enumerate(found_urls):
            parsed = self.parse_single_url(
                match,
                source_type="bulk_text",
                extra_meta={"match_index": idx},
            )
            if parsed and parsed.canonical_url not in seen:
                seen.add(parsed.canonical_url)
                results.append(parsed)

        return results

    def parse_csv(self, file_path_or_content: str | Path) -> List[ParsedLink]:
        """Ingest URLs from CSV, auto-detecting the URL column or header."""
        rows: List[Dict[str, str]] = []
        raw_data = ""

        if isinstance(file_path_or_content, Path) or (
            isinstance(file_path_or_content, str) and "\n" not in file_path_or_content and Path(file_path_or_content).exists()
        ):
            with open(file_path_or_content, "r", encoding="utf-8-sig", errors="replace") as f:
                raw_data = f.read()
        else:
            raw_data = str(file_path_or_content)

        if not raw_data.strip():
            return []

        # Read CSV rows using standard reader
        f_stream = io.StringIO(raw_data)
        reader = csv.reader(f_stream)
        all_rows = [row for row in reader if any(field.strip() for field in row)]

        if not all_rows:
            return []

        # Check if first row contains a URL (meaning row 0 is actually data, not a header)
        first_row_has_url = any(bool(URL_REGEX.search(cell)) for cell in all_rows[0])
        has_named_header = any(
            any(kw in cell.strip().lower() for kw in ["url", "link", "permalink", "video", "media", "address"])
            for cell in all_rows[0]
        )

        if first_row_has_url and not has_named_header:
            header = [f"col_{i}" for i in range(len(all_rows[0]))]
            data_rows = all_rows
        else:
            header = all_rows[0]
            data_rows = all_rows[1:] if len(all_rows) > 1 else all_rows

        # Detect URL column index
        target_col_idx = self._detect_url_column(header, data_rows)

        results: List[ParsedLink] = []
        seen: Set[str] = set()

        for row_idx, row in enumerate(data_rows):
            if target_col_idx >= len(row):
                continue
            raw_cell = row[target_col_idx].strip()
            if not raw_cell:
                continue

            # Extract URL if cell contains embedded text or clean URL
            match = URL_REGEX.search(raw_cell)
            url_to_process = match.group(0) if match else raw_cell

            # Collect other columns as metadata
            meta = {
                "csv_row": row_idx + 1,
            }
            if len(all_rows) > 1:
                for c_idx, cell_value in enumerate(row):
                    if c_idx != target_col_idx and c_idx < len(header):
                        col_name = header[c_idx].strip() or f"col_{c_idx}"
                        meta[col_name] = cell_value.strip()

            parsed = self.parse_single_url(
                url_to_process,
                source_type="csv",
                extra_meta=meta,
            )
            if parsed and parsed.canonical_url not in seen:
                seen.add(parsed.canonical_url)
                results.append(parsed)

        return results

    @staticmethod
    def _detect_url_column(header: List[str], data_rows: List[List[str]]) -> int:
        """Find the most likely column index containing media URLs."""
        url_header_keywords = {
            "url",
            "link",
            "links",
            "video_url",
            "media_url",
            "permalink",
            "href",
            "post_url",
            "source",
            "address",
        }

        # Check explicit header matches
        for idx, col in enumerate(header):
            cleaned = col.strip().lower()
            if cleaned in url_header_keywords or any(kw in cleaned for kw in url_header_keywords):
                return idx

        # Heuristic inspection: count URL regex matches across rows
        scores = [0] * max(len(header), max(len(r) for r in data_rows[:20]) if data_rows else 0)
        sample = data_rows[:30]

        for row in sample:
            for idx, cell in enumerate(row):
                if idx < len(scores) and URL_REGEX.search(cell):
                    scores[idx] += 1

        best_col = max(range(len(scores)), key=lambda i: scores[i]) if scores and max(scores) > 0 else 0
        return best_col
