"""Unit tests for Link Vault configuration engine."""

from pathlib import Path
import pytest
from pydantic import ValidationError

from src.config import LinkVaultConfig, EngineConfig, PlatformSetting, AnalysisConfig


def test_default_config_initialization():
    """Verify default configuration has valid platform maps and engine defaults."""
    cfg = LinkVaultConfig()
    assert cfg.version == "1.0"
    assert cfg.engine.max_workers == 4
    assert cfg.engine.timeout_seconds == 60
    assert "instagram" in cfg.platforms
    assert "youtube" in cfg.platforms
    assert "tiktok" in cfg.platforms
    assert cfg.platforms["instagram"].require_cookies is True
    assert cfg.platforms["youtube"].require_cookies is False
    assert cfg.analysis.keyframes.count == 5


def test_custom_engine_validation():
    """Verify bounds and validation on engine parameters."""
    with pytest.raises(ValidationError):
        # max_workers > 32 should fail validation
        EngineConfig(max_workers=100)

    with pytest.raises(ValidationError):
        # timeout < 5 should fail validation
        EngineConfig(timeout_seconds=2)


def test_yaml_serialization_roundtrip(tmp_path: Path):
    """Test exporting configuration to YAML and loading it back."""
    cfg = LinkVaultConfig()
    cfg.engine.max_workers = 8
    cfg.analysis.keyframes.count = 10

    yaml_file = tmp_path / "test_config.yaml"
    cfg.to_yaml(yaml_file)

    assert yaml_file.exists()
    loaded = LinkVaultConfig.load_from_yaml(yaml_file)

    assert loaded.engine.max_workers == 8
    assert loaded.analysis.keyframes.count == 10
    assert loaded.platforms["facebook"].require_cookies is True


def test_missing_yaml_raises_filenotfound(tmp_path: Path):
    """Verify FileNotFoundError is raised when YAML does not exist."""
    fake_path = tmp_path / "non_existent.yaml"
    with pytest.raises(FileNotFoundError):
        LinkVaultConfig.load_from_yaml(fake_path)
