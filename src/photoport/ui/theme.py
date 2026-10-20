"""Design system and theme engine for PhotoPort desktop UI.

Provides centralized design tokens, semantic color palettes, typography,
and responsive stylesheets for Dark and Light desktop themes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ThemeMode = Literal["dark", "light"]


@dataclass(frozen=True)
class ColorPalette:
    """Color palette tokens for PhotoPort UI."""

    # Backgrounds & surfaces
    bg_app: str
    bg_surface: str
    bg_surface_alt: str
    bg_surface_raised: str
    bg_card: str
    bg_card_hover: str
    bg_input: str

    # Borders & dividers
    border_subtle: str
    border_medium: str
    border_focus: str

    # Text colors
    text_primary: str
    text_secondary: str
    text_muted: str
    text_inverse: str

    # Brand & Action
    primary: str
    primary_hover: str
    primary_pressed: str
    primary_subtle: str

    # Semantic status colors
    success: str
    success_bg: str
    success_border: str

    warning: str
    warning_bg: str
    warning_border: str

    danger: str
    danger_hover: str
    danger_bg: str
    danger_border: str

    info: str
    info_bg: str
    info_border: str


DARK_PALETTE = ColorPalette(
    bg_app="#0f172a",          # Slate 900
    bg_surface="#1e293b",      # Slate 800
    bg_surface_alt="#131c2e",  # Deeper Slate
    bg_surface_raised="#334155",# Slate 700
    bg_card="#1e293b",
    bg_card_hover="#273549",
    bg_input="#0b1120",        # Deepest Slate input background

    border_subtle="#243247",
    border_medium="#334155",
    border_focus="#38bdf8",    # Sky 400

    text_primary="#f8fafc",    # Slate 50
    text_secondary="#cbd5e1",  # Slate 300
    text_muted="#64748b",      # Slate 500
    text_inverse="#0f172a",

    primary="#2563eb",         # Royal Blue
    primary_hover="#3b82f6",
    primary_pressed="#1d4ed8",
    primary_subtle="rgba(37, 99, 235, 0.15)",

    success="#10b981",         # Emerald 500
    success_bg="rgba(16, 185, 129, 0.15)",
    success_border="#059669",

    warning="#f59e0b",         # Amber 500
    warning_bg="rgba(245, 158, 11, 0.15)",
    warning_border="#d97706",

    danger="#ef4444",          # Red 500
    danger_hover="#dc2626",
    danger_bg="rgba(239, 68, 68, 0.15)",
    danger_border="#b91c1c",

    info="#0ea5e9",            # Sky 500
    info_bg="rgba(14, 165, 233, 0.15)",
    info_border="#0284c7",
)

LIGHT_PALETTE = ColorPalette(
    bg_app="#f8fafc",          # Slate 50
    bg_surface="#ffffff",      # White
    bg_surface_alt="#f1f5f9",  # Slate 100
    bg_surface_raised="#e2e8f0",# Slate 200
    bg_card="#ffffff",
    bg_card_hover="#f8fafc",
    bg_input="#ffffff",

    border_subtle="#e2e8f0",   # Slate 200
    border_medium="#cbd5e1",   # Slate 300
    border_focus="#2563eb",    # Blue 600

    text_primary="#0f172a",    # Slate 900
    text_secondary="#334155",  # Slate 700
    text_muted="#64748b",      # Slate 500
    text_inverse="#ffffff",

    primary="#2563eb",         # Royal Blue
    primary_hover="#1d4ed8",
    primary_pressed="#1e40af",
    primary_subtle="#eff6ff",

    success="#059669",
    success_bg="#ecfdf5",
    success_border="#a7f3d0",

    warning="#d97706",
    warning_bg="#fffbeb",
    warning_border="#fde68a",

    danger="#dc2626",
    danger_hover="#b91c1c",
    danger_bg="#fef2f2",
    danger_border="#fecaca",

    info="#0284c7",
    info_bg="#f0f9ff",
    info_border="#bae6fd",
)


def get_palette(mode: ThemeMode = "dark") -> ColorPalette:
    """Return color palette for requested theme mode."""
    return DARK_PALETTE if mode == "dark" else LIGHT_PALETTE


def generate_stylesheet(mode: ThemeMode = "dark") -> str:
    """Generate comprehensive QSS stylesheet for the application."""
    p = get_palette(mode)

    return f"""
