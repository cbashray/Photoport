"""Upload backend abstractions for PhotoPort.

Decouples upload strategies into explicit, isolated backends:
1. OfficialOriginalBackend: standard Google Photos API, full original resolution, 100% quota charged.
2. StorageSaverBackend: client-side non-destructive compression & downscaling, standard API, uploaded bytes charged.
3. ExperimentalGpmcBackend: isolated experimental stub for unofficial gpmc / Pixel spoofing approach.
"""

from __future__ import annotations

import abc
import logging
from pathlib import Path
from typing import Any

from photoport.config import AppConfig
from photoport.media.converter import MediaConverter
from photoport.storage.models import UploadQualityMode

logger = logging.getLogger("photoport.google_photos.backend")


class UploadBackend(abc.ABC):
    """Abstract interface defining an upload quality backend."""

    @property
    @abc.abstractmethod
    def quality_mode(self) -> UploadQualityMode:
        """The quality mode handled by this backend."""
        ...

    @property
    @abc.abstractmethod
    def display_name(self) -> str:
        """Human-readable display name for the UI."""
        ...

    @property
    @abc.abstractmethod
    def badge_text(self) -> str:
        """Short badge text for cards (e.g. 'Supported', 'Client Compressed', 'Experimental')."""
        ...

    @property
    @abc.abstractmethod
    def description(self) -> str:
        """Comprehensive explanation of quality, compression, and storage implications."""
        ...

    @abc.abstractmethod
    def is_available(self) -> tuple[bool, str]:
        """Check whether this backend can be used in the current environment.

        Returns:
            Tuple of (available: bool, explanation: str).
        """
        ...

    def detect_capabilities(self) -> dict[str, Any]:
        """Return capability, auth requirements, and compliance metadata for this backend."""
        return {
            "has_supported_zero_quota_api": False,
            "requires_master_token": False,
            "requires_device_spoofing": False,
            "violates_terms_of_service": False,
            "is_available": self.is_available()[0],
        }

    @abc.abstractmethod
    def estimate_upload_size(self, original_bytes: int, is_photo: bool = True) -> int:
        """Estimate the upload payload size in bytes for a given item size."""
        ...

    @abc.abstractmethod
    def prepare_media(
        self,
        media_path: Path,
        temp_dir: Path,
        is_photo: bool = True,
    ) -> tuple[Path, bool]:
        """Prepare media file for uploading.

        Args:
            media_path: Path to extracted original file.
            temp_dir: Temporary directory for staging converted files.
            is_photo: True if media is an image.

        Returns:
            Tuple of (upload_path: Path, is_temporary: bool).
            If is_temporary is True, caller must delete upload_path after upload completes.
        """
        ...

    def cleanup_prepared(self, prepared_path: Path, is_temporary: bool) -> None:
        """Clean up any temporary prepared files."""
        if is_temporary and prepared_path.exists():
            try:
                prepared_path.unlink()
                logger.debug("Cleaned up temporary prepared file: %s", prepared_path.name)
            except OSError as exc:
                logger.warning("Could not delete temporary prepared file %s: %s", prepared_path, exc)


class OfficialOriginalBackend(UploadBackend):
    """Supported official Google Photos API backend uploading bit-for-bit originals."""

    def __init__(self, config: AppConfig | None = None) -> None:
        self.config = config

    @property
    def quality_mode(self) -> UploadQualityMode:
        return UploadQualityMode.ORIGINAL

    @property
    def display_name(self) -> str:
        return "Original Quality"

    @property
    def badge_text(self) -> str:
        return "Official API • Full Fidelity"

    @property
    def description(self) -> str:
        return (
            "Preserves full original resolution and bit-for-bit file contents. "
            "Uploaded directly via supported Google Photos Library API. "
            "Consumes 100% of uploaded file size against your Google One quota."
        )

    def is_available(self) -> tuple[bool, str]:
        return True, "Supported official Google Photos Library API."

    def detect_capabilities(self) -> dict[str, Any]:
        return {
            "backend_id": "official_original",
            "has_supported_zero_quota_api": False,
            "requires_master_token": False,
            "requires_device_spoofing": False,
            "violates_terms_of_service": False,
            "is_available": True,
            "supports_official_api": True,
            "metered_against_quota": True,
        }

    def estimate_upload_size(self, original_bytes: int, is_photo: bool = True) -> int:
        return original_bytes

    def prepare_media(
        self,
        media_path: Path,
        temp_dir: Path,
        is_photo: bool = True,
    ) -> tuple[Path, bool]:
        # Original quality uses the extracted file directly without modification
        return media_path, False


