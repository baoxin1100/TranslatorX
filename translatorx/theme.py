"""Interface themes: colour tokens plus the Qt stylesheet they generate.

The application ships a dark theme and a light theme. Both are described by the
same :class:`Theme` token set, so a stylesheet is just the shared template with
one theme's tokens substituted in. Every colour that the interface uses lives
here; widgets that paint themselves (``Switch``) read the active theme instead
of hard-coding values.

Design rules for the palettes:

* The brand accent (``accent``) is identical in both themes, so buttons and the
  logo keep their identity when the user switches.
* Text/hairline tokens keep a WCAG AA contrast ratio (>= 4.5:1) against the
  surface they are drawn on; ``tests/test_theme.py`` asserts this.
* Dark surfaces are darker than the canvas, light surfaces are lighter than the
  canvas, so inputs read as raised in both themes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, fields
from pathlib import Path
from string import Template

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPalette, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication

from .config_store import app_config

logger = logging.getLogger("translatorx.theme")

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
CONFIG_KEY = "theme"


@dataclass(frozen=True)
class Theme:
    """Every colour the interface needs, plus how it is presented to the user."""

    key: str
    name: str
    dark: bool
    # surfaces
    bg: str
    titlebar_bg: str
    footer_bg: str
    dialog_bg: str
    surface: str
    surface_hover: str
    surface_hover_strong: str
    surface_sunken: str
    # lines
    border: str
    border_strong: str
    border_input_hover: str
    # text
    text: str
    text_soft: str
    text_body: str
    text_label: str
    text_muted: str
    on_accent: str
    # accent ramp
    accent: str
    accent_hover: str
    accent_pressed: str
    accent_alpha: str
    focus: str
    accent_soft_text: str
    accent_soft_bg: str
    accent_soft_border: str
    accent_soft_hover_bg: str
    accent_soft_hover_border: str
    accent_soft_pressed_bg: str
    # icons
    title_icon: str
    icon_muted: str
    icon_hover: str
    info_border: str
    # states
    disabled_text: str
    disabled_border: str
    radio_border: str
    slider_handle: str
    danger_bg: str
    danger_border: str
    link: str
    # switches
    switch_on: str
    switch_off: str
    switch_border_on: str
    switch_border_off: str
    switch_knob: str
    # assets
    down_arrow: str


DARK = Theme(
    key="dark",
    name="深色",
    dark=True,
    bg="#090b0f",
    titlebar_bg="#090b0f",
    footer_bg="#090b0f",
    dialog_bg="#0d1015",
    surface="#101318",
    surface_hover="#15191f",
    surface_hover_strong="#1c2129",
    surface_sunken="#07090c",
    border="#20252c",
    border_strong="#323a45",
    border_input_hover="#4a5665",
    text="#f3f6f8",
    text_soft="#e3e9f0",
    text_body="#d7dde5",
    text_label="#a6b0bd",
    text_muted="#748090",
    on_accent="#ffffff",
    accent="#24528f",
    accent_hover="#2f66aa",
    accent_pressed="#1d4478",
    accent_alpha="rgba(36,82,143,0.7)",
    focus="#4f83c2",
    accent_soft_text="#dceaff",
    accent_soft_bg="#122038",
    accent_soft_border="#274b78",
    accent_soft_hover_bg="#182b49",
    accent_soft_hover_border="#3b6599",
    accent_soft_pressed_bg="#0e1a2d",
    title_icon="#dceaff",
    icon_muted="#8fa6c0",
    icon_hover="#7ea7d2",
    info_border="#60758d",
    disabled_text="#778292",
    disabled_border="#262c35",
    radio_border="#4a5665",
    slider_handle="#dceaff",
    danger_bg="rgba(255,112,112,0.16)",
    danger_border="rgba(255,112,112,0.42)",
    link="#5f9fe5",
    switch_on="#24528f",
    switch_off="#252b33",
    switch_border_on="#4f83c2",
    switch_border_off="#596572",
    switch_knob="#f7fbff",
    down_arrow="assets/chevron-down.svg",
)


LIGHT = Theme(
    key="light",
    name="浅色",
    dark=False,
    # A light canvas with white cards: the header and footer sit on white, the
    # content area on a very light grey, which is what gives the light theme its
    # structure without adding borders everywhere.
    bg="#f3f5f9",
    titlebar_bg="#ffffff",
    footer_bg="#ffffff",
    dialog_bg="#ffffff",
    surface="#ffffff",
    surface_hover="#eef1f6",
    surface_hover_strong="#e4e8ef",
    surface_sunken="#eef1f6",
    border="#d9dfe8",
    border_strong="#c3cbd7",
    border_input_hover="#9aa6b6",
    text="#18212e",
    text_soft="#2b3442",
    text_body="#333e4d",
    text_label="#4c5768",
    text_muted="#646e7c",
    on_accent="#ffffff",
    accent="#24528f",
    accent_hover="#2f66aa",
    accent_pressed="#1d4478",
    accent_alpha="rgba(36,82,143,0.45)",
    focus="#2f66aa",
    accent_soft_text="#1c3f70",
    accent_soft_bg="#e8f0fb",
    accent_soft_border="#b7cbe8",
    accent_soft_hover_bg="#d9e7f8",
    accent_soft_hover_border="#8fb2dd",
    accent_soft_pressed_bg="#c7dcf4",
    title_icon="#3a4553",
    icon_muted="#5b6878",
    icon_hover="#24528f",
    info_border="#97a3b3",
    disabled_text="#9aa4b1",
    disabled_border="#dfe4eb",
    radio_border="#a8b3c1",
    slider_handle="#ffffff",
    danger_bg="rgba(206,60,60,0.12)",
    danger_border="rgba(206,60,60,0.38)",
    link="#1a5fb4",
    switch_on="#24528f",
    switch_off="#cfd7e1",
    switch_border_on="#24528f",
    switch_border_off="#aab5c2",
    switch_knob="#ffffff",
    down_arrow="assets/chevron-down-light.svg",
)


THEMES: dict[str, Theme] = {theme.key: theme for theme in (DARK, LIGHT)}
DEFAULT_THEME_KEY = DARK.key


STYLE_TEMPLATE = Template(
    """
