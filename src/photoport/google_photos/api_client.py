"""Google Photos API client for uploads and album management."""

from __future__ import annotations

import logging
from pathlib import Path

import requests

from photoport.config import (
    GOOGLE_PHOTOS_ALBUMS_URL,
    GOOGLE_PHOTOS_BATCH_CREATE_URL,
    GOOGLE_PHOTOS_MEDIA_ITEMS_URL,
    GOOGLE_PHOTOS_UPLOAD_URL,
    MAX_BATCH_CREATE_ITEMS,
    UPLOAD_BUFFER_SIZE,
)
from photoport.utils.file_types import get_mime_type

logger = logging.getLogger("photoport.google_photos.api_client")


class GooglePhotosAPIError(Exception):
    """Error from the Google Photos API."""

    def __init__(self, message: str, status_code: int = 0, is_retryable: bool = False) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.is_retryable = is_retryable


class GooglePhotosClient:
    """Low-level Google Photos API client.

    Handles raw byte uploads, media item creation, and album operations.
    All methods require a valid access token.
    """

    def __init__(self, timeout: int = 300) -> None:
        self.timeout = timeout
        self._session = requests.Session()

    def upload_bytes(
        self,
        access_token: str,
        file_path: Path,
        file_name: str,
    ) -> str:
        """Upload raw media bytes to Google Photos.

        Uses streaming to avoid loading the entire file into memory.

        Args:
            access_token: Valid OAuth access token.
            file_path: Local path to the media file.
            file_name: Original file name for the upload.

        Returns:
            Upload token string for use with batchCreate.

        Raises:
            GooglePhotosAPIError: On upload failure.
        """
        mime_type = get_mime_type(file_name)
        file_size = file_path.stat().st_size

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-type": "application/octet-stream",
            "X-Goog-Upload-Content-Type": mime_type,
            "X-Goog-Upload-Protocol": "raw",
            "X-Goog-Upload-File-Name": file_name,
        }

        logger.debug("Uploading %s (%d bytes, %s)", file_name, file_size, mime_type)

        try:
            with open(file_path, "rb") as f:
                response = self._session.post(
                    GOOGLE_PHOTOS_UPLOAD_URL,
                    headers=headers,
                    data=_streaming_reader(f, UPLOAD_BUFFER_SIZE),
                    timeout=self.timeout,
                )

            if response.status_code == 200:
                upload_token = response.text.strip()
                if not upload_token:
                    raise GooglePhotosAPIError(
                        "Upload succeeded but returned empty token",
                        status_code=200,
                        is_retryable=True,
                    )
                logger.debug("Upload token received for %s", file_name)
                return upload_token

            self._handle_error(response, f"upload bytes for {file_name}")

        except requests.exceptions.Timeout as exc:
            raise GooglePhotosAPIError(
                f"Upload timed out for {file_name}",
                status_code=0,
                is_retryable=True,
            ) from exc
        except requests.exceptions.ConnectionError as exc:
            raise GooglePhotosAPIError(
                f"Connection error uploading {file_name}: {exc}",
                status_code=0,
                is_retryable=True,
            ) from exc

        # Should not reach here due to _handle_error raising
        raise GooglePhotosAPIError(f"Unexpected upload failure for {file_name}")

    def batch_create(
        self,
        access_token: str,
        items: list[dict],
        album_id: str = "",
    ) -> list[dict]:
        """Create media items from upload tokens.

        Args:
            access_token: Valid OAuth access token.
            items: List of dicts with 'uploadToken', 'fileName', and optional 'description'.
            album_id: Optional album ID to add items to.

        Returns:
            List of result dicts from the API response.

        Raises:
            GooglePhotosAPIError: On API failure.
            ValueError: If items exceeds MAX_BATCH_CREATE_ITEMS.
        """
        if len(items) > MAX_BATCH_CREATE_ITEMS:
            raise ValueError(
                f"batchCreate supports max {MAX_BATCH_CREATE_ITEMS} items, got {len(items)}"
            )

        new_media_items = []
        for item in items:
            entry: dict = {
                "simpleMediaItem": {
                    "uploadToken": item["uploadToken"],
                    "fileName": item.get("fileName", ""),
                },
            }
            if item.get("description"):
                entry["description"] = item["description"][:1000]
            new_media_items.append(entry)

        body: dict = {"newMediaItems": new_media_items}
        if album_id:
            body["albumId"] = album_id

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

        try:
            response = self._session.post(
                GOOGLE_PHOTOS_BATCH_CREATE_URL,
                headers=headers,
                json=body,
                timeout=60,
            )

            if response.status_code == 200:
                data = response.json()
                results = data.get("newMediaItemResults", [])
                logger.debug("batchCreate returned %d results", len(results))
                return results

            self._handle_error(response, "batchCreate")

        except requests.exceptions.Timeout as exc:
            raise GooglePhotosAPIError(
                "batchCreate timed out",
                status_code=0,
                is_retryable=True,
            ) from exc
        except requests.exceptions.ConnectionError as exc:
            raise GooglePhotosAPIError(
                f"Connection error during batchCreate: {exc}",
                status_code=0,
                is_retryable=True,
            ) from exc

        raise GooglePhotosAPIError("Unexpected batchCreate failure")

    def create_album(self, access_token: str, title: str) -> dict:
        """Create a new album.

        Returns:
            Album dict with 'id', 'title', 'productUrl'.
        """
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }
        body = {"album": {"title": title}}

        response = self._session.post(
            GOOGLE_PHOTOS_ALBUMS_URL,
            headers=headers,
            json=body,
            timeout=30,
        )

        if response.status_code == 200:
            album = response.json()
            logger.info("Created album '%s' (ID: %s)", title, album.get("id", ""))
            return album

        self._handle_error(response, f"create album '{title}'")
        raise GooglePhotosAPIError(f"Failed to create album '{title}'")

    def add_items_to_album(
        self,
        access_token: str,
        album_id: str,
        media_item_ids: list[str],
    ) -> None:
        """Add media items to an app-created album."""
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }
        body = {"mediaItemIds": media_item_ids}
        url = f"{GOOGLE_PHOTOS_ALBUMS_URL}/{album_id}:batchAddMediaItems"

        response = self._session.post(
            url, headers=headers, json=body, timeout=30,
        )

        if response.status_code == 200:
            logger.debug(
                "Added %d items to album %s", len(media_item_ids), album_id
            )
            return

        self._handle_error(response, f"add items to album {album_id}")

    def get_media_item(self, access_token: str, media_item_id: str) -> dict | None:
        """Retrieve a media item by ID (app-created content only)."""
        headers = {"Authorization": f"Bearer {access_token}"}
        url = f"{GOOGLE_PHOTOS_MEDIA_ITEMS_URL}/{media_item_id}"

        response = self._session.get(url, headers=headers, timeout=30)

        if response.status_code == 200:
            return response.json()
        elif response.status_code == 404:
            return None
        else:
            self._handle_error(response, f"get media item {media_item_id}")
            return None

    def _handle_error(self, response: requests.Response, context: str) -> None:
        """Parse error response and raise appropriate exception."""
        status = response.status_code
        try:
            error_body = response.json()
            error_msg = error_body.get("error", {}).get("message", response.text)
        except Exception:
            error_msg = response.text[:500]

        is_retryable = status in (429, 500, 502, 503, 504)

        if status == 429:
            logger.warning("Rate limited during %s: %s", context, error_msg)
        elif status == 401:
            logger.warning("Authentication expired during %s", context)
        elif status == 403:
            logger.error("Permission denied during %s: %s", context, error_msg)
        else:
            logger.error("API error %d during %s: %s", status, context, error_msg)

        raise GooglePhotosAPIError(
            f"API error {status} during {context}: {error_msg}",
            status_code=status,
            is_retryable=is_retryable,
        )

    def close(self) -> None:
        """Close the HTTP session."""
        self._session.close()


def _streaming_reader(file_obj, chunk_size: int):
    """Generator that yields file data in chunks for streaming upload."""
    while True:
        chunk = file_obj.read(chunk_size)
        if not chunk:
            break
        yield chunk
