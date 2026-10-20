"""Parse Google Takeout JSON sidecar metadata files."""

from __future__ import annotations

import json
import logging
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import PurePosixPath

logger = logging.getLogger("photoport.metadata.sidecar_parser")


@dataclass
class SidecarMetadata:
    """Parsed metadata from a Takeout JSON sidecar."""

    title: str = ""
    description: str = ""
    capture_timestamp: str = ""       # ISO 8601
    capture_epoch: int = 0            # Unix epoch seconds
    latitude: float | None = None
    longitude: float | None = None
    altitude: float | None = None
    url: str = ""
    is_favorite: bool = False
    is_archived: bool = False
    is_trashed: bool = False
    album_name: str = ""              # Inferred from directory
    raw_json: dict = field(default_factory=dict)
    parse_errors: list[str] = field(default_factory=list)


class SidecarParser:
    """Parse Takeout JSON sidecar files.

    Google Takeout exports JSON sidecars alongside media files with metadata
    including timestamps, descriptions, and geo-location. This parser handles
    common Takeout JSON formats and naming variations.
    """

    def parse_from_zip(
        self, archive_path: str, member_path: str, max_size: int = 10 * 1024 * 1024
    ) -> SidecarMetadata:
        """Parse a sidecar JSON from within a ZIP archive.

        Reads the JSON member directly from the archive without extracting
        the full archive. Limits read size to prevent abuse.
        """
        meta = SidecarMetadata()

        try:
            with zipfile.ZipFile(archive_path, "r") as zf:
                info = zf.getinfo(member_path)

                if info.file_size > max_size:
                    meta.parse_errors.append(
                        f"Sidecar too large ({info.file_size} bytes): {member_path}"
                    )
                    return meta

                with zf.open(info) as f:
                    raw_bytes = f.read(max_size)

            raw_json = json.loads(raw_bytes.decode("utf-8", errors="replace"))
            meta.raw_json = raw_json
            self._extract_fields(raw_json, meta)

            # Infer album name from directory structure
            parts = PurePosixPath(member_path).parts
            # Typical: Google Photos/AlbumName/file.json
            if len(parts) >= 2:
                # Look for the directory above the file
                parent_dir = parts[-2]
                if parent_dir.lower() != "google photos":
                    meta.album_name = parent_dir

        except json.JSONDecodeError as exc:
            meta.parse_errors.append(f"Malformed JSON in {member_path}: {exc}")
            logger.warning("Malformed JSON sidecar: %s — %s", member_path, exc)
        except KeyError:
            meta.parse_errors.append(f"Sidecar not found in archive: {member_path}")
        except Exception as exc:
            meta.parse_errors.append(f"Error parsing {member_path}: {exc}")
            logger.warning("Error parsing sidecar %s: %s", member_path, exc)

        return meta

    def parse_from_string(self, json_str: str) -> SidecarMetadata:
        """Parse sidecar metadata from a JSON string."""
        meta = SidecarMetadata()
        try:
            raw_json = json.loads(json_str)
            meta.raw_json = raw_json
            self._extract_fields(raw_json, meta)
        except json.JSONDecodeError as exc:
            meta.parse_errors.append(f"Malformed JSON: {exc}")
        return meta

    def _extract_fields(self, data: dict, meta: SidecarMetadata) -> None:
        """Extract metadata fields from parsed JSON."""

        # Title
        meta.title = str(data.get("title", ""))

        # Description
        meta.description = str(data.get("description", ""))

        # Timestamp — Google uses 'photoTakenTime' or 'creationTime'
        timestamp_data = data.get("photoTakenTime") or data.get("creationTime", {})
        if isinstance(timestamp_data, dict):
            epoch_str = timestamp_data.get("timestamp", "")
            if epoch_str:
                try:
                    epoch = int(epoch_str)
                    meta.capture_epoch = epoch
                    meta.capture_timestamp = datetime.fromtimestamp(
                        epoch, tz=UTC
                    ).isoformat()
                except (ValueError, OSError) as exc:
                    meta.parse_errors.append(f"Invalid timestamp '{epoch_str}': {exc}")

        # Geo-location
        geo_data = data.get("geoData") or data.get("geoDataExif", {})
        if isinstance(geo_data, dict):
            lat = geo_data.get("latitude")
            lon = geo_data.get("longitude")
            alt = geo_data.get("altitude")
            if lat is not None and lat != 0.0:
                meta.latitude = float(lat)
            if lon is not None and lon != 0.0:
                meta.longitude = float(lon)
            if alt is not None:
                meta.altitude = float(alt)

        # Favorite / archived / trashed
        meta.is_favorite = bool(data.get("favorited", False))
        meta.is_archived = bool(data.get("archived", False))
        meta.is_trashed = bool(data.get("trashed", False))

        # URL (photo viewer URL)
        meta.url = str(data.get("url", ""))