QWidget { color: $text; font-family: "Segoe UI", "Microsoft YaHei UI"; font-size: 13px; }
QMainWindow { background: transparent; }
QWidget#root { background: $bg; border-radius: 16px; }
QFrame#titlebar { background: $titlebar_bg; border-bottom: 1px solid $border; border-top-left-radius: 16px; border-top-right-radius: 16px; }
QFrame#footer { background: $footer_bg; border: none; border-bottom-left-radius: 16px; border-bottom-right-radius: 16px; }
QLabel#windowTitle { font-weight: 700; font-size: 18px; }
QLabel#settingsDialogTitle { font-weight: 700; font-size: 14px; color: $text; }
QLabel#statusLabel, QLabel#hintLabel { color: $text_muted; font-size: 12px; }
QLabel#fieldLabel { color: $text_label; font-weight: 600; }
QComboBox {
  min-height: 44px; padding: 0 38px 0 13px; background: $surface;
  border: 1px solid $border; border-radius: 9px; selection-background-color: $accent;
}
QComboBox:hover { border-color: $border_strong; background: $surface_hover; }
QComboBox:focus { border: 2px solid $focus; padding-left: 12px; }
QComboBox::drop-down { width: 34px; border: none; }
QComboBox::down-arrow { image: url($down_arrow); width: 14px; height: 14px; }
QComboBox QAbstractItemView {
  background: $surface; border: 1px solid $border_strong;
  selection-background-color: $accent; selection-color: $on_accent; outline: 0;
}
QComboBox QAbstractItemView::item:selected { background: $accent; color: $on_accent; }
QComboBox#themeCombo { min-height: 32px; padding: 0 30px 0 10px; }
QComboBox#themeCombo:focus { padding-left: 9px; }
QComboBox#themeCombo::drop-down { width: 26px; }
QPushButton#refreshButton, QToolButton#titleButton, QToolButton#closeButton {
  background: transparent; border: 1px solid transparent; border-radius: 8px;
}
QPushButton#refreshButton { min-width: 44px; max-width: 44px; min-height: 44px; background: $surface; border-color: $border; font-size: 18px; }
QPushButton#refreshButton:hover, QToolButton#titleButton:hover { color: $icon_hover; background: $surface_hover; border-color: $border_strong; }
QToolButton#closeButton:hover { color: $on_accent; background: $danger_bg; border-color: $danger_border; }
QToolButton#titleButton, QToolButton#closeButton { min-width: 30px; max-width: 30px; min-height: 30px; max-height: 30px; }
QToolButton#titleButton { font-size: 17px; }
QPushButton#runButton {
  min-height: 52px; color: $on_accent; background: $accent; border: 1px solid $accent;
  border-radius: 10px; font-weight: 700; font-size: 14px;
}
QPushButton#runButton:hover { background: $accent_hover; border-color: $accent_hover; }
QPushButton#runButton:pressed { background: $accent_pressed; border-color: $accent_pressed; }
QPushButton#runButton:disabled {
  color: $disabled_text; background: $surface_hover; border-color: $disabled_border;
}
QPushButton#runButton[running="true"] { background: $surface; border-color: $accent_alpha; }
QDialog { background: $bg; }
QGroupBox { border: 1px solid $border; border-radius: 9px; margin-top: 10px; padding-top: 8px; font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; color: $text_label; }
QLineEdit { min-height: 36px; padding: 0 10px; background: $surface; border: 1px solid $border; border-radius: 7px; }
QLineEdit:focus { border: 2px solid $focus; }
QPlainTextEdit#testResults { padding: 8px; background: $surface_sunken; border: 1px solid $border; border-radius: 7px; color: $text_label; }
QPushButton#settingsActionButton { min-height: 34px; padding: 0 14px; color: $accent_soft_text; background: $accent_soft_bg; border: 1px solid $accent_soft_border; border-radius: 7px; }
QPushButton#settingsActionButton:hover { background: $accent_soft_hover_bg; border-color: $accent_soft_hover_border; }
QPushButton#settingsActionButton:pressed { background: $accent_soft_pressed_bg; border-color: $focus; }
QPushButton#settingsActionButton:disabled { color: $text_muted; background: $surface; border-color: $border; }
QRadioButton { min-height: 34px; spacing: 8px; color: $text_body; }
QRadioButton::indicator { width: 16px; height: 16px; border-radius: 9px; border: 1px solid $radio_border; background: $surface; }
QRadioButton::indicator:hover { border-color: $focus; }
QRadioButton::indicator:checked {
  border-color: $focus;
  background: qradialgradient(cx:0.5, cy:0.5, radius:0.45, fx:0.5, fy:0.5,
    stop:0 $focus, stop:0.38 $focus, stop:0.42 $surface, stop:1 $surface);
}
QSlider::groove:horizontal { height: 4px; background: $border; border-radius: 2px; }
QSlider::sub-page:horizontal { background: $accent; border-radius: 2px; }
QSlider::handle:horizontal { width: 12px; height: 12px; margin: -4px 0; background: $slider_handle; border: 2px solid $accent; border-radius: 6px; }
QSlider::handle:horizontal:hover { background: $on_accent; border-color: $focus; }
QLabel#fontValue { min-width: 34px; color: $accent_soft_text; font-weight: 600; }
QToolButton#infoButton { min-width: 12px; max-width: 12px; min-height: 12px; max-height: 12px;
  padding: 0; color: $icon_muted; background: transparent; border: 1px solid $info_border; border-radius: 6px;
  font-size: 7px; font-weight: 700; }
