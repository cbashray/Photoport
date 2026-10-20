"""Tests for archive scanning."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from photoport.archives.archive_scanner import ArchiveScanner


@pytest.fixture
def scanner():
    return ArchiveScanner()


@pytest.fixture
def valid_takeout_zip(tmp_path: Path) -> Path:
    """Create a small valid Takeout-style ZIP archive."""
    zip_path = tmp_path / "takeout.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        # Media files
        zf.writestr("Google Photos/Vacation/photo1.jpg", b"\xff\xd8\xff" + b"\x00" * 100)
        zf.writestr("Google Photos/Vacation/photo2.png", b"\x89PNG" + b"\x00" * 100)
        zf.writestr("Google Photos/Vacation/video1.mp4", b"\x00" * 200)

        # JSON sidecars
        zf.writestr("Google Photos/Vacation/photo1.jpg.json", '{"title": "Photo 1"}')
        zf.writestr("Google Photos/Vacation/photo2.png.json", '{"title": "Photo 2"}')

        # Unsupported file
        zf.writestr("Google Photos/Vacation/readme.txt", "hello")

        # Another album
        zf.writestr("Google Photos/Family/photo3.heic", b"\x00" * 50)
    return zip_path


@pytest.fixture
def corrupt_zip(tmp_path: Path) -> Path:
    """Create a corrupt ZIP file."""
    zip_path = tmp_path / "corrupt.zip"
    zip_path.write_bytes(b"This is not a zip file")
    return zip_path


def test_scan_valid_archive(scanner: ArchiveScanner, valid_takeout_zip: Path):
    """Test scanning a valid Takeout ZIP produces correct media counts."""
    result = scanner.scan_archives([str(valid_takeout_zip)])

    assert len(result.archives) == 1
    assert result.total_media_count == 4  # jpg, png, mp4, heic
    assert result.total_sidecar_count == 2  # two .json files
    assert result.total_unsupported_count == 1  # readme.txt
    assert len(result.errors) == 0


def test_scan_media_entries_have_correct_info(scanner: ArchiveScanner, valid_takeout_zip: Path):
    """Test that scanned media entries have correct file names and sizes."""
    result = scanner.scan_archives([str(valid_takeout_zip)])

    names = {e.file_name for e in result.media_entries}
    assert "photo1.jpg" in names
    assert "photo2.png" in names
    assert "video1.mp4" in names
    assert "photo3.heic" in names


def test_scan_total_media_bytes(scanner: ArchiveScanner, valid_takeout_zip: Path):
    """Test total media bytes calculation."""
    result = scanner.scan_archives([str(valid_takeout_zip)])
    assert result.total_media_bytes > 0


def test_scan_corrupt_zip(scanner: ArchiveScanner, corrupt_zip: Path):
    """Test that corrupt ZIP produces errors without crashing."""
    result = scanner.scan_archives([str(corrupt_zip)])
    assert len(result.errors) > 0
    assert result.total_media_count == 0


def test_scan_nonexistent_file(scanner: ArchiveScanner):
    """Test that scanning a missing file produces an error."""
    result = scanner.scan_archives(["/nonexistent/file.zip"])
    assert len(result.errors) > 0


def test_scan_multiple_archives(scanner: ArchiveScanner, tmp_path: Path):
    """Test scanning multiple ZIP archives."""
    zip1 = tmp_path / "archive1.zip"
    zip2 = tmp_path / "archive2.zip"

    with zipfile.ZipFile(zip1, "w") as zf:
        zf.writestr("photos/img1.jpg", b"\xff\xd8\xff" + b"\x00" * 50)
    with zipfile.ZipFile(zip2, "w") as zf:
        zf.writestr("photos/img2.jpg", b"\xff\xd8\xff" + b"\x00" * 50)

    result = scanner.scan_archives([str(zip1), str(zip2)])
    assert len(result.archives) == 2
    assert result.total_media_count == 2


def test_scan_empty_archive(scanner: ArchiveScanner, tmp_path: Path):
    """Test scanning an empty ZIP archive."""
    zip_path = tmp_path / "empty.zip"
    with zipfile.ZipFile(zip_path, "w"):
        pass  # Empty archive

    result = scanner.scan_archives([str(zip_path)])
    assert result.total_media_count == 0
    assert len(result.errors) == 0


def test_unsafe_path_rejection(scanner: ArchiveScanner):
    """Test that path traversal entries are flagged as unsafe."""
    assert scanner._is_unsafe_path("../../../etc/passwd") is True
    assert scanner._is_unsafe_path("/absolute/path.jpg") is True
    assert scanner._is_unsafe_path("C:/windows/path.jpg") is True
    assert scanner._is_unsafe_path("Google Photos/album/photo.jpg") is False


def test_scan_archive_with_directories(scanner: ArchiveScanner, tmp_path: Path):
    """Test that directory entries in ZIP are skipped."""
    zip_path = tmp_path / "with_dirs.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("Google Photos/", "")  # Directory entry
        zf.writestr("Google Photos/album/", "")  # Directory entry
        zf.writestr("Google Photos/album/photo.jpg", b"\xff\xd8\xff" + b"\x00" * 50)

    result = scanner.scan_archives([str(zip_path)])
    assert result.total_media_count == 1


def test_scan_single_zip_without_extraction(scanner: ArchiveScanner, valid_takeout_zip: Path, tmp_path: Path):
    """Test that scanning a ZIP inspects central directory headers without decompressing files to disk."""
    result = scanner.scan_archives([str(valid_takeout_zip)])
    assert len(result.archives) == 1
    assert result.total_media_count == 4
    for entry in result.media_entries:
        assert entry.is_extracted_file is False
        assert entry.crc32 is not None
        assert entry.file_size > 0
    # Confirm no files were extracted into tmp_path
    extracted_files = list(tmp_path.glob("Google Photos/**"))
    assert len(extracted_files) == 0


def test_scan_extracted_directory_recursive(scanner: ArchiveScanner, tmp_path: Path):
    """Test scanning an already-extracted Google Takeout folder recursively."""
    takeout_dir = tmp_path / "Takeout"
    album1 = takeout_dir / "Google Photos" / "2023"
    album2 = takeout_dir / "Google Photos" / "Trip"
    album1.mkdir(parents=True)
    album2.mkdir(parents=True)

    # Media and sidecar in album 1
    (album1 / "beach.jpg").write_bytes(b"\xff\xd8\xff" + b"\x00" * 150)
    (album1 / "beach.jpg.json").write_text('{"title": "Beach"}')

    # Media and unsupported in album 2
    (album2 / "mountain.png").write_bytes(b"\x89PNG" + b"\x00" * 250)
    (album2 / "metadata_summary.csv").write_text("id,name\n1,mountain")

    result = scanner.scan_archives([str(takeout_dir)])

    assert len(result.extracted_folders) == 1
    assert result.total_media_count == 2
    assert result.total_sidecar_count == 1
    assert result.total_unsupported_count == 1
    assert result.eligible_media_bytes == 153 + 254  # 150+3 for jpg, 250+4 for png

    for entry in result.media_entries:
        assert entry.is_extracted_file is True
        assert entry.file_name in ("beach.jpg", "mountain.png")


def test_scan_deduplicates_duplicate_entries(scanner: ArchiveScanner, tmp_path: Path):
    """Test that duplicate media entries (identical name, size, crc32) are recognized and excluded from eligible bytes."""
    zip1 = tmp_path / "archive_part1.zip"
    zip2 = tmp_path / "archive_part2.zip"

    shared_content = b"\xff\xd8\xff" + b"\x01" * 500

    # Same file in Year folder in part1 and in Album folder in part2
    with zipfile.ZipFile(zip1, "w") as zf:
        zf.writestr("Google Photos/Photos from 2022/sunset.jpg", shared_content)
        zf.writestr("Google Photos/Photos from 2022/unique1.jpg", b"\xff\xd8\xff" + b"\x02" * 100)

    with zipfile.ZipFile(zip2, "w") as zf:
        zf.writestr("Google Photos/Summer Vacation/sunset.jpg", shared_content)
        zf.writestr("Google Photos/Summer Vacation/unique2.jpg", b"\xff\xd8\xff" + b"\x03" * 200)

    result = scanner.scan_archives([str(zip1), str(zip2)])

    assert result.total_media_count == 4
    assert result.total_duplicate_count == 1
    assert result.duplicate_media_bytes == len(shared_content)
    assert result.eligible_media_count == 3
    assert result.eligible_media_bytes == (len(shared_content) + 103 + 203)


def test_scanning_limitations_reported(scanner: ArchiveScanner, valid_takeout_zip: Path):
    """Test that scanning limitations are populated and clearly reported."""
    result = scanner.scan_archives([str(valid_takeout_zip)])
    assert isinstance(result.scanning_limitations, list)
    assert len(result.scanning_limitations) >= 3
    assert any("central directory" in s for s in result.scanning_limitations)
    assert any("Duplicate" in s for s in result.scanning_limitations)


def test_different_photos_sharing_name_and_size_not_excluded_in_zips(scanner: ArchiveScanner, tmp_path: Path):
    """Confirm different photos sharing exact filename and byte length in ZIPs are NOT falsely deduplicated."""
    zip1 = tmp_path / "album_a.zip"
    zip2 = tmp_path / "album_b.zip"

    # Same name "IMG_0001.JPG", same byte size (100 bytes), but completely DIFFERENT content/CRC32
    content_a = b"\xff\xd8\xff" + b"A" * 97
    content_b = b"\xff\xd8\xff" + b"B" * 97

    with zipfile.ZipFile(zip1, "w") as zf:
        zf.writestr("Takeout/2021/IMG_0001.JPG", content_a)

    with zipfile.ZipFile(zip2, "w") as zf:
        zf.writestr("Takeout/2022/IMG_0001.JPG", content_b)

    result = scanner.scan_archives([str(zip1), str(zip2)])

    assert result.total_media_count == 2
    assert result.total_duplicate_count == 0  # Neither should be marked as duplicate
    assert result.eligible_media_count == 2
    assert result.eligible_media_bytes == 200


def test_different_photos_sharing_name_and_size_not_excluded_in_extracted_folder(scanner: ArchiveScanner, tmp_path: Path):
    """Confirm different photos sharing exact filename and byte length in extracted folders are NOT falsely deduplicated."""
    folder = tmp_path / "TakeoutFolder"
    dir_a = folder / "Google Photos" / "Trip1"
    dir_b = folder / "Google Photos" / "Trip2"
    dir_a.mkdir(parents=True)
    dir_b.mkdir(parents=True)

    content_a = b"\xff\xd8\xff" + b"X" * 150
    content_b = b"\xff\xd8\xff" + b"Y" * 150

    (dir_a / "photo.jpg").write_bytes(content_a)
    (dir_b / "photo.jpg").write_bytes(content_b)

    result = scanner.scan_archives([str(folder)])

    assert result.total_media_count == 2
    assert result.total_duplicate_count == 0
    assert result.eligible_media_count == 2
    assert result.eligible_media_bytes == len(content_a) + len(content_b)


def test_empty_archive_and_empty_folder(scanner: ArchiveScanner, tmp_path: Path):
    """Scanning empty ZIP archives and empty directory trees succeeds with 0 media and 0 errors."""
    empty_zip = tmp_path / "empty.zip"
    with zipfile.ZipFile(empty_zip, "w"):
        pass

    empty_dir = tmp_path / "empty_dir"
    empty_dir.mkdir()

    result = scanner.scan_archives([str(empty_zip), str(empty_dir)])
    assert result.total_media_count == 0
    assert result.eligible_media_bytes == 0
    assert len(result.errors) == 0


def test_misleading_filenames_classification(scanner: ArchiveScanner, tmp_path: Path):
    """Test that misleading filenames (e.g. photo.jpg.json, photo.json.jpg, notes.txt) are correctly classified."""
    zip_path = tmp_path / "misleading.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        # Sidecar with photo in name
        zf.writestr("Takeout/photo.jpg.json", '{"title": "sidecar"}')
        # Photo with json in name
        zf.writestr("Takeout/photo.json.jpg", b"\xff\xd8\xff" + b"\x00" * 100)
        # Text file with jpg in name
        zf.writestr("Takeout/notes.jpg.txt", "just text")
        # Unsupported file
        zf.writestr("Takeout/archive.tar.gz", b"\x00" * 50)

    result = scanner.scan_archives([str(zip_path)])
    assert result.total_media_count == 1
    assert result.media_entries[0].file_name == "photo.json.jpg"
    assert result.total_sidecar_count == 1
    assert result.sidecar_entries[0].file_name == "photo.jpg.json"
    assert result.total_unsupported_count == 2


