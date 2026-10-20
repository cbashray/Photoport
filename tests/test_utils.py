"""Tests for hashing and disk space utilities."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from photoport.utils.disk_space import (
    format_bytes,
    get_free_space,
    get_total_space,
    has_sufficient_space,
)
from photoport.utils.file_types import (
    classify_file,
    is_media_file,
    is_sidecar_file,
)
from photoport.utils.hashing import compute_file_sha256


def test_format_bytes():
    assert format_bytes(500) == "500.0 B"
    assert format_bytes(1024) == "1.0 KB"
    assert format_bytes(1024 * 1024) == "1.0 MB"
    assert format_bytes(1024 * 1024 * 1024) == "1.0 GB"
    assert format_bytes(1024 * 1024 * 1024 * 1024) == "1.0 TB"


def test_file_type_classification():
    assert is_media_file("vacation.jpg")
    assert is_media_file("clip.mp4")
    assert is_media_file("photo.HEIC")
    assert not is_media_file("notes.txt")
    assert is_sidecar_file("photo.jpg.json")
    assert not is_sidecar_file("photo.jpg")

    media_type, mime = classify_file("test.png")
    assert mime == "image/png"


def test_compute_file_sha256(tmp_path: Path):
    test_file = tmp_path / "sample.bin"
    test_file.write_bytes(b"PhotoPort hashing test payload")

    h1 = compute_file_sha256(test_file)
    h2 = compute_file_sha256(test_file)
    assert h1 == h2
    assert len(h1) == 64


def test_disk_space_utilities(tmp_path: Path):
    with patch("shutil.disk_usage") as mock_usage:
        mock_usage.return_value = (1000000000, 200000000, 800000000)
        assert get_total_space(tmp_path) == 1000000000
        assert get_free_space(tmp_path) == 800000000
        assert has_sufficient_space(tmp_path, 500000000)
        assert not has_sufficient_space(tmp_path, 800000000)
