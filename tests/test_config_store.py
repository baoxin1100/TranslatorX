from __future__ import annotations

import pytest

from translatorx import config_store, paths
from translatorx.config_store import ConfigStore


@pytest.fixture(autouse=True)
def _isolate_legacy_ini(monkeypatch):
    """Keep the developer's real legacy INI out of unrelated tests."""
    monkeypatch.setattr(config_store, "_legacy_ini_paths", lambda: [])


def test_store_round_trip(tmp_path):
    path = tmp_path / "translatorx.json"
    store = ConfigStore(path)
    store.set_value("engine", "baidu")
    store.set_value("window_hwnd", 1234)
    store.sync()

    assert path.is_file()
    reloaded = ConfigStore(path)
    assert reloaded.value("engine") == "baidu"
    assert reloaded.value("window_hwnd") == 1234


def test_sync_without_changes_does_not_write(tmp_path):
    path = tmp_path / "translatorx.json"
    ConfigStore(path).sync()
    assert not path.exists()


def test_value_converts_types(tmp_path):
    path = tmp_path / "translatorx.json"
    path.write_text(
        '{"flag": "true", "count": "12", "ratio": "0.5", "off": "0"}',
        encoding="utf-8",
    )
    store = ConfigStore(path)
    assert store.value("flag", False, type=bool) is True
    assert store.value("off", True, type=bool) is False
    assert store.value("count", 0, type=int) == 12
    assert store.value("ratio", 0.0, type=float) == 0.5
    assert store.value("missing", 7, type=int) == 7
    assert store.value("missing", "fallback") == "fallback"


def test_broken_json_starts_from_empty_store(tmp_path):
    path = tmp_path / "translatorx.json"
    path.write_text("{ not json", encoding="utf-8")
    store = ConfigStore(path)
    assert store.all() == {}

    store.set_value("engine", "tencent")
    store.sync()
    assert ConfigStore(path).value("engine") == "tencent"


def test_imports_legacy_ini_and_keeps_the_file(tmp_path, monkeypatch):
    legacy = tmp_path / "TranslatorX.ini"
    legacy.write_text("[General]\nengine=baidu\nshow_latency=true\n", encoding="utf-8")
    monkeypatch.setattr(config_store, "_legacy_ini_paths", lambda: [legacy])

    path = tmp_path / "translatorx.json"
    store = ConfigStore(path)

    assert store.value("engine") == "baidu"
    assert store.value("show_latency") == "true"
    assert legacy.is_file()
    assert ConfigStore(path).value("engine") == "baidu"


def test_existing_json_wins_over_legacy_ini(tmp_path, monkeypatch):
    legacy = tmp_path / "TranslatorX.ini"
    legacy.write_text("[General]\nengine=baidu\n", encoding="utf-8")
    monkeypatch.setattr(config_store, "_legacy_ini_paths", lambda: [legacy])

    path = tmp_path / "translatorx.json"
    path.write_text('{"engine": "tencent"}', encoding="utf-8")

    assert ConfigStore(path).value("engine") == "tencent"


def test_app_data_dir_sits_next_to_the_apps_directory(tmp_path, monkeypatch):
    root = tmp_path / "install"
    monkeypatch.setattr(
        paths, "PACKAGE_ROOT", root / "data" / "apps" / "TranslatorX" / "working"
    )
    assert paths.app_data_dir() == root / "data" / "TranslatorX"
    assert paths.config_file_path() == root / "data" / "TranslatorX" / "config" / "translatorx.json"
    assert paths.log_file_path() == root / "data" / "TranslatorX" / "logs" / "translatorx.log"


def test_app_data_dir_falls_back_to_the_application_directory(tmp_path, monkeypatch):
    app_dir = tmp_path / "somewhere" / "TranslatorX"
    monkeypatch.setattr(paths, "PACKAGE_ROOT", app_dir / "working")
    assert paths.app_data_dir() == app_dir


def test_app_data_dir_keeps_the_source_root(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "PACKAGE_ROOT", tmp_path / "src")
    assert paths.app_data_dir() == tmp_path / "src"


def test_app_config_is_a_singleton(tmp_path, monkeypatch):
    monkeypatch.setattr(config_store, "_store", ConfigStore(tmp_path / "translatorx.json"))
    assert config_store.app_config() is config_store.app_config()
