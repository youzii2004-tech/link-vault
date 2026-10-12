"""Link Vault — Enterprise Omni-Channel Media Ingestion & Video Intelligence Pipeline.

Universal batch URL resolver, multi-platform media downloader, and multimodal
video intelligence pipeline.
"""

from .analyzer import KeyframeRecord, TranscriptSegment, VideoAnalysisResult, VideoAnalyzer
from .config import AnalysisConfig, EngineConfig, LinkVaultConfig, PlatformSetting
from .downloader import DownloadResult, MediaDownloader
from .parser import LinkParser, ParsedLink

__version__ = "1.0.0"
__author__ = "Muhammad Usaid Siddiqui"

__all__ = [
    "LinkVaultConfig",
    "EngineConfig",
    "PlatformSetting",
    "AnalysisConfig",
    "LinkParser",
    "ParsedLink",
    "MediaDownloader",
    "DownloadResult",
    "VideoAnalyzer",
    "VideoAnalysisResult",
    "KeyframeRecord",
    "TranscriptSegment",
]
