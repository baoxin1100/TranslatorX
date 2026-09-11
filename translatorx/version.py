from __future__ import annotations

import json
import os

from .paths import app_dir


def _environment_version() -> str:
    return os.environ.get("PYAPPIFY_APP_VERSION", "").strip()


def _module_version() -> str:
    try:
        import pyappify
    except ImportError:
        return ""
    return str(getattr(pyappify, "app_version", "") or "").strip()


def _recorded_version() -> str:
    """Read the version PyAppify recorded in ``app.json``.

    PyAppify only exports ``PYAPPIFY_APP_VERSION`` when it starts the app
    itself. The application shortcut starts the app directly, so the version
    has to come from the metadata the launcher maintains.
    """
    try:
        payload = (app_dir() / "app.json").read_text(encoding="utf-8")
    except OSError:
        return ""
    try:
        data = json.loads(payload)
    except ValueError:
        return ""
    if not isinstance(data, dict):
        return ""
    return str(data.get("current_version") or "").strip()


def get_app_version() -> str:
    """Return the release tag of the installed build, or "" when unknown."""
    for candidate in (_environment_version(), _module_version(), _recorded_version()):
        if candidate:
            return candidate
    return ""
