from __future__ import annotations

from translatorx.version import get_app_version


def test_get_app_version_uses_pyappify_release_tag(monkeypatch):
    monkeypatch.setenv("PYAPPIFY_APP_VERSION", "v1.2.3")

    assert get_app_version() == "v1.2.3"


def test_get_app_version_is_empty_without_release_context(monkeypatch):
    monkeypatch.delenv("PYAPPIFY_APP_VERSION", raising=False)
    monkeypatch.setattr("pyappify.app_version", None)

    assert get_app_version() == ""