class StorageSaverBackend(UploadBackend):
    """Storage Saver backend that applies local client-side downscaling and compression."""

    def __init__(
        self,
        config: AppConfig | None = None,
        converter: MediaConverter | None = None,
    ) -> None:
        self.config = config
        max_mp = config.storage_saver_max_megapixels if config else 16.0
        quality = config.storage_saver_quality if config else 85
        self.estimated_ratio = config.storage_saver_estimated_ratio if config else 0.50
        self.converter = converter or MediaConverter(max_megapixels=max_mp, quality=quality)

    @property
    def quality_mode(self) -> UploadQualityMode:
        return UploadQualityMode.STORAGE_SAVER

    @property
    def display_name(self) -> str:
        return "Storage Saver"

    @property
    def badge_text(self) -> str:
        return "Client Compression • ~50% Smaller"

    @property
    def description(self) -> str:
        return (
            "Downscales photos >16 MP and applies high-quality JPEG compression (Q85) "
            "prior to upload. Source files are NEVER modified. Reduces payload by ~40–60%. "
            "IMPORTANT: Google still charges the actual uploaded bytes against your storage quota."
        )

    def is_available(self) -> tuple[bool, str]:
        return True, "Local client-side conversion pipeline available."

    def detect_capabilities(self) -> dict[str, Any]:
        return {
            "backend_id": "storage_saver",
            "has_supported_zero_quota_api": False,
            "requires_master_token": False,
            "requires_device_spoofing": False,
            "violates_terms_of_service": False,
            "is_available": True,
            "supports_client_compression": True,
            "metered_against_quota": True,
        }

    def estimate_upload_size(self, original_bytes: int, is_photo: bool = True) -> int:
        if is_photo:
            return max(1, int(original_bytes * self.estimated_ratio))
        # Non-photos (videos, etc.) are uploaded at original size unless a video pipeline is configured
        return original_bytes

    def prepare_media(
        self,
        media_path: Path,
        temp_dir: Path,
        is_photo: bool = True,
    ) -> tuple[Path, bool]:
        if not is_photo:
            return media_path, False

        res = self.converter.convert_photo(media_path, temp_dir)
        if res.converted:
            return res.output_path, True
        return media_path, False


class ExperimentalGpmcBackend(UploadBackend):
    """Isolated experimental stub for unofficial gpmc / Pixel spoofing approach.

    Strictly disabled by default to prevent Terms of Service violations and account bans.
    """

    def __init__(self, config: AppConfig | None = None) -> None:
        self.config = config

    @property
    def quality_mode(self) -> UploadQualityMode:
        return UploadQualityMode.EXPERIMENTAL_GPMC

    @property
    def display_name(self) -> str:
        return "Experimental Zero-Quota (Pixel Spoofing)"

    @property
    def badge_text(self) -> str:
        return "Unavailable • Unsupported by Google API"

    @property
    def description(self) -> str:
        return (
            "UNAVAILABLE & UNSUPPORTED. Google provides no official zero-quota API or scope. "
            "Upstream tools rely on spoofing 2016 Pixel XL hardware properties and extracting Android master tokens, "
            "directly violating Google Terms of Service and risking permanent Google Account suspension."
        )

    def is_available(self) -> tuple[bool, str]:
        return (
            False,
            "Unavailable: Google provides no legitimate zero-quota API. "
            "Unofficial device spoofing violates Google Terms of Service and requires master tokens. "
            "Original Quality is the supported alternative.",
        )

    def get_unsupported_reasons(self) -> list[str]:
        """Detailed technical reasons why zero-quota cannot be supported legitimately."""
        return [
            "Google provides no public developer API or scope for zero-quota uploads.",
            "The official Google Photos Library REST API meters 100% of uploaded bytes against Google One quota.",
            "Unofficial gpmc requires extracting an Android Master Token (aas_et/...) or user password, bypassing OAuth 2.0 PKCE.",
            "Hardware spoofing (emulating a 2016 Pixel XL) violates Google Terms of Service and API Acceptable Use Policy.",
            "Google fraud detection flags anomalous device signatures, creating a severe risk of permanent Google Account suspension.",
        ]

    def detect_capabilities(self) -> dict[str, Any]:
        """Audit capabilities, authorization requirements, and account eligibility."""
        return {
            "backend_id": "experimental_gpmc",
            "has_supported_zero_quota_api": False,
            "requires_master_token": True,
            "requires_device_spoofing": True,
            "violates_terms_of_service": True,
            "is_available": False,
            "risk_level": "CRITICAL_ACCOUNT_SUSPENSION",
            "is_eligible": False,
            "eligible_account_types": [],  # No account tier is legitimately eligible
            "recommended_fallback": UploadQualityMode.ORIGINAL,
            "limitation_reasons": self.get_unsupported_reasons(),
        }

    @property
    def fallback_backend(self) -> UploadBackend:
        """Safe supported fallback backend (OfficialOriginalBackend)."""
        return OfficialOriginalBackend(self.config)

    def estimate_upload_size(self, original_bytes: int, is_photo: bool = True) -> int:
        # Zero-quota cannot be guaranteed without live testing; returned as 0 for speculative modeling
        return 0

    def prepare_media(
        self,
        media_path: Path,
        temp_dir: Path,
        is_photo: bool = True,
    ) -> tuple[Path, bool]:
        reasons = "; ".join(self.get_unsupported_reasons()[:2])
        raise NotImplementedError(
            f"Zero-quota upload mode is unavailable because Google provides no legitimate zero-quota API ({reasons}). "
            "PhotoPort will safely fall back to the supported Original Quality backend."
        )


def get_upload_backend(
    mode: UploadQualityMode | str,
    config: AppConfig | None = None,
) -> UploadBackend:
    """Factory to retrieve the appropriate upload backend for a quality mode."""
    if isinstance(mode, str):
        try:
            mode = UploadQualityMode(mode)
        except ValueError:
            mode = UploadQualityMode.ORIGINAL

    if mode == UploadQualityMode.ORIGINAL:
        return OfficialOriginalBackend(config)
    elif mode == UploadQualityMode.STORAGE_SAVER:
        return StorageSaverBackend(config)
    elif mode == UploadQualityMode.EXPERIMENTAL_GPMC:
        return ExperimentalGpmcBackend(config)

    return OfficialOriginalBackend(config)