/* ==========================================================================
   PhotoPort Desktop Theme — Mode: {mode.upper()}
   ========================================================================== */

QMainWindow {{
    background-color: {p.bg_app};
    color: {p.text_primary};
}}

QWidget {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Inter", "Helvetica Neue", Arial, sans-serif;
    font-size: 13px;
    color: {p.text_primary};
}}

/* Tooltips */
QToolTip {{
    background-color: {p.bg_surface_raised};
    color: {p.text_primary};
    border: 1px solid {p.border_medium};
    border-radius: 4px;
    padding: 6px 10px;
    font-size: 12px;
}}

/* Tab Widget & Bar */
QTabWidget::pane {{
    border: 1px solid {p.border_subtle};
    border-radius: 8px;
    background-color: {p.bg_surface};
    padding: 12px;
}}

QTabBar::tab {{
    background-color: transparent;
    color: {p.text_muted};
    padding: 10px 18px;
    margin-right: 4px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    font-weight: 600;
    font-size: 13px;
}}

QTabBar::tab:hover {{
    color: {p.text_primary};
    background-color: {p.bg_surface_alt};
}}

QTabBar::tab:selected {{
    color: {p.primary};
    background-color: {p.bg_surface};
    border-bottom: 2px solid {p.primary};
}}

/* Push Buttons */
QPushButton {{
    background-color: {p.bg_surface_raised};
    color: {p.text_primary};
    border: 1px solid {p.border_medium};
    border-radius: 6px;
    padding: 8px 16px;
    font-size: 13px;
    font-weight: 600;
    min-height: 20px;
}}

QPushButton:hover {{
    background-color: {p.bg_card_hover};
    border-color: {p.border_focus};
    color: {p.text_primary};
}}

QPushButton:pressed {{
    background-color: {p.primary_subtle};
}}

QPushButton:disabled {{
    background-color: {p.bg_surface_alt};
    color: {p.text_muted};
    border-color: {p.border_subtle};
}}

QPushButton#primary_button {{
    background-color: {p.primary};
    color: #ffffff;
    border: 1px solid {p.primary};
    font-weight: 700;
    padding: 10px 22px;
}}

QPushButton#primary_button:hover {{
    background-color: {p.primary_hover};
    border-color: {p.primary_hover};
}}

QPushButton#primary_button:pressed {{
    background-color: {p.primary_pressed};
}}

QPushButton#primary_button:disabled {{
    background-color: {p.bg_surface_raised};
    color: {p.text_muted};
    border-color: {p.border_subtle};
}}

QPushButton#secondary_button {{
    background-color: transparent;
    color: {p.text_secondary};
    border: 1px solid {p.border_medium};
}}

QPushButton#secondary_button:hover {{
    background-color: {p.bg_surface_raised};
    border-color: {p.text_secondary};
    color: {p.text_primary};
}}

QPushButton#danger_button {{
    background-color: {p.danger};
    color: #ffffff;
    border: 1px solid {p.danger};
}}

QPushButton#danger_button:hover {{
    background-color: {p.danger_hover};
    border-color: {p.danger_hover};
}}

/* Group Boxes & Panels */
QGroupBox {{
    font-weight: 700;
    font-size: 13px;
    color: {p.text_secondary};
    border: 1px solid {p.border_subtle};
    border-radius: 8px;
    margin-top: 14px;
    padding-top: 16px;
    background-color: {p.bg_surface};
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    left: 14px;
    padding: 0 8px;
    color: {p.text_primary};
}}

/* Progress Bar */
QProgressBar {{
    border: 1px solid {p.border_subtle};
    border-radius: 6px;
    text-align: center;
    height: 22px;
    background-color: {p.bg_input};
    color: {p.text_primary};
    font-weight: 600;
    font-size: 12px;
}}

