"""Upload Quality selection widget with radio-card presentation.

Inspired by modern cloud backup quality selection panels.
Provides clear disclosures regarding official vs unofficial backends,
client-side compression, and storage quota implications.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from photoport.google_photos.backend_interface import get_upload_backend
from photoport.storage.models import UploadQualityMode

logger = logging.getLogger("photoport.ui.quality_selector")


class QualityCard(QFrame):
    """Interactive card containing a radio button, badges, and detailed disclosures."""

    def __init__(
        self,
        mode: UploadQualityMode,
        title: str,
        badge_text: str,
        badge_color: str,
        description: str,
        storage_note: str,
        is_experimental: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.mode = mode
        self.is_experimental = is_experimental

        self.setFrameShape(QFrame.StyledPanel)
        self.setCursor(Qt.PointingHandCursor)
        self.setObjectName("quality_card")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        # Header row: Radio + Title + Badge
        header_row = QHBoxLayout()
        header_row.setSpacing(8)

        self.radio = QRadioButton(title)
        self.radio.setStyleSheet("font-weight: bold; font-size: 13px;")
        header_row.addWidget(self.radio)

        self.badge = QLabel(f" {badge_text} ")
        self.badge.setStyleSheet(
            f"background-color: {badge_color}; color: white; border-radius: 4px; "
            "font-size: 11px; font-weight: bold; padding: 2px 6px;"
        )
        header_row.addWidget(self.badge)
        header_row.addStretch()

        layout.addLayout(header_row)

        # Description
        self.desc_label = QLabel(description)
        self.desc_label.setWordWrap(True)
        self.desc_label.setStyleSheet("color: #cbd5e1; font-size: 12px; margin-left: 22px;")
        layout.addWidget(self.desc_label)

        # Storage quota impact disclosure
        self.storage_label = QLabel(f"📊 Storage impact: {storage_note}")
        self.storage_label.setWordWrap(True)
        self.storage_label.setStyleSheet(
            "color: #94a3b8; font-size: 11px; font-weight: 500; margin-left: 22px; font-style: italic;"
        )
        layout.addWidget(self.storage_label)

        # Forward card clicks to radio
        self.mousePressEvent = lambda event: self.radio.setChecked(True)

    def set_checked(self, checked: bool) -> None:
        self.radio.setChecked(checked)
        self._update_style(checked)

    def is_checked(self) -> bool:
        return self.radio.isChecked()

    def _update_style(self, checked: bool) -> None:
        if checked:
            self.setStyleSheet(
                "#quality_card { border: 2px solid #2563eb; background-color: rgba(37, 99, 235, 0.15); border-radius: 8px; }"
            )
        else:
            self.setStyleSheet(
                "#quality_card { border: 1px solid #334155; background-color: rgba(30, 41, 59, 0.6); border-radius: 8px; }"
                "#quality_card:hover { border-color: #475569; background-color: rgba(30, 41, 59, 0.9); }"
            )


class QualitySelectorWidget(QGroupBox):
    """Quality selection panel containing radio-cards for each upload mode."""

    quality_changed = Signal(object)  # Emits UploadQualityMode

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Upload Quality & Storage Optimization", parent)
        self._button_group = QButtonGroup(self)
        self._cards: dict[UploadQualityMode, QualityCard] = {}
        self._current_mode = UploadQualityMode.ORIGINAL
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(12, 14, 12, 12)

        # Card 1: Original Quality
        card_orig = QualityCard(
            mode=UploadQualityMode.ORIGINAL,
            title="Original Quality",
            badge_text="Supported • Full Fidelity",
            badge_color="#3182CE",
            description=(
                "Preserves exact source resolution and bit-for-bit file contents. "
                "Uploaded directly via supported Google Photos Library API."
            ),
            storage_note="Consumes 100% of uploaded file size against your Google One quota.",
            is_experimental=False,
            parent=self,
        )
        self._cards[UploadQualityMode.ORIGINAL] = card_orig
        self._button_group.addButton(card_orig.radio)
        layout.addWidget(card_orig)

        # Card 2: Storage Saver
        card_saver = QualityCard(
            mode=UploadQualityMode.STORAGE_SAVER,
            title="Storage Saver (High Quality)",
            badge_text="Client Compressed • ~50% Smaller",
            badge_color="#38A169",
            description=(
                "Downscales photos >16 MP and applies high-quality JPEG compression (Q85) "
                "prior to upload. Source files are NEVER modified. Reduces payload by ~40–60%."
            ),
            storage_note="NOTE: Uploads are NOT quota-free; Google charges actual uploaded bytes against your quota.",
            is_experimental=False,
            parent=self,
        )
        self._cards[UploadQualityMode.STORAGE_SAVER] = card_saver
        self._button_group.addButton(card_saver.radio)
        layout.addWidget(card_saver)

        # Card 3: Experimental Zero-Quota (Unsupported / Unavailable)
        card_gpmc = QualityCard(
            mode=UploadQualityMode.EXPERIMENTAL_GPMC,
            title="Experimental Zero-Quota (Pixel Spoofing)",
            badge_text="Unavailable • Unsupported by Google API",
            badge_color="#A0AEC0",
            description=(
                "Google provides NO legitimate zero-quota API. Unofficial tools rely on spoofing "
                "2016 Pixel XL hardware properties and extracting master credentials, directly violating "
                "Google Terms of Service and risking permanent Google Account suspension."
            ),
            storage_note="Quota bypass cannot be supported legitimately. PhotoPort strictly uses supported APIs.",
            is_experimental=True,
            parent=self,
        )
        self._cards[UploadQualityMode.EXPERIMENTAL_GPMC] = card_gpmc
        self._button_group.addButton(card_gpmc.radio)
        layout.addWidget(card_gpmc)

        # Connect radio triggers
        card_orig.radio.toggled.connect(lambda c: self._on_radio_toggled(UploadQualityMode.ORIGINAL, c))
        card_saver.radio.toggled.connect(lambda c: self._on_radio_toggled(UploadQualityMode.STORAGE_SAVER, c))
        card_gpmc.radio.toggled.connect(lambda c: self._on_radio_toggled(UploadQualityMode.EXPERIMENTAL_GPMC, c))

        # Default to Original
        card_orig.set_checked(True)

    def _on_radio_toggled(self, mode: UploadQualityMode, checked: bool) -> None:
        if not checked:
            if mode in self._cards:
                self._cards[mode]._update_style(False)
            return

        # Intercept experimental mode: explain technical limitation and keep safe mode
        if mode == UploadQualityMode.EXPERIMENTAL_GPMC:
            backend = get_upload_backend(mode)
            is_avail, avail_reason = backend.is_available()
            if not is_avail:
                reasons_text = "\n".join(f"• {r}" for r in getattr(backend, "get_unsupported_reasons", lambda: [avail_reason])())
                QMessageBox.information(
                    self,
                    "Zero-Quota Mode Unavailable",
                    f"🚫 Zero-Quota Original Quality is unavailable in PhotoPort.\n\n"
                    f"Google does not offer a supported developer API or OAuth scope for zero-quota uploads. "
                    f"All official Google Photos API uploads count against your storage quota.\n\n"
                    f"Technical limitations & security findings:\n{reasons_text}\n\n"
                    "PhotoPort has preserved your selection on supported Original Quality mode.",
                )
                # Revert to previous safe mode
                safe_mode = self._current_mode if self._current_mode != UploadQualityMode.EXPERIMENTAL_GPMC else UploadQualityMode.ORIGINAL
                self._cards[safe_mode].set_checked(True)
                return

        self._current_mode = mode
        for m, card in self._cards.items():
            card._update_style(m == mode)

        logger.info("Upload quality mode selected: %s", mode.value)
        self.quality_changed.emit(mode)

    def get_selected_mode(self) -> UploadQualityMode:
        """Return the currently selected UploadQualityMode."""
        return self._current_mode

    def set_selected_mode(self, mode: UploadQualityMode) -> None:
        """Programmatically select a quality mode with safe fallback for unavailable modes."""
        backend = get_upload_backend(mode)
        is_avail, _ = backend.is_available()
        target_mode = mode if is_avail else UploadQualityMode.ORIGINAL

        if target_mode in self._cards:
            self._cards[target_mode].set_checked(True)
            self._current_mode = target_mode
            for m, card in self._cards.items():
                card._update_style(m == target_mode)
