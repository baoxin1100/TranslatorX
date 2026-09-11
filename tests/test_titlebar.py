from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication, QMainWindow, QToolButton

from translatorx.ui import TitleBar


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


class _StubWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[str] = []

    def open_settings(self) -> None:
        self.calls.append("settings")

    def hide_to_tray(self) -> None:
        self.calls.append("tray")


def test_titlebar_exposes_settings_minimize_and_close(app):
    window = _StubWindow()
    bar = TitleBar(window)

    buttons = bar.findChildren(QToolButton)
    assert [button.toolTip() for button in buttons] == [
        "翻译服务设置",
        "最小化到系统托盘",
        "关闭程序",
    ]

    buttons[0].click()
    buttons[1].click()
    assert window.calls == ["settings", "tray"]
