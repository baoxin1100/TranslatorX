from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication

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
