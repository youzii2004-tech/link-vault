"""Link Vault Omni-Channel Media Downloader.

Orchestrates yt-dlp and gallery-dl execution with session cookie authentication routing,
exponential backoff retry policies, thread-pool concurrency, and strict local disk isolation.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import re
import time
from typing import Any, Callable, Dict, List, Optional
import urllib.request

from .config import EngineConfig, LinkVaultConfig
from .parser import ParsedLink

logger = logging.getLogger("linkvault.downloader")


@dataclass
class DownloadResult:
    """Telemetry and outcome of a media download attempt."""

    link_id: str
    url: str
    platform: str
    success: bool
    file_path: Optional[str] = None
    title: Optional[str] = None
    duration: Optional[float] = None
    thumbnail_path: Optional[str] = None
    error: Optional[str] = None
    retries_attempted: int = 0
    timestamp: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Convert result to dictionary representation."""
        return asdict(self)


class MediaDownloader:
    """Robust multi-platform media downloader engine."""

    def __init__(
        self,
        config: Optional[LinkVaultConfig] = None,
        download_dir: Optional[Path] = None,
        cookies_path: Optional[Path] = None,
        max_workers: int = 4,
    ):
        self.config = config or LinkVaultConfig()
        self.download_dir = Path(download_dir or self.config.engine.download_dir)
        self.download_dir.mkdir(parents=True, exist_ok=True)

        self.cookies_path = Path(cookies_path) if cookies_path else self.config.engine.cookies_path
        if self.cookies_path and not self.cookies_path.exists():
            logger.warning("Configured cookies path does not exist on disk: %s", self.cookies_path)

        self.max_workers = max_workers or self.config.engine.max_workers
        self.max_retries = self.config.engine.max_retries
        self.backoff_factor = self.config.engine.retry_backoff_factor
        self.rate_limit_delay = self.config.engine.rate_limit_delay_seconds
        self.user_agent = self.config.engine.user_agent

    @staticmethod
    def sanitize_filename(name: str) -> str:
        """Strip dangerous characters to ensure secure local filesystem storage."""
        cleaned = re.sub(r'[\\/*?:"<>|]', "", name)
        cleaned = re.sub(r"\s+", "_", cleaned)
        return cleaned.strip("._")[:120] or "media"

    def validate_cookies_file(self, path: Optional[Path]) -> bool:
        """Verify that the cookies file matches the standard Netscape HTTP format."""
        if not path or not path.exists():
            return False
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                first_lines = [f.readline() for _ in range(5)]
                for line in first_lines:
                    if "# Netscape HTTP Cookie File" in line or "# HTTP Cookie File" in line:
                        return True
            # Fallback check for tab-delimited records
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and len(line.split("\t")) >= 7:
                        return True
        except Exception as e:
            logger.error("Error reading cookies file: %s", e)
        return False

    def download_link(self, link: ParsedLink) -> DownloadResult:
        """Download a single media link with retry backoff and engine failover."""
        attempts = 0
        last_error = ""

        out_template = str(self.download_dir / f"{link.id}_%(title).100s.%(ext)s")
        active_cookies = str(self.cookies_path) if (self.cookies_path and self.cookies_path.exists()) else None

        while attempts <= self.max_retries:
            try:
                # Attempt primary download via yt-dlp
                res = self._download_with_ytdlp(link, out_template, active_cookies)
                if res.success:
                    res.retries_attempted = attempts
                    return res
                last_error = res.error or "Unknown download failure"
            except Exception as e:
                last_error = str(e)
                logger.warning("Attempt %d failed for %s: %s", attempts + 1, link.canonical_url, e)

            # Direct stream fallback if generic media file URL
            if link.platform == "generic" or link.canonical_url.split("?")[0].endswith((".mp4", ".webm")):
                try:
                    res_direct = self._download_direct_stream(link)
                    if res_direct.success:
                        res_direct.retries_attempted = attempts
                        return res_direct
                except Exception as de:
                    last_error = f"{last_error}; Direct fallback: {de}"

            attempts += 1
            if attempts <= self.max_retries:
                sleep_time = self.rate_limit_delay * (self.backoff_factor ** (attempts - 1))
                time.sleep(sleep_time)

        return DownloadResult(
            link_id=link.id,
            url=link.canonical_url,
            platform=link.platform,
            success=False,
            error=last_error,
            retries_attempted=attempts,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    def _download_with_ytdlp(
        self,
        link: ParsedLink,
        out_template: str,
        cookies_file: Optional[str],
    ) -> DownloadResult:
        """Execute extraction and download via yt_dlp Python engine."""
        try:
            import yt_dlp
        except ImportError:
            return DownloadResult(
                link_id=link.id,
                url=link.canonical_url,
                platform=link.platform,
                success=False,
                error="yt-dlp package is not installed",
                timestamp=datetime.now(timezone.utc).isoformat(),
            )

        ydl_opts: Dict[str, Any] = {
            "outtmpl": out_template,
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "user_agent": self.user_agent,
            "socket_timeout": self.config.engine.timeout_seconds,
            "overwrites": False,
        }

        # Route session cookies when specified
        if cookies_file:
            ydl_opts["cookiefile"] = cookies_file

        # Format preferences
        platform_cfg = self.config.platforms.get(link.platform)
        if platform_cfg and platform_cfg.preferred_format:
            ydl_opts["format"] = platform_cfg.preferred_format
        else:
            ydl_opts["format"] = "best[ext=mp4]/bestvideo+bestaudio/best"

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(link.canonical_url, download=True)
                if not info:
                    return DownloadResult(
                        link_id=link.id,
                        url=link.canonical_url,
                        platform=link.platform,
                        success=False,
                        error="No media metadata could be extracted",
                        timestamp=datetime.now(timezone.utc).isoformat(),
                    )

                # Determine saved filename
                file_path: Optional[str] = None
                if "_filename" in info:
                    file_path = str(Path(info["_filename"]).resolve())
                elif "requested_downloads" in info and info["requested_downloads"]:
                    file_path = str(Path(info["requested_downloads"][0]["filepath"]).resolve())
                else:
                    # Scan output directory for matched link id
                    matches = list(self.download_dir.glob(f"{link.id}_*"))
                    if matches:
                        file_path = str(matches[0].resolve())

                return DownloadResult(
                    link_id=link.id,
                    url=link.canonical_url,
                    platform=link.platform,
                    success=True,
                    file_path=file_path,
                    title=info.get("title"),
                    duration=info.get("duration"),
                    thumbnail_path=info.get("thumbnail"),
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )
        except Exception as e:
            return DownloadResult(
                link_id=link.id,
                url=link.canonical_url,
                platform=link.platform,
                success=False,
                error=str(e),
                timestamp=datetime.now(timezone.utc).isoformat(),
            )

    def _download_direct_stream(self, link: ParsedLink) -> DownloadResult:
        """Direct stream fallback download for raw video files (MP4/WebM)."""
        clean_ext = ".mp4"
        clean_path = link.canonical_url.split("?")[0].lower()
        for ext in [".mp4", ".webm", ".mkv", ".mov"]:
            if clean_path.endswith(ext):
                clean_ext = ext
                break

        target_file = self.download_dir / f"{link.id}_direct{clean_ext}"
        req = urllib.request.Request(
            link.canonical_url,
            headers={"User-Agent": self.user_agent},
        )

        with urllib.request.urlopen(req, timeout=self.config.engine.timeout_seconds) as response:
            with open(target_file, "wb") as out_f:
                while chunk := response.read(65536):
                    out_f.write(chunk)

        return DownloadResult(
            link_id=link.id,
            url=link.canonical_url,
            platform=link.platform,
            success=True,
            file_path=str(target_file.resolve()),
            title=f"Direct Stream {link.id}",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    def download_batch(
        self,
        links: List[ParsedLink],
        progress_callback: Optional[Callable[[int, int, DownloadResult], None]] = None,
    ) -> List[DownloadResult]:
        """Process batch of links using a concurrent worker pool."""
        results: List[DownloadResult] = []
        total = len(links)
        completed = 0

        if not links:
            return []

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_link = {executor.submit(self.download_link, link): link for link in links}
            for future in as_completed(future_to_link):
                res = future.result()
                results.append(res)
                completed += 1
                if progress_callback:
                    progress_callback(completed, total, res)

        return results
