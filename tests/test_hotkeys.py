from types import SimpleNamespace

from PySide6.QtWidgets import QApplication

from translatorx import ui


def test_ocr_and_target_gate():
    app = QApplication.instance() or QApplication([])
    state = SimpleNamespace(_ocr_ready=True, window_combo=SimpleNamespace(currentData=lambda: 100))
    assert ui.MainWindow._f8_available(state)
    state._ocr_ready = False
    assert not ui.MainWindow._f8_available(state)
    state._ocr_ready = True
    state.window_combo = SimpleNamespace(currentData=lambda: 0)
    assert not ui.MainWindow._f8_available(state)


def test_sync_installs_and_uninstalls_hook(monkeypatch):
    calls = []
    monkeypatch.setattr(ui, "install_f8_hook", lambda cb: calls.append(("install", cb)) or True)
    monkeypatch.setattr(ui, "uninstall_f8_hook", lambda: calls.append("uninstall"))
    state = SimpleNamespace(_f8_registered=False,
        _logger=SimpleNamespace(warning=lambda *_: None, info=lambda *_: None),
        window_combo=SimpleNamespace(currentData=lambda: 100), _f8_available=lambda: True,
        _on_f8_hotkey=lambda: None)
    ui.MainWindow._sync_f8_hotkey(state)
    assert state._f8_registered is True
    assert calls == [("install", state._on_f8_hotkey)]
    ui.MainWindow._sync_f8_hotkey(state)
    assert calls == [("install", state._on_f8_hotkey)]
    state._f8_available = lambda: False
    ui.MainWindow._sync_f8_hotkey(state)
    assert state._f8_registered is False
    assert calls[-1] == "uninstall"


def test_shortcut_sweep_stops_after_its_limit(monkeypatch):
    calls = []
    monkeypatch.setattr(ui, "remove_launcher_shortcuts", lambda: calls.append("sweep") or [])
    state = SimpleNamespace(
        _shortcut_sweeps=0,
        _shortcut_timer=SimpleNamespace(stop=lambda: calls.append("stop")),
        _logger=SimpleNamespace(info=lambda *_: None, exception=lambda *_: None),
    )
    for _ in range(25):
        ui.MainWindow._drop_launcher_shortcuts(state)
    assert calls.count("sweep") == 20
    assert "stop" in calls
