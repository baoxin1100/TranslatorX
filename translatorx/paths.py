from __future__ import annotations

import sys
from pathlib import Path

# <app>/translatorx/paths.py -> <app>
PACKAGE_ROOT = Path(__file__).resolve().parent.parent


def install_root() -> Path:
    """Return the directory the application runs from.

    A frozen build (PyInstaller) unpacks its modules into _internal, so paths
    derived from __file__ point inside the bundle. Configuration and logs
    belong next to the executable instead.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return PACKAGE_ROOT


def app_dir() -> Path:
    """Return the directory PyAppify manages for this application.

    It holds app.json and .pyappify-shortcut.py. When running from source
    there is no launcher layout, so the source root is used.
    """
    root = install_root()
    if root.name.casefold() == "working":
        return root.parent
    return root


def app_data_dir() -> Path:
    """Return the directory that survives launcher updates and app deletion.

    PyAppify re-syncs data/apps/<app>/working on every update and deletes
    anything there that is not part of the synced repository, and its "delete
    app" action removes data/apps/<app> entirely. Keeping configuration and
    logs beside apps avoids both.
    """
    root = install_root()
    if root.name.casefold() != "working":
        return root

    app_dir = root.parent
    apps_dir = app_dir.parent
    data_dir = apps_dir.parent
    if apps_dir.name.casefold() == "apps" and data_dir.name.casefold() == "data":
        return data_dir / app_dir.name
    return app_dir


def config_dir() -> Path:
    return app_data_dir() / "config"


def config_file_path() -> Path:
    return config_dir() / "translatorx.json"


def log_dir() -> Path:
    return app_data_dir() / "logs"


def log_file_path() -> Path:
    return log_dir() / "translatorx.log"


def debug_capture_path() -> Path:
    return log_dir() / "debug_capture.png"
