"""Build album manifest from Takeout archive structure and sidecar metadata."""

from __future__ import annotations

import logging
from collections import defaultdict
from pathlib import PurePosixPath

from photoport.archives.archive_scanner import ArchiveEntry

logger = logging.getLogger("photoport.metadata.album_manifest")


class AlbumManifest:
    """Discover album organization from Takeout folder structure.

    Google Takeout exports albums as subdirectories under 'Google Photos/'.
    This class builds a mapping of album names to their member media files.
    """

    # Directories in Takeout that are NOT albums
    IGNORED_DIRS = frozenset({
        "google photos",
        "photos from",
        "trash",
    })

    def build(self, media_entries: list[ArchiveEntry]) -> dict[str, list[ArchiveEntry]]:
        """Build album → media file mapping.

        Returns:
            Dict mapping album names to lists of media entries in that album.
        """
        albums: dict[str, list[ArchiveEntry]] = defaultdict(list)

        for entry in media_entries:
            album_name = self._infer_album(entry.member_path)
            if album_name:
                albums[album_name].append(entry)

        logger.info(
            "Album manifest: %d albums discovered with %d total items",
            len(albums),
            sum(len(v) for v in albums.values()),
        )

        # Report albums
        for name, items in sorted(albums.items()):
            logger.debug("  Album '%s': %d items", name, len(items))

        return dict(albums)

    def _infer_album(self, member_path: str) -> str:
        """Infer album name from the ZIP member path.

        Typical Takeout structure:
            Google Photos/Album Name/photo.jpg
            Takeout/Google Photos/Album Name/photo.jpg

        Returns the album name or empty string if not in an album.
        """
        parts = PurePosixPath(member_path).parts

        # Find "Google Photos" marker in path
        gp_index = -1
        for i, part in enumerate(parts):
            if part.lower() == "google photos":
                gp_index = i
                break

        if gp_index < 0:
            # No "Google Photos" in path — try using parent directory
            if len(parts) >= 2:
                parent = parts[-2]
                if parent.lower() not in self.IGNORED_DIRS:
                    return parent
            return ""

        # After "Google Photos", the next directory is the album name
        # The file itself is at least one more level deep
        if gp_index + 2 <= len(parts) - 1:
            album_dir = parts[gp_index + 1]
            if album_dir.lower() not in self.IGNORED_DIRS:
                return album_dir

        return ""

    def get_album_names(self, media_entries: list[ArchiveEntry]) -> list[str]:
        """Return sorted list of unique album names."""
        albums = self.build(media_entries)
        return sorted(albums.keys())
