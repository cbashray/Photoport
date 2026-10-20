"""Migration manager — the central orchestrator for the entire migration process."""

from __future__ import annotations

import logging
import time
from datetime import datetime
from enum import Enum

from photoport.archives.archive_scanner import ArchiveScanner, ArchiveScanResult
from photoport.archives.archive_validator import ArchiveValidator
from photoport.archives.safe_extract import SafeExtractor
from photoport.config import AppConfig
from photoport.google_photos.album_service import AlbumService
from photoport.google_photos.api_client import GooglePhotosClient
from photoport.google_photos.backend_interface import get_upload_backend
from photoport.google_photos.quota_service import QuotaService, StorageInfo
from photoport.google_photos.upload_service import UploadService
from photoport.metadata.album_manifest import AlbumManifest
from photoport.metadata.metadata_matcher import MetadataMatcher
from photoport.metadata.sidecar_parser import SidecarParser
from photoport.migration.storage_preflight import (
    PreflightStatus,
    StoragePreflightResult,
    StoragePreflightService,
)
from photoport.storage.database import Database
from photoport.storage.models import (
    AlbumRecord,
    MediaItem,
    MediaItemStatus,
    MediaType,
    MigrationSession,
    UploadQualityMode,
)
from photoport.storage.repository import (
    AlbumRepository,
    MediaItemRepository,
    SessionRepository,
)
from photoport.utils.file_types import check_file_size, get_mime_type, is_photo, is_video
from photoport.utils.formatting import format_bytes

logger = logging.getLogger("photoport.migration.migration_manager")


