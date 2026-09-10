from __future__ import annotations

from PySide6.QtCore import QAbstractNativeEventFilter

from .windows import is_hotkey_message


class HotkeyEventFilter(QAbstractNativeEventFilter):
    """Receive registered hotkeys independently of QWidget native dispatch."""

    def __init__(self, hotkey_id: int, callback) -> None:
        super().__init__()
        self.hotkey_id = hotkey_id
        self.callback = callback

    def nativeEventFilter(self, event_type, message):  # noqa: N802
        if bytes(event_type) in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
            if is_hotkey_message(message, self.hotkey_id):
                self.callback()
                return True, 0
        return False, 0