QToolButton#infoButton:hover { color: $accent_soft_text; border-color: $focus; background: $accent_soft_bg; }
QMenu { padding: 6px; background: $surface; border: 1px solid $border_strong; border-radius: 7px; }
QMenu::item { min-width: 126px; padding: 7px 14px; border-radius: 5px; }
QMenu::item:selected { color: $on_accent; background: $accent; }
QDialog#aboutDialog { background: $dialog_bg; border: 1px solid $border_strong; border-radius: 12px; }
QLabel#aboutTitle { color: $text; font-size: 16px; font-weight: 700; }
QLabel#aboutNote { color: $text_muted; font-size: 12px; }
QLabel#aboutStatus { color: $text_label; font-size: 12px; }
QPushButton#aboutLinkButton, QPushButton#aboutUpdateButton, QPushButton#aboutCloseButton {
  min-height: 36px; padding: 0 14px; border-radius: 8px; font-weight: 600;
}
QPushButton#aboutLinkButton { color: $accent_soft_text; background: $accent_soft_bg; border: 1px solid $accent_soft_border; }
QPushButton#aboutLinkButton:hover { background: $accent_soft_hover_bg; border-color: $accent_soft_hover_border; }
QPushButton#aboutLinkButton:pressed { background: $accent_soft_pressed_bg; border-color: $focus; }
QPushButton#aboutUpgradeButton {
  min-height: 26px; padding: 0 12px; border-radius: 7px; font-size: 12px; font-weight: 600;
  color: $on_accent; background: $accent; border: 1px solid $accent;
}
QPushButton#aboutUpgradeButton:hover { background: $accent_hover; border-color: $accent_hover; }
QPushButton#aboutUpgradeButton:pressed { background: $accent_pressed; border-color: $accent_pressed; }
QPushButton#aboutUpgradeButton:disabled { color: $disabled_text; background: $surface_hover; border-color: $disabled_border; }
QPushButton#aboutUpdateButton { color: $on_accent; background: $accent; border: 1px solid $accent; }
QPushButton#aboutUpdateButton:hover { background: $accent_hover; border-color: $accent_hover; }
QPushButton#aboutUpdateButton:pressed { background: $accent_pressed; border-color: $accent_pressed; }
QPushButton#aboutUpdateButton:disabled { color: $disabled_text; background: $surface_hover; border-color: $disabled_border; }
QPushButton#aboutCloseButton { color: $text_soft; background: $surface_hover; border: 1px solid $border_strong; }
QPushButton#aboutCloseButton:hover { color: $on_accent; background: $surface_hover_strong; border-color: $border_input_hover; }
""".strip()
)


# Palette roles that make the theme reach widgets the stylesheet does not cover,
# such as rich-text links and placeholder text.
PALETTE_ROLES = {
    QPalette.ColorRole.Link: "link",
    QPalette.ColorRole.Highlight: "accent",
    QPalette.ColorRole.HighlightedText: "on_accent",
    QPalette.ColorRole.PlaceholderText: "text_muted",
    QPalette.ColorRole.ToolTipBase: "surface",
    QPalette.ColorRole.ToolTipText: "text",
}


def tokens(theme: Theme) -> dict[str, str]:
    return {field.name: str(getattr(theme, field.name)) for field in fields(theme)}


def stylesheet(theme: Theme) -> str:
    """Render the shared stylesheet with one theme's tokens."""
    return STYLE_TEMPLATE.substitute(tokens(theme))


