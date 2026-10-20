"""Storage Preflight Service — estimates migration payload, verifies destination quota,
and enforces capacity safeguards across single ZIPs, multi-ZIP archives, and extracted folders.

Unified preflight service used across UI, MigrationManager, and CLI tools.
Never hardcodes user emails, storage plans, or capacities.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum

from photoport.archives.archive_scanner import ArchiveScanResult
from photoport.google_photos.quota_service import QuotaService, StorageInfo
from photoport.storage.models import MediaItemStatus, UploadQualityMode
from photoport.storage.repository import MediaItemRepository
from photoport.utils.formatting import format_bytes

logger = logging.getLogger("photoport.migration.preflight")


class PreflightStatus(Enum):
    """Tri-state capacity verification status."""
    ENOUGH = "ENOUGH"
    INSUFFICIENT = "INSUFFICIENT"
    UNKNOWN = "UNKNOWN"


@dataclass
class StoragePreflightResult:
    """Comprehensive result of storage preflight analysis."""

    status: PreflightStatus
    storage_info: StorageInfo

    # Payload statistics (in bytes and counts)
    total_discovered_items: int = 0
    total_discovered_bytes: int = 0
    eligible_items_count: int = 0
    eligible_media_bytes: int = 0
    duplicate_items_count: int = 0
    duplicate_bytes: int = 0
    oversized_items_count: int = 0
    oversized_bytes: int = 0
    unsupported_items_count: int = 0
    sidecar_items_count: int = 0

    # Resumed session accounting
    is_resumed_migration: bool = False
    already_uploaded_items_count: int = 0
    already_uploaded_bytes: int = 0
    ambiguous_items_count: int = 0
    ambiguous_bytes: int = 0
    remaining_items_count: int = 0
    remaining_upload_bytes: int = 0

    # Quality mode and estimated payload
    quality_mode: UploadQualityMode = UploadQualityMode.ORIGINAL
    estimated_upload_bytes: int = 0

    # Safety buffer and total requirement
    safety_margin_percent: float = 5.0
    safety_margin_bytes: int = 0
    total_required_bytes: int = 0
    free_bytes: int = 0
    shortfall_bytes: int = 0

    # Explanations, limitations, and recommendations
    warnings: list[str] = field(default_factory=list)
    scanning_limitations: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    error_message: str = ""

    @property
    def can_proceed(self) -> bool:
        """Only True if capacity is definitively confirmed sufficient."""
        return self.status == PreflightStatus.ENOUGH

    def summary_text(self) -> str:
        """Return a readable multi-line summary of preflight results."""
        lines = [
            f"Preflight Status     : {self.status.value}",
            f"Quality Mode         : {self.quality_mode.value}",
            f"Destination Account  : {self.storage_info.user_email or 'Not connected'}",
            f"Available Storage    : {format_bytes(self.free_bytes)}",
            f"Raw Media Size       : {format_bytes(self.remaining_upload_bytes)} ({self.remaining_items_count} files)",
            f"Estimated Upload     : {format_bytes(self.estimated_upload_bytes or self.remaining_upload_bytes)}",
            f"Safety Margin        : {format_bytes(self.safety_margin_bytes)} ({self.safety_margin_percent:.1f}%)",
            f"Total Required       : {format_bytes(self.total_required_bytes)}",
        ]
        if self.shortfall_bytes > 0:
            lines.append(f"Capacity Shortfall   : {format_bytes(self.shortfall_bytes)}")
        if self.is_resumed_migration:
            lines.append(
                f"Resumed Migration    : {self.already_uploaded_items_count} files ({format_bytes(self.already_uploaded_bytes)}) already uploaded"
            )
        if self.ambiguous_items_count > 0:
            lines.append(
                f"Ambiguous In-Flight  : {self.ambiguous_items_count} files ({format_bytes(self.ambiguous_bytes)}) counted conservatively"
            )
        return "\n".join(lines)


class StoragePreflightService:
    """Unified service for estimating upload size and checking destination capacity."""

    def __init__(self, quota_service: QuotaService | None = None) -> None:
        self.quota_service = quota_service or QuotaService()

    def run_preflight(
        self,
        scan_result: ArchiveScanResult | None = None,
        media_repo: MediaItemRepository | None = None,
        access_token: str | None = None,
        storage_info: StorageInfo | None = None,
        total_scan_bytes: int | None = None,
        safety_margin_percent: float = 5.0,
        safety_margin_min_bytes: int = 500 * 1024 * 1024,
        max_retries: int = 5,
        quality_mode: UploadQualityMode | str = UploadQualityMode.ORIGINAL,
        storage_saver_estimated_ratio: float = 0.50,
    ) -> StoragePreflightResult:
        """Run storage preflight analysis comparing payload with available destination capacity.

        Args:
            scan_result: ArchiveScanResult from scanning archives or folders.
            media_repo: MediaItemRepository for ledger items and resumed state.
            access_token: OAuth access token for fetching fresh destination quota.
            storage_info: Pre-fetched StorageInfo (fetched via access_token if omitted).
            total_scan_bytes: Explicit payload size in bytes (e.g. for CLI audits or target estimates).
            safety_margin_percent: Percentage buffer for live storage variance.
            safety_margin_min_bytes: Minimum byte buffer for safety margin.
            max_retries: Maximum upload retry threshold.

        Returns:
            StoragePreflightResult with status ENOUGH, INSUFFICIENT, or UNKNOWN.
        """
        # Step 1: Retrieve fresh quota information if token is available and storage_info not provided
        if storage_info is None and access_token:
            try:
                storage_info = self.quota_service.get_storage_info(access_token)
            except Exception as exc:
                logger.error("Failed to fetch destination storage info: %s", exc)
                storage_info = StorageInfo(is_unknown=True, error=str(exc))
        elif storage_info is None:
            storage_info = StorageInfo(
                is_unknown=True,
                error="Not authenticated: Connect a Google account to verify storage.",
            )

        # Step 2: Extract scan-level payload metrics
        total_discovered_items = 0
        total_discovered_bytes = 0
        eligible_items_count = 0
        eligible_media_bytes = 0
        duplicate_items_count = 0
        duplicate_bytes = 0
        oversized_items_count = 0
        oversized_bytes = 0
        unsupported_items_count = 0
        sidecar_items_count = 0
        scanning_limitations: list[str] = []

        if scan_result:
            scan_result.calculate_metrics()
            total_discovered_items = (
                scan_result.total_media_count
                + scan_result.total_sidecar_count
                + scan_result.total_unsupported_count
            )
            total_discovered_bytes = scan_result.total_archive_size or scan_result.total_media_bytes
            eligible_items_count = scan_result.eligible_media_count
            eligible_media_bytes = scan_result.eligible_media_bytes
            duplicate_items_count = scan_result.total_duplicate_count
            duplicate_bytes = scan_result.duplicate_media_bytes
            oversized_items_count = scan_result.total_oversized_count
            oversized_bytes = scan_result.oversized_media_bytes
            unsupported_items_count = scan_result.total_unsupported_count
            sidecar_items_count = scan_result.total_sidecar_count
            scanning_limitations = list(scan_result.scanning_limitations)
        elif total_scan_bytes is not None:
            total_discovered_bytes = total_scan_bytes
            eligible_media_bytes = total_scan_bytes
            eligible_items_count = 1

        # Step 3: Account for resumed migrations using ledger repository
        is_resumed_migration = False
        already_uploaded_items_count = 0
        already_uploaded_bytes = 0
        ambiguous_items_count = 0
        ambiguous_bytes = 0
        remaining_items_count = eligible_items_count
        remaining_upload_bytes = eligible_media_bytes

        if media_repo and media_repo.total_count() > 0:
            status_counts = media_repo.count_by_status()
            uploaded_count = (
                status_counts.get(MediaItemStatus.UPLOADED.value, 0)
                + status_counts.get(MediaItemStatus.VERIFIED.value, 0)
            )

            if uploaded_count > 0:
                is_resumed_migration = True
                already_uploaded_items_count = uploaded_count
                already_uploaded_bytes = media_repo.uploaded_media_size()

            ambiguous_items_count = (
                status_counts.get(MediaItemStatus.UPLOADING.value, 0)
                + status_counts.get(MediaItemStatus.NEEDS_REVIEW.value, 0)
            )
            ambiguous_bytes = media_repo.ambiguous_media_size()

            remaining_items_count = media_repo.remaining_item_count(max_retries=max_retries)
            remaining_upload_bytes = media_repo.remaining_upload_size(max_retries=max_retries)

        # Step 4: Adjust estimated payload according to quality mode
        if isinstance(quality_mode, str):
            try:
                quality_mode = UploadQualityMode(quality_mode)
            except ValueError:
                quality_mode = UploadQualityMode.ORIGINAL

        warnings: list[str] = []
        recommendations: list[str] = []
        is_mode_uncertain = False

        if quality_mode == UploadQualityMode.ORIGINAL:
            estimated_upload_bytes = remaining_upload_bytes
        elif quality_mode == UploadQualityMode.STORAGE_SAVER:
            estimated_upload_bytes = max(0, int(remaining_upload_bytes * storage_saver_estimated_ratio))
            warnings.append(
                f"Storage Saver estimated payload: {format_bytes(estimated_upload_bytes)} "
                f"(~{int(storage_saver_estimated_ratio * 100)}% of raw {format_bytes(remaining_upload_bytes)}). "
                "NOTE: Uploads are NOT quota-free; Google charges actual uploaded bytes against your storage quota."
            )
            warnings.append(
                "Storage Saver size is an estimation; actual savings depend on source image resolution and compressibility."
            )
        elif quality_mode == UploadQualityMode.EXPERIMENTAL_GPMC:
            # Unofficial gpmc / Pixel spoofing cannot guarantee zero quota without live verification
            estimated_upload_bytes = 0
            is_mode_uncertain = True
            warnings.append(
                "CRITICAL: Experimental zero-quota backend relies on unofficial Pixel XL spoofing. "
                "Storage quota bypass is unverified and CANNOT be guaranteed. Google may still charge full quota or suspend the account."
            )
            recommendations.append(
                "Do not use Experimental Zero-Quota for personal or production libraries. Use supported Original Quality or Storage Saver."
            )
        else:
            estimated_upload_bytes = remaining_upload_bytes

        # Calculate configurable safety margin based on estimated upload bytes
        if estimated_upload_bytes > 0:
            calc_margin = int(estimated_upload_bytes * (safety_margin_percent / 100.0))
            safety_margin_bytes = max(calc_margin, safety_margin_min_bytes)
        else:
            safety_margin_bytes = 0

        total_required_bytes = estimated_upload_bytes + safety_margin_bytes
        free_bytes = storage_info.free_bytes if storage_info.available else 0

        # Step 5: Tri-state capacity comparison
        shortfall_bytes = 0

        if not storage_info.available or storage_info.is_unknown:
            status = PreflightStatus.UNKNOWN
            error_reason = storage_info.error or "Unknown destination storage capacity"
            warnings.append(f"Storage capacity could not be confirmed: {error_reason}")
            recommendations.append("Click 'Retry Storage Check' after checking internet connectivity.")
            recommendations.append("Ensure the Google Drive API is enabled in your Google Cloud project.")
            recommendations.append("If this is an unmetered institutional Workspace account, limit cannot be determined via Google API.")
        elif is_mode_uncertain:
            status = PreflightStatus.UNKNOWN
            warnings.append("Migration capacity cannot be confirmed: quota behavior for experimental mode is unverified.")
            recommendations.append("Switch to 'Original Quality' or 'Storage Saver' to verify capacity with supported Google APIs.")
        elif free_bytes < total_required_bytes:
            status = PreflightStatus.INSUFFICIENT
            shortfall_bytes = total_required_bytes - free_bytes
            warnings.append(
                f"Insufficient destination storage: Need {format_bytes(total_required_bytes)} "
                f"(includes {format_bytes(safety_margin_bytes)} safety buffer), but account has only {format_bytes(free_bytes)} free."
            )
            recommendations.append("Upgrade your Google One storage plan to accommodate your library.")
            recommendations.append("Switch to a different Google account with sufficient quota using 'Switch Account'.")
            recommendations.append("Empty your Google Drive Trash and delete unneeded files to free up space.")
            recommendations.append("Select fewer archives to migrate in smaller batches.")
        else:
            status = PreflightStatus.ENOUGH

        # Informative notifications for excluded or ambiguous items
        if duplicate_items_count > 0:
            warnings.append(
                f"{duplicate_items_count} duplicate entries ({format_bytes(duplicate_bytes)}) will be skipped during upload."
            )
        if oversized_items_count > 0:
            warnings.append(
                f"{oversized_items_count} files ({format_bytes(oversized_bytes)}) exceed Google Photos size limits and will be skipped."
            )
        if ambiguous_items_count > 0:
            warnings.append(
                f"{ambiguous_items_count} files ({format_bytes(ambiguous_bytes)}) have ambiguous crash status and were included conservatively."
            )

        return StoragePreflightResult(
            status=status,
            storage_info=storage_info,
            total_discovered_items=total_discovered_items,
            total_discovered_bytes=total_discovered_bytes,
            eligible_items_count=eligible_items_count,
            eligible_media_bytes=eligible_media_bytes,
            duplicate_items_count=duplicate_items_count,
            duplicate_bytes=duplicate_bytes,
            oversized_items_count=oversized_items_count,
            oversized_bytes=oversized_bytes,
            unsupported_items_count=unsupported_items_count,
            sidecar_items_count=sidecar_items_count,
            is_resumed_migration=is_resumed_migration,
            already_uploaded_items_count=already_uploaded_items_count,
            already_uploaded_bytes=already_uploaded_bytes,
            ambiguous_items_count=ambiguous_items_count,
            ambiguous_bytes=ambiguous_bytes,
            remaining_items_count=remaining_items_count,
            remaining_upload_bytes=remaining_upload_bytes,
            quality_mode=quality_mode,
            estimated_upload_bytes=estimated_upload_bytes,
            safety_margin_percent=safety_margin_percent,
            safety_margin_bytes=safety_margin_bytes,
            total_required_bytes=total_required_bytes,
            free_bytes=free_bytes,
            shortfall_bytes=shortfall_bytes,
            warnings=warnings,
            scanning_limitations=scanning_limitations,
            recommendations=recommendations,
            error_message=storage_info.error if not storage_info.available else "",
        )
