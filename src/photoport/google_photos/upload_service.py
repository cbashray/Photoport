"""Upload service — orchestrates single-file upload workflow with retry logic."""

from __future__ import annotations

import logging
import random
import time
from pathlib import Path

from photoport.config import DEFAULT_MAX_RETRIES, DEFAULT_RETRY_BASE_DELAY, DEFAULT_RETRY_MAX_DELAY
from photoport.google_photos.api_client import GooglePhotosAPIError, GooglePhotosClient
from photoport.storage.models import MediaItem, MediaItemStatus
from photoport.storage.repository import MediaItemRepository

logger = logging.getLogger("photoport.google_photos.upload_service")


class UploadResult:
    """Result of a single media item upload."""

    def __init__(
        self,
        success: bool,
        media_item_id: str = "",
        error_message: str = "",
        is_retryable: bool = False,
        needs_review: bool = False,
    ) -> None:
        self.success = success
        self.media_item_id = media_item_id
        self.error_message = error_message
        self.is_retryable = is_retryable
        self.needs_review = needs_review


class UploadService:
    """Manages the upload lifecycle for individual media items.

    Responsibilities:
    1. Upload raw bytes to get an upload token
    2. Create the media item via batchCreate
    3. Handle retries with exponential backoff + jitter
    4. Update the migration ledger
    5. Report results
    """

    def __init__(
        self,
        api_client: GooglePhotosClient,
        repo: MediaItemRepository,
        max_retries: int = DEFAULT_MAX_RETRIES,
        base_delay: float = DEFAULT_RETRY_BASE_DELAY,
        max_delay: float = DEFAULT_RETRY_MAX_DELAY,
    ) -> None:
        self.api = api_client
        self.repo = repo
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay

    def upload_file(
        self,
        item: MediaItem,
        file_path: Path,
        access_token: str,
        album_id: str = "",
    ) -> UploadResult:
        """Upload a single media file through the complete workflow.

        Steps:
        1. Upload bytes → get upload token
        2. batchCreate → get media item ID
        3. Update ledger with result
        """
        if item.id is None:
            return UploadResult(
                success=False,
                error_message="Media item has no database ID",
            )

        # Mark as uploading
        self.repo.update_status(item.id, MediaItemStatus.UPLOADING)

        try:
            # Step 1: Upload bytes
            logger.info("Uploading: %s (%d bytes)", item.file_name, item.file_size)
            upload_token = self.api.upload_bytes(
                access_token=access_token,
                file_path=file_path,
                file_name=item.file_name,
            )

            # Persist upload token so crash recovery knows raw byte transfer succeeded
            self.repo.update_status(
                item.id,
                MediaItemStatus.UPLOADING,
                upload_token=upload_token,
            )

            # Step 2: Create media item via batchCreate
            batch_items = [{
                "uploadToken": upload_token,
                "fileName": item.file_name,
                "description": item.description[:1000] if item.description else "",
            }]

            results = self.api.batch_create(
                access_token=access_token,
                items=batch_items,
                album_id=album_id,
            )

            if not results:
                # Ambiguous — upload may have succeeded
                self.repo.update_status(
                    item.id,
                    MediaItemStatus.NEEDS_REVIEW,
                    error_message="batchCreate returned empty results — upload status ambiguous",
                )
                return UploadResult(
                    success=False,
                    needs_review=True,
                    error_message="batchCreate returned no results",
                )

            result = results[0]
            status_info = result.get("status", {})
            status_code = status_info.get("code", -1) if isinstance(status_info, dict) else -1

            # Check for status message (Google uses "code" 0 for success, or has "message")
            if "mediaItem" in result:
                media_item = result["mediaItem"]
                media_id = media_item.get("id", "")

                self.repo.update_status(
                    item.id,
                    MediaItemStatus.UPLOADED,
                    google_media_id=media_id,
                    upload_token=upload_token,
                )

                logger.info(
                    "Upload successful: %s → Google Media ID: %s",
                    item.file_name, media_id,
                )

                return UploadResult(success=True, media_item_id=media_id)

            else:
                error_msg = status_info.get("message", "Unknown batchCreate error") if isinstance(status_info, dict) else str(status_info)
                is_retryable = status_code in (429, 500, 502, 503, 504)

                new_status = (
                    MediaItemStatus.FAILED_RETRYABLE if is_retryable
                    else MediaItemStatus.FAILED_PERMANENT
                )
                self.repo.update_status(item.id, new_status, error_message=error_msg)

                return UploadResult(
                    success=False,
                    error_message=error_msg,
                    is_retryable=is_retryable,
                )

        except GooglePhotosAPIError as exc:
            logger.warning("API error uploading %s: %s", item.file_name, exc)

            new_status = (
                MediaItemStatus.FAILED_RETRYABLE if exc.is_retryable
                else MediaItemStatus.FAILED_PERMANENT
            )

            # Special case: if we uploaded bytes but batchCreate timed out,
            # mark as NEEDS_REVIEW since the upload may have completed
            if exc.status_code == 0 and "timeout" in str(exc).lower():
                new_status = MediaItemStatus.NEEDS_REVIEW

            self.repo.update_status(item.id, new_status, error_message=str(exc))
            self.repo.increment_retry(item.id)

            return UploadResult(
                success=False,
                error_message=str(exc),
                is_retryable=exc.is_retryable,
                needs_review=(new_status == MediaItemStatus.NEEDS_REVIEW),
            )

        except Exception as exc:
            logger.error("Unexpected error uploading %s: %s", item.file_name, exc)
            self.repo.update_status(
                item.id,
                MediaItemStatus.FAILED_RETRYABLE,
                error_message=str(exc),
            )
            self.repo.increment_retry(item.id)
            return UploadResult(
                success=False,
                error_message=str(exc),
                is_retryable=True,
            )

    def upload_with_retry(
        self,
        item: MediaItem,
        file_path: Path,
        access_token: str,
        album_id: str = "",
        cancel_flag: callable = lambda: False,
    ) -> UploadResult:
        """Upload with exponential backoff retry.

        Args:
            cancel_flag: Callable returning True if the operation should be cancelled.
        """
        last_result: UploadResult | None = None

        for attempt in range(self.max_retries + 1):
            if cancel_flag():
                logger.info("Upload cancelled for %s", item.file_name)
                return UploadResult(
                    success=False,
                    error_message="Upload cancelled by user",
                )

            if attempt > 0:
                delay = self._calculate_backoff(attempt)
                logger.info(
                    "Retry %d/%d for %s in %.1f seconds",
                    attempt, self.max_retries, item.file_name, delay,
                )
                time.sleep(delay)

            result = self.upload_file(item, file_path, access_token, album_id)

            if result.success:
                return result

            last_result = result

            if not result.is_retryable:
                logger.warning(
                    "Permanent failure for %s: %s", item.file_name, result.error_message
                )
                return result

        # Exhausted all retries
        if last_result:
            if item.id:
                self.repo.update_status(
                    item.id,
                    MediaItemStatus.FAILED_PERMANENT,
                    error_message=f"Exhausted {self.max_retries} retries: {last_result.error_message}",
                )
            return last_result

        return UploadResult(success=False, error_message="No upload attempts made")

    def _calculate_backoff(self, attempt: int) -> float:
        """Calculate delay with exponential backoff and jitter."""
        delay = min(self.base_delay * (2 ** (attempt - 1)), self.max_delay)
        jitter = random.uniform(0, delay * 0.5)
        return delay + jitter
