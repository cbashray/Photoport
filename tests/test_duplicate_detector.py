"""Tests for duplicate detection logic."""

from __future__ import annotations

from pathlib import Path

import pytest

from photoport.storage.database import Database
from photoport.storage.models import MediaItem, MediaItemStatus, MediaType
from photoport.storage.repository import MediaItemRepository


@pytest.fixture
def db(tmp_path: Path):
    database = Database(tmp_path / "test.db")
    yield database
    database.close()


@pytest.fixture
def repo(db: Database):
    return MediaItemRepository(db)


def _make_item(
    archive: str = "test.zip",
    member: str = "photo.jpg",
    sha256: str = "abc123",
    status: MediaItemStatus = MediaItemStatus.DISCOVERED,
) -> MediaItem:
    return MediaItem(
        archive_path=archive,
        zip_member_path=member,
        file_name=member.split("/")[-1],
        file_size=1000,
        media_type=MediaType.PHOTO,
        sha256_hash=sha256,
        mime_type="image/jpeg",
        status=status,
    )


class TestDuplicateDetection:
    """Tests for duplicate detection via SHA-256 hashes."""

    def test_detect_duplicate_by_hash(self, repo: MediaItemRepository):
        """Items with the same hash should be detectable."""
        item1 = _make_item(member="album/photo1.jpg", sha256="deadbeef")
        item2 = _make_item(member="album/photo2.jpg", sha256="deadbeef")

        repo.insert(item1)
        repo.insert(item2)

        matches = repo.get_by_hash("deadbeef")
        assert len(matches) == 2

    def test_different_hashes_not_duplicates(self, repo: MediaItemRepository):
        item1 = _make_item(member="album/photo1.jpg", sha256="hash1")
        item2 = _make_item(member="album/photo2.jpg", sha256="hash2")

        repo.insert(item1)
        repo.insert(item2)

        matches = repo.get_by_hash("hash1")
        assert len(matches) == 1

    def test_same_name_different_hash(self, repo: MediaItemRepository):
        """Same file name but different content should not be treated as duplicate."""
        item1 = _make_item(archive="zip1.zip", member="photo.jpg", sha256="hash_a")
        item2 = _make_item(archive="zip2.zip", member="photo.jpg", sha256="hash_b")

        repo.insert(item1)
        repo.insert(item2)

        assert len(repo.get_by_hash("hash_a")) == 1
        assert len(repo.get_by_hash("hash_b")) == 1

    def test_uploaded_duplicate_detected(self, repo: MediaItemRepository):
        """Already-uploaded items should be found as duplicates."""
        item1 = _make_item(
            member="album/original.jpg", sha256="same_hash",
            status=MediaItemStatus.UPLOADED,
        )
        repo.insert(item1)

        matches = repo.get_by_hash("same_hash")
        uploaded = [m for m in matches if m.status == MediaItemStatus.UPLOADED]
        assert len(uploaded) == 1


class TestUniqueConstraint:
    """Test the (archive_path, zip_member_path) uniqueness constraint."""

    def test_duplicate_insert_ignored(self, repo: MediaItemRepository):
        item = _make_item()
        id1 = repo.insert(item)
        assert id1 > 0
        _ = repo.insert(item)  # Same path — ignored by OR IGNORE
        assert repo.total_count() == 1

    def test_exists_check(self, repo: MediaItemRepository):
        item = _make_item()
        repo.insert(item)

        assert repo.exists("test.zip", "photo.jpg") is True
        assert repo.exists("other.zip", "photo.jpg") is False
