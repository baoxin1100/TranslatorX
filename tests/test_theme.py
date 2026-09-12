from __future__ import annotations

import re
import tempfile
from pathlib import Path

import pytest
from PySide6.QtGui import QIcon, QPalette
from PySide6.QtWidgets import QApplication

from translatorx import config_store
from translatorx.config_store import ConfigStore
from translatorx.theme import (
    CONFIG_KEY,
    DARK,
    DEFAULT_THEME_KEY,
    LIGHT,
    THEMES,
    Theme,
    stylesheet,
    theme_choices,
    theme_manager,
    tinted_icon,
)


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    """Keep the developer's real settings out of theme tests."""
    monkeypatch.setattr(config_store, "_store", ConfigStore(tmp_path / "translatorx.json"))


def _luminance(color: str) -> float:
    channels = []
    for offset in (1, 3, 5):
        value = int(color[offset : offset + 2], 16) / 255
        channels.append(value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def contrast_ratio(foreground: str, background: str) -> float:
    first, second = _luminance(foreground), _luminance(background)
    return (max(first, second) + 0.05) / (min(first, second) + 0.05)


TEXT_PAIRS = [
    ("text", "bg"),
    ("text", "titlebar_bg"),
    ("text", "footer_bg"),
    ("text", "dialog_bg"),
    ("text", "surface"),
    ("text_label", "bg"),
    ("text_body", "bg"),
    ("text_muted", "bg"),
    ("text_muted", "dialog_bg"),
    ("accent_soft_text", "accent_soft_bg"),
    ("link", "bg"),
]

ACCENT_PAIRS = [
    ("on_accent", "accent"),
    ("on_accent", "accent_hover"),
]

ICON_PAIRS = [
    ("title_icon", "titlebar_bg"),
    ("icon_muted", "bg"),
    ("focus", "surface"),
]


def test_both_themes_are_registered():
    assert theme_choices() == [(DARK.key, "深色"), (LIGHT.key, "浅色")]
    assert set(THEMES) == {"dark", "light"}
    assert DEFAULT_THEME_KEY == DARK.key


@pytest.mark.parametrize("theme", [DARK, LIGHT])
def test_stylesheet_substitutes_every_token(theme: Theme):
    rendered = stylesheet(theme)
    assert "$" not in rendered
    assert "QWidget#root" in rendered
    # No placeholder may survive as a literal token name.
    assert not re.search(r"\$[a-z_]+", rendered)


def test_dark_theme_keeps_the_shipped_palette():
    rendered = stylesheet(DARK)
    for rule in [
        "QWidget#root { background: #090b0f; border-radius: 16px; }",
        "QFrame#titlebar { background: #090b0f; border-bottom: 1px solid #20252c;",
        "QPushButton#runButton {",
        "  min-height: 52px; color: #ffffff; background: #24528f; border: 1px solid #24528f;",
        "QPlainTextEdit#testResults { padding: 8px; background: #07090c;",
    ]:
        assert rule in rendered


def test_light_theme_inverts_the_surfaces_and_keeps_the_accent():
    light = stylesheet(LIGHT)
    assert light != stylesheet(DARK)
    assert "QWidget#root { background: #f3f5f9; border-radius: 16px; }" in light
    assert "QLineEdit { min-height: 36px; padding: 0 10px; background: #ffffff;" in light
    # The brand accent is shared so buttons keep their identity across themes.
    assert LIGHT.accent == DARK.accent
    assert "#24528f" in light


def test_theme_swaps_the_dropdown_arrow_asset():
    assert DARK.down_arrow == "assets/chevron-down.svg"
    assert LIGHT.down_arrow == "assets/chevron-down-light.svg"
    assert f"image: url({LIGHT.down_arrow})" in stylesheet(LIGHT)


@pytest.mark.parametrize("theme", [DARK, LIGHT])
@pytest.mark.parametrize("pair", TEXT_PAIRS)
def test_body_text_meets_wcag_aa(theme: Theme, pair: tuple[str, str]):
    foreground, background = (getattr(theme, name) for name in pair)
    assert contrast_ratio(foreground, background) >= 4.5, pair


@pytest.mark.parametrize("theme", [DARK, LIGHT])
@pytest.mark.parametrize("pair", ACCENT_PAIRS)
def test_button_labels_meet_wcag_aa(theme: Theme, pair: tuple[str, str]):
    foreground, background = (getattr(theme, name) for name in pair)
    assert contrast_ratio(foreground, background) >= 4.5, pair


@pytest.mark.parametrize("theme", [DARK, LIGHT])
@pytest.mark.parametrize("pair", ICON_PAIRS)
def test_icons_and_focus_rings_meet_wcag_non_text_contrast(theme: Theme, pair: tuple[str, str]):
    foreground, background = (getattr(theme, name) for name in pair)
    assert contrast_ratio(foreground, background) >= 3.0, pair


def test_setting_a_theme_persists_it_and_announces_the_change(app):
    seen: list[Theme] = []
    theme_manager.changed.connect(seen.append)
    try:
        theme_manager.set_key("light")
        assert theme_manager.key == "light"
        assert theme_manager.current() is LIGHT
        assert app_config_value() == "light"
        assert seen[-1] is LIGHT
        # Switching back keeps the config in step with the rendered theme.
        assert app.styleSheet() == stylesheet(LIGHT)
    finally:
        theme_manager.changed.disconnect(seen.append)
        theme_manager.set_key(DEFAULT_THEME_KEY)


def app_config_value() -> object:
    return config_store.app_config().value(CONFIG_KEY)


def test_unknown_theme_falls_back_to_the_default(app):
    assert theme_manager.set_key("solarized", persist=False) is DARK
    assert theme_manager.key == DEFAULT_THEME_KEY


def test_saved_theme_is_picked_up_on_startup(app, monkeypatch):
    store = ConfigStore(Path(tempfile.mkdtemp()) / "translatorx.json")
    store.set_value(CONFIG_KEY, "light")
    store.sync()
    monkeypatch.setattr(config_store, "_store", store)

    from translatorx.theme import ThemeManager

    manager = ThemeManager()
    assert manager.key == "light"
    assert manager.current() is LIGHT


def test_apply_publishes_the_theme_to_the_palette(app):
    theme_manager.set_key("light", persist=False)
    palette = app.palette()
    assert palette.color(QPalette.ColorRole.Link).name() == LIGHT.link
    assert palette.color(QPalette.ColorRole.Highlight).name() == LIGHT.accent
    theme_manager.set_key(DARK.key, persist=False)
    assert app.palette().color(QPalette.ColorRole.Link).name() == DARK.link


def test_tinted_icon_uses_the_requested_colour(app):
    icon = tinted_icon("close.svg", "#3a4553", 32)
    image = icon.pixmap(32, 32).toImage()
    opaque = [
        image.pixelColor(x, y)
        for y in range(image.height())
        for x in range(image.width())
        if image.pixelColor(x, y).alpha() > 200
    ]
    assert opaque
    # The stroke keeps the requested hue; edge pixels may round by a step.
    for color in opaque:
        assert abs(color.red() - 0x3A) <= 2
        assert abs(color.green() - 0x45) <= 2
        assert abs(color.blue() - 0x53) <= 2
    # And it is a dark tint, unlike the light one used by the dark theme.
    lighter = tinted_icon("close.svg", "#dceaff", 32).pixmap(32, 32).toImage()
    assert image.pixelColor(16, 16).lightness() < lighter.pixelColor(16, 16).lightness()


def test_tinted_icon_never_raises_for_a_missing_asset(app):
    # Qt cannot render it, so the helper falls back to the raw path.
    assert isinstance(tinted_icon("does-not-exist.svg", "#ffffff", 16), QIcon)
