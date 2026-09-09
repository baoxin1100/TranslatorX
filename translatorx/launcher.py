from __future__ import annotations

import logging
import threading


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
