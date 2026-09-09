from __future__ import annotations

import logging


logger = logging.getLogger(__name__)


def hide_pyappify_launcher() -> bool:
    """Hide the PyAppify window after TranslatorX has displayed successfully."""
    try:
        import pyappify
    except ImportError:
        logger.debug("PyAppify integration is unavailable; running without a launcher")
        return False

    if not getattr(pyappify, "pid", None):
        logger.debug("No PyAppify parent process was supplied")
        return False

    try:
        pyappify.hide_pyappify()
    except Exception:
        logger.exception("Failed to hide the PyAppify launcher")
        return False

    logger.info("TranslatorX window displayed; PyAppify launcher hidden")
    return True
