"""Tests for report generation (CSV, JSON, and summary export)."""

from __future__ import annotations

import json
from pathlib import Path

from photoport.migration.report_generator import ReportGenerator
from photoport.storage.database import Database
from photoport.storage.models import MediaItem, MediaItemStatus, MediaType, MigrationSession
from photoport.storage.repository import AlbumRepository, MediaItemRepository, SessionRepository


def test_report_generation(tmp_path: Path):
    db_path = tmp_path / "report_test.db"
    db = Database(db_path)
    media_repo = MediaItemRepository(db)
    album_repo = AlbumRepository(db)
    session_repo = SessionRepository(db)

    # Insert test session
    session = MigrationSession(
        started_at="2026-10-19T10:00:00",
        completed_at="2026-10-19T10:30:00",
        total_archives=1,
        total_files_discovered=2,
        total_photos=2,
        total_uploaded=1,
        total_failed=1,
        status="COMPLETED",
        destination_account="user@gmail.com",
    )
    s_id = session_repo.create(session)
    session.id = s_id

    # Insert media items
    item1 = MediaItem(
        archive_path="archive1.zip",
        zip_member_path="Photos/img1.jpg",
        file_name="img1.jpg",
        file_size=1024,
        media_type=MediaType.PHOTO,
        mime_type="image/jpeg",
        status=MediaItemStatus.UPLOADED,
        google_media_id="g_123",
    )
    item2 = MediaItem(
        archive_path="archive1.zip",
        zip_member_path="Photos/img2.jpg",
        file_name="img2.jpg",
        file_size=2048,
        media_type=MediaType.PHOTO,
        mime_type="image/jpeg",
        status=MediaItemStatus.FAILED_PERMANENT,
        error_message="Unsupported format",
    )
    media_repo.insert(item1)
    media_repo.insert(item2)

    generator = ReportGenerator(media_repo, album_repo, session_repo)

    # 1. JSON Report
    json_path = tmp_path / "report.json"
    generator.export_json(json_path, session)
    assert json_path.exists()
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["session"]["destination_account"] == "user@gmail.com"
    assert len(data["items"]) == 2

    # 2. CSV Report
    csv_path = tmp_path / "report.csv"
    generator.export_csv(csv_path)
    assert csv_path.exists()
    content = csv_path.read_text(encoding="utf-8")
    assert "img1.jpg" in content
    assert "img2.jpg" in content

    # 3. Text Summary
    summary = generator.generate_summary_text(session)
    assert "PhotoPort Migration Report" in summary
    assert "user@gmail.com" in summary

    db.close()


def test_report_needs_review_items(tmp_path: Path):
    db_path = tmp_path / "review_report_test.db"
    db = Database(db_path)
    media_repo = MediaItemRepository(db)
    album_repo = AlbumRepository(db)
    session_repo = SessionRepository(db)

    item = MediaItem(
        archive_path="archive1.zip",
        zip_member_path="Photos/ambiguous.jpg",
        file_name="ambiguous.jpg",
        file_size=4096,
        media_type=MediaType.PHOTO,
        mime_type="image/jpeg",
        status=MediaItemStatus.NEEDS_REVIEW,
        upload_token="token_ambiguous_123",
        error_message="Ambiguous upload status: server timeout during batchCreate",
    )
    media_repo.insert(item)

    generator = ReportGenerator(media_repo, album_repo, session_repo)
    summary_data = generator.generate_summary()
    assert summary_data["totals"]["needs_review"] == 1
    assert len(summary_data["failed_items"]) == 1
    assert summary_data["failed_items"][0]["status"] == "NEEDS_REVIEW"
    assert summary_data["failed_items"][0]["file_name"] == "ambiguous.jpg"

    text_report = generator.get_readable_report()
    assert "Needs review:         1" in text_report
    assert "[NEEDS_REVIEW] ambiguous.jpg" in text_report

    csv_path = tmp_path / "review_report.csv"
    generator.export_csv(csv_path)
    csv_text = csv_path.read_text(encoding="utf-8")
    assert "NEEDS_REVIEW" in csv_text
    assert "ambiguous.jpg" in csv_text

    db.close()

