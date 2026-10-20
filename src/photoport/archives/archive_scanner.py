"""Archive scanning — enumerate media in Takeout ZIP files without full extraction."""

from __future__ import annotations

import logging
import os
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from photoport.config import PHOTO_MAX_SIZE, VIDEO_MAX_SIZE
from photoport.utils.file_types import is_json_sidecar, is_photo, is_supported, is_video

logger = logging.getLogger("photoport.archives.scanner")


@dataclass
class ArchiveEntry:
    """A single entry discovered inside an archive or extracted folder."""

    archive_path: str
    member_path: str
    file_name: str
    file_size: int
    is_media: bool
    is_sidecar: bool
    is_directory: bool
    crc32: int | None = None
    is_extracted_file: bool = False


@dataclass
class ArchiveScanResult:
    """Results of scanning one or more archives or extracted folders."""

    archives: list[str] = field(default_factory=list)
    extracted_folders: list[str] = field(default_factory=list)
    total_archive_size: int = 0
    media_entries: list[ArchiveEntry] = field(default_factory=list)
    sidecar_entries: list[ArchiveEntry] = field(default_factory=list)
    unsupported_entries: list[ArchiveEntry] = field(default_factory=list)
    oversized_entries: list[ArchiveEntry] = field(default_factory=list)
    duplicate_media_entries: list[ArchiveEntry] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    total_media_bytes: int = 0
    deduplicated_media_bytes: int = 0
    duplicate_media_bytes: int = 0
    oversized_media_bytes: int = 0
    eligible_media_bytes: int = 0
    scanning_limitations: list[str] = field(default_factory=list)

    @property
    def total_media_count(self) -> int:
        return len(self.media_entries)

    @property
    def eligible_media_count(self) -> int:
        return len(self.media_entries) - len(self.duplicate_media_entries) - len(self.oversized_entries)

    @property
    def total_sidecar_count(self) -> int:
        return len(self.sidecar_entries)

    @property
    def total_unsupported_count(self) -> int:
        return len(self.unsupported_entries)

    @property
    def total_duplicate_count(self) -> int:
        return len(self.duplicate_media_entries)

    @property
    def total_oversized_count(self) -> int:
        return len(self.oversized_entries)

    def calculate_metrics(self) -> None:
        """Calculate deduplicated and eligible media metrics and report limitations."""
        seen_items: dict[tuple, ArchiveEntry] = {}
        unique_media: list[ArchiveEntry] = []
        self.duplicate_media_entries = []
        self.oversized_entries = []
        self.duplicate_media_bytes = 0
        self.oversized_media_bytes = 0

        for entry in self.media_entries:
            # Check Google Photos file size limits
            if is_photo(entry.file_name) and entry.file_size > PHOTO_MAX_SIZE:
                self.oversized_entries.append(entry)
                self.oversized_media_bytes += entry.file_size
                continue
            if is_video(entry.file_name) and entry.file_size > VIDEO_MAX_SIZE:
                self.oversized_entries.append(entry)
                self.oversized_media_bytes += entry.file_size
                continue

            # Identify duplicate entries across folders or archives (e.g. year folder vs album folder)
            # Use CRC32 if available (ZIPs), or (filename, size) for extracted files
            dedup_key = (
                entry.file_name.lower(),
                entry.file_size,
                entry.crc32 if entry.crc32 is not None else 0,
            )

            if dedup_key in seen_items:
                self.duplicate_media_entries.append(entry)
                self.duplicate_media_bytes += entry.file_size
            else:
                seen_items[dedup_key] = entry
                unique_media.append(entry)

        self.deduplicated_media_bytes = sum(e.file_size for e in unique_media)
        self.eligible_media_bytes = self.deduplicated_media_bytes

        # Document scanning limitations
        self.scanning_limitations = [
            "ZIP archives are inspected via central directory headers without full decompression to preserve local disk space.",
            "Duplicate detection at scan time identifies identical filename, size, and CRC32 entries (common across Takeout year and album folders).",
            "JSON sidecar metadata files are parsed for timestamps and geo-coordinates but excluded from Google Photos upload bytes.",
            "Calculations assume 100% original quality storage consumption per Google Photos API specification.",
            "EXIF metadata injection on temporary upload copies may add a negligible overhead (+2 to 10 KB per image).",
        ]


