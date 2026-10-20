"""Application-wide configuration and constants."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

# ---------------------------------------------------------------------------
# Application identity
# ---------------------------------------------------------------------------
APP_NAME: Final[str] = "PhotoPort"
APP_VERSION: Final[str] = "1.0.0"
APP_ORG: Final[str] = "PhotoPort"

# ---------------------------------------------------------------------------
# Platform-specific data directories
# ---------------------------------------------------------------------------

def _default_data_dir() -> Path:
    """Return per-user application data directory."""
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / APP_NAME


def _default_temp_dir() -> Path:
    """Return default temporary directory for extracted files."""
    override = os.environ.get("PHOTOPORT_TEMP_DIR")
    if override:
        return Path(override)
    return _default_data_dir() / "temp"


def _default_log_dir() -> Path:
    return _default_data_dir() / "logs"


# ---------------------------------------------------------------------------
# Google API constants
# ---------------------------------------------------------------------------
GOOGLE_PHOTOS_UPLOAD_URL: Final[str] = "https://photoslibrary.googleapis.com/v1/uploads"
GOOGLE_PHOTOS_BATCH_CREATE_URL: Final[str] = (
    "https://photoslibrary.googleapis.com/v1/mediaItems:batchCreate"
)
GOOGLE_PHOTOS_ALBUMS_URL: Final[str] = "https://photoslibrary.googleapis.com/v1/albums"
GOOGLE_PHOTOS_MEDIA_ITEMS_URL: Final[str] = "https://photoslibrary.googleapis.com/v1/mediaItems"
GOOGLE_DRIVE_ABOUT_URL: Final[str] = "https://www.googleapis.com/drive/v3/about"

OAUTH_SCOPES: Final[list[str]] = [
    "https://www.googleapis.com/auth/photoslibrary.appendonly",
    "https://www.googleapis.com/auth/photoslibrary.readonly.appcreateddata",
    "https://www.googleapis.com/auth/drive.readonly",
]

# ---------------------------------------------------------------------------
# Supported file types
# ---------------------------------------------------------------------------
SUPPORTED_PHOTO_EXTENSIONS: Final[frozenset[str]] = frozenset({
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".heic", ".heif",
    ".webp", ".tiff", ".tif", ".avif", ".ico",
})

SUPPORTED_VIDEO_EXTENSIONS: Final[frozenset[str]] = frozenset({
    ".mp4", ".mov", ".m4v", ".avi", ".mkv", ".mpg", ".mpeg",
    ".3gp", ".3g2", ".asf", ".divx", ".m2t", ".m2ts", ".mmv",
    ".mod", ".mts", ".tod", ".wmv",
})

SUPPORTED_EXTENSIONS: Final[frozenset[str]] = SUPPORTED_PHOTO_EXTENSIONS | SUPPORTED_VIDEO_EXTENSIONS

PHOTO_MAX_SIZE: Final[int] = 200 * 1024 * 1024  # 200 MB
VIDEO_MAX_SIZE: Final[int] = 20 * 1024 * 1024 * 1024  # 20 GB

# ---------------------------------------------------------------------------
# Upload / retry defaults
# ---------------------------------------------------------------------------
MAX_BATCH_CREATE_ITEMS: Final[int] = 50
DEFAULT_MAX_RETRIES: Final[int] = 5
DEFAULT_MAX_CONCURRENT: Final[int] = 1
DEFAULT_RETRY_BASE_DELAY: Final[float] = 2.0
DEFAULT_RETRY_MAX_DELAY: Final[float] = 300.0
DAILY_API_REQUEST_QUOTA: Final[int] = 10_000
UPLOAD_BUFFER_SIZE: Final[int] = 8 * 1024 * 1024  # 8 MB streaming buffer

# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------
HASH_CHUNK_SIZE: Final[int] = 1024 * 1024  # 1 MB chunks for incremental SHA-256

# ---------------------------------------------------------------------------
# Configuration dataclass
# ---------------------------------------------------------------------------

@dataclass
class AppConfig:
    """Runtime configuration for the application."""

    credentials_path: Path = field(
        default_factory=lambda: Path(os.environ.get("GOOGLE_CREDENTIALS_PATH", "credentials.json"))
    )
    data_dir: Path = field(default_factory=_default_data_dir)
    temp_dir: Path = field(default_factory=_default_temp_dir)
    log_dir: Path = field(default_factory=_default_log_dir)
    log_level: str = field(
        default_factory=lambda: os.environ.get("PHOTOPORT_LOG_LEVEL", "INFO")
    )
    max_concurrent: int = field(
        default_factory=lambda: int(os.environ.get("PHOTOPORT_MAX_CONCURRENT", "1"))
    )
    max_retries: int = field(
        default_factory=lambda: int(os.environ.get("PHOTOPORT_MAX_RETRIES", "5"))
    )
    recreate_albums: bool = True
    delete_temp_after_verify: bool = True
    enable_duplicate_detection: bool = True
    enable_exif_injection: bool = False  # opt-in: inject dates from sidecar JSON
    storage_safety_margin_percent: float = 5.0  # 5% safety margin for live quota variance
    storage_safety_margin_min_bytes: int = 500 * 1024 * 1024  # 500 MB minimum buffer
    storage_recheck_interval_items: int = 50  # recheck quota during migration every 50 uploads

    @property
    def db_path(self) -> Path:
        return self.data_dir / "photoport.db"

    @property
    def token_path(self) -> Path:
        return self.data_dir / "token.json"

    def ensure_dirs(self) -> None:
        """Create required directories if they don't exist."""
        for d in (self.data_dir, self.temp_dir, self.log_dir):
            d.mkdir(parents=True, exist_ok=True)


def get_config() -> AppConfig:
    """Return the global application configuration."""
    cfg = AppConfig()
    cfg.ensure_dirs()
    return cfg
