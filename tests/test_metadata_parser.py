"""Tests for metadata parsing and matching."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import piexif
import pytest

from photoport.archives.archive_scanner import ArchiveEntry
from photoport.metadata.exif_injector import inject_exif_metadata
from photoport.metadata.metadata_matcher import MetadataMatcher
from photoport.metadata.sidecar_parser import SidecarParser


@pytest.fixture
def parser():
    return SidecarParser()


@pytest.fixture
def matcher():
    return MetadataMatcher()


class TestSidecarParser:
    """Tests for Takeout JSON sidecar parsing."""

    def test_parse_basic_sidecar(self, parser: SidecarParser):
        sidecar_json = json.dumps({
            "title": "Beach photo",
            "description": "A lovely beach sunset",
            "photoTakenTime": {"timestamp": "1625000000"},
            "geoData": {
                "latitude": 37.7749,
                "longitude": -122.4194,
                "altitude": 10.0,
            },
        })

        meta = parser.parse_from_string(sidecar_json)
        assert meta.title == "Beach photo"
        assert meta.description == "A lovely beach sunset"
        assert meta.capture_epoch == 1625000000
        assert "2021" in meta.capture_timestamp  # June 2021
        assert meta.latitude == pytest.approx(37.7749)
        assert meta.longitude == pytest.approx(-122.4194)
        assert len(meta.parse_errors) == 0

    def test_parse_creation_time_fallback(self, parser: SidecarParser):
        """Test parsing when creationTime is used instead of photoTakenTime."""
        sidecar_json = json.dumps({
            "title": "Test",
            "creationTime": {"timestamp": "1700000000"},
        })

        meta = parser.parse_from_string(sidecar_json)
        assert meta.capture_epoch == 1700000000

    def test_parse_empty_sidecar(self, parser: SidecarParser):
        meta = parser.parse_from_string("{}")
        assert meta.title == ""
        assert meta.description == ""
        assert meta.capture_epoch == 0

    def test_parse_malformed_json(self, parser: SidecarParser):
        meta = parser.parse_from_string("not valid json {{{")
        assert len(meta.parse_errors) > 0

    def test_parse_zero_coordinates_ignored(self, parser: SidecarParser):
        """Test that (0, 0) coordinates are treated as missing."""
        sidecar_json = json.dumps({
            "geoData": {"latitude": 0.0, "longitude": 0.0},
        })

        meta = parser.parse_from_string(sidecar_json)
        assert meta.latitude is None
        assert meta.longitude is None

    def test_parse_favorite_and_archived(self, parser: SidecarParser):
        sidecar_json = json.dumps({
            "favorited": True,
            "archived": True,
            "trashed": False,
        })

        meta = parser.parse_from_string(sidecar_json)
        assert meta.is_favorite is True
        assert meta.is_archived is True
        assert meta.is_trashed is False

    def test_parse_from_zip(self, parser: SidecarParser, tmp_path: Path):
        """Test parsing a sidecar directly from a ZIP archive."""
        sidecar_data = json.dumps({
            "title": "From ZIP",
            "description": "Parsed from archive",
            "photoTakenTime": {"timestamp": "1600000000"},
        })

        zip_path = tmp_path / "test.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("Google Photos/Album/photo.jpg.json", sidecar_data)

        meta = parser.parse_from_zip(
            str(zip_path), "Google Photos/Album/photo.jpg.json"
        )

        assert meta.title == "From ZIP"
        assert meta.description == "Parsed from archive"
        assert meta.album_name == "Album"

    def test_invalid_timestamp(self, parser: SidecarParser):
        sidecar_json = json.dumps({
            "photoTakenTime": {"timestamp": "not_a_number"},
        })
        meta = parser.parse_from_string(sidecar_json)
        assert len(meta.parse_errors) > 0


class TestMetadataMatcher:
    """Tests for matching media files to their sidecars."""

    def _make_entry(
        self,
        path: str,
        is_media: bool = False,
        is_sidecar: bool = False,
    ) -> ArchiveEntry:
        from pathlib import PurePosixPath
        return ArchiveEntry(
            archive_path="archive.zip",
            member_path=path,
            file_name=PurePosixPath(path).name,
            file_size=100,
            is_media=is_media,
            is_sidecar=is_sidecar,
            is_directory=False,
        )

    def test_standard_sidecar_match(self, matcher: MetadataMatcher):
        """Test matching photo.jpg → photo.jpg.json"""
        media = [self._make_entry("album/photo.jpg", is_media=True)]
        sidecars = [self._make_entry("album/photo.jpg.json", is_sidecar=True)]

        matches = matcher.match(media, sidecars)
        assert matches["album/photo.jpg"] is not None
        assert matches["album/photo.jpg"].member_path == "album/photo.jpg.json"

    def test_stem_based_match(self, matcher: MetadataMatcher):
        """Test matching photo.jpg → photo.json"""
        media = [self._make_entry("album/photo.jpg", is_media=True)]
        sidecars = [self._make_entry("album/photo.json", is_sidecar=True)]

        matches = matcher.match(media, sidecars)
        assert matches["album/photo.jpg"] is not None

    def test_no_sidecar_found(self, matcher: MetadataMatcher):
        """Test that unmatched media returns None."""
        media = [self._make_entry("album/orphan.jpg", is_media=True)]
        sidecars = [self._make_entry("album/other.jpg.json", is_sidecar=True)]

        matches = matcher.match(media, sidecars)
        assert matches["album/orphan.jpg"] is None

    def test_multiple_media_multiple_sidecars(self, matcher: MetadataMatcher):
        media = [
            self._make_entry("a/img1.jpg", is_media=True),
            self._make_entry("a/img2.png", is_media=True),
        ]
        sidecars = [
            self._make_entry("a/img1.jpg.json", is_sidecar=True),
            self._make_entry("a/img2.png.json", is_sidecar=True),
        ]

        matches = matcher.match(media, sidecars)
        assert matches["a/img1.jpg"] is not None
        assert matches["a/img2.png"] is not None

    def test_photo_duplicate_naming_variants(self, matcher: MetadataMatcher):
        """Test photo.jpg(1).json and photo(1).jpg.json matching."""
        # Variant 1: photo(1).jpg → photo(1).jpg.json
        media1 = [self._make_entry("album/photo(1).jpg", is_media=True)]
        sidecars1 = [self._make_entry("album/photo(1).jpg.json", is_sidecar=True)]
        matches1 = matcher.match(media1, sidecars1)
        assert matches1["album/photo(1).jpg"] is not None
        assert matches1["album/photo(1).jpg"].member_path == "album/photo(1).jpg.json"

        # Variant 2: photo(1).jpg → photo.jpg(1).json (Google Takeout duplicate format)
        media2 = [self._make_entry("album/photo(1).jpg", is_media=True)]
        sidecars2 = [self._make_entry("album/photo.jpg(1).json", is_sidecar=True)]
        matches2 = matcher.match(media2, sidecars2)
        assert matches2["album/photo(1).jpg"] is not None
        assert matches2["album/photo(1).jpg"].member_path == "album/photo.jpg(1).json"

    def test_multiple_numbered_duplicate_files_isolated_matching(self, matcher: MetadataMatcher):
        """Ensure photo.jpg, photo(1).jpg, and photo(2).jpg each get their own distinct sidecar."""
        media = [
            self._make_entry("album/photo.jpg", is_media=True),
            self._make_entry("album/photo(1).jpg", is_media=True),
            self._make_entry("album/photo(2).jpg", is_media=True),
        ]
        sidecars = [
            self._make_entry("album/photo.jpg.json", is_sidecar=True),
            self._make_entry("album/photo.jpg(1).json", is_sidecar=True),
            self._make_entry("album/photo(2).jpg.json", is_sidecar=True),
        ]

        matches = matcher.match(media, sidecars)
        assert matches["album/photo.jpg"].member_path == "album/photo.jpg.json"
        assert matches["album/photo(1).jpg"].member_path == "album/photo.jpg(1).json"
        assert matches["album/photo(2).jpg"].member_path == "album/photo(2).jpg.json"


class TestExifInjection:
    """Tests for temporary copy EXIF timestamp injection."""

    MINI_JPEG = bytes.fromhex(
        "ffd8ffe000104a46494600010101004800480000ffdb004300080606070605080707070909080a0c140d0c0b0b0c1912130f141d1a1f1e1d1a1c1c20242e2720222c231c1c2837292c30313434341f27393d38323c2e333432ffc0000b080001000101011100ffda0008010100003f00bf00ffd9"
    )

    def test_inject_timestamp_and_gps_into_jpeg(self, tmp_path: Path):
        test_jpg = tmp_path / "sample.jpg"
        test_jpg.write_bytes(self.MINI_JPEG)

        ok = inject_exif_metadata(
            test_jpg,
            capture_timestamp="2022-08-20T15:30:00Z",
            latitude=37.7749,
            longitude=-122.4194,
        )
        assert ok is True

        exif_data = piexif.load(str(test_jpg))
        dto = exif_data["Exif"].get(piexif.ExifIFD.DateTimeOriginal)
        assert dto == b"2022:08:20 15:30:00"

        # Check GPS
        gps = exif_data["GPS"]
        assert piexif.GPSIFD.GPSLatitude in gps
        assert gps[piexif.GPSIFD.GPSLatitudeRef] == b"N"
        assert gps[piexif.GPSIFD.GPSLongitudeRef] == b"W"

    def test_inject_preserves_existing_camera_exif(self, tmp_path: Path):
        test_jpg = tmp_path / "camera.jpg"
        test_jpg.write_bytes(self.MINI_JPEG)

        # Pre-set camera EXIF
        camera_date = b"2018:01:01 12:00:00"
        exif_dict = {"0th": {}, "Exif": {piexif.ExifIFD.DateTimeOriginal: camera_date}, "GPS": {}, "1st": {}, "thumbnail": None}
        piexif.insert(piexif.dump(exif_dict), str(test_jpg))

        # Attempt to inject sidecar date (should NOT overwrite existing camera date)
        ok = inject_exif_metadata(test_jpg, capture_timestamp="2024-05-01T00:00:00Z")
        assert ok is False  # Nothing modified

        exif_data = piexif.load(str(test_jpg))
        assert exif_data["Exif"][piexif.ExifIFD.DateTimeOriginal] == camera_date

    def test_unsupported_formats_reported(self, tmp_path: Path):
        from photoport.metadata.exif_injector import inject_exif_metadata

        mp4_file = tmp_path / "clip.mp4"
        mp4_file.write_bytes(b"\x00" * 100)
        assert inject_exif_metadata(mp4_file, capture_timestamp="2022-01-01T00:00:00Z") is False

        png_file = tmp_path / "image.png"
        png_file.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 50)
        assert inject_exif_metadata(png_file, capture_timestamp="2022-01-01T00:00:00Z") is False
