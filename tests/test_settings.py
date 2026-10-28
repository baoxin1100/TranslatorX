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

def test_provider_picker_prefills_base_url_and_free_models(app, isolated_config):
    dialog = CredentialDialog()
    combo = dialog.provider_combo
    combo.setCurrentIndex(combo.findData("zhipu"))
    app.processEvents()

    assert dialog.openai_base_url.text() == "https://open.bigmodel.cn/api/paas/v4"
    labels = [dialog.openai_model.itemText(index) for index in range(dialog.openai_model.count())]
    assert "glm-4.7-flash（免费）" in labels
    # The saved value must be the model id, not the decorated label.
    assert dialog._model_text() == "glm-4.7-flash"
    assert "GLM-4.7-Flash" in dialog.provider_note.text()


def test_saving_settings_persists_the_provider_and_model_id(app, isolated_config):
    dialog = CredentialDialog()
    combo = dialog.provider_combo
    combo.setCurrentIndex(combo.findData("volcengine"))
    dialog._save_and_accept()

    assert isolated_config.value("TRANSLATORX_OPENAI_PROVIDER") == "volcengine"
    assert isolated_config.value("TRANSLATORX_OPENAI_BASE_URL").startswith("https://ark.")
    assert isolated_config.value("TRANSLATORX_OPENAI_MODEL") == "doubao-seed-2.0-lite"


def test_saved_provider_is_restored_when_the_dialog_reopens(app, isolated_config):
    isolated_config.setValue("TRANSLATORX_OPENAI_PROVIDER", "deepseek")
    isolated_config.setValue("TRANSLATORX_OPENAI_BASE_URL", "https://api.deepseek.com/v1")
    isolated_config.setValue("TRANSLATORX_OPENAI_MODEL", "deepseek-chat")

    dialog = CredentialDialog()
    assert dialog.provider_combo.currentData() == "deepseek"
    assert dialog.openai_base_url.text() == "https://api.deepseek.com/v1"
    assert dialog._model_text() == "deepseek-chat"


def test_provider_is_inferred_from_the_saved_base_url(app, isolated_config):
    isolated_config.setValue(
        "TRANSLATORX_OPENAI_BASE_URL", "https://open.bigmodel.cn/api/paas/v4"
    )
    isolated_config.setValue("TRANSLATORX_OPENAI_MODEL", "glm-4.7-flash")

    dialog = CredentialDialog()
    assert dialog.provider_combo.currentData() == "zhipu"
    assert dialog._model_text() == "glm-4.7-flash"

def test_pasting_a_vendor_base_url_adopts_its_provider(app, isolated_config):
    dialog = CredentialDialog()
    combo = dialog.provider_combo
    combo.setCurrentIndex(combo.findData("custom"))
    dialog.openai_base_url.setText("https://open.bigmodel.cn/api/paas/v4/")

    dialog._detect_provider_from_url()

    assert combo.currentData() == "zhipu"
    assert dialog.openai_base_url.text() == "https://open.bigmodel.cn/api/paas/v4"
    assert dialog._model_text() == "glm-4.7-flash"


def test_model_fetch_failure_explains_a_missing_model_list(app, isolated_config):
    dialog = CredentialDialog()
    combo = dialog.provider_combo
    combo.setCurrentIndex(combo.findData("zhipu"))

    dialog._show_model_results(
        {"ok": False, "error": "401 Client Error: Unauthorized", "latency": 113}
    )

    text = dialog.test_results.toPlainText()
    assert "401" in text
    assert "没有 /models 列表接口" in text

def test_model_fetch_button_only_shows_when_the_provider_has_no_presets(app, isolated_config):
    dialog = CredentialDialog()
    dialog.show()
    app.processEvents()
    combo = dialog.provider_combo

    combo.setCurrentIndex(combo.findData("zhipu"))
    app.processEvents()
    # 智谱 has no /models route, so the button would only ever fail.
    assert dialog.fetch_models_button.isHidden()

    combo.setCurrentIndex(combo.findData("siliconflow"))
    app.processEvents()
    assert not dialog.fetch_models_button.isHidden()
    dialog.close()
