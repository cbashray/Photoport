"""Quota and storage checking service."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import requests

from photoport.config import GOOGLE_DRIVE_ABOUT_URL

logger = logging.getLogger("photoport.google_photos.quota_service")


@dataclass
class StorageInfo:
    """Google account storage information."""

    total_bytes: int = 0
    used_bytes: int = 0
    free_bytes: int = 0
    drive_usage_bytes: int = 0
    drive_trash_bytes: int = 0
    available: bool = False
    is_unknown: bool = False
    error: str = ""
    user_email: str = ""
    display_name: str = ""

    @property
    def usage_percent(self) -> float:
        if self.total_bytes == 0:
            return 0.0
        return (self.used_bytes / self.total_bytes) * 100

    def fit_status(self, required_bytes: int, safety_margin_bytes: int = 0) -> str:
        """Return tri-state storage fit: 'ENOUGH', 'INSUFFICIENT', or 'UNKNOWN'."""
        if not self.available or self.is_unknown:
            return "UNKNOWN"
        total_needed = required_bytes + safety_margin_bytes
        return "ENOUGH" if self.free_bytes >= total_needed else "INSUFFICIENT"

    def can_fit(self, required_bytes: int, safety_margin_bytes: int = 0) -> bool:
        """Check if the planned upload can fit in available storage.

        Note: Returns False if storage is unknown or insufficient.
        Use fit_status() to distinguish unknown from confirmed insufficient.
        """
        if not self.available or self.is_unknown:
            return False
        total_needed = required_bytes + safety_margin_bytes
        return self.free_bytes >= total_needed


class QuotaService:
    """Check Google account storage quotas.

    Uses the Google Drive API (about.get) since the Photos API
    does not expose storage quota information. Requires the
    `drive.readonly` OAuth scope.
    """

    def get_storage_info(self, access_token: str) -> StorageInfo:
        """Retrieve storage quota from Google Drive API.

        Returns:
            StorageInfo with quota details, or error info if unavailable.
        """
        info = StorageInfo()

        try:
            headers = {"Authorization": f"Bearer {access_token}"}
            params = {"fields": "user,storageQuota"}

            response = requests.get(
                GOOGLE_DRIVE_ABOUT_URL,
                headers=headers,
                params=params,
                timeout=15,
            )

            if response.status_code != 200:
                info.error = f"Drive API returned status {response.status_code}"
                info.is_unknown = True
                logger.warning("Storage quota check failed: %s", info.error)
                return info

            data = response.json()
            user_data = data.get("user", {})
            info.user_email = user_data.get("emailAddress", "")
            info.display_name = user_data.get("displayName", "")
            quota = data.get("storageQuota", {})

            limit_str = quota.get("limit", "")
            usage_str = quota.get("usage", "0")
            drive_usage = quota.get("usageInDrive", "0")
            drive_trash = quota.get("usageInDriveTrash", "0")

            if not limit_str or limit_str == "-1":
                # Storage limit unmetered / not reported (e.g., some Workspace/pooled accounts)
                info.error = "Storage limit is unmetered or not reported by Google (capacity unknown)"
                info.is_unknown = True
                info.available = False
                info.used_bytes = int(usage_str)
                info.drive_usage_bytes = int(drive_usage)
                info.drive_trash_bytes = int(drive_trash)
                logger.info("Storage limit not reported (unmetered or pooled organization account)")
                return info

            info.total_bytes = int(limit_str)
            info.used_bytes = int(usage_str)
            info.free_bytes = info.total_bytes - info.used_bytes
            info.drive_usage_bytes = int(drive_usage)
            info.drive_trash_bytes = int(drive_trash)
            info.available = True

            logger.info(
                "Storage: %s total, %s used, %s free (%.1f%%)",
                _format_gb(info.total_bytes),
                _format_gb(info.used_bytes),
                _format_gb(info.free_bytes),
                info.usage_percent,
            )
            return info

        except requests.exceptions.RequestException as exc:
            info.error = f"Network error checking storage: {exc}"
            logger.warning(info.error)
            return info
        except (ValueError, KeyError) as exc:
            info.error = f"Error parsing storage response: {exc}"
            logger.warning(info.error)
            return info


def _format_gb(n: int) -> str:
    """Format bytes as GB string."""
    return f"{n / (1024 ** 3):.2f} GB"