def theme_choices() -> list[tuple[str, str]]:
    """Theme keys with their display names, in menu order."""
    return [(theme.key, theme.name) for theme in (DARK, LIGHT)]


def tinted_icon(asset_name: str, color: str, size: int = 72) -> QIcon:
    """Render a monochrome SVG asset in the requested colour.

    The bundled icons are stroked in a single light colour, so themes cannot
    reuse them as-is. Rendering at ``size`` (well above the display size) keeps
    them crisp on high-DPI screens.
    """
    path = ASSETS_DIR / asset_name
    renderer = QSvgRenderer(str(path))
    if not renderer.isValid():
        logger.warning("图标无法渲染，回退到原始文件：%s", path)
        return QIcon(str(path))
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(pixmap.rect(), QColor(color))
    painter.end()
    return QIcon(pixmap)


class ThemeManager(QObject):
    """Owns the active theme, persists it, and republishes changes."""

    changed = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self._key = self._saved_key()

    @staticmethod
    def _saved_key() -> str:
        try:
            saved = str(app_config().value(CONFIG_KEY, DEFAULT_THEME_KEY)).strip()
        except Exception:
            logger.exception("读取主题设置失败，使用默认主题")
            return DEFAULT_THEME_KEY
        return saved if saved in THEMES else DEFAULT_THEME_KEY

    @property
    def key(self) -> str:
        return self._key

    def current(self) -> Theme:
        return THEMES.get(self._key, THEMES[DEFAULT_THEME_KEY])

    def set_key(self, key: str, persist: bool = True) -> Theme:
        """Switch to ``key`` and repaint every window."""
        if key not in THEMES:
            key = DEFAULT_THEME_KEY
        self._key = key
        if persist:
            try:
                store = app_config()
                store.setValue(CONFIG_KEY, key)
                store.sync()
            except Exception:
                logger.exception("保存主题设置失败")
        return self.apply()

    def apply(self) -> Theme:
        theme = self.current()
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(stylesheet(theme))
            palette = app.palette()
            for role, token in PALETTE_ROLES.items():
                palette.setColor(role, QColor(getattr(theme, token)))
            app.setPalette(palette)
        self.changed.emit(theme)
        return theme


theme_manager = ThemeManager()
