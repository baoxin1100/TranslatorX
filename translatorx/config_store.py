from __future__ import annotations

import configparser
import json
import logging
import os
from pathlib import Path
from typing import Any

from .paths import config_file_path


_logger = logging.getLogger("translatorx.config")


def _legacy_ini_paths() -> list[Path]:
    """Locations used by the retired QSettings-based store, newest first."""
    paths: list[Path] = []
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        paths.append(Path(local_appdata) / "TranslatorX" / "TranslatorX" / "TranslatorX.ini")
    package_root = Path(__file__).resolve().parent.parent
    paths.append(package_root / "TranslatorX" / "TranslatorX.ini")
    paths.append(Path(__file__).resolve().parent / "TranslatorX.ini")
    return paths


def _read_legacy_ini(path: Path) -> dict[str, str]:
    parser = configparser.ConfigParser()
    try:
        with path.open("r", encoding="utf-8") as handle:
            parser.read_file(handle)
    except (OSError, configparser.Error, UnicodeError):
        _logger.warning("无法读取旧版配置文件：%s", path, exc_info=True)
        return {}
    return {key: value for _section in parser.sections() for key, value in parser.items(_section)}


class ConfigStore:
    """Dictionary backed by a JSON file inside the application directory."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = Path(path) if path is not None else config_file_path()
        self._values: dict[str, Any] = {}
        self._dirty = False
        self._loaded = self._read()
        if not self._loaded:
            self._import_legacy_settings()

    @property
    def path(self) -> Path:
        return self._path

    def _read(self) -> bool:
        try:
            raw = self._path.read_text(encoding="utf-8")
        except OSError:
            return False
        try:
            data = json.loads(raw)
        except ValueError:
            _logger.warning("配置文件不是合法 JSON，将重新创建：%s", self._path)
            return False
        if isinstance(data, dict):
            self._values = {str(key): value for key, value in data.items()}
        return True

    def _import_legacy_settings(self) -> None:
        """One-off import of the retired INI store.

        The legacy file is left in place so an older installation sharing it
        keeps working until it is replaced.
        """
        for legacy in _legacy_ini_paths():
            if not legacy.is_file():
                continue
            values = _read_legacy_ini(legacy)
            if not values:
                continue
            self._values.update(values)
            self._dirty = True
            self.sync()
            _logger.info("已从旧版 INI 迁移 %d 项配置：%s", len(values), legacy)
            if legacy.exists():
                _logger.info("旧版配置文件仍保留，可手动删除：%s", legacy)
            return

    def all(self) -> dict[str, Any]:
        return dict(self._values)

    def value(self, key: str, default: Any = None, type: Any = None) -> Any:  # noqa: A002
        value = self._values.get(key, default)
        if type is None or value is None:
            return value
        converted = self._convert(value, type)
        return default if converted is None else converted

    @staticmethod
    def _convert(value: Any, target: type) -> Any:
        if isinstance(value, target) and target is not bool:
            return value
        try:
            if target is bool:
                if isinstance(value, str):
                    return value.strip().lower() in {"1", "true", "yes", "on"}
                return bool(value)
            if target is int:
                return int(value)
            if target is float:
                return float(value)
            if target is str:
                return str(value)
        except (TypeError, ValueError):
            return None
        return value

    def set_value(self, key: str, value: Any) -> None:
        self._values[str(key)] = value
        self._dirty = True

    setValue = set_value  # noqa: N815 - keeps QSettings call sites unchanged

    def sync(self) -> None:
        if not self._dirty:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self._path.with_name(self._path.name + ".tmp")
            temporary.write_text(
                json.dumps(self._values, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            temporary.replace(self._path)
        except OSError:
            _logger.exception("写入配置文件失败：%s", self._path)
            return
        self._dirty = False


_store: ConfigStore | None = None


def app_config() -> ConfigStore:
    """Return the process-wide configuration store."""
    global _store
    if _store is None:
        _store = ConfigStore()
    return _store


def set_app_config(store: ConfigStore | None) -> None:
    """Replace the process-wide store (used by tests)."""
    global _store
    _store = store
