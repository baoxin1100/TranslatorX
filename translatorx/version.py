from __future__ import annotations

import os


def get_app_version() -> str:
    """Return the release tag supplied by the PyAppify launcher."""
    version = os.environ.get("PYAPPIFY_APP_VERSION", "").strip()
    if version:
        return version

    try:
        import pyappify
    except ImportError:
        return ""

    return str(getattr(pyappify, "app_version", "") or "").strip()
