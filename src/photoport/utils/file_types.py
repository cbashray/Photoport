"""File type classification and MIME type mapping."""

from __future__ import annotations

from pathlib import Path

from photoport.config import (
    PHOTO_MAX_SIZE,
    SUPPORTED_EXTENSIONS,
    SUPPORTED_PHOTO_EXTENSIONS,
    SUPPORTED_VIDEO_EXTENSIONS,
    VIDEO_MAX_SIZE,
)

# MIME type mapping for upload headers
MIME_TYPES: dict[str, str] = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".heic": "image/heic",
    ".heif": "image/heif",
    ".webp": "image/webp",
    ".tiff": "image/tiff",
    ".tif": "image/tiff",
    ".avif": "image/avif",
    ".ico": "image/x-icon",
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".m4v": "video/x-m4v",
    ".avi": "video/x-msvideo",
    ".mkv": "video/x-matroska",
    ".mpg": "video/mpeg",
    ".mpeg": "video/mpeg",
    ".3gp": "video/3gpp",
    ".3g2": "video/3gpp2",
    ".asf": "video/x-ms-asf",
    ".divx": "video/x-divx",
    ".m2t": "video/mp2t",
    ".m2ts": "video/mp2t",
    ".mmv": "video/x-mmv",
    ".mod": "video/x-mod",
    ".mts": "video/mp2t",
    ".tod": "video/mp2t",
    ".wmv": "video/x-ms-wmv",
}


def is_supported(filename: str) -> bool:
    """Return True if the file extension is a supported media type."""
    return Path(filename).suffix.lower() in SUPPORTED_EXTENSIONS


def is_photo(filename: str) -> bool:
    """Return True if the file is a supported photo type."""
    return Path(filename).suffix.lower() in SUPPORTED_PHOTO_EXTENSIONS


def is_video(filename: str) -> bool:
    """Return True if the file is a supported video type."""
    return Path(filename).suffix.lower() in SUPPORTED_VIDEO_EXTENSIONS


def is_json_sidecar(filename: str) -> bool:
    """Return True if the file looks like a Takeout JSON sidecar."""
    return filename.lower().endswith(".json")


is_media_file = is_supported
is_sidecar_file = is_json_sidecar


def classify_file(filename: str) -> tuple[str, str]:
    """Return a tuple of (media_type, mime_type) for the given file."""
    mime = get_mime_type(filename)
    if is_photo(filename):
        return "PHOTO", mime
    if is_video(filename):
        return "VIDEO", mime
    return "UNKNOWN", mime


def get_mime_type(filename: str) -> str:
    """Return MIME type for the given file, defaulting to application/octet-stream."""
    ext = Path(filename).suffix.lower()
    return MIME_TYPES.get(ext, "application/octet-stream")


def get_max_file_size(filename: str) -> int:
    """Return maximum upload size in bytes for the given file type."""
    if is_video(filename):
        return VIDEO_MAX_SIZE
    return PHOTO_MAX_SIZE


def check_file_size(filename: str, size: int) -> str | None:
    """Return an error message if the file exceeds its type's maximum size, else None."""
    max_size = get_max_file_size(filename)
    if size > max_size:
        from photoport.utils.disk_space import format_bytes
        return (
            f"File '{filename}' ({format_bytes(size)}) exceeds maximum "
            f"upload size ({format_bytes(max_size)}) for this type."
        )
    return None
