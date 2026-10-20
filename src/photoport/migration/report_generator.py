"""Migration report generation — CSV and JSON exports."""

from __future__ import annotations

import csv
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from photoport.storage.database import Database
from photoport.storage.repository import AlbumRepository, MediaItemRepository, SessionRepository

if TYPE_CHECKING:
    from photoport.storage.models import MigrationSession

logger = logging.getLogger("photoport.migration.report_generator")


class ReportGenerator:
    """Generate comprehensive migration reports."""

    def __init__(
        self,
        db_or_media_repo: Database | MediaItemRepository,
        album_repo: AlbumRepository | None = None,
        session_repo: SessionRepository | None = None,
    ) -> None:
        if isinstance(db_or_media_repo, Database):
            self.media_repo = MediaItemRepository(db_or_media_repo)
            self.album_repo = AlbumRepository(db_or_media_repo)
            self.session_repo = SessionRepository(db_or_media_repo)
        else:
            self.media_repo = db_or_media_repo
            self.album_repo = album_repo or AlbumRepository(db_or_media_repo.db)
            self.session_repo = session_repo or SessionRepository(db_or_media_repo.db)

    def generate_summary(self, session: MigrationSession | None = None) -> dict:
        """Generate a summary dict of the migration."""
        counts = self.media_repo.count_by_status()
        items = self.media_repo.get_all()
        albums = self.album_repo.get_all()
        if session is None:
            session = self.session_repo.get_latest()

        total = self.media_repo.total_count()
        photos = sum(1 for i in items if i.media_type.value == "PHOTO")
        videos = sum(1 for i in items if i.media_type.value == "VIDEO")
        uploaded = counts.get("UPLOADED", 0) + counts.get("VERIFIED", 0)
        failed = counts.get("FAILED_PERMANENT", 0) + counts.get("FAILED_RETRYABLE", 0)
        skipped = counts.get("SKIPPED", 0)
        needs_review = counts.get("NEEDS_REVIEW", 0)

        quality_mode_val = (
            session.quality_mode.value
            if session and hasattr(session, "quality_mode") and hasattr(session.quality_mode, "value")
            else (str(session.quality_mode) if session and hasattr(session, "quality_mode") else "original")
        )

        return {
            "generated_at": datetime.utcnow().isoformat(),
            "session": {
                "started_at": session.started_at if session else "",
                "completed_at": session.completed_at if session else "",
                "status": session.status if session else "UNKNOWN",
                "destination_account": session.destination_account if session else "",
                "quality_mode": quality_mode_val,
            },
            "totals": {
                "archives_processed": session.total_archives if session else 0,
                "files_discovered": total,
                "photos": photos,
                "videos": videos,
                "successful_uploads": uploaded,
                "failed_uploads": failed,
                "skipped_files": skipped,
                "needs_review": needs_review,
            },
            "status_breakdown": counts,
            "albums": {
                "total": len(albums),
                "created": sum(1 for a in albums if a.google_album_id),
                "failed": sum(1 for a in albums if a.status == "FAILED"),
                "details": [
                    {
                        "name": a.source_name,
                        "status": a.status,
                        "items": a.item_count,
                        "added": a.items_added,
                    }
                    for a in albums
                ],
            },
            "failed_items": [
                {
                    "file_name": i.file_name,
                    "archive": i.archive_path,
                    "error": i.error_message,
                    "retries": i.retry_count,
                    "status": i.status.value,
                }
                for i in items
                if i.status in (
                    __import__("photoport.storage.models", fromlist=["MediaItemStatus"]).MediaItemStatus.FAILED_PERMANENT,
                    __import__("photoport.storage.models", fromlist=["MediaItemStatus"]).MediaItemStatus.FAILED_RETRYABLE,
                    __import__("photoport.storage.models", fromlist=["MediaItemStatus"]).MediaItemStatus.NEEDS_REVIEW,
                )
            ],
        }

    def export_json(self, output_path: Path, session: MigrationSession | None = None) -> None:
        """Export the full migration report as JSON."""
        summary = self.generate_summary(session)
        items = self.media_repo.get_all()

        item_list = [
            {
                "id": i.id,
                "file_name": i.file_name,
                "archive_path": i.archive_path,
                "zip_member_path": i.zip_member_path,
                "file_size": i.file_size,
                "media_type": i.media_type.value,
                "sha256_hash": i.sha256_hash,
                "status": i.status.value,
                "google_media_id": i.google_media_id,
                "album_name": i.album_name,
                "error_message": i.error_message,
                "retry_count": i.retry_count,
                "capture_timestamp": i.capture_timestamp,
            }
            for i in items
        ]

        report = {
            **summary,
            "items": item_list,
            "all_items": item_list,
        }

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        logger.info("JSON report exported to %s", output_path)

    def export_csv(self, output_path: Path) -> None:
        """Export media items as CSV."""
        items = self.media_repo.get_all()

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "ID", "File Name", "Archive", "ZIP Path", "Size (bytes)",
                "Type", "SHA-256", "Status", "Google Media ID", "Album",
                "Error", "Retries", "Capture Time",
            ])
            for i in items:
                writer.writerow([
                    i.id, i.file_name, i.archive_path, i.zip_member_path,
                    i.file_size, i.media_type.value, i.sha256_hash,
                    i.status.value, i.google_media_id, i.album_name,
                    i.error_message, i.retry_count, i.capture_timestamp,
                ])

        logger.info("CSV report exported to %s", output_path)

    def generate_summary_text(self, session: MigrationSession | None = None) -> str:
        """Generate human-readable summary text."""
        return self.get_readable_report(session)

    def get_readable_report(self, session: MigrationSession | None = None) -> str:
        """Generate a human-readable text report."""
        summary = self.generate_summary(session)
        totals = summary["totals"]
        sess = summary["session"]
        albums_info = summary["albums"]

        dest = sess.get("destination_account", "")

        lines = [
            "=" * 60,
            "  PhotoPort Migration Report",
            "=" * 60,
            "",
            f"  Generated:   {summary['generated_at']}",
        ]
        if dest:
            lines.append(f"  Destination: {dest}")
        lines.extend([
            f"  Started:     {sess['started_at']}",
            f"  Completed:   {sess['completed_at']}",
            f"  Status:      {sess['status']}",
            f"  Quality:     {sess.get('quality_mode', 'original')}",
            "",
            "─" * 60,
            "  SUMMARY",
            "─" * 60,
            f"  Archives processed:      {totals['archives_processed']}",
            f"  Total files discovered:   {totals['files_discovered']}",
            f"  Photos:                   {totals['photos']}",
            f"  Videos:                   {totals['videos']}",
            "",
            f"  ✅ Successful uploads:    {totals['successful_uploads']}",
            f"  ❌ Failed uploads:        {totals['failed_uploads']}",
            f"  ⏭️  Skipped files:        {totals['skipped_files']}",
            f"  ⚠️  Needs review:         {totals['needs_review']}",
            "",
            "─" * 60,
            "  ALBUMS",
            "─" * 60,
            f"  Total albums:             {albums_info['total']}",
            f"  Successfully created:     {albums_info['created']}",
            f"  Failed:                   {albums_info['failed']}",
        ])

        if summary["failed_items"]:
            lines.extend([
                "",
                "─" * 60,
                "  FAILED ITEMS",
                "─" * 60,
            ])
            for item in summary["failed_items"][:50]:
                lines.append(
                    f"  [{item['status']}] {item['file_name']}: {item['error']}"
                )
            if len(summary["failed_items"]) > 50:
                lines.append(
                    f"  ... and {len(summary['failed_items']) - 50} more"
                )

        lines.extend(["", "=" * 60])
        return "\n".join(lines)
