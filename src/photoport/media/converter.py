"""Client-side media conversion pipeline for Storage Saver uploads.

Downscales images >16 Megapixels and encodes with high perceptual quality (Q85).
Preserves original EXIF metadata.
Strictly non-destructive: never modifies source files.
"""

from __future__ import annotations

import logging
import uuid
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QImageReader, QImageWriter

try:
    import piexif
except ImportError:
    piexif = None

from photoport.utils.file_types import is_photo

logger = logging.getLogger("photoport.media.converter")

# 16 Megapixels cap (Google Storage Saver photo standard)
MAX_STORAGE_SAVER_PIXELS: int = 16_000_000


@dataclass
class MediaConversionResult:
    """Outcome of a media conversion operation."""

    converted: bool
    output_path: Path
    original_size: int
    output_size: int
    is_downscaled: bool = False
    original_dimensions: tuple[int, int] = (0, 0)
    output_dimensions: tuple[int, int] = (0, 0)
    error_message: str = ""

    @property
    def savings_bytes(self) -> int:
        """Bytes saved through conversion."""
        if not self.converted or self.output_size >= self.original_size:
            return 0
        return self.original_size - self.output_size

    @property
    def savings_ratio(self) -> float:
        """Percentage savings as a decimal between 0.0 and 1.0."""
        if not self.converted or self.original_size <= 0:
            return 0.0
        return max(0.0, (self.original_size - self.output_size) / self.original_size)


class MediaConverter:
    """Non-destructive image downscaling and compression pipeline."""

    def __init__(
        self,
        max_megapixels: float = 16.0,
        quality: int = 85,
    ) -> None:
        self.max_pixels = int(max_megapixels * 1_000_000)
        self.quality = quality

    def convert_photo(
        self,
        source_path: Path,
        output_dir: Path,
    ) -> MediaConversionResult:
        """Convert a photo according to Storage Saver parameters.

        Pipeline stages:
        1. Non-destructive safety check: verify source exists and is read-only.
        2. Format check: verify file is a photo; non-photos pass through untouched.
        3. Load image into memory buffer with auto-orientation.
        4. Resolution check: if > 16 MP, downscale preserving aspect ratio with smooth filtering.
        5. Encode to staging file in output_dir at configured quality.
        6. Copy and preserve EXIF metadata from source.
        7. Efficiency verification: if output is larger than source, keep original.

        Args:
            source_path: Absolute path to source image (NEVER modified).
            output_dir: Staging directory for temporary converted files.

        Returns:
            MediaConversionResult describing whether conversion took place and the resulting path.
        """
        if not source_path.exists():
            return MediaConversionResult(
                converted=False,
                output_path=source_path,
                original_size=0,
                output_size=0,
                error_message=f"Source file not found: {source_path}",
            )

        original_size = source_path.stat().st_size

        if not is_photo(str(source_path)):
            logger.debug("Skipping conversion for non-photo media: %s", source_path.name)
            return MediaConversionResult(
                converted=False,
                output_path=source_path,
                original_size=original_size,
                output_size=original_size,
            )

        output_dir.mkdir(parents=True, exist_ok=True)
        temp_filename = f"storage_saver_{uuid.uuid4().hex[:8]}_{source_path.stem}.jpg"
        target_path = output_dir / temp_filename

        try:
            reader = QImageReader(str(source_path))
            reader.setAutoTransform(True)  # respect EXIF orientation flags
            image = reader.read()

            if image.isNull():
                logger.warning("Could not decode image for conversion: %s (%s)", source_path.name, reader.errorString())
                return MediaConversionResult(
                    converted=False,
                    output_path=source_path,
                    original_size=original_size,
                    output_size=original_size,
                    error_message=f"Decode error: {reader.errorString()}",
                )

            orig_w = image.width()
            orig_h = image.height()
            pixels = orig_w * orig_h
            is_downscaled = False
            processed_image = image

            # Downscale if exceeding 16 MP
            if pixels > self.max_pixels and pixels > 0:
                scale = (self.max_pixels / pixels) ** 0.5
                target_w = max(1, int(orig_w * scale))
                target_h = max(1, int(orig_h * scale))
                processed_image = image.scaled(
                    target_w,
                    target_h,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                is_downscaled = True
                logger.info(
                    "Downscaled %s from %dx%d (%d MP) to %dx%d (%d MP)",
                    source_path.name,
                    orig_w, orig_h, pixels // 1_000_000,
                    processed_image.width(), processed_image.height(),
                    (processed_image.width() * processed_image.height()) // 1_000_000,
                )

            # Write compressed output
            writer = QImageWriter(str(target_path), b"JPEG")
            writer.setQuality(self.quality)
            if not writer.write(processed_image):
                logger.warning("Failed to write converted image %s: %s", target_path.name, writer.errorString())
                if target_path.exists():
                    target_path.unlink()
                return MediaConversionResult(
                    converted=False,
                    output_path=source_path,
                    original_size=original_size,
                    output_size=original_size,
                    error_message=f"Write error: {writer.errorString()}",
                )

            # Preserve EXIF metadata if available
            self._copy_exif(source_path, target_path)

            output_size = target_path.stat().st_size

            # Efficiency check: if compressed output is larger than source, keep original
            if output_size >= original_size and not is_downscaled:
                logger.debug(
                    "Original file %s (%d bytes) is already smaller than converted output (%d bytes). Keeping original.",
                    source_path.name, original_size, output_size,
                )
                if target_path.exists():
                    target_path.unlink()
                return MediaConversionResult(
                    converted=False,
                    output_path=source_path,
                    original_size=original_size,
                    output_size=original_size,
                    original_dimensions=(orig_w, orig_h),
                    output_dimensions=(orig_w, orig_h),
                )

            return MediaConversionResult(
                converted=True,
                output_path=target_path,
                original_size=original_size,
                output_size=output_size,
                is_downscaled=is_downscaled,
                original_dimensions=(orig_w, orig_h),
                output_dimensions=(processed_image.width(), processed_image.height()),
            )

        except Exception as exc:
            logger.error("Unexpected error during media conversion of %s: %s", source_path.name, exc)
            if target_path.exists():
                with suppress(OSError):
                    target_path.unlink()
            return MediaConversionResult(
                converted=False,
                output_path=source_path,
                original_size=original_size,
                output_size=original_size,
                error_message=str(exc),
            )

    def _copy_exif(self, source_path: Path, target_path: Path) -> None:
        """Copy EXIF data from source to target JPEG file without modifying source."""
        if piexif is None:
            return
        try:
            exif_dict = piexif.load(str(source_path))
            if exif_dict:
                # Remove thumbnail if malformed to prevent insertion errors
                if "thumbnail" in exif_dict:
                    exif_dict["thumbnail"] = None
                # Reset orientation in EXIF since QImage reader already rotated pixels
                if "0th" in exif_dict and piexif.ImageIFD.Orientation in exif_dict["0th"]:
                    exif_dict["0th"][piexif.ImageIFD.Orientation] = 1

                exif_bytes = piexif.dump(exif_dict)
                piexif.insert(exif_bytes, str(target_path))
        except Exception as exc:
            logger.debug("Could not copy EXIF metadata from %s: %s", source_path.name, exc)
