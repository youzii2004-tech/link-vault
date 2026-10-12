"""Link Vault Multimodal Video Intelligence Pipeline.

Orchestrates deep audio stream verification via ffprobe, uniform keyframe
extraction via ffmpeg, timestamped speech-to-text transcription via faster-whisper,
and comprehensive structured JSON metadata export.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import shutil
import subprocess
from typing import Any, Dict, List, Optional, Tuple

from .config import AnalysisConfig, LinkVaultConfig

logger = logging.getLogger("linkvault.analyzer")


@dataclass
class KeyframeRecord:
    """Metadata for an extracted video keyframe."""

    index: int
    timestamp_seconds: float
    image_path: str
    width: int
    height: int


@dataclass
class TranscriptSegment:
    """Timestamped speech transcript segment."""

    start: float
    end: float
    text: str


@dataclass
class VideoAnalysisResult:
    """Comprehensive multimodal video intelligence output."""

    file_path: str
    file_name: str
    duration_seconds: float
    width: int
    height: int
    resolution: str
    aspect_ratio: str
    video_codec: str
    audio_codec: Optional[str]
    has_audio: bool
    framerate: float
    bitrate_kbps: int
    keyframes: List[Dict[str, Any]] = field(default_factory=list)
    transcript: List[Dict[str, Any]] = field(default_factory=list)
    full_transcript: str = ""
    summary_notes: str = ""
    analysis_timestamp: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Convert analysis result to dictionary."""
        return asdict(self)


