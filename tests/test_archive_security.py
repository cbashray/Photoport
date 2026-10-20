"""Tests for archive security — path traversal, encryption, etc."""

from __future__ import annotations

import os
import zipfile
from pathlib import Path

import pytest

from photoport.archives.archive_scanner import ArchiveScanner
from photoport.archives.archive_validator import ArchiveValidator
from photoport.archives.safe_extract import SafeExtractor


@pytest.fixture
def scanner():
    return ArchiveScanner()


@pytest.fixture
def validator():
    return ArchiveValidator()


class TestPathTraversal:
    """Tests for ZIP path traversal prevention."""

    def test_rejects_dotdot_path(self, scanner: ArchiveScanner, tmp_path: Path):
        """Ensure entries with '..' in path are rejected."""
        zip_path = tmp_path / "traversal.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("../../../etc/passwd", "malicious content")
            zf.writestr("safe/photo.jpg", b"\xff" * 50)

        result = scanner.scan_archives([str(zip_path)])
        assert len(result.errors) > 0
        # Safe file should still be found
        assert result.total_media_count == 1

    def test_rejects_absolute_path(self, scanner: ArchiveScanner, tmp_path: Path):
        """Ensure absolute paths are rejected."""
        zip_path = tmp_path / "absolute.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("/etc/shadow", "malicious")
            zf.writestr("photo.jpg", b"\xff" * 50)

        result = scanner.scan_archives([str(zip_path)])
        assert len(result.errors) > 0

    def test_safe_extractor_rejects_traversal(self, tmp_path: Path):
        """Test SafeExtractor also rejects dangerous paths."""
        extractor = SafeExtractor(tmp_path / "temp")

        with pytest.raises(ValueError, match="Unsafe"):
            extractor.extract_member("/dummy.zip", "../../../etc/passwd")


class TestEncryptedArchives:
    """Tests for encrypted ZIP handling."""

    def test_validation_detects_corrupt(self, validator: ArchiveValidator, tmp_path: Path):
        """Test that a corrupt archive is flagged."""
        bad_path = tmp_path / "bad.zip"
        bad_path.write_bytes(b"not a zip")

        result = validator.validate(bad_path)
        assert result.is_valid is False
        assert result.is_zip is False


class TestArchiveValidation:
    """Tests for the archive validator."""

    def test_valid_archive(self, validator: ArchiveValidator, tmp_path: Path):
        zip_path = tmp_path / "valid.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("photo.jpg", b"\xff" * 50)

        result = validator.validate(zip_path)
        assert result.is_valid is True
        assert result.file_size > 0

    def test_nonexistent_file(self, validator: ArchiveValidator):
        result = validator.validate("/nonexistent/file.zip")
        assert result.is_valid is False

    def test_duplicate_detection(self, validator: ArchiveValidator, tmp_path: Path):
        zip_path = tmp_path / "archive.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("photo.jpg", b"\xff" * 50)

        dups = validator.check_duplicates([str(zip_path), str(zip_path)])
        assert len(dups) > 0

    def test_no_duplicates(self, validator: ArchiveValidator, tmp_path: Path):
        zip1 = tmp_path / "a.zip"
        zip2 = tmp_path / "b.zip"
        with zipfile.ZipFile(zip1, "w") as zf:
            zf.writestr("1.jpg", b"\xff")
        with zipfile.ZipFile(zip2, "w") as zf:
            zf.writestr("2.jpg", b"\xff")

        dups = validator.check_duplicates([str(zip1), str(zip2)])
        assert len(dups) == 0


class TestSafeExtraction:
    """Tests for safe file extraction."""

    def test_extract_member(self, tmp_path: Path):
        """Test extracting a single member from a ZIP."""
        zip_path = tmp_path / "test.zip"
        content = b"\xff\xd8\xff" + b"\x00" * 1000

        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("album/photo.jpg", content)

        extractor = SafeExtractor(tmp_path / "temp")
        file_path, sha256_hash = extractor.extract_member(
            str(zip_path), "album/photo.jpg"
        )

        assert file_path.exists()
        assert file_path.read_bytes() == content
        assert len(sha256_hash) == 64  # SHA-256 hex digest length

    def test_extract_preserves_bytes(self, tmp_path: Path):
        """Verify that extraction does not alter file bytes."""
        import hashlib

        zip_path = tmp_path / "integrity.zip"
        content = os.urandom(10000)  # Random bytes
        expected_hash = hashlib.sha256(content).hexdigest()

        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("data.bin", content)

        extractor = SafeExtractor(tmp_path / "temp")
        file_path, computed_hash = extractor.extract_member(
            str(zip_path), "data.bin"
        )

        assert file_path.read_bytes() == content
        assert computed_hash == expected_hash

    def test_extract_nonexistent_member(self, tmp_path: Path):
        """Test extracting a member that doesn't exist raises an error."""
        zip_path = tmp_path / "test.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("exists.jpg", b"\xff")

        extractor = SafeExtractor(tmp_path / "temp")
        with pytest.raises(FileNotFoundError):
            extractor.extract_member(str(zip_path), "doesnotexist.jpg")

    def test_cleanup(self, tmp_path: Path):
        """Test temp file cleanup."""
        zip_path = tmp_path / "test.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("photo.jpg", b"\xff" * 50)

        extractor = SafeExtractor(tmp_path / "temp")
        file_path, _ = extractor.extract_member(str(zip_path), "photo.jpg")
        assert file_path.exists()

        extractor.cleanup_file(file_path)
        assert not file_path.exists()
