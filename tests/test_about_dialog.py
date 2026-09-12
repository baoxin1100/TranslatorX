from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication

from translatorx.ui import AboutDialog


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def dialog(app):
    about = AboutDialog()
    about.current_version = "v1.0.13"
    return about


def test_upgrade_button_starts_hidden_and_check_button_keeps_its_label(dialog):
    assert dialog.update_button.text() == "检查更新"
    assert dialog.upgrade_button.text() == "立即更新"
    assert dialog.upgrade_button.isHidden()


def test_newer_version_reveals_upgrade_button_without_renaming_check(dialog):
    dialog._on_checked(True, "v1.0.14", "")

    assert dialog._pending_version == "v1.0.14"
    assert dialog.status_label.text() == "发现新版本：当前 v1.0.13 → 最新 v1.0.14"
    # The check button must stay a check button.
    assert dialog.update_button.text() == "检查更新"
    assert dialog.update_button.isEnabled()
    assert not dialog.upgrade_button.isHidden()
    assert dialog.upgrade_button.isEnabled()


def test_upgrade_button_sits_below_the_version_message(app, dialog):
    dialog.show()
    app.processEvents()
    dialog._on_checked(True, "v1.0.14", "")
    app.processEvents()

    assert (
        dialog.upgrade_button.geometry().top()
        > dialog.status_label.geometry().bottom()
    )


def test_upgrade_button_hidden_when_already_latest(dialog):
    dialog._on_checked(True, "v1.0.14", "")
    assert not dialog.upgrade_button.isHidden()

    dialog._on_checked(True, "v1.0.13", "")
    assert dialog._pending_version == ""
    assert dialog.upgrade_button.isHidden()
    assert dialog.status_label.text() == "当前已是最新版本（v1.0.13）"
    assert dialog.update_button.text() == "检查更新"


def test_upgrade_button_hidden_on_failure_or_missing_version(dialog):
    dialog._on_checked(True, "v1.0.14", "")
    dialog._on_checked(False, "", "网络不可达")
    assert dialog.upgrade_button.isHidden()
    assert "网络不可达" in dialog.status_label.text()
    assert dialog.update_button.text() == "检查更新"

    dialog._on_checked(True, "", "")
    assert dialog.upgrade_button.isHidden()
    assert dialog.update_button.text() == "检查更新"


def test_upgrade_button_emits_update_request_only_when_pending(dialog):
    seen: list[str] = []
    dialog.update_requested.connect(lambda: seen.append("update"))

    dialog.upgrade_button.click()
    assert seen == []

    dialog._on_checked(True, "v1.0.14", "")
    dialog.upgrade_button.click()
    assert seen == ["update"]