class VideoAnalyzer:
    """Multimodal intelligence engine analyzing video files."""

    def __init__(
        self,
        config: Optional[LinkVaultConfig] = None,
        output_dir: Optional[Path] = None,
    ):
        self.config = config or LinkVaultConfig()
        self.analysis_config: AnalysisConfig = self.config.analysis
        self.output_dir = Path(output_dir or self.analysis_config.output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.keyframes_dir = self.output_dir / "keyframes"
        self.keyframes_dir.mkdir(parents=True, exist_ok=True)

        self.ffprobe_bin = shutil.which("ffprobe")
        self.ffmpeg_bin = shutil.which("ffmpeg")

    def probe_media(self, video_path: Path) -> Dict[str, Any]:
        """Extract deep stream and container metadata using ffprobe."""
        if not self.ffprobe_bin:
            logger.warning("ffprobe binary not found on system PATH")
            return {}

        cmd = [
            self.ffprobe_bin,
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(video_path),
        ]

        try:
            res = subprocess.run(cmd, capture_output=True, text=True, check=True)
            return json.loads(res.stdout)
        except Exception as e:
            logger.error("Failed to probe %s with ffprobe: %s", video_path, e)
            return {}

    @staticmethod
    def calculate_aspect_ratio(width: int, height: int) -> str:
        """Compute standard aspect ratio string (e.g. 16:9, 9:16, 1:1, 4:5)."""
        if width <= 0 or height <= 0:
            return "unknown"

        ratio = width / height
        if abs(ratio - 16 / 9) < 0.05:
            return "16:9"
        if abs(ratio - 9 / 16) < 0.05:
            return "9:16"
        if abs(ratio - 1.0) < 0.05:
            return "1:1"
        if abs(ratio - 4 / 5) < 0.05:
            return "4:5"
        if abs(ratio - 4 / 3) < 0.05:
            return "4:3"

        return f"{width}:{height}"

    def extract_uniform_keyframes(
        self,
        video_path: Path,
        duration: float,
        width: int,
        height: int,
        count: Optional[int] = None,
    ) -> List[KeyframeRecord]:
        """Extract uniformly distributed keyframes across video duration using ffmpeg."""
        if not self.ffmpeg_bin or duration <= 0:
            return []

        num_frames = count or self.analysis_config.keyframes.count
        stem = video_path.stem
        records: List[KeyframeRecord] = []

        # Calculate time intervals (avoiding the exact first/last millisecond)
        step = duration / (num_frames + 1)
        timestamps = [round(step * (i + 1), 2) for i in range(num_frames)]

        for idx, ts in enumerate(timestamps):
            out_img = self.keyframes_dir / f"{stem}_kf_{idx + 1:02d}_{int(ts)}s.jpg"
            cmd = [
                self.ffmpeg_bin,
                "-y",
                "-ss",
                str(ts),
                "-i",
                str(video_path),
                "-vframes",
                "1",
                "-q:v",
                str(self.analysis_config.keyframes.quality),
                str(out_img),
            ]
            try:
                subprocess.run(cmd, capture_output=True, check=True)
                if out_img.exists() and out_img.stat().st_size > 0:
                    records.append(
                        KeyframeRecord(
                            index=idx + 1,
                            timestamp_seconds=ts,
                            image_path=str(out_img.resolve()),
                            width=width,
                            height=height,
                        )
                    )
            except Exception as e:
                logger.warning("Failed to extract keyframe at %ss: %s", ts, e)

        return records

    def transcribe_audio(
        self,
        video_path: Path,
        has_audio: bool,
    ) -> Tuple[List[TranscriptSegment], str]:
        """Transcribe audio using faster-whisper with silent video fallback."""
        if not has_audio or not self.analysis_config.transcription.enabled:
            return [], ""

        try:
            from faster_whisper import WhisperModel
        except ImportError:
            logger.info("faster-whisper is not installed. Skipping speech transcription.")
            return [], ""

        cfg = self.analysis_config.transcription
        try:
            model = WhisperModel(
                cfg.model_size,
                device=cfg.device,
                compute_type=cfg.compute_type,
            )
            segments, _ = model.transcribe(
                str(video_path),
                language=cfg.language,
                beam_size=1,
            )

            results: List[TranscriptSegment] = []
            full_texts: List[str] = []

            for seg in segments:
                text = seg.text.strip()
                if text:
                    results.append(
                        TranscriptSegment(
                            start=round(seg.start, 2),
                            end=round(seg.end, 2),
                            text=text,
                        )
                    )
                    full_texts.append(text)

            return results, " ".join(full_texts)
        except Exception as e:
            logger.warning("Transcription failed or audio was silent: %s", e)
            return [], ""

    def analyze_video(self, video_path: str | Path) -> VideoAnalysisResult:
        """Execute the full multimodal intelligence pipeline on a video file."""
        target_path = Path(video_path).resolve()
        if not target_path.exists():
            raise FileNotFoundError(f"Video file not found: {target_path}")

        probe_data = self.probe_media(target_path)
        format_info = probe_data.get("format", {})
        streams = probe_data.get("streams", [])

        # Parse duration
        duration = float(format_info.get("duration", 0.0))
        bitrate_kbps = int(float(format_info.get("bit_rate", 0)) / 1000) if format_info.get("bit_rate") else 0

        # Video stream analysis
        video_stream = next((s for s in streams if s.get("codec_type") == "video"), {})
        width = int(video_stream.get("width", 0))
        height = int(video_stream.get("height", 0))
        video_codec = video_stream.get("codec_name", "unknown")

        # Frame rate parsing
        fps = 0.0
        r_frame_rate = video_stream.get("r_frame_rate", "0/1")
        if "/" in r_frame_rate:
            num, den = r_frame_rate.split("/")
            fps = round(float(num) / float(den), 2) if float(den) > 0 else 0.0

        # Audio stream analysis
        audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)
        has_audio = audio_stream is not None
        audio_codec = audio_stream.get("codec_name") if audio_stream else None

        aspect_ratio = self.calculate_aspect_ratio(width, height)
        resolution_str = f"{width}x{height}" if width and height else "unknown"

        # 1. Keyframe extraction
        keyframes = self.extract_uniform_keyframes(target_path, duration, width, height)

        # 2. Transcription
        transcript_segs, full_text = self.transcribe_audio(target_path, has_audio)

        # 3. Assemble result
        result = VideoAnalysisResult(
            file_path=str(target_path),
            file_name=target_path.name,
            duration_seconds=duration,
            width=width,
            height=height,
            resolution=resolution_str,
            aspect_ratio=aspect_ratio,
            video_codec=video_codec,
            audio_codec=audio_codec,
            has_audio=has_audio,
            framerate=fps,
            bitrate_kbps=bitrate_kbps,
            keyframes=[asdict(kf) if hasattr(kf, "__dataclass_fields__") else kf for kf in keyframes],
            transcript=[asdict(ts) if hasattr(ts, "__dataclass_fields__") else ts for ts in transcript_segs],
            full_transcript=full_text,
            summary_notes="Analysis completed successfully" if has_audio else "Video stream without audio track",
            analysis_timestamp=datetime.now(timezone.utc).isoformat(),
        )

        # 4. Save metadata JSON
        json_output = self.output_dir / f"{target_path.stem}.analysis.json"
        with open(json_output, "w", encoding="utf-8") as f:
            json.dump(result.to_dict(), f, indent=2)

        return result
