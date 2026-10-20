"""Safe extraction of individual files from ZIP archives."""

from __future__ import annotations

import contextlib
import hashlib
import logging
import os
import shutil
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

from photoport.config import HASH_CHUNK_SIZE

logger = logging.getLogger("photoport.archives.safe_extract")


class SafeExtractor:
    """Extract individual members from ZIP archives safely.

    - Validates paths to prevent directory traversal.
    - Extracts to a configured temporary directory.
    - Supports incremental SHA-256 computation during extraction.
    - Cleans up temporary files when requested.
    """

    def __init__(self, temp_dir: Path) -> None:
        self.temp_dir = temp_dir
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    def extract_member(
        self,
        archive_path: str,
        member_path: str,
        compute_hash: bool = True,
    ) -> tuple[Path, str]:
        """Extract a single ZIP member to a temporary file.

        Returns:
            Tuple of (extracted_file_path, sha256_hex_digest).
            If compute_hash is False, sha256 will be an empty string.

        Raises:
            ValueError: If the member path is unsafe.
            FileNotFoundError: If the archive or member doesn't exist.
            zipfile.BadZipFile: If the archive is corrupt.
        """
        # Validate the member path
        if self._is_unsafe_path(member_path):
            raise ValueError(f"Unsafe member path rejected: {member_path}")

        file_name = PurePosixPath(member_path).name
        if not file_name:
            raise ValueError(f"Empty file name in member path: {member_path}")

        # Create a unique temp subdirectory to avoid name collisions
        extract_dir = Path(tempfile.mkdtemp(dir=str(self.temp_dir), prefix="pp_"))
        dest_path = extract_dir / file_name
        sha256_hex = ""

        try:
            if os.path.isdir(archive_path):
                source_file = Path(archive_path) / member_path
                if not source_file.exists():
                    raise FileNotFoundError(f"File '{member_path}' not found in folder {archive_path}")

                file_size = source_file.stat().st_size
                with open(source_file, "rb") as src, open(dest_path, "wb") as dst:
                    hasher = hashlib.sha256() if compute_hash else None
                    while True:
                        chunk = src.read(HASH_CHUNK_SIZE)
                        if not chunk:
                            break
                        dst.write(chunk)
                        if hasher:
                            hasher.update(chunk)
                    if hasher:
                        sha256_hex = hasher.hexdigest()

                logger.debug(
                    "Copied extracted file %s -> %s (%d bytes, hash=%s)",
                    member_path, dest_path, file_size,
                    sha256_hex[:16] + "..." if sha256_hex else "skipped",
                )
                return dest_path, sha256_hex

            with zipfile.ZipFile(archive_path, "r") as zf:
                # Verify the member exists
                try:
                    info = zf.getinfo(member_path)
                except KeyError:
                    raise FileNotFoundError(
                        f"Member '{member_path}' not found in {archive_path}"
                    ) from None

                # Extract to temp directory using streaming to avoid loading into RAM
                with zf.open(info) as src, open(dest_path, "wb") as dst:
                    hasher = hashlib.sha256() if compute_hash else None
                    while True:
                        chunk = src.read(HASH_CHUNK_SIZE)
                        if not chunk:
                            break
                        dst.write(chunk)
                        if hasher:
                            hasher.update(chunk)

                    if hasher:
                        sha256_hex = hasher.hexdigest()

                logger.debug(
                    "Extracted %s -> %s (%d bytes, hash=%s)",
                    member_path, dest_path, info.file_size,
                    sha256_hex[:16] + "..." if sha256_hex else "skipped",
                )
                return dest_path, sha256_hex

        except Exception:
            # Clean up on failure
            if extract_dir.exists():
                shutil.rmtree(str(extract_dir), ignore_errors=True)
            raise

    def cleanup_file(self, path: Path) -> None:
        """Remove an extracted temporary file and its parent temp directory if empty."""
        try:
            if path.exists():
                path.unlink()
            parent = path.parent
            if parent.exists() and parent != self.temp_dir:
                # Remove the temp subdirectory if empty
                with contextlib.suppress(OSError):
                    parent.rmdir()
        except Exception as exc:
            logger.warning("Failed to clean up temp file %s: %s", path, exc)

    def cleanup_all(self) -> None:
        """Remove all temporary extraction files."""
        try:
            if self.temp_dir.exists():
                for item in self.temp_dir.iterdir():
                    if item.is_dir():
                        shutil.rmtree(str(item), ignore_errors=True)
                    else:
                        item.unlink(missing_ok=True)
                logger.info("Cleaned up temp directory: %s", self.temp_dir)
        except Exception as exc:
            logger.warning("Failed to clean up temp dir %s: %s", self.temp_dir, exc)

    def get_temp_usage(self) -> int:
        """Return total bytes used in the temp directory."""
        total = 0
        try:
            for root, _dirs, files in os.walk(str(self.temp_dir)):
                for f in files:
                    total += os.path.getsize(os.path.join(root, f))
        except Exception:
            pass
        return total

    @staticmethod
    def _is_unsafe_path(member_path: str) -> bool:
        """Check for directory traversal in ZIP member paths."""
        if member_path.startswith("/") or member_path.startswith("\\"):
            return True
        parts = PurePosixPath(member_path).parts
        if ".." in parts:
            return True
        return bool(len(parts) > 0 and len(parts[0]) >= 2 and parts[0][1] == ":")
