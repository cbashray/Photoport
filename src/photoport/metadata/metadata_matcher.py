"""Match media files with their JSON sidecar metadata."""

from __future__ import annotations

import logging
from pathlib import PurePosixPath

from photoport.archives.archive_scanner import ArchiveEntry

logger = logging.getLogger("photoport.metadata.metadata_matcher")


class MetadataMatcher:
    """Match Takeout media files with their corresponding JSON sidecar files.

    Google Takeout uses several naming conventions for sidecars:
    - photo.jpg → photo.jpg.json
    - photo.jpg → photo.json
    - photo(1).jpg → photo(1).jpg.json
    - photo.jpg → photo.jpg.supplemental-metadata.json (newer exports)

    This matcher handles these variations and warns about ambiguous cases.
    """

    def match(
        self,
        media_entries: list[ArchiveEntry],
        sidecar_entries: list[ArchiveEntry],
    ) -> dict[str, ArchiveEntry | None]:
        """Match media entries to their sidecars.

        Returns:
            Dict mapping media member_path to the matched sidecar ArchiveEntry
            (or None if no sidecar was found).
        """
        # Build sidecar lookup: keyed by normalized path
        sidecar_by_path: dict[str, ArchiveEntry] = {}
        for sc in sidecar_entries:
            sidecar_by_path[sc.member_path] = sc

        matches: dict[str, ArchiveEntry | None] = {}
        matched_sidecars: set[str] = set()

        for media in media_entries:
            sidecar = self._find_sidecar(media.member_path, sidecar_by_path, matched_sidecars)
            matches[media.member_path] = sidecar
            if sidecar:
                matched_sidecars.add(sidecar.member_path)

        # Report unmatched sidecars
        unmatched = set(sidecar_by_path.keys()) - matched_sidecars
        if unmatched:
            logger.info(
                "%d sidecar files did not match any media file", len(unmatched)
            )

        matched_count = sum(1 for v in matches.values() if v is not None)
        logger.info(
            "Metadata matching: %d media files, %d matched with sidecars, %d without",
            len(media_entries), matched_count, len(media_entries) - matched_count,
        )

        return matches

    def _find_sidecar(
        self,
        media_path: str,
        sidecar_map: dict[str, ArchiveEntry],
        used_sidecars: set[str] | None = None,
    ) -> ArchiveEntry | None:
        """Find the sidecar for a given media path using ordered naming strategies.

        Handles:
        - photo.jpg → photo.jpg.json
        - photo.jpg → photo.json
        - photo(1).jpg → photo(1).jpg.json
        - photo(1).jpg → photo.jpg(1).json (Google Takeout duplicate naming)
        - photo(1).jpg → photo(1).json
        - photo.jpg → photo.jpg(1).json (if photo.jpg.json is absent)
        - Truncated stems (>46 chars)
        - Supplemental metadata format
        """
        p = PurePosixPath(media_path)
        stem = p.stem
        suffix = p.suffix
        parent = p.parent
        used = used_sidecars or set()

        candidates: list[str] = []

        # 1. Exact media.ext.json (e.g. photo.jpg.json, photo(1).jpg.json)
        candidates.append(media_path + ".json")

        # 2. Supplemental metadata format
        candidates.append(media_path + ".supplemental-metadata.json")

        # 3. Handle (N) pattern in media name (e.g., photo(1).jpg)
        if "(" in stem and stem.endswith(")"):
            l_paren = stem.rfind("(")
            r_paren = stem.rfind(")")
            if l_paren != -1 and r_paren > l_paren:
                num = stem[l_paren + 1 : r_paren]
                base_stem = stem[:l_paren].rstrip()
                # Takeout duplicate format 1: photo.jpg(1).json
                candidates.append(str(parent / f"{base_stem}{suffix}({num}).json"))
                # Takeout duplicate format 2: photo(1).json
                candidates.append(str(parent / f"{stem}.json"))
                # Takeout duplicate format 3: photo.jpg(1).supplemental-metadata.json
                candidates.append(str(parent / f"{base_stem}{suffix}({num}).supplemental-metadata.json"))

        # 4. If media does NOT have (N), but Takeout sidecar was indexed as photo.jpg(1).json
        candidates.append(str(parent / f"{p.name}(1).json"))

        # 5. Stem-based (e.g. photo.json)
        candidates.append(str(parent / f"{stem}.json"))

        # 6. Truncated stems (Takeout truncates at 46-51 chars before .json)
        if len(stem) > 46:
            for trunc_len in (46, 47, 48, 49, 50, 51):
                if len(stem) >= trunc_len:
                    candidates.append(str(parent / f"{stem[:trunc_len]}.json"))
                    candidates.append(str(parent / f"{stem[:trunc_len]}{suffix}.json"))

        # 7. Fallback for photo(1).jpg: check base photo.jpg.json only if no numbered sidecar exists
        if "(" in stem and stem.endswith(")"):
            l_paren = stem.rfind("(")
            base_stem = stem[:l_paren].rstrip()
            candidates.append(str(parent / f"{base_stem}{suffix}.json"))
            candidates.append(str(parent / f"{base_stem}.json"))

        # Pass 1: Match against an unused sidecar to prevent cross-contamination
        for c in candidates:
            if c in sidecar_map and c not in used:
                return sidecar_map[c]

        # Pass 2: Allow fallback to already-matched sidecar only if no unused candidate exists
        for c in candidates:
            if c in sidecar_map:
                return sidecar_map[c]

        return None
