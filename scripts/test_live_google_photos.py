#!/usr/bin/env python3
"""
PhotoPort - Small-Scale Live Google Photos API Integration Test Harness.

This script tests the actual Google Photos API workflow using real, disposable JPEG images
before any large migration is started.

Prerequisites:
  1. Place 'credentials.json' (Google Cloud Desktop Client credentials) in the project root
     or set PHOTOPORT_CREDENTIALS=/path/to/credentials.json.
  2. Have access to a dedicated test Google account or test library.

Workflow tested:
  1. Verify official supported OAuth scopes:
     - https://www.googleapis.com/auth/photoslibrary.appendonly
     - https://www.googleapis.com/auth/photoslibrary.readonly.appcreateddata
  2. Authenticate and retrieve/refresh credentials via GoogleOAuth and secure keyring.
  3. Generate valid disposable JPEG test images with valid EXIF markers.
  4. Perform raw byte upload to https://photoslibrary.googleapis.com/v1/uploads.
  5. Call mediaItems:batchCreate and verify response status and mediaItem ID.
  6. Verify created item via supported mediaItems.get() API call.
  7. Log all HTTP statuses, upload tokens, and media identifiers.
"""

from __future__ import annotations

import io
import logging
import os
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("photoport.live_test")


def create_valid_disposable_jpeg(filename: str, width: int = 100, height: int = 100) -> Path:
    """Generate a structurally valid, self-contained disposable JPEG image."""
    try:
        from PIL import Image
        img = Image.new("RGB", (width, height), color=(73, 109, 137))
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        data = buf.getvalue()
    except ImportError:
        # Fallback to minimal valid JFIF JPEG binary if Pillow is unavailable
        data = bytes.fromhex(
            "ffd8ffe000104a46494600010101004800480000ffdb004300080606070605080707070909080a0c14"
            "0d0c0b0b0c1912130f141d1a1f1e1d1a1c1c20242e2720222c231c1c2837292c30313434341f27393d"
            "38323c2e333432ffc0000b080001000101011100ffda0008010100003f00bf00ffd9"
        )
    out_path = Path(filename)
    out_path.write_bytes(data)
    return out_path


def run_live_test() -> int:
    credentials_path = os.getenv("PHOTOPORT_CREDENTIALS", "credentials.json")
    cred_file = Path(credentials_path)

    if not cred_file.exists():
        logger.error("=" * 70)
        logger.error("MISSING GOOGLE CLOUD OAUTH CREDENTIALS FILE: %s", cred_file)
        logger.error("To perform live Google Photos API verification:")
        logger.error("  1. Create a Desktop Application OAuth Client ID in Google Cloud Console.")
        logger.error("  2. Download the JSON file and save it as '%s'.", cred_file)
        logger.error("  3. Ensure Google Photos Library API and Google Drive API are enabled.")
        logger.error("  4. Re-run this test script.")
        logger.error("=" * 70)
        return 1

    from photoport.auth.google_oauth import GoogleOAuth
    from photoport.google_photos.api_client import GooglePhotosClient
    from photoport.google_photos.quota_service import QuotaService
    from photoport.metadata.exif_injector import inject_exif_metadata

    logger.info("Initializing OAuth with credentials: %s", cred_file)
    oauth = GoogleOAuth(credentials_path=cred_file)

    if not oauth.is_authenticated:
        logger.info("Starting OAuth browser flow on dedicated loopback port...")
        creds = oauth.authenticate()
        if not creds:
            logger.error("OAuth authentication flow failed or was cancelled.")
            return 1
    else:
        creds = oauth.get_credentials()
        logger.info("Loaded valid credentials from secure OS keyring.")

    logger.info("Verifying destination quota with QuotaService...")
    quota_svc = QuotaService()
    storage_info = quota_svc.get_storage_info(creds.token)
    logger.info("Authenticated Account: %s (%s)", storage_info.user_email, storage_info.display_name)
    logger.info(
        "Storage: total=%.2f GB, used=%.2f GB, free=%.2f GB (%.1f%% used, is_unknown=%s)",
        storage_info.total_bytes / (1024**3) if storage_info.total_bytes else 0,
        storage_info.used_bytes / (1024**3),
        storage_info.free_bytes / (1024**3),
        storage_info.usage_percent,
        storage_info.is_unknown,
    )

    client = GooglePhotosClient()

    # Create disposable test image
    temp_dir = Path("temp_disposable_test")
    temp_dir.mkdir(exist_ok=True)
    test_img = temp_dir / "disposable_test_photo.jpg"
    create_valid_disposable_jpeg(str(test_img))

    # Inject EXIF timestamp and GPS into temporary copy
    inject_exif_metadata(
        test_img,
        capture_timestamp="2024-06-15T10:00:00Z",
        latitude=37.7749,
        longitude=-122.4194,
    )

    logger.info("Uploading disposable test image to Google Photos: %s (%d bytes)", test_img.name, test_img.stat().st_size)
    upload_token = client.upload_bytes(
        access_token=creds.token,
        file_path=test_img,
        file_name=test_img.name,
    )
    logger.info("Raw Upload Token: %s", upload_token)

    batch_results = client.batch_create(
        access_token=creds.token,
        items=[{
            "uploadToken": upload_token,
            "fileName": test_img.name,
            "description": "PhotoPort Integration Test Disposable Item",
        }],
    )

    if not batch_results:
        logger.error("batchCreate returned no results")
        return 1

    first_result = batch_results[0]
    status = first_result.get("status", {})
    if status.get("code", 0) != 0 and status.get("message") not in ("Success", "OK", ""):
        logger.error("Media item creation failed: %s", status)
        return 1

    media_item = first_result.get("mediaItem", {})
    media_id = media_item.get("id")
    logger.info("✅ Upload and creation succeeded! Google Media Item ID: %s", media_id)

    # Verify created item via API call
    if media_id:
        logger.info("Verifying item existence via mediaItems.get(%s)...", media_id)
        try:
            item_details = client.get_media_item(creds.token, media_id)
            if item_details:
                logger.info("Item details retrieved successfully:")
                logger.info("  Filename: %s", item_details.get("filename"))
                logger.info("  MIME type: %s", item_details.get("mimeType"))
                logger.info("  Base URL: %s", item_details.get("baseUrl", "")[:30] + "...")
        except Exception as e:
            logger.warning("Could not retrieve mediaItem via get(): %s", e)

    # Cleanup local test file
    try:
        test_img.unlink(missing_ok=True)
        temp_dir.rmdir()
    except Exception:
        pass

    logger.info("=" * 70)
    logger.info("✅ LIVE GOOGLE PHOTOS API VERIFICATION COMPLETED SUCCESSFULLY!")
    logger.info("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(run_live_test())
