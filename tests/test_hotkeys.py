import ctypes
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication

from translatorx.hotkeys import HotkeyEventFilter
from translatorx import ui, windows


@pytest.mark.parametrize("event_type", [b"windows_generic_MSG", b"windows_dispatcher_MSG"])
def test_filter_handles_own_hotkey_once(event_type):
    calls = []
    listener = HotkeyEventFilter(123, lambda: calls.append(True))
    msg = windows.wintypes.MSG()
    msg.message = windows.WM_HOTKEY
    msg.wParam = 123
    assert listener.nativeEventFilter(event_type, ctypes.addressof(msg)) == (True, 0)
    assert calls == [True]
    msg.wParam = 456
    assert listener.nativeEventFilter(event_type, ctypes.addressof(msg)) == (False, 0)
    assert calls == [True]


def test_registration_uses_thread_queue_and_retries_failure(monkeypatch):
    calls = []
    answers = iter([False, True])
    monkeypatch.setattr(ui, "register_f8_hotkey", lambda hwnd, key: calls.append((hwnd, key)) or next(answers))
    monkeypatch.setattr(ui, "unregister_hotkey", lambda hwnd, key: calls.append(("remove", hwnd, key)))
    state = SimpleNamespace(_f8_registered=False, _f8_registration_failed=False,
        HOTKEY_ID=123, _logger=SimpleNamespace(warning=lambda *_: None, info=lambda *_: None),
        window_combo=SimpleNamespace(currentData=lambda: 100), _f8_available=lambda: True)
    ui.MainWindow._sync_f8_hotkey(state)
    assert not state._f8_registered
    ui.MainWindow._sync_f8_hotkey(state)
    assert state._f8_registered
    ui.MainWindow._sync_f8_hotkey(state)
    assert calls == [(0, 123), (0, 123)]
    state._f8_available = lambda: False
    ui.MainWindow._sync_f8_hotkey(state)
    assert not state._f8_registered
    assert calls[-1] == ("remove", 0, 123)


def test_target_foreground_and_ocr_gate(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(ui, "is_target_foreground", lambda hwnd: hwnd == 100)
    state = SimpleNamespace(_ocr_ready=True, window_combo=SimpleNamespace(currentData=lambda: 100))
    assert ui.MainWindow._f8_available(state)
    state._ocr_ready = False
    assert not ui.MainWindow._f8_available(state)
    state._ocr_ready = True
    monkeypatch.setattr(ui, "is_target_foreground", lambda hwnd: False)
    assert not ui.MainWindow._f8_available(state)
