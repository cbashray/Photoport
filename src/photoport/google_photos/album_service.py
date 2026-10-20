"""Album service — create and populate albums via the Google Photos API."""

from __future__ import annotations

import logging

from photoport.google_photos.api_client import GooglePhotosAPIError, GooglePhotosClient
from photoport.storage.repository import AlbumRepository

logger = logging.getLogger("photoport.google_photos.album_service")


class AlbumService:
    """Manages album creation and population in Google Photos.

    Important limitation: albums created via the API are "app-created" albums.
    The API can only add items to albums that were created by this application.
    Pre-existing user albums cannot be modified.
    """

    def __init__(self, api_client: GooglePhotosClient, album_repo: AlbumRepository) -> None:
        self.api = api_client
        self.album_repo = album_repo

    def create_album(self, access_token: str, album_name: str) -> str | None:
        """Create an album in Google Photos.

        Returns:
            Google album ID if successful, None on failure.
        """
        # Check if already created
        existing = self.album_repo.get_by_name(album_name)
        if existing and existing.google_album_id:
            logger.info("Album '%s' already created (ID: %s)", album_name, existing.google_album_id)
            return existing.google_album_id

        try:
            result = self.api.create_album(access_token, album_name)
            album_id = result.get("id", "")
            if album_id:
                self.album_repo.update_google_id(album_name, album_id)
                logger.info("Created album '%s' → %s", album_name, album_id)
                return album_id
            else:
                logger.error("Album creation returned no ID for '%s'", album_name)
                return None

        except GooglePhotosAPIError as exc:
            logger.error("Failed to create album '%s': %s", album_name, exc)
            return None

    def add_items_to_album(
        self,
        access_token: str,
        album_name: str,
        media_item_ids: list[str],
    ) -> bool:
        """Add media items to an album.

        Args:
            album_name: The source album name.
            media_item_ids: Google Photos media item IDs to add.

        Returns:
            True if items were added successfully.
        """
        album = self.album_repo.get_by_name(album_name)
        if not album or not album.google_album_id:
            logger.warning(
                "Cannot add items to album '%s' — album not created", album_name
            )
            return False

        try:
            # API supports up to 50 items per request
            batch_size = 50
            for i in range(0, len(media_item_ids), batch_size):
                batch = media_item_ids[i : i + batch_size]
                self.api.add_items_to_album(
                    access_token, album.google_album_id, batch,
                )
                for _ in batch:
                    self.album_repo.increment_added(album_name)

            logger.info(
                "Added %d items to album '%s'", len(media_item_ids), album_name
            )
            return True

        except GooglePhotosAPIError as exc:
            logger.error(
                "Failed to add items to album '%s': %s", album_name, exc
            )
            return False

    def create_all_albums(
        self, access_token: str, album_names: list[str]
    ) -> dict[str, str]:
        """Create all albums and return a mapping of name → Google album ID."""
        result: dict[str, str] = {}
        for name in album_names:
            album_id = self.create_album(access_token, name)
            if album_id:
                result[name] = album_id
        return result
