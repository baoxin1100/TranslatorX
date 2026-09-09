from __future__ import annotations

import sys
from types import SimpleNamespace

from translatorx.launcher import hide_pyappify_launcher


def test_hide_pyappify_launcher_calls_launcher_api(monkeypatch):
    calls = []
    monkeypatch.setitem(
        sys.modules,
        "pyappify",
        SimpleNamespace(pid=123, hide_pyappify=lambda: calls.append("hidden")),
    )

    assert hide_pyappify_launcher() is True
    assert calls == ["hidden"]


def test_hide_pyappify_launcher_does_not_break_startup(monkeypatch):
    def fail_to_hide():
        raise RuntimeError("launcher unavailable")

    monkeypatch.setitem(
        sys.modules,
        "pyappify",
        SimpleNamespace(pid=123, hide_pyappify=fail_to_hide),
    )

    assert hide_pyappify_launcher() is False


def test_hide_pyappify_launcher_ignores_direct_start(monkeypatch):
    calls = []
    monkeypatch.setitem(
        sys.modules,
        "pyappify",
        SimpleNamespace(pid=None, hide_pyappify=lambda: calls.append("hidden")),
    )

    assert hide_pyappify_launcher() is False
    assert calls == []
