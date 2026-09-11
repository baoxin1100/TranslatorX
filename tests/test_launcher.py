from __future__ import annotations

import sys
from types import SimpleNamespace

from translatorx import launcher
from translatorx.launcher import hide_pyappify_launcher


def test_hide_pyappify_launcher_calls_launcher_api(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "translatorx.launcher.threading.Thread",
        lambda target, **_kwargs: SimpleNamespace(start=target),
    )
    monkeypatch.setitem(
        sys.modules,
        "pyappify",
        SimpleNamespace(
            pid=123,
            hide_pyappify=lambda: calls.append("hidden"),
            kill_pyappify=lambda: calls.append("closed"),
        ),
    )

    assert hide_pyappify_launcher() is True
    assert calls == ["hidden", "closed"]


def test_hide_pyappify_launcher_does_not_break_startup(monkeypatch):
    calls = []

    def fail_to_hide():
        raise RuntimeError("launcher unavailable")

    monkeypatch.setattr(
        "translatorx.launcher.threading.Thread",
        lambda target, **_kwargs: SimpleNamespace(start=target),
    )
    monkeypatch.setitem(
        sys.modules,
        "pyappify",
        SimpleNamespace(
            pid=123,
            hide_pyappify=fail_to_hide,
            kill_pyappify=lambda: calls.append("closed"),
        ),
    )

    assert hide_pyappify_launcher() is True
    assert calls == ["closed"]


def test_hide_pyappify_launcher_ignores_direct_start(monkeypatch):
    calls = []
    monkeypatch.setitem(
        sys.modules,
        "pyappify",
        SimpleNamespace(
            pid=None,
            hide_pyappify=lambda: calls.append("hidden"),
            kill_pyappify=lambda: calls.append("closed"),
        ),
    )

    assert hide_pyappify_launcher() is False
    assert calls == []


def test_show_launcher_opens_the_launcher(monkeypatch):
    monkeypatch.setitem(sys.modules, "pyappify", SimpleNamespace(show_pyappify=lambda: 4321))
    assert launcher.show_launcher() is True


def test_show_launcher_without_pyappify(monkeypatch):
    monkeypatch.setitem(sys.modules, "pyappify", SimpleNamespace())
    assert launcher.show_launcher() is False


def test_references_executable_matches_utf16_path(tmp_path):
    shortcut = tmp_path / "probe.lnk"
    shortcut.write_bytes(b"\x00" * 16 + "TranslatorX.exe".encode("utf-16-le") + b"\x00" * 8)
    assert launcher._references_executable(shortcut, "TranslatorX.exe") is True
    assert launcher._references_executable(shortcut, "Other.exe") is False


def test_references_executable_missing_file(tmp_path):
    assert launcher._references_executable(tmp_path / "missing.lnk", "TranslatorX.exe") is False


def test_remove_launcher_shortcuts_keeps_application_shortcut(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "_launcher_executable", lambda: r"C:\apps\TranslatorX.exe")
    monkeypatch.setattr(launcher, "_shortcut_directories", lambda: [tmp_path])

    app_shortcut = tmp_path / "TranslatorX.lnk"
    launcher_shortcut = tmp_path / "TranslatorX Launcher.lnk"
    other_shortcut = tmp_path / "Other App.lnk"
    app_shortcut.write_bytes(b"pythonw.exe" + b"\x00" * 8)
    launcher_shortcut.write_bytes(b"prefix" + "TranslatorX.exe".encode("utf-16-le"))
    other_shortcut.write_bytes(b"unrelated payload")

    removed = launcher.remove_launcher_shortcuts()

    assert app_shortcut.exists()
    assert other_shortcut.exists()
    assert not launcher_shortcut.exists()
    assert removed == [str(launcher_shortcut)]


def test_remove_launcher_shortcuts_without_pyappify(monkeypatch):
    monkeypatch.setattr(launcher, "_launcher_executable", lambda: None)
    assert launcher.remove_launcher_shortcuts() == []
