from __future__ import annotations

import logging
import os
import threading
from pathlib import Path


logger = logging.getLogger(__name__)


def hide_pyappify_launcher() -> bool:
    """Dismiss the PyAppify launcher after TranslatorX is fully displayed."""
    try:
        import pyappify
    except ImportError:
        logger.debug("PyAppify integration is unavailable; running without a launcher")
        return False

    if not getattr(pyappify, "pid", None):
        logger.debug("No PyAppify parent process was supplied")
        return False

    def dismiss_launcher() -> None:
        try:
            pyappify.hide_pyappify()
        except Exception:
            logger.exception("Failed to minimize the PyAppify launcher")
        try:
            pyappify.kill_pyappify()
        except Exception:
            logger.exception("Failed to close the PyAppify launcher")
        else:
            logger.info("TranslatorX window displayed; PyAppify launcher closed")

    threading.Thread(
        target=dismiss_launcher,
        name="translatorx-close-launcher",
        daemon=True,
    ).start()
    return True


def show_launcher() -> bool:
    """Open the PyAppify launcher window so the user can apply an update."""
    try:
        import pyappify
    except ImportError:
        logger.warning("PyAppify integration is unavailable; cannot open the launcher")
        return False

    opener = getattr(pyappify, "show_pyappify", None)
    if opener is None:
        logger.warning("This PyAppify version does not expose show_pyappify()")
        return False

    try:
        result = opener()
    except Exception:
        logger.exception("Failed to open the PyAppify launcher")
        return False
    logger.info("PyAppify launcher requested; pid=%s", result)
    return result is not None


def _launcher_executable() -> str | None:
    try:
        import pyappify
    except ImportError:
        return None

    executable = getattr(pyappify, "pyappify_executable", None)
    if executable:
        return str(executable)

    finder = getattr(pyappify, "find_pyappify_executable", None)
    if finder is None:
        return None
    try:
        return finder()
    except Exception:
        logger.debug("Failed to locate the PyAppify launcher", exc_info=True)
        return None


def _shortcut_directories() -> list[Path]:
    directories: list[Path] = []
    appdata = os.environ.get("APPDATA")
    if appdata:
        directories.append(Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs")
        directories.append(
            Path(appdata)
            / "Microsoft"
            / "Internet Explorer"
            / "Quick Launch"
            / "User Pinned"
            / "TaskBar"
        )
    programdata = os.environ.get("ProgramData")
    if programdata:
        directories.append(Path(programdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs")
    for key in ("USERPROFILE", "PUBLIC"):
        base = os.environ.get(key)
        if base:
            directories.append(Path(base) / "Desktop")
    return directories


def _references_executable(shortcut: Path, executable_name: str) -> bool:
    try:
        data = shortcut.read_bytes()
    except OSError:
        return False
    for encoding in ("utf-16-le", "mbcs", "utf-8"):
        try:
            needle = executable_name.encode(encoding)
        except (LookupError, UnicodeError):
            continue
        if needle in data:
            return True
    return False


def remove_launcher_shortcuts() -> list[str]:
    """Delete launcher shortcuts so only the application shortcut remains.

    PyAppify unconditionally recreates both shortcuts whenever the launcher
    runs, so this runs again on every application start.
    """
    executable = _launcher_executable()
    if not executable:
        logger.debug("PyAppify launcher executable unknown; leaving shortcuts untouched")
        return []

    executable_name = os.path.basename(executable)
    app_name = os.path.splitext(executable_name)[0]
    keep = f"{app_name}.lnk".casefold()

    removed: list[str] = []
    for directory in _shortcut_directories():
        if not directory.is_dir():
            continue
        for shortcut in sorted(directory.glob("*.lnk")):
            if shortcut.name.casefold() == keep:
                continue
            if not _references_executable(shortcut, executable_name):
                continue
            try:
                shortcut.unlink()
            except OSError as exc:
                logger.warning("Failed to remove launcher shortcut %s: %s", shortcut, exc)
                continue
            removed.append(str(shortcut))
            logger.info("Removed launcher shortcut %s", shortcut)
    return removed
