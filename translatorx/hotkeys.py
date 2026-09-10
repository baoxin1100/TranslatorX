"""Deprecated: F8 handling moved to a WH_KEYBOARD_LL hook in ``windows.py``.

The ``HotkeyEventFilter`` (RegisterHotKey + WM_HOTKEY) approach was replaced by
``install_f8_hook()`` / ``uninstall_f8_hook()`` so F8 still fires while a
fullscreen game captures the keyboard. This module is no longer imported.
"""
