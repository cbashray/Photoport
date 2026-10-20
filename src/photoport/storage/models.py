"""Data models for the migration ledger."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime


class MediaItemStatus(enum.Enum):
    """Lifecycle states for a media item in the migration pipeline."""

    DISCOVERED = "DISCOVERED"
    VALIDATED = "VALIDATED"
    READY = "READY"
    UPLOADING = "UPLOADING"
    UPLOADED = "UPLOADED"
    VERIFIED = "VERIFIED"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    FAILED_PERMANENT = "FAILED_PERMANENT"
    SKIPPED = "SKIPPED"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class MediaType(enum.Enum):
    """Classification of media files."""

    PHOTO = "PHOTO"
    VIDEO = "VIDEO"
    UNKNOWN = "UNKNOWN"


@dataclass
class MediaItem:
    """Represents a single media file discovered in a Takeout archive."""

    id: int | None = None
    archive_path: str = ""           # Path to the source ZIP file
    zip_member_path: str = ""        # Path within the ZIP
    file_name: str = ""              # Original file name
    file_size: int = 0               # Size in bytes
    media_type: MediaType = MediaType.UNKNOWN
    sha256_hash: str = ""            # SHA-256 of the source file
    mime_type: str = ""
    status: MediaItemStatus = MediaItemStatus.DISCOVERED
    upload_token: str = ""           # Google upload token (transient)
    google_media_id: str = ""        # Google Photos media item ID
    album_name: str = ""             # Album association from Takeout
    description: str = ""            # From sidecar JSON
    capture_timestamp: str = ""      # ISO timestamp from sidecar JSON
    error_message: str = ""
    retry_count: int = 0
    last_attempt: str = ""           # ISO timestamp
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    # Sidecar metadata fields
    sidecar_path: str = ""           # Path to the JSON sidecar within the ZIP
    latitude: float | None = None
    longitude: float | None = None
    exif_injected: bool = False      # True if we injected EXIF from sidecar


@dataclass
class AlbumRecord:
    """Represents an album to be recreated."""

    id: int | None = None
    source_name: str = ""            # Album name from Takeout
    google_album_id: str = ""        # ID of the created Google Photos album
    item_count: int = 0
    items_added: int = 0
    status: str = "PENDING"          # PENDING, CREATED, POPULATED, FAILED
    error_message: str = ""
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())


@dataclass
class MigrationSession:
    """Represents a migration job session."""

    id: int | None = None
    started_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    completed_at: str = ""
    total_archives: int = 0
    total_files_discovered: int = 0
    total_photos: int = 0
    total_videos: int = 0
    total_uploaded: int = 0
    total_verified: int = 0
    total_failed: int = 0
    total_skipped: int = 0
    total_needs_review: int = 0
    status: str = "IN_PROGRESS"      # IN_PROGRESS, COMPLETED, PAUSED, CANCELLED, FAILED
    destination_account: str = ""
