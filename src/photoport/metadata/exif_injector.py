"""EXIF metadata injection for temporary media files before upload."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("photoport.metadata.exif_injector")

SUPPORTED_EXIF_EXTENSIONS = frozenset({".jpg", ".jpeg", ".tif", ".tiff"})


def _iso_to_exif_date(ts_str: str) -> str | None:
    """Convert an ISO-8601 or epoch timestamp string to EXIF format 'YYYY:MM:DD HH:MM:SS'."""
    if not ts_str:
        return None

    # Epoch timestamp
    if ts_str.isdigit():
        try:
            dt = datetime.utcfromtimestamp(int(ts_str))
            return dt.strftime("%Y:%m:%d %H:%M:%S")
        except Exception:
            pass

    # ISO format variants
    clean_ts = ts_str.rstrip("Z").split("+")[0]
    try:
        dt = datetime.fromisoformat(clean_ts)
        return dt.strftime("%Y:%m:%d %H:%M:%S")
    except Exception:
        pass

    for fmt in (
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ):
        try:
            dt = datetime.strptime(ts_str, fmt)
            return dt.strftime("%Y:%m:%d %H:%M:%S")
        except Exception:
            continue

    return None


def _to_gps_rational(val: float) -> tuple[tuple[int, int], tuple[int, int], tuple[int, int]]:
    """Convert a decimal latitude or longitude to EXIF rational tuple (deg, min, sec)."""
    abs_val = abs(val)
    deg = int(abs_val)
    min_float = (abs_val - deg) * 60
    minute = int(min_float)
    sec_float = (min_float - minute) * 60
    sec = int(round(sec_float * 1000))
    return ((deg, 1), (minute, 1), (sec, 1000))


def inject_exif_metadata(
    file_path: Path,
    capture_timestamp: str = "",
    latitude: float | None = None,
    longitude: float | None = None,
) -> bool:
    """Inject sidecar timestamp and GPS metadata into a temporary copy of a JPEG/TIFF file.

    Guarantees:
    - Only temporary files are modified; source archives are never modified.
    - If camera EXIF (DateTimeOriginal) is already embedded in the file, it is preserved.
    - For unsupported formats (PNG, HEIC, MP4, MOV), returns False and logs limitation.

    Returns:
        True if EXIF metadata was successfully written, False otherwise.
    """
    if file_path.suffix.lower() not in SUPPORTED_EXIF_EXTENSIONS:
        logger.debug(
            "EXIF injection not supported for format '%s' (%s). "
            "Google Photos will infer timestamp from container headers or upload date.",
            file_path.suffix, file_path.name,
        )
        return False

    if not capture_timestamp and latitude is None and longitude is None:
        return False

    try:
        import piexif
    except ImportError:
        logger.warning("piexif library not available; skipping EXIF injection.")
        return False

    try:
        try:
            exif_dict = piexif.load(str(file_path))
        except Exception:
            exif_dict = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}

        modified = False

        # 1. Timestamp injection
        if capture_timestamp:
            exif_date_str = _iso_to_exif_date(capture_timestamp)
            if exif_date_str:
                exif_date_bytes = exif_date_str.encode("ascii")
                # Preserve existing camera DateTimeOriginal if present
                existing_dto = exif_dict.get("Exif", {}).get(piexif.ExifIFD.DateTimeOriginal)
                if not existing_dto:
                    exif_dict.setdefault("Exif", {})[piexif.ExifIFD.DateTimeOriginal] = exif_date_bytes
                    exif_dict.setdefault("0th", {})[piexif.ImageIFD.DateTime] = exif_date_bytes
                    modified = True

        # 2. GPS injection
        if latitude is not None and longitude is not None and (latitude != 0.0 or longitude != 0.0):
            existing_gps = exif_dict.get("GPS", {}).get(piexif.GPSIFD.GPSLatitude)
            if not existing_gps:
                gps_ifd = exif_dict.setdefault("GPS", {})
                lat_ref = b"N" if latitude >= 0 else b"S"
                lon_ref = b"E" if longitude >= 0 else b"W"
                gps_ifd[piexif.GPSIFD.GPSLatitudeRef] = lat_ref
                gps_ifd[piexif.GPSIFD.GPSLatitude] = _to_gps_rational(latitude)
                gps_ifd[piexif.GPSIFD.GPSLongitudeRef] = lon_ref
                gps_ifd[piexif.GPSIFD.GPSLongitude] = _to_gps_rational(longitude)
                modified = True

        if modified:
            exif_bytes = piexif.dump(exif_dict)
            piexif.insert(exif_bytes, str(file_path))
            logger.debug("Successfully injected sidecar metadata into temp file: %s", file_path.name)
            return True

        return False

    except Exception as exc:
        logger.warning("Failed to inject EXIF metadata into %s: %s", file_path.name, exc)
        return False
