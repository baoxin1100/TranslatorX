from __future__ import annotations

import logging
import sys
import threading
import ctypes
from ctypes import wintypes
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .paths import log_file_path


def process_memory_mb() -> float | None:
    """Return the current process working set in MiB with one cheap Win32 call."""
    if sys.platform != "win32":
        return None
    try:
        class ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        process = ctypes.windll.kernel32.GetCurrentProcess()
        get_memory_info = ctypes.windll.psapi.GetProcessMemoryInfo
        get_memory_info.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(ProcessMemoryCounters),
            wintypes.DWORD,
        ]
        get_memory_info.restype = wintypes.BOOL
        ok = get_memory_info(
            process, ctypes.byref(counters), counters.cb
        )
        if ok:
            return counters.WorkingSetSize / (1024.0 * 1024.0)
    except (AttributeError, OSError, TypeError):
        return None
    return None


def log_path() -> Path:
    return log_file_path()


def setup_logging() -> Path:
    path = log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # Each launch starts a fresh session log; remove rollover files from the
    # previous session as well so logs do not accumulate between launches.
    for previous_log in path.parent.glob(f"{path.name}.*"):
        try:
            previous_log.unlink()
        except OSError:
            pass
    try:
        handler = RotatingFileHandler(
            path,
            mode="w",
            maxBytes=2 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
    except OSError:
        handler = logging.NullHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()
    root.addHandler(handler)
    logging.captureWarnings(True)

    def excepthook(exc_type, exc_value, exc_traceback):
        logging.getLogger("translatorx.crash").critical(
            "未捕获异常",
            exc_info=(exc_type, exc_value, exc_traceback),
        )
        sys.__excepthook__(exc_type, exc_value, exc_traceback)

    sys.excepthook = excepthook

    def thread_excepthook(args):
        logging.getLogger("translatorx.crash").critical(
            "线程未捕获异常（%s）",
            args.thread.name if args.thread else "unknown",
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    threading.excepthook = thread_excepthook
    logging.getLogger("translatorx").info("TranslatorX 启动，日志文件：%s", path)
    return path


def install_qt_message_handler() -> None:
    from PySide6.QtCore import qInstallMessageHandler

    def qt_message_handler(mode, context, message):
        logging.getLogger("translatorx.qt").warning(
            "%s (%s:%s %s)",
            message,
            context.file or "<unknown>",
            context.line,
            context.function or "<unknown>",
        )

    qInstallMessageHandler(qt_message_handler)
