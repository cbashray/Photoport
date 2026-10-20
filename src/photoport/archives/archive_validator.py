"""Archive validation — integrity checks and pre-flight validation."""

from __future__ import annotations

import logging
import os
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("photoport.archives.validator")


@dataclass
class ValidationResult:
    """Result of archive validation."""

    archive_path: str = ""
    is_valid: bool = True
    is_zip: bool = True
    is_encrypted: bool = False
    has_unsupported_compression: bool = False
    file_size: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class ArchiveValidator:
    """Validate Takeout ZIP archives before processing."""

    def validate(self, archive_path: str | Path) -> ValidationResult:
        """Validate a single archive and return detailed results."""
        path = str(archive_path)
        result = ValidationResult(archive_path=path)

        # Check path exists
        if os.path.isdir(path):
            result.is_zip = False
            total_size = 0
            try:
                for root, _dirs, files in os.walk(path):
                    for f in files:
                        total_size += os.path.getsize(os.path.join(root, f))
                result.file_size = total_size
                result.is_valid = True
                return result
            except Exception as exc:
                result.is_valid = False
                result.errors.append(f"Cannot read directory {path}: {exc}")
                return result

        if not os.path.isfile(path):
            result.is_valid = False
            result.errors.append(f"File not found: {path}")
            return result

        result.file_size = os.path.getsize(path)

        # Check it's a valid ZIP
        if not zipfile.is_zipfile(path):
            result.is_valid = False
            result.is_zip = False
            result.errors.append(f"Not a valid ZIP file: {path}")
            return result

        try:
            with zipfile.ZipFile(path, "r") as zf:
                # Test archive integrity
                bad_file = zf.testzip()
                if bad_file is not None:
                    result.is_valid = False
                    result.errors.append(
                        f"Corrupt entry in archive: {bad_file}"
                    )

                for info in zf.infolist():
                    # Check for encryption
                    if info.flag_bits & 0x1:
                        result.is_encrypted = True
                        result.is_valid = False
                        result.errors.append(
                            f"Encrypted entry: {info.filename}. "
                            "Re-export from Google Takeout without password protection."
                        )

                    # Check for unsupported compression
                    if info.compress_type not in (
                        zipfile.ZIP_STORED,
                        zipfile.ZIP_DEFLATED,
                        zipfile.ZIP_BZIP2,
                        zipfile.ZIP_LZMA,
                    ):
                        result.has_unsupported_compression = True
                        result.warnings.append(
                            f"Unsupported compression method {info.compress_type} "
                            f"for {info.filename}"
                        )

        except zipfile.BadZipFile as exc:
            result.is_valid = False
            result.errors.append(f"Bad ZIP file: {exc}")
        except Exception as exc:
            result.is_valid = False
            result.errors.append(f"Validation error: {exc}")

        if result.is_valid:
            logger.info("Archive validated OK: %s (%d bytes)", path, result.file_size)
        else:
            logger.warning("Archive validation failed: %s — %s", path, result.errors)

        return result

    def validate_batch(self, paths: list[str | Path]) -> list[ValidationResult]:
        """Validate multiple archives."""
        return [self.validate(p) for p in paths]

    def check_duplicates(self, paths: list[str | Path]) -> list[str]:
        """Check for duplicate archive paths (by resolved path)."""
        seen: dict[str, str] = {}
        duplicates: list[str] = []
        for p in paths:
            resolved = str(Path(p).resolve())
            if resolved in seen:
                duplicates.append(f"Duplicate archive: {p} is the same as {seen[resolved]}")
            else:
                seen[resolved] = str(p)
        return duplicates