class ArchiveScanner:
    """Scan Takeout ZIP archives and extracted folders to enumerate contents.

    Never extracts archives solely to calculate sizes. Reads only ZIP central
    directories and recursively scans extracted directories.
    """

    def scan_archives(self, paths: list[str | Path]) -> ArchiveScanResult:
        """Scan one or more ZIP archives or extracted folders and return a combined result."""
        result = ArchiveScanResult()

        for raw_path in paths:
            path = str(raw_path)
            try:
                if os.path.isdir(path):
                    self._scan_directory(path, result)
                elif os.path.isfile(path):
                    self._scan_single_zip(path, result)
                else:
                    error_msg = f"Path not found: {path}"
                    logger.error(error_msg)
                    result.errors.append(error_msg)
            except Exception as exc:
                error_msg = f"Error scanning {path}: {exc}"
                logger.error(error_msg)
                result.errors.append(error_msg)

        result.calculate_metrics()

        logger.info(
            "Scan complete: %d archives, %d extracted folders, %d media files (%d eligible, %d duplicates, %d oversized), %d sidecars",
            len(result.archives),
            len(result.extracted_folders),
            result.total_media_count,
            result.eligible_media_count,
            result.total_duplicate_count,
            result.total_oversized_count,
            result.total_sidecar_count,
        )
        return result

    def _scan_directory(self, folder_path: str, result: ArchiveScanResult) -> None:
        """Recursively scan an extracted Takeout folder or folder containing ZIPs."""
        # Check if the directory solely contains ZIP archives
        direct_zips = [
            os.path.join(folder_path, f)
            for f in os.listdir(folder_path)
            if f.lower().endswith(".zip") and os.path.isfile(os.path.join(folder_path, f))
        ]

        # If it's a directory containing ZIP files and no loose media, scan the ZIPs directly
        direct_files = [
            f for f in os.listdir(folder_path)
            if os.path.isfile(os.path.join(folder_path, f)) and not f.startswith(".")
        ]
        if direct_zips and len(direct_zips) == len(direct_files):
            for zip_p in direct_zips:
                self._scan_single_zip(zip_p, result)
            return

        result.extracted_folders.append(folder_path)

        for root, _dirs, files in os.walk(folder_path):
            for file_name in files:
                if file_name.startswith("."):
                    continue

                full_path = os.path.join(root, file_name)
                try:
                    rel_path = os.path.relpath(full_path, folder_path).replace("\\", "/")
                except ValueError:
                    rel_path = file_name

                if self._is_unsafe_path(rel_path):
                    result.errors.append(f"Unsafe path rejected in {folder_path}: {rel_path}")
                    continue

                try:
                    file_size = os.path.getsize(full_path)
                except OSError as exc:
                    result.errors.append(f"Could not read size for {full_path}: {exc}")
                    continue

                result.total_archive_size += file_size

                entry = ArchiveEntry(
                    archive_path=folder_path,
                    member_path=rel_path,
                    file_name=file_name,
                    file_size=file_size,
                    is_media=is_supported(file_name),
                    is_sidecar=is_json_sidecar(file_name),
                    is_directory=False,
                    crc32=None,
                    is_extracted_file=True,
                )

                if entry.is_media:
                    result.media_entries.append(entry)
                    result.total_media_bytes += file_size
                elif entry.is_sidecar:
                    result.sidecar_entries.append(entry)
                else:
                    result.unsupported_entries.append(entry)

    def _scan_single_zip(self, archive_path: str, result: ArchiveScanResult) -> None:
        """Scan a single ZIP archive reading only its central directory."""
        if not os.path.isfile(archive_path):
            result.errors.append(f"File not found: {archive_path}")
            return

        archive_size = os.path.getsize(archive_path)
        result.archives.append(archive_path)
        result.total_archive_size += archive_size

        try:
            with zipfile.ZipFile(archive_path, "r") as zf:
                for info in zf.infolist():
                    if info.flag_bits & 0x1:  # encrypted
                        result.errors.append(
                            f"Encrypted entry in {archive_path}: {info.filename}. "
                            "PhotoPort cannot process encrypted archives. "
                            "Please re-export from Google Takeout without encryption."
                        )
                        continue

                    if info.is_dir():
                        continue

                    if self._is_unsafe_path(info.filename):
                        result.errors.append(
                            f"Unsafe path rejected in {archive_path}: {info.filename}"
                        )
                        continue

                    file_name = PurePosixPath(info.filename).name

                    entry = ArchiveEntry(
                        archive_path=archive_path,
                        member_path=info.filename,
                        file_name=file_name,
                        file_size=info.file_size,
                        is_media=is_supported(file_name),
                        is_sidecar=is_json_sidecar(file_name),
                        is_directory=False,
                        crc32=info.CRC,
                        is_extracted_file=False,
                    )

                    if entry.is_media:
                        result.media_entries.append(entry)
                        result.total_media_bytes += info.file_size
                    elif entry.is_sidecar:
                        result.sidecar_entries.append(entry)
                    else:
                        result.unsupported_entries.append(entry)

        except zipfile.BadZipFile:
            result.errors.append(f"Corrupt or invalid ZIP file: {archive_path}")
        except Exception as exc:
            result.errors.append(f"Unexpected error reading {archive_path}: {exc}")

    @staticmethod
    def _is_unsafe_path(member_path: str) -> bool:
        """Check if a member path attempts directory traversal."""
        if member_path.startswith("/") or member_path.startswith("\\"):
            return True
        parts = PurePosixPath(member_path).parts
        if ".." in parts:
            return True
        return bool(len(parts) > 0 and len(parts[0]) >= 2 and parts[0][1] == ":")
