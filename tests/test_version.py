from __future__ import annotations

import json

import pytest

from translatorx import paths, version
from translatorx.version import get_app_version


@pytest.fixture(autouse=True)
def _isolate_version_sources(monkeypatch, tmp_path):
    """Keep the developer machine's app.json out of these tests."""
    monkeypatch.setattr(paths, "PACKAGE_ROOT", tmp_path / "src")
    monkeypatch.setattr(version, "app_dir", lambda: tmp_path)


def test_get_app_version_uses_pyappify_release_tag(monkeypatch):
    monkeypatch.setenv("PYAPPIFY_APP_VERSION", "v1.2.3")

    assert get_app_version() == "v1.2.3"


def test_get_app_version_falls_back_to_app_json(monkeypatch, tmp_path):
    monkeypatch.delenv("PYAPPIFY_APP_VERSION", raising=False)
    monkeypatch.setattr("pyappify.app_version", None)
    (tmp_path / "app.json").write_text('{"current_version": "v1.0.11"}', encoding="utf-8")

    assert get_app_version() == "v1.0.11"


def test_get_app_version_ignores_broken_app_json(monkeypatch, tmp_path):
    monkeypatch.delenv("PYAPPIFY_APP_VERSION", raising=False)
    monkeypatch.setattr("pyappify.app_version", None)
    (tmp_path / "app.json").write_text("{ not json", encoding="utf-8")

    assert get_app_version() == ""


def test_get_app_version_is_empty_without_release_context(monkeypatch):
    monkeypatch.delenv("PYAPPIFY_APP_VERSION", raising=False)
    monkeypatch.setattr("pyappify.app_version", None)

    assert get_app_version() == ""


def test_recorded_version_reads_current_version(tmp_path, monkeypatch):
    (tmp_path / "app.json").write_text(
        json.dumps({"name": "TranslatorX", "current_version": "v9.9.9"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(version, "app_dir", lambda: tmp_path)

    assert version._recorded_version() == "v9.9.9"
