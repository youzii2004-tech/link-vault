"""Link Vault Configuration Engine.

Provides strict Pydantic v2 validation and loading schemas for omni-channel
media ingestion, downloader execution, cookie management, and multimodal
video intelligence.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional
import yaml
from pydantic import BaseModel, Field, field_validator


class PlatformSetting(BaseModel):
    """Platform-specific ingestion and downloader constraints."""

    enabled: bool = True
    require_cookies: bool = False
    allowed_types: List[str] = Field(default_factory=lambda: ["video", "post"])
    preferred_format: Optional[str] = None


class KeyframesConfig(BaseModel):
    """Uniform keyframe extraction settings."""

    enabled: bool = True
    count: int = Field(default=5, ge=1, le=50)
    format: str = Field(default="jpg", pattern="^(jpg|jpeg|png)$")
    quality: int = Field(default=2, ge=1, le=31)


class AudioConfig(BaseModel):
    """Audio probe and extraction parameters."""

    detect_streams: bool = True
    extract_wav: bool = True


class TranscriptionConfig(BaseModel):
    """Timestamped multimodal transcription configuration."""

    enabled: bool = True
    engine: str = Field(default="faster-whisper", pattern="^(faster-whisper|whisper|none)$")
    model_size: str = "tiny"
    device: str = "cpu"
    compute_type: str = "int8"
    language: Optional[str] = None
    fallback_silent: bool = True


class AnalysisConfig(BaseModel):
    """Multimodal video intelligence pipeline configuration."""

    enabled: bool = True
    output_dir: Path = Path("analysis_output")
    keyframes: KeyframesConfig = Field(default_factory=KeyframesConfig)
    audio: AudioConfig = Field(default_factory=AudioConfig)
    transcription: TranscriptionConfig = Field(default_factory=TranscriptionConfig)

    @field_validator("output_dir", mode="before")
    @classmethod
    def parse_path(cls, v: Any) -> Path:
        return Path(v) if v is not None else Path("analysis_output")


class EngineConfig(BaseModel):
    """Core runtime, network concurrency, and retry parameters."""

    download_dir: Path = Path("downloads")
    analysis_dir: Path = Path("analysis_output")
    cookies_path: Optional[Path] = None
    max_workers: int = Field(default=4, ge=1, le=32)
    timeout_seconds: int = Field(default=60, ge=5, le=600)
    rate_limit_delay_seconds: float = Field(default=1.5, ge=0.0, le=30.0)
    max_retries: int = Field(default=3, ge=0, le=10)
    retry_backoff_factor: float = Field(default=2.0, ge=1.0, le=10.0)
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    )

    @field_validator("download_dir", "analysis_dir", mode="before")
    @classmethod
    def parse_engine_paths(cls, v: Any) -> Path:
        return Path(v)

    @field_validator("cookies_path", mode="before")
    @classmethod
    def parse_cookies_path(cls, v: Any) -> Optional[Path]:
        if not v:
            return None
        return Path(v)


def default_platform_settings() -> Dict[str, PlatformSetting]:
    """Default platform matrix for omni-channel media ingestion."""
    return {
        "instagram": PlatformSetting(
            enabled=True,
            require_cookies=True,
            allowed_types=["reel", "post", "carousel", "tv"],
        ),
        "tiktok": PlatformSetting(
            enabled=True,
            require_cookies=False,
            allowed_types=["video", "photo"],
        ),
        "youtube": PlatformSetting(
            enabled=True,
            require_cookies=False,
            allowed_types=["short", "video"],
            preferred_format="bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        ),
        "facebook": PlatformSetting(
            enabled=True,
            require_cookies=True,
            allowed_types=["reel", "watch", "video"],
        ),
        "x": PlatformSetting(
            enabled=True,
            require_cookies=False,
            allowed_types=["video", "gif", "post"],
        ),
        "pinterest": PlatformSetting(
            enabled=True,
            require_cookies=False,
            allowed_types=["pin", "video"],
        ),
        "reddit": PlatformSetting(
            enabled=True,
            require_cookies=False,
            allowed_types=["video", "post"],
        ),
        "generic": PlatformSetting(
            enabled=True,
            require_cookies=False,
            allowed_types=["media", "stream"],
        ),
    }


class LinkVaultConfig(BaseModel):
    """Top-level Link Vault configuration schema."""

    version: str = "1.0"
    engine: EngineConfig = Field(default_factory=EngineConfig)
    platforms: Dict[str, PlatformSetting] = Field(default_factory=default_platform_settings)
    analysis: AnalysisConfig = Field(default_factory=AnalysisConfig)

    @classmethod
    def load_from_yaml(cls, path: str | Path) -> "LinkVaultConfig":
        """Load and validate configuration from a YAML file.

        Falls back to default settings if file is empty or missing.
        """
        yaml_path = Path(path)
        if not yaml_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {yaml_path}")

        with open(yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        return cls(**data)

    def to_yaml(self, path: str | Path) -> None:
        """Serialize configuration to a target YAML file."""
        target_path = Path(path)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        dumped = self.model_dump(mode="json")
        with open(target_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(dumped, f, sort_keys=False)
