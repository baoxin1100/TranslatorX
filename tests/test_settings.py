from __future__ import annotations

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QScrollArea

from translatorx import config_store
from translatorx.config_store import ConfigStore
from translatorx.settings import (
    CredentialDialog,
    _model_endpoint,
    _parse_model_ids,
    _protect_secret,
    _unprotect_secret,
)
from translatorx.theme import DEFAULT_THEME_KEY, theme_manager


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    store = ConfigStore(tmp_path / "translatorx.json")
    monkeypatch.setattr(config_store, "_store", store)
    return store


@pytest.fixture(autouse=True)
def restore_theme():
    original = theme_manager.key
    yield
    theme_manager.set_key(original, persist=False)


def test_saved_secret_is_encrypted_and_can_be_restored():
    secret = "sk-test-密钥-123"
    protected = _protect_secret(secret)
    assert secret not in protected
    assert _unprotect_secret(protected) == secret


def test_invalid_saved_secret_is_ignored():
    assert _unprotect_secret("not valid dpapi data") == ""


def test_model_listing_parser_and_endpoint_are_compatible():
    assert _model_endpoint("https://example.test/v1/chat/completions") == "https://example.test/v1/models"
    assert _parse_model_ids({"data": [{"id": "z"}, {"id": "a"}, {"id": "z"}]}) == ["a", "z"]
    assert _parse_model_ids({"models": ["custom-model"]}) == ["custom-model"]


def test_theme_picker_sits_in_the_top_right_and_applies_immediately(app, isolated_config):
    theme_manager.set_key(DEFAULT_THEME_KEY, persist=False)
    dialog = CredentialDialog()
    dialog.show()
    app.processEvents()

    combo = dialog.theme_combo
    assert [combo.itemText(index) for index in range(combo.count())] == ["深色", "浅色"]
    assert combo.currentData() == DEFAULT_THEME_KEY

    geometry = combo.geometry()
    assert geometry.top() < dialog.height() // 2
    assert geometry.right() >= dialog.width() - 60

    combo.setCurrentIndex(combo.findData("light"))
    assert theme_manager.key == "light"
    assert isolated_config.value("theme") == "light"

    combo.setCurrentIndex(combo.findData(DEFAULT_THEME_KEY))
    assert theme_manager.key == DEFAULT_THEME_KEY
    assert isolated_config.value("theme") == DEFAULT_THEME_KEY


def test_theme_picker_does_not_write_the_config_while_building(app, isolated_config):
    CredentialDialog()
    assert isolated_config.value("theme") is None


def test_settings_dialog_scrolls_instead_of_losing_its_buttons(app, isolated_config):
    dialog = CredentialDialog()
    dialog.show()
    app.processEvents()

    scroll = dialog.findChild(QScrollArea)
    assert scroll is not None
    assert dialog.minimumSizeHint().height() < 400  # it used to need 711 px

    dialog.resize(520, 420)
    app.processEvents()
    assert dialog.height() == 420

    box = dialog.findChild(QDialogButtonBox)
    footer_bottom = box.mapTo(dialog, box.rect().bottomLeft()).y()
    assert footer_bottom < dialog.height()
    # The credentials themselves stay reachable by scrolling.
    assert scroll.verticalScrollBar().maximum() > 0
    dialog.close()


def test_settings_dialog_is_fitted_into_a_short_screen(app, isolated_config):
    dialog = CredentialDialog()
    dialog.show()
    app.processEvents()

    for available in (QRect(0, 0, 1280, 600), QRect(0, 0, 1093, 574), QRect(1920, 0, 1280, 600)):
        dialog.fit_to_screen(available)
        app.processEvents()
        assert available.contains(dialog.geometry())
        assert dialog.height() <= available.height() - 48
    dialog.close()


def test_settings_dialog_is_dragged_by_its_header_only(app, isolated_config):
    dialog = CredentialDialog()
    dialog.show()
    app.processEvents()
    dialog.fit_to_screen(QRect(0, 0, 1280, 700))
    app.processEvents()

    def send(kind, local, global_point, buttons, button):
        event = QMouseEvent(
            kind,
            QPointF(*local),
            QPointF(*global_point),
            button,
            buttons,
            Qt.KeyboardModifier.NoModifier,
        )
        if kind == QEvent.Type.MouseButtonPress:
            dialog.mousePressEvent(event)
        elif kind == QEvent.Type.MouseMove:
            dialog.mouseMoveEvent(event)
        else:
            dialog.mouseReleaseEvent(event)

    origin = dialog.frameGeometry().topLeft()
    header_y = dialog._header.geometry().center().y()
    before = dialog.pos()
    send(QEvent.Type.MouseButtonPress, (60, header_y), (origin.x() + 60, origin.y() + header_y),
         Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton)
    send(QEvent.Type.MouseMove, (140, header_y + 30), (origin.x() + 140, origin.y() + header_y + 30),
         Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton)
    send(QEvent.Type.MouseButtonRelease, (140, header_y + 30), (origin.x() + 140, origin.y() + header_y + 30),
         Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton)
    assert dialog.pos() == before + QPoint(80, 30)

    # A press inside the scrolling content must not move the window.
    moved = dialog.pos()
    send(QEvent.Type.MouseButtonPress, (260, dialog.height() - 30),
         (origin.x() + 260, origin.y() + dialog.height() - 30),
         Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton)
    send(QEvent.Type.MouseMove, (300, dialog.height() - 10),
         (origin.x() + 300, origin.y() + dialog.height()),
         Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton)
    assert dialog.pos() == moved
    dialog.close()