QProgressBar::chunk {{
    background-color: {p.primary};
    border-radius: 5px;
}}

/* Text Editors & Input fields */
QTextEdit, QPlainTextEdit, QLineEdit {{
    background-color: {p.bg_input};
    color: {p.text_primary};
    border: 1px solid {p.border_subtle};
    border-radius: 6px;
    font-size: 13px;
    padding: 8px 10px;
    selection-background-color: {p.primary};
    selection-color: #ffffff;
}}

QTextEdit:focus, QPlainTextEdit:focus, QLineEdit:focus {{
    border: 1px solid {p.border_focus};
}}

/* Tables & Lists */
QTableWidget, QTableView {{
    background-color: {p.bg_surface};
    color: {p.text_primary};
    border: 1px solid {p.border_subtle};
    border-radius: 6px;
    gridline-color: {p.border_subtle};
    selection-background-color: {p.primary_subtle};
    selection-color: {p.text_primary};
}}

QTableWidget::item {{
    padding: 6px 10px;
    border-bottom: 1px solid {p.border_subtle};
}}

QTableWidget::item:selected {{
    background-color: {p.primary_subtle};
    color: {p.text_primary};
}}

QHeaderView::section {{
    background-color: {p.bg_surface_alt};
    color: {p.text_secondary};
    padding: 8px 10px;
    border: none;
    border-bottom: 2px solid {p.border_medium};
    font-weight: 700;
    font-size: 12px;
}}

/* Scrollbars */
QScrollBar:vertical {{
    background: {p.bg_app};
    width: 10px;
    margin: 0px;
    border-radius: 5px;
}}

QScrollBar::handle:vertical {{
    background: {p.border_medium};
    min-height: 24px;
    border-radius: 5px;
}}

QScrollBar::handle:vertical:hover {{
    background: {p.text_muted};
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}

QScrollBar:horizontal {{
    background: {p.bg_app};
    height: 10px;
    margin: 0px;
    border-radius: 5px;
}}

QScrollBar::handle:horizontal {{
    background: {p.border_medium};
    min-width: 24px;
    border-radius: 5px;
}}

QScrollBar::handle:horizontal:hover {{
    background: {p.text_muted};
}}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0px;
}}

/* Status & Menu Bar */
QStatusBar {{
    background-color: {p.bg_surface_alt};
    color: {p.text_muted};
    border-top: 1px solid {p.border_subtle};
    font-size: 12px;
    padding: 4px 8px;
}}

QMenuBar {{
    background-color: {p.bg_app};
    color: {p.text_primary};
    border-bottom: 1px solid {p.border_subtle};
    padding: 2px 4px;
}}

QMenuBar::item {{
    padding: 6px 12px;
    background: transparent;
    border-radius: 4px;
}}

QMenuBar::item:selected {{
    background-color: {p.bg_surface_raised};
}}

QMenu {{
    background-color: {p.bg_surface};
    color: {p.text_primary};
    border: 1px solid {p.border_medium};
    border-radius: 6px;
    padding: 4px;
}}

QMenu::item {{
    padding: 6px 24px 6px 16px;
    border-radius: 4px;
}}

QMenu::item:selected {{
    background-color: {p.primary};
    color: #ffffff;
}}

QMenu::separator {{
    height: 1px;
    background: {p.border_subtle};
    margin: 4px 0;
}}

/* Custom Labels */
QLabel#header_label {{
    font-size: 22px;
    font-weight: 800;
    color: {p.text_primary};
}}

QLabel#sub_label {{
    font-size: 13px;
    color: {p.text_muted};
}}

QLabel#stat_value {{
    font-size: 22px;
    font-weight: 700;
    color: {p.text_primary};
}}

QLabel#stat_label {{
    font-size: 11px;
    color: {p.text_muted};
    font-weight: 600;
    text-transform: uppercase;
}}

QLabel#warning_label {{
    color: {p.warning};
    font-weight: 600;
}}

QLabel#success_label {{
    color: {p.success};
    font-weight: 600;
}}

QLabel#error_label {{
    color: {p.danger};
    font-weight: 600;
}}
"""