class MigrationPhase(Enum):
    IDLE = "IDLE"
    SCANNING = "SCANNING"
    VALIDATING = "VALIDATING"
    MATCHING_METADATA = "MATCHING_METADATA"
    CHECKING_STORAGE = "CHECKING_STORAGE"
    CREATING_ALBUMS = "CREATING_ALBUMS"
    UPLOADING = "UPLOADING"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class MigrationManager:
    """Orchestrates the complete migration pipeline.

    Phases:
    1. Scan archives → discover media and sidecars
    2. Validate → check file types, sizes, archive integrity
    3. Match metadata → pair media with JSON sidecars
    4. Check storage → verify destination has capacity
    5. Create albums → build album structure
    6. Upload → transfer media files one at a time
    7. Verify → confirm upload results
    8. Report → generate migration report
    """

    def __init__(self, config: AppConfig, db: Database | None = None) -> None:
        self.config = config
        self.db = db if db is not None else Database(config.db_path)
        self.media_repo = MediaItemRepository(self.db)
        self.album_repo = AlbumRepository(self.db)
        self.session_repo = SessionRepository(self.db)
        self.scanner = ArchiveScanner()
        self.validator = ArchiveValidator()
        self.extractor = SafeExtractor(config.temp_dir)
        self.sidecar_parser = SidecarParser()
        self.metadata_matcher = MetadataMatcher()
        self.album_manifest = AlbumManifest()
        self.api_client = GooglePhotosClient()
        self.upload_service = UploadService(
            self.api_client, self.media_repo, max_retries=config.max_retries,
        )
        self.album_service = AlbumService(self.api_client, self.album_repo)
        self.quota_service = QuotaService()
        self.preflight_service = StoragePreflightService(self.quota_service)

        # State
        self.phase = MigrationPhase.IDLE
        self.scan_result: ArchiveScanResult | None = None
        self.storage_info: StorageInfo | None = None
        self.last_preflight: StoragePreflightResult | None = None
        self.session: MigrationSession | None = None
        self._cancel_requested = False
        self._pause_requested = False
        self._current_file = ""
        self._upload_count = 0
        self._upload_start_time = 0.0
        self._bytes_uploaded = 0

        # Callbacks for UI updates
        self.on_phase_change: callable | None = None
        self.on_progress: callable | None = None
        self.on_file_change: callable | None = None
        self.on_error: callable | None = None

    # ------------------------------------------------------------------
    # Phase 1: Scan
    # ------------------------------------------------------------------

    def scan_archives(self, archive_paths: list[str]) -> ArchiveScanResult:
        """Scan archives and register media in the ledger."""
        self._set_phase(MigrationPhase.SCANNING)
        self.scan_result = self.scanner.scan_archives(archive_paths)

        # Validate archives
        self._set_phase(MigrationPhase.VALIDATING)
        for path in archive_paths:
            validation = self.validator.validate(path)
            if not validation.is_valid:
                for err in validation.errors:
                    self.scan_result.errors.append(err)

        # Check for duplicate archives
        dups = self.validator.check_duplicates(archive_paths)
        self.scan_result.errors.extend(dups)

        # Match metadata
        self._set_phase(MigrationPhase.MATCHING_METADATA)
        matches = self.metadata_matcher.match(
            self.scan_result.media_entries,
            self.scan_result.sidecar_entries,
        )

        # Register media items in the ledger
        items_to_insert: list[MediaItem] = []
        for entry in self.scan_result.media_entries:
            # Skip if already registered
            if self.media_repo.exists(entry.archive_path, entry.member_path):
                continue

            # Determine media type
            if is_photo(entry.file_name):
                media_type = MediaType.PHOTO
            elif is_video(entry.file_name):
                media_type = MediaType.VIDEO
            else:
                media_type = MediaType.UNKNOWN

            # Check file size limits
            size_error = check_file_size(entry.file_name, entry.file_size)
            status = MediaItemStatus.DISCOVERED
            error_msg = ""
            if size_error:
                status = MediaItemStatus.SKIPPED
                error_msg = size_error

            # Parse sidecar metadata if available
            sidecar_entry = matches.get(entry.member_path)
            description = ""
            capture_ts = ""
            album_name = ""
            sidecar_path = ""
            latitude = None
            longitude = None

            if sidecar_entry:
                sidecar_path = sidecar_entry.member_path
                meta = self.sidecar_parser.parse_from_zip(
                    sidecar_entry.archive_path, sidecar_entry.member_path,
                )
                description = meta.description
                capture_ts = meta.capture_timestamp
                latitude = meta.latitude
                longitude = meta.longitude
                if not album_name:
                    album_name = meta.album_name

            # Infer album from directory structure
            if not album_name:
                album_names = self.album_manifest._infer_album(entry.member_path)
                if album_names:
                    album_name = album_names

            item = MediaItem(
                archive_path=entry.archive_path,
                zip_member_path=entry.member_path,
                file_name=entry.file_name,
                file_size=entry.file_size,
                media_type=media_type,
                mime_type=get_mime_type(entry.file_name),
                status=status,
                album_name=album_name,
                description=description,
                capture_timestamp=capture_ts,
                sidecar_path=sidecar_path,
                latitude=latitude,
                longitude=longitude,
                error_message=error_msg,
            )
            items_to_insert.append(item)

        if items_to_insert:
            inserted = self.media_repo.insert_batch(items_to_insert)
            logger.info("Registered %d new media items in ledger", inserted)

        # Register albums
        albums = self.album_manifest.build(self.scan_result.media_entries)
        for album_name, entries in albums.items():
            self.album_repo.upsert(AlbumRecord(
                source_name=album_name,
                item_count=len(entries),
            ))

        self._set_phase(MigrationPhase.IDLE)
        return self.scan_result

    # ------------------------------------------------------------------
    # Phase 2: Preflight
    # ------------------------------------------------------------------

    def preflight_check(
        self,
        access_token: str | None = None,
        storage_info: StorageInfo | None = None,
        refresh_storage: bool = False,
        quality_mode: UploadQualityMode | str | None = None,
    ) -> dict:
        """Run comprehensive pre-migration storage preflight checks and return a detailed summary."""
        self._set_phase(MigrationPhase.CHECKING_STORAGE)

        target_info = storage_info if storage_info is not None else (None if refresh_storage else self.storage_info)

        mode_val = quality_mode if quality_mode is not None else self.config.upload_quality_mode
        if isinstance(mode_val, str):
            try:
                resolved_mode = UploadQualityMode(mode_val)
            except ValueError:
                resolved_mode = UploadQualityMode.ORIGINAL
        else:
            resolved_mode = mode_val

        result: StoragePreflightResult = self.preflight_service.run_preflight(
            scan_result=self.scan_result,
            media_repo=self.media_repo,
            access_token=access_token,
            storage_info=target_info,
            safety_margin_percent=self.config.storage_safety_margin_percent,
            safety_margin_min_bytes=self.config.storage_safety_margin_min_bytes,
            max_retries=self.config.max_retries,
            quality_mode=resolved_mode,
            storage_saver_estimated_ratio=self.config.storage_saver_estimated_ratio,
        )
        self.last_preflight = result
        self.storage_info = result.storage_info

        counts = self.media_repo.count_by_status() if self.media_repo.total_count() > 0 else {}
        total_items = self.media_repo.total_count() or result.total_discovered_items

        preflight = {
            "status": result.status.value,
            "can_proceed": result.can_proceed,
            "quality_mode": result.quality_mode.value,
            "total_items": total_items,
            "total_size_bytes": result.total_discovered_bytes,
            "remaining_upload_bytes": result.remaining_upload_bytes,
            "estimated_upload_bytes": result.estimated_upload_bytes,
            "safety_margin_bytes": result.safety_margin_bytes,
            "total_required_bytes": result.total_required_bytes,
            "shortfall_bytes": result.shortfall_bytes,
            "free_bytes": result.free_bytes,
            "is_resumed": result.is_resumed_migration,
            "counts_by_status": counts,
            "storage": {
                "available": result.storage_info.available,
                "total_gb": result.storage_info.total_bytes / (1024**3) if result.storage_info.available else None,
                "used_gb": result.storage_info.used_bytes / (1024**3) if result.storage_info.available else None,
                "free_gb": result.storage_info.free_bytes / (1024**3) if result.storage_info.available else None,
                "can_fit": result.status == PreflightStatus.ENOUGH,
                "fit_status": result.status.value,
                "error": result.storage_info.error,
                "user_email": result.storage_info.user_email,
            },
            "albums": len(self.album_repo.get_all()),
            "warnings": list(result.warnings),
            "recommendations": list(result.recommendations),
            "scanning_limitations": list(result.scanning_limitations),
            "preflight_result": result,
        }

        self._set_phase(MigrationPhase.IDLE)
        return preflight

    def recover_interrupted_uploads(self) -> dict[str, int]:
        """Recover media items left in inconsistent states after an unexpected crash.

        Distinguishes:
        - Items in UPLOADING with google_media_id: already created in Google Photos → marked UPLOADED.
        - Items in UPLOADING with an upload_token: raw bytes finished uploading, but
          the process crashed before or during batchCreate. Because the creation outcome
          is ambiguous and Google Photos may already have created the photo, we do NOT
          blindly re-upload (which would risk duplicates). We transition the item to
          NEEDS_REVIEW with an informative message.
        - Items in UPLOADING without an upload_token: crashed during file extraction or while
          streaming bytes. The API was never called to create the item. Safe to reset to READY.
        - Items already in NEEDS_REVIEW: preserved without automatic retry.

        Returns:
            Dictionary with counts: {"reset_ready": int, "marked_review": int, "marked_uploaded": int}
        """
        counts = {"reset_ready": 0, "marked_review": 0, "marked_uploaded": 0}
        interrupted = self.media_repo.get_by_status(MediaItemStatus.UPLOADING, limit=100000)

        for item in interrupted:
            if not item.id:
                continue

            if item.google_media_id:
                self.media_repo.update_status(
                    item.id,
                    MediaItemStatus.UPLOADED,
                    google_media_id=item.google_media_id,
                    upload_token=item.upload_token,
                    error_message="Recovered: item confirmed uploaded with Google Media ID",
                )
                counts["marked_uploaded"] += 1
                logger.info(
                    "Recovered interrupted item %s: already confirmed uploaded (ID: %s)",
                    item.file_name, item.google_media_id,
                )

            elif item.upload_token:
                msg = (
                    "Interrupted after raw byte upload; batchCreate outcome ambiguous. "
                    "Preserved in NEEDS_REVIEW to avoid potential duplicate creation."
                )
                self.media_repo.update_status(
                    item.id,
                    MediaItemStatus.NEEDS_REVIEW,
                    upload_token=item.upload_token,
                    error_message=msg,
                )
                counts["marked_review"] += 1
                logger.warning("Recovered interrupted item %s: marked NEEDS_REVIEW", item.file_name)

            else:
                self.media_repo.update_status(
                    item.id,
                    MediaItemStatus.READY,
                    error_message="Recovered: reset to READY after interrupted process (no bytes transferred)",
                )
                counts["reset_ready"] += 1
                logger.info("Recovered interrupted item %s: reset to READY", item.file_name)

        return counts

    def reconcile_item(self, item_id: int, action: str, note: str = "") -> bool:
        """Safely reconcile an item in NEEDS_REVIEW status.

        Supported actions:
        - 'mark_uploaded': User confirmed item exists on Google Photos. Status → UPLOADED.
        - 'force_retry': User confirmed item does NOT exist on Google Photos. Reset token → READY.
        - 'skip': User chooses to ignore/skip item. Status → SKIPPED.

        Returns:
            True if action was applied successfully, False otherwise.
        """
        item = self.media_repo.get_by_id(item_id)
        if not item:
            logger.error("Reconciliation failed: item ID %d not found", item_id)
            return False

        if action == "mark_uploaded":
            msg = note or "Manually confirmed uploaded on Google Photos by user"
            self.media_repo.update_status(
                item_id,
                MediaItemStatus.UPLOADED,
                google_media_id=item.google_media_id,
                upload_token=item.upload_token,
                error_message=msg,
            )
            logger.info("Reconciled item %s: marked as UPLOADED (%s)", item.file_name, msg)
            return True

        elif action == "force_retry":
            msg = note or "Force retry requested by user after verifying item is absent on Google Photos"
            self.media_repo.update_status(
                item_id,
                MediaItemStatus.READY,
                upload_token="",
                error_message=msg,
            )
            logger.info("Reconciled item %s: reset to READY for re-upload (%s)", item.file_name, msg)
            return True

        elif action == "skip":
            msg = note or "Skipped by user during review of ambiguous upload"
            self.media_repo.update_status(
                item_id,
                MediaItemStatus.SKIPPED,
                error_message=msg,
            )
            logger.info("Reconciled item %s: marked SKIPPED (%s)", item.file_name, msg)
            return True

        else:
            logger.error("Unknown reconciliation action '%s' for item %d", action, item_id)
            return False

    # ------------------------------------------------------------------
    # Phase 3: Execute migration
    # ------------------------------------------------------------------

    def start_migration(
        self,
        access_token_provider: callable,
        recreate_albums: bool = True,
        progress_callback: callable | None = None,
        quality_mode: UploadQualityMode | str | None = None,
    ) -> None:
        """Execute the migration using the selected or persisted upload quality mode.

        Args:
            access_token_provider: Callable that returns a current valid access token.
            recreate_albums: Whether to create album structure.
            progress_callback: Called with (completed, total, current_file) on each upload.
            quality_mode: Upload quality mode to use (defaults to config or persisted session).
        """
        self._cancel_requested = False
        self._pause_requested = False

        # Recover any interrupted items from a prior crashed run
        recovery_stats = self.recover_interrupted_uploads()
        if any(recovery_stats.values()):
            logger.info("Crash recovery performed before starting: %s", recovery_stats)

        # Check for existing incomplete session to preserve its quality mode across restarts
        latest_session = self.session_repo.get_latest()
        if latest_session and latest_session.status in ("IN_PROGRESS", "PAUSED"):
            selected_quality = latest_session.quality_mode
            self.session = latest_session
            logger.info("Resuming session %d with persisted quality mode '%s'", self.session.id, selected_quality.value)
        else:
            mode_val = quality_mode if quality_mode is not None else self.config.upload_quality_mode
            if isinstance(mode_val, str):
                try:
                    selected_quality = UploadQualityMode(mode_val)
                except ValueError:
                    selected_quality = UploadQualityMode.ORIGINAL
            else:
                selected_quality = mode_val

            self.session = MigrationSession(
                total_archives=len(self.scan_result.archives) if self.scan_result else 0,
                total_files_discovered=self.media_repo.total_count(),
                quality_mode=selected_quality,
            )
            session_id = self.session_repo.create(self.session)
            self.session.id = session_id
            logger.info("Created migration session %d with quality mode '%s'", session_id, selected_quality.value)

        # Retrieve and validate backend for the selected mode
        backend = get_upload_backend(selected_quality, self.config)
        is_avail, avail_reason = backend.is_available()
        if not is_avail:
            raise ValueError(
                f"Selected upload quality mode '{backend.display_name}' is not available: {avail_reason}"
            )

        # Enforce storage preflight check immediately before starting upload
        access_token = access_token_provider()
        preflight_dict = self.preflight_check(access_token, quality_mode=selected_quality)
        status = preflight_dict["status"]

        if status == PreflightStatus.INSUFFICIENT.value:
            req_str = format_bytes(preflight_dict["total_required_bytes"])
            free_str = format_bytes(preflight_dict["free_bytes"])
            shortfall_str = format_bytes(preflight_dict["shortfall_bytes"])
            raise ValueError(
                f"Migration stopped: destination storage is insufficient. "
                f"Requires {req_str} (including safety buffer for {backend.display_name}), but destination account has only {free_str} free. "
                f"Shortfall: {shortfall_str}."
            )
        elif status == PreflightStatus.UNKNOWN.value:
            error_reason = preflight_dict["storage"].get("error") or "Capacity could not be confirmed"
            raise ValueError(
                f"Migration stopped: destination storage capacity could not be verified ({error_reason}). "
                "Capacity must be confirmed before starting full migration."
            )

        # Create albums if requested
        if recreate_albums:
            self._set_phase(MigrationPhase.CREATING_ALBUMS)
            albums = self.album_repo.get_all()
            album_id_map: dict[str, str] = {}
            for album in albums:
                if self._cancel_requested:
                    break
                album_id = self.album_service.create_album(access_token, album.source_name)
                if album_id:
                    album_id_map[album.source_name] = album_id

        # Validate all DISCOVERED items → READY
        self._set_phase(MigrationPhase.VALIDATING)
        discovered = self.media_repo.get_by_status(MediaItemStatus.DISCOVERED, limit=100000)
        for item in discovered:
            if item.id:
                self.media_repo.update_status(item.id, MediaItemStatus.READY)

        # Upload
        self._set_phase(MigrationPhase.UPLOADING)
        self._upload_start_time = time.time()
        self._upload_count = 0
        self._bytes_uploaded = 0

        while not self._cancel_requested:
            if self._pause_requested:
                self._set_phase(MigrationPhase.PAUSED)
                while self._pause_requested and not self._cancel_requested:
                    time.sleep(0.5)
                if not self._cancel_requested:
                    self._set_phase(MigrationPhase.UPLOADING)

            # Get next batch of ready items
            ready_items = self.media_repo.get_by_status(MediaItemStatus.READY, limit=1)
            if not ready_items:
                # Check for retryable items
                retryable = self.media_repo.get_retryable(self.config.max_retries, limit=1)
                if retryable:
                    ready_items = retryable
                    for item in ready_items:
                        if item.id:
                            self.media_repo.update_status(item.id, MediaItemStatus.READY)
                else:
                    break  # No more items to process

            for item in ready_items:
                if self._cancel_requested:
                    break

                # Refresh token if needed
                access_token = access_token_provider()

                self._current_file = item.file_name
                if self.on_file_change:
                    self.on_file_change(item.file_name)

                # Extract the file
                try:
                    file_path, sha256_hash = self.extractor.extract_member(
                        item.archive_path, item.zip_member_path, compute_hash=True,
                    )
                except Exception as exc:
                    logger.error("Failed to extract %s: %s", item.file_name, exc)
                    if item.id:
                        self.media_repo.update_status(
                            item.id, MediaItemStatus.FAILED_PERMANENT,
                            error_message=f"Extraction failed: {exc}",
                        )
                    continue

                try:
                    # Optional: inject timestamp and GPS into temporary copy before upload
                    if self.config.enable_exif_injection and (item.capture_timestamp or item.latitude is not None):
                        from photoport.metadata.exif_injector import inject_exif_metadata
                        injected = inject_exif_metadata(
                            file_path,
                            capture_timestamp=item.capture_timestamp,
                            latitude=item.latitude,
                            longitude=item.longitude,
                        )
                        if injected:
                            from photoport.utils.hashing import sha256_file
                            sha256_hash = sha256_file(file_path)

                    # Update hash
                    if item.id and sha256_hash:
                        self.media_repo.update_hash(item.id, sha256_hash)

                    # Check for duplicates
                    if sha256_hash and self.config.enable_duplicate_detection:
                        existing = self.media_repo.get_by_hash(sha256_hash)
                        already_uploaded = [
                            e for e in existing
                            if e.id != item.id
                            and e.status in (MediaItemStatus.UPLOADED, MediaItemStatus.VERIFIED)
                        ]
                        if already_uploaded:
                            logger.info(
                                "Duplicate detected: %s matches already-uploaded %s",
                                item.file_name, already_uploaded[0].file_name,
                            )
                            if item.id:
                                self.media_repo.update_status(
                                    item.id, MediaItemStatus.SKIPPED,
                                    error_message=f"Duplicate of {already_uploaded[0].file_name}",
                                )
                            continue

                    # Determine album
                    album_id = ""
                    if recreate_albums and item.album_name:
                        album_id = album_id_map.get(item.album_name, "")

                    # Prepare media via backend (e.g. StorageSaver converts photo to temporary downscaled staging file)
                    is_item_photo = is_photo(item.file_name)
                    upload_file_path, is_temporary_prepared = backend.prepare_media(
                        media_path=file_path,
                        temp_dir=self.config.temp_dir,
                        is_photo=is_item_photo,
                    )

                    try:
                        # Upload
                        result = self.upload_service.upload_with_retry(
                            item=item,
                            file_path=upload_file_path,
                            access_token=access_token,
                            album_id=album_id,
                            cancel_flag=lambda: self._cancel_requested,
                        )
                    finally:
                        if is_temporary_prepared:
                            backend.cleanup_prepared(upload_file_path, is_temporary=True)

                    if result.success:
                        self._upload_count += 1
                        self._bytes_uploaded += item.file_size

                        # Periodic storage recheck during long migrations
                        if (
                            self.config.storage_recheck_interval_items > 0
                            and self._upload_count % self.config.storage_recheck_interval_items == 0
                        ):
                            try:
                                cur_token = access_token_provider()
                                fresh_info = self.quota_service.get_storage_info(cur_token)
                                self.storage_info = fresh_info
                                rem_size = self.media_repo.remaining_upload_size(max_retries=self.config.max_retries)
                                if fresh_info.available and fresh_info.free_bytes < rem_size:
                                    logger.warning(
                                        "Storage exhausted during migration! Free: %s, Remaining needed: %s. Pausing migration.",
                                        format_bytes(fresh_info.free_bytes),
                                        format_bytes(rem_size),
                                    )
                                    self._pause_requested = True
                                    if self.on_error:
                                        self.on_error(
                                            f"Migration paused: storage became insufficient ({format_bytes(fresh_info.free_bytes)} free, {format_bytes(rem_size)} needed)."
                                        )
                            except Exception as recheck_exc:
                                logger.warning("Periodic storage recheck failed: %s", recheck_exc)

                    # Report progress
                    if progress_callback:
                        counts = self.media_repo.count_by_status()
                        total = self.media_repo.total_count()
                        done = counts.get("UPLOADED", 0) + counts.get("VERIFIED", 0) + counts.get("SKIPPED", 0)
                        progress_callback(done, total, item.file_name)

                    if self.on_progress:
                        counts = self.media_repo.count_by_status()
                        self.on_progress(counts)

                finally:
                    # Clean up temp file
                    if self.config.delete_temp_after_verify:
                        self.extractor.cleanup_file(file_path)

        # Update session
        if self.session and self.session.id:
            counts = self.media_repo.count_by_status()
            self.session.total_uploaded = counts.get("UPLOADED", 0) + counts.get("VERIFIED", 0)
            self.session.total_failed = counts.get("FAILED_PERMANENT", 0) + counts.get("FAILED_RETRYABLE", 0)
            self.session.total_skipped = counts.get("SKIPPED", 0)
            self.session.total_needs_review = counts.get("NEEDS_REVIEW", 0)
            self.session.completed_at = datetime.utcnow().isoformat()
            self.session.status = "CANCELLED" if self._cancel_requested else "COMPLETED"
            self.session_repo.update(self.session)

        final_phase = MigrationPhase.CANCELLED if self._cancel_requested else MigrationPhase.COMPLETED
        self._set_phase(final_phase)

    # ------------------------------------------------------------------
    # Controls
    # ------------------------------------------------------------------

    def pause(self) -> None:
        """Request migration pause."""
        self._pause_requested = True
        logger.info("Pause requested")

    def resume(self) -> None:
        """Resume a paused migration."""
        self._pause_requested = False
        logger.info("Resume requested")

    def cancel(self) -> None:
        """Request migration cancellation."""
        self._cancel_requested = True
        logger.info("Cancel requested")

    @property
    def is_paused(self) -> bool:
        return self._pause_requested

    @property
    def is_cancelled(self) -> bool:
        return self._cancel_requested

    @property
    def current_file(self) -> str:
        return self._current_file

    @property
    def transfer_speed(self) -> float:
        """Return current transfer speed in bytes/second."""
        elapsed = time.time() - self._upload_start_time
        if elapsed <= 0:
            return 0.0
        return self._bytes_uploaded / elapsed

    @property
    def eta_seconds(self) -> float:
        """Estimated time remaining in seconds."""
        speed = self.transfer_speed
        if speed <= 0:
            return 0.0
        remaining_bytes = self.media_repo.total_size_by_status(MediaItemStatus.READY)
        return remaining_bytes / speed

    def get_status_counts(self) -> dict[str, int]:
        """Return current counts by status."""
        return self.media_repo.count_by_status()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _set_phase(self, phase: MigrationPhase) -> None:
        self.phase = phase
        logger.info("Phase: %s", phase.value)
        if self.on_phase_change:
            self.on_phase_change(phase)

    def close(self) -> None:
        """Clean up resources."""
        self.api_client.close()
        self.db.close()
