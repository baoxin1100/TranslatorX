from __future__ import annotations

import ctypes
import logging
from dataclasses import dataclass
from ctypes import wintypes

from .models import WindowInfo


_logger = logging.getLogger("translatorx.windows")

user32 = ctypes.windll.user32
dwmapi = getattr(ctypes.windll, "dwmapi", None)

GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_TOPMOST = 0x00000008
DWMWA_CLOAKED = 14
GA_ROOTOWNER = 3
GA_ROOT = 2
MONITOR_DEFAULTTONEAREST = 2
WDA_EXCLUDEFROMCAPTURE = 0x00000011
WDA_NONE = 0x00000000
VK_F8 = 0x77
WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
HC_ACTION = 0
HWND_TOP = 0
HWND_TOPMOST = -1
HWND_NOTOPMOST = -2
GW_HWNDPREV = 3
WM_WINDOWPOSCHANGING = 0x0046
SWP_NOZORDER = 0x0004
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040
SWP_FRAMECHANGED = 0x0020
GWL_STYLE = -16
WS_CAPTION = 0x00C00000
WS_THICKFRAME = 0x00040000
WS_MINIMIZEBOX = 0x00020000
WS_MAXIMIZEBOX = 0x00010000
WS_SYSMENU = 0x00080000
WS_POPUP = 0x80000000
WS_CHILD = 0x40000000
GW_OWNER = 4
POPUP_MIN_WIDTH = 24
POPUP_MIN_HEIGHT = 16
POPUP_OWNER_DEPTH = 4


@dataclass(frozen=True, slots=True)
class WindowedState:
    style: int
    ex_style: int
    rect: tuple[int, int, int, int]


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
        ("szDevice", wintypes.WCHAR * 32),
    ]

WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
user32.EnumWindows.restype = wintypes.BOOL
user32.IsWindow.argtypes = [wintypes.HWND]
user32.IsWindow.restype = wintypes.BOOL
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetWindowRect.restype = wintypes.BOOL
user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetClientRect.restype = wintypes.BOOL
user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
user32.ClientToScreen.restype = wintypes.BOOL
user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongW.restype = wintypes.LONG
user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.LONG]
user32.SetWindowLongW.restype = wintypes.LONG
class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


LowLevelKeyboardProc = ctypes.WINFUNCTYPE(
    wintypes.LPARAM, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM,
)


user32.GetForegroundWindow.argtypes = []
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetAncestor.restype = wintypes.HWND
user32.SetWindowsHookExW.argtypes = [ctypes.c_int, LowLevelKeyboardProc, wintypes.HINSTANCE, wintypes.DWORD]
user32.SetWindowsHookExW.restype = wintypes.HHOOK
user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
user32.CallNextHookEx.restype = wintypes.LPARAM
user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
user32.UnhookWindowsHookEx.restype = wintypes.BOOL
user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetWindow.restype = wintypes.HWND
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
user32.MonitorFromWindow.restype = wintypes.HMONITOR
user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MONITORINFOEXW)]
user32.GetMonitorInfoW.restype = wintypes.BOOL
if hasattr(user32, "GetDpiForWindow"):
    user32.GetDpiForWindow.argtypes = [wintypes.HWND]
    user32.GetDpiForWindow.restype = wintypes.UINT
if hasattr(user32, "SetWindowDisplayAffinity"):
    user32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
    user32.SetWindowDisplayAffinity.restype = wintypes.BOOL
user32.SetWindowPos.argtypes = [
    wintypes.HWND,
    wintypes.HWND,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.UINT,
]
user32.SetWindowPos.restype = wintypes.BOOL

if dwmapi is not None:
    dwmapi.DwmGetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
    dwmapi.DwmGetWindowAttribute.restype = ctypes.c_long


def enable_per_monitor_dpi_awareness() -> None:
    try:
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except (AttributeError, OSError):
        user32.SetProcessDPIAware()


def _is_cloaked(hwnd: int) -> bool:
    if dwmapi is None:
        return False
    cloaked = wintypes.DWORD()
    result = dwmapi.DwmGetWindowAttribute(
        wintypes.HWND(hwnd),
        wintypes.DWORD(DWMWA_CLOAKED),
        ctypes.byref(cloaked),
        ctypes.sizeof(cloaked),
    )
    return result == 0 and bool(cloaked.value)


def _client_window_rect(hwnd: int) -> tuple[int, int, int, int] | None:
    """Return the visible client area in desktop pixels, excluding frame/title bar."""
    client = wintypes.RECT()
    if not user32.GetClientRect(wintypes.HWND(hwnd), ctypes.byref(client)):
        return None
    origin = wintypes.POINT(client.left, client.top)
    if not user32.ClientToScreen(wintypes.HWND(hwnd), ctypes.byref(origin)):
        return None
    width = client.right - client.left
    height = client.bottom - client.top
    if width <= 0 or height <= 0:
        return None
    return origin.x, origin.y, width, height


def list_windows(exclude_hwnds: set[int] | None = None) -> list[WindowInfo]:
    excluded = exclude_hwnds or set()
    windows: list[WindowInfo] = []

    @WNDENUMPROC
    def callback(hwnd: int, _lparam: int) -> bool:
        hwnd_value = int(hwnd)
        if hwnd_value in excluded or not user32.IsWindowVisible(hwnd):
            return True
        if user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & WS_EX_TOOLWINDOW:
            return True
        if _is_cloaked(hwnd_value):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, len(buffer))
        title = buffer.value.strip()
        if not title:
            return True
        rect = wintypes.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return True
        client_rect = _client_window_rect(hwnd_value)
        if client_rect is None:
            return True
        left, top, width, height = client_rect
        if width < 120 or height < 80:
            return True
        windows.append(WindowInfo(hwnd_value, title, left, top, width, height))
        return True

    user32.EnumWindows(callback, 0)
    return sorted(windows, key=lambda item: item.title.casefold())


def get_window_info(hwnd: int) -> WindowInfo | None:
    if not hwnd or not user32.IsWindow(hwnd) or not user32.IsWindowVisible(hwnd):
        return None
    client_rect = _client_window_rect(hwnd)
    if client_rect is None:
        return None
    length = user32.GetWindowTextLengthW(hwnd)
    buffer = ctypes.create_unicode_buffer(max(1, length + 1))
    user32.GetWindowTextW(hwnd, buffer, len(buffer))
    left, top, width, height = client_rect
    return WindowInfo(hwnd, buffer.value.strip(), left, top, width, height)


def is_target_foreground(hwnd: int) -> bool:
    foreground = int(user32.GetForegroundWindow() or 0)
    if not foreground:
        return False
    if foreground == hwnd:
        return True
    return int(user32.GetAncestor(foreground, GA_ROOTOWNER) or 0) == hwnd


def _window_process_id(hwnd: int) -> int:
    process = wintypes.DWORD()
    user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(process))
    return int(process.value)


def _window_style(hwnd: int) -> int:
    return int(user32.GetWindowLongW(wintypes.HWND(hwnd), GWL_STYLE))


def _window_rect(hwnd: int) -> tuple[int, int, int, int] | None:
    rect = wintypes.RECT()
    if not user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect)):
        return None
    return rect.left, rect.top, rect.right, rect.bottom


def _rects_overlap(first: tuple[int, int, int, int], second: tuple[int, int, int, int]) -> bool:
    return (
        first[0] < second[2]
        and second[0] < first[2]
        and first[1] < second[3]
        and second[1] < first[3]
    )


def _is_owned_by(window: int, target: int) -> bool:
    """Walk the Win32 owner chain from ``window`` looking for ``target``."""
    current = window
    for _ in range(POPUP_OWNER_DEPTH):
        owner = int(user32.GetWindow(wintypes.HWND(current), wintypes.UINT(GW_OWNER)) or 0)
        if not owner:
            return False
        if owner == target:
            return True
        current = owner
    return False


def _is_ownerless_popup(
    window: int,
    style: int,
    process_ids: set[int],
    target_bounds: tuple[int, int, int, int] | None,
) -> bool:
    """Match the toolkits that create popups without a Win32 owner.

    Qt, for example, opens a combo box drop-down as a visible ``WS_POPUP``
    window with no owner and no frame -- it even keeps the application title,
    so the title cannot be used to tell it apart. What does tell it apart is
    being chrome-less, in the target's process, and overlapping the target: a
    window with a caption or a resize frame is an application window instead.
    """
    if not style & WS_POPUP or style & WS_CHILD:
        return False
    if style & (WS_CAPTION | WS_THICKFRAME):
        return False
    if target_bounds is None or _window_process_id(window) not in process_ids:
        return False
    bounds = _window_rect(window)
    return bounds is not None and _rects_overlap(bounds, target_bounds)


def find_target_popup(hwnd: int, exclude_hwnds: set[int] | None = None) -> WindowInfo | None:
    """Return the topmost popup that belongs to ``hwnd``, if one is open.

    Menus, combo box drop-downs, tooltips and dialogs are top-level windows of
    their own, so they never appear in a window capture of ``hwnd``. They belong
    to the target either through the Win32 owner chain or, for toolkits that do
    not set an owner, by being a chrome-less top-level window of the same
    process over it. ``EnumWindows`` walks the Z order, so the first match is the
    topmost popup, and a window that is only found below the target cannot be
    covering it.
    """
    if not hwnd:
        return None
    excluded = set(exclude_hwnds or ())
    excluded.add(hwnd)
    process_ids = {_window_process_id(hwnd)}
    target_bounds = _window_rect(hwnd)
    found: list[WindowInfo] = []
    passed_target = False

    @WNDENUMPROC
    def callback(window: int, _lparam: int) -> bool:
        nonlocal passed_target
        value = int(window)
        if value == hwnd:
            passed_target = True
            return True
        if value in excluded or not user32.IsWindowVisible(window):
            return True
        if _is_cloaked(value):
            return True
        style = _window_style(value)
        if style & WS_CHILD:
            return True
        if not _is_owned_by(value, hwnd):
            if passed_target or not _is_ownerless_popup(
                value, style, process_ids, target_bounds
            ):
                return True
        bounds = _window_rect(value)
        if bounds is None:
            return True
        if bounds[2] - bounds[0] < POPUP_MIN_WIDTH or bounds[3] - bounds[1] < POPUP_MIN_HEIGHT:
            return True
        info = get_window_info(value)
        if info is None:
            return True
        found.append(info)
        return False

    user32.EnumWindows(callback, 0)
    return found[0] if found else None


class PopupFollower:
    """Keeps track of the popup the capture should follow instead of the target."""

    def __init__(self) -> None:
        self.window: WindowInfo | None = None

    @property
    def hwnd(self) -> int:
        return self.window.hwnd if self.window is not None else 0

    def active(self, target: WindowInfo | None) -> WindowInfo | None:
        """The window to capture right now: the popup while one is open."""
        return self.window or target

    def update(self, target: WindowInfo | None, exclude_hwnds: set[int] | None = None) -> bool:
        """Refresh the followed popup. Returns True when the captured window changed."""
        if target is None:
            changed = self.window is not None
            self.window = None
            return changed
        try:
            popup = find_target_popup(target.hwnd, exclude_hwnds=exclude_hwnds)
        except Exception:
            _logger.exception("查找目标窗口弹窗失败：hwnd=%s", target.hwnd)
            popup = None
        changed = (popup.hwnd if popup is not None else 0) != self.hwnd
        self.window = popup
        return changed


_f8_hook_handle = None
_f8_hook_proc = None
_f8_on_press = None
_f8_key_down = False


def _f8_keyboard_proc(nCode, wParam, lParam):
    global _f8_key_down
    if nCode == HC_ACTION and wParam in (WM_KEYDOWN, WM_SYSKEYDOWN, WM_KEYUP, WM_SYSKEYUP):
        kb = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
        if kb.vkCode == VK_F8:
            if wParam in (WM_KEYDOWN, WM_SYSKEYDOWN):
                if not _f8_key_down and _f8_on_press is not None:
                    _f8_key_down = True
                    try:
                        _f8_on_press()
                    except Exception:
                        _logger.exception("F8 钩子回调异常")
            else:
                _f8_key_down = False
    return user32.CallNextHookEx(_f8_hook_handle, nCode, wParam, lParam)


def install_f8_hook(on_f8) -> bool:
    """Install a low-level keyboard hook that calls ``on_f8`` on the F8 key."""
    global _f8_hook_handle, _f8_hook_proc, _f8_on_press
    if _f8_hook_handle:
        return True
    _f8_on_press = on_f8
    _f8_hook_proc = LowLevelKeyboardProc(_f8_keyboard_proc)
    _f8_hook_handle = user32.SetWindowsHookExW(
        WH_KEYBOARD_LL, _f8_hook_proc, None, 0
    )
    return bool(_f8_hook_handle)


def uninstall_f8_hook() -> None:
    """Remove the low-level keyboard hook installed by :func:`install_f8_hook`."""
    global _f8_hook_handle, _f8_hook_proc, _f8_on_press, _f8_key_down
    if _f8_hook_handle:
        user32.UnhookWindowsHookEx(_f8_hook_handle)
    _f8_hook_handle = None
    _f8_hook_proc = None
    _f8_on_press = None
    _f8_key_down = False


def exclude_window_from_capture(hwnd: int) -> bool:
    """Keep our overlay visible while excluding it from desktop capture."""
    setter = getattr(user32, "SetWindowDisplayAffinity", None)
    if setter is None or not hwnd:
        return False
    return bool(setter(wintypes.HWND(hwnd), wintypes.DWORD(WDA_EXCLUDEFROMCAPTURE)))


def include_window_in_capture(hwnd: int) -> bool:
    setter = getattr(user32, "SetWindowDisplayAffinity", None)
    if setter is None or not hwnd:
        return False
    return bool(setter(wintypes.HWND(hwnd), wintypes.DWORD(WDA_NONE)))


class WINDOWPOS(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND), ("hwndInsertAfter", wintypes.HWND),
        ("x", ctypes.c_int), ("y", ctypes.c_int),
        ("cx", ctypes.c_int), ("cy", ctypes.c_int),
        ("flags", wintypes.UINT),
    ]


def _respect_foreground_barrier(anchor: int, target_hwnd: int, overlay_hwnd: int) -> int:
    foreground = int(user32.GetForegroundWindow() or 0)
    if not foreground or foreground in {target_hwnd, overlay_hwnd}:
        return anchor
    foreground = int(user32.GetAncestor(wintypes.HWND(foreground), GA_ROOT) or foreground)
    if foreground in {target_hwnd, overlay_hwnd}:
        return anchor
    # A topmost target or a shell activation transition can leave the target
    # above the new foreground window. In that case prioritize the foreground
    # window; otherwise preserve every window already occluding the target.
    current = foreground
    visited = set()
    while current and current not in visited:
        if current == target_hwnd:
            return foreground
        visited.add(current)
        current = int(user32.GetWindow(wintypes.HWND(current), wintypes.UINT(GW_HWNDPREV)) or 0)
    return anchor


def constrain_overlay_show(message, target_hwnd: int) -> None:
    """Constrain the first native show before Windows commits its Z order."""
    msg = wintypes.MSG.from_address(int(message))
    if msg.message != WM_WINDOWPOSCHANGING or not msg.lParam or not target_hwnd:
        return
    position = WINDOWPOS.from_address(msg.lParam)
    if not position.flags & SWP_SHOWWINDOW or is_target_foreground(target_hwnd):
        return
    if not user32.IsWindow(wintypes.HWND(target_hwnd)):
        return
    anchor = int(user32.GetWindow(wintypes.HWND(target_hwnd), GW_HWNDPREV) or 0)
    if anchor == position.hwnd:
        anchor = int(user32.GetWindow(position.hwnd, GW_HWNDPREV) or 0)
    anchor = _respect_foreground_barrier(anchor, target_hwnd, int(position.hwnd or 0))
    if anchor and user32.GetWindowLongW(wintypes.HWND(anchor), GWL_EXSTYLE) & WS_EX_TOPMOST:
        anchor = HWND_TOP
    position.hwndInsertAfter = anchor
    position.flags = (position.flags & ~SWP_NOZORDER) | SWP_NOACTIVATE


def place_overlay_above_target(overlay_hwnd: int, target_hwnd: int) -> bool:
    """Place the overlay above only its target, without native ownership."""
    if (
        not overlay_hwnd
        or not target_hwnd
        or not user32.IsWindow(wintypes.HWND(overlay_hwnd))
        or not user32.IsWindow(wintypes.HWND(target_hwnd))
    ):
        return False

    overlay = wintypes.HWND(overlay_hwnd)
    target = wintypes.HWND(target_hwnd)
    flags = SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE

    # Capture the target's original non-overlay predecessor before changing
    # topmost state. Demoting a topmost overlay changes the chain immediately.
    window_above_target = int(
        user32.GetWindow(target, wintypes.UINT(GW_HWNDPREV)) or 0
    )
    if window_above_target == overlay_hwnd:
        window_above_target = int(
            user32.GetWindow(overlay, wintypes.UINT(GW_HWNDPREV)) or 0
        )
        if window_above_target == overlay_hwnd:
            window_above_target = 0

    # Ordinary targets must stay in the ordinary band. Globally promoting an
    # overlay on every tick can cover a newly activated application during a
    # taskbar switch. Only a genuinely topmost target needs a topmost overlay.
    if (
        is_target_foreground(target_hwnd)
        and user32.GetWindowLongW(target, GWL_EXSTYLE) & WS_EX_TOPMOST
    ):
        return bool(user32.SetWindowPos(
            overlay, wintypes.HWND(HWND_TOPMOST),
            0, 0, 0, 0, flags,
        ))

    # Undo any topmost state left from the foreground phase, then restore the
    # overlay immediately behind the window that originally preceded target.
    if not user32.SetWindowPos(
        overlay, wintypes.HWND(HWND_NOTOPMOST),
        0, 0, 0, 0, flags,
    ):
        return False

    # Returning to an ordinary target must explicitly raise the overlay in
    # the ordinary band. Do not reuse a background anchor (or put the overlay
    # behind the target's own foreground root). Demotion above ensures this
    # does not restore global topmost behavior.
    if is_target_foreground(target_hwnd):
        if not user32.SetWindowPos(
            overlay, wintypes.HWND(HWND_TOP), 0, 0, 0, 0, flags,
        ):
            return False
        # Windows may report success yet keep an ordinary window below a
        # foreground window belonging to another process. Check the actual
        # chain before using a temporary promotion, and always demote again.
        current = int(user32.GetWindow(target, wintypes.UINT(GW_HWNDPREV)) or 0)
        visited = set()
        while current and current not in visited:
            if current == overlay_hwnd:
                return True
            visited.add(current)
            current = int(user32.GetWindow(wintypes.HWND(current), wintypes.UINT(GW_HWNDPREV)) or 0)
        if is_target_foreground(target_hwnd):
            promoted = bool(user32.SetWindowPos(
                overlay, wintypes.HWND(HWND_TOPMOST), 0, 0, 0, 0, flags,
            ))
            demoted = bool(user32.SetWindowPos(
                overlay, wintypes.HWND(HWND_NOTOPMOST), 0, 0, 0, 0, flags,
            ))
            return promoted and demoted
        # Activation changed during positioning; use the background policy.

    insert_after = (
        window_above_target
        if window_above_target and user32.IsWindow(wintypes.HWND(window_above_target))
        else HWND_TOP
    )
    insert_after = _respect_foreground_barrier(insert_after, target_hwnd, overlay_hwnd)
    # An anchor in the topmost band can promote the overlay again. HWND_TOP
    # preserves its now non-topmost status at the boundary between the bands.
    if insert_after and user32.GetWindowLongW(wintypes.HWND(insert_after), GWL_EXSTYLE) & WS_EX_TOPMOST:
        insert_after = HWND_TOP
    positioned = bool(user32.SetWindowPos(
        overlay, wintypes.HWND(insert_after), 0, 0, 0, 0,
        flags,
    ))
    if not positioned:
        return False

    return True



def make_borderless_fullscreen(hwnd: int) -> WindowedState | None:
    """Remove window chrome and cover the monitor containing ``hwnd``."""
    if not hwnd or not user32.IsWindow(wintypes.HWND(hwnd)):
        return None
    rect = wintypes.RECT()
    if not user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect)):
        return None
    monitor = user32.MonitorFromWindow(wintypes.HWND(hwnd), MONITOR_DEFAULTTONEAREST)
    info = MONITORINFOEXW()
    info.cbSize = ctypes.sizeof(info)
    if not monitor or not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        return None
    style = int(user32.GetWindowLongW(wintypes.HWND(hwnd), GWL_STYLE))
    ex_style = int(user32.GetWindowLongW(wintypes.HWND(hwnd), GWL_EXSTYLE))
    state = WindowedState(style, ex_style, (
        rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top,
    ))
    borderless_style = style & ~(WS_CAPTION | WS_THICKFRAME | WS_MINIMIZEBOX | WS_MAXIMIZEBOX | WS_SYSMENU)
    user32.SetWindowLongW(wintypes.HWND(hwnd), GWL_STYLE, borderless_style)
    monitor_rect = info.rcMonitor
    ok = user32.SetWindowPos(
        wintypes.HWND(hwnd), None,
        monitor_rect.left, monitor_rect.top,
        monitor_rect.right - monitor_rect.left,
        monitor_rect.bottom - monitor_rect.top,
        SWP_NOACTIVATE | SWP_FRAMECHANGED | SWP_SHOWWINDOW,
    )
    return state if ok else None


def restore_windowed_state(hwnd: int, state: WindowedState | None) -> bool:
    if state is None or not hwnd or not user32.IsWindow(wintypes.HWND(hwnd)):
        return False
    user32.SetWindowLongW(wintypes.HWND(hwnd), GWL_STYLE, state.style)
    user32.SetWindowLongW(wintypes.HWND(hwnd), GWL_EXSTYLE, state.ex_style)
    x, y, width, height = state.rect
    return bool(user32.SetWindowPos(
        wintypes.HWND(hwnd), None, x, y, width, height,
        SWP_NOACTIVATE | SWP_FRAMECHANGED | SWP_SHOWWINDOW,
    ))
def get_window_monitor_metrics(hwnd: int) -> tuple[int, int, int, str]:
    """Return native monitor origin, target DPI and Windows display name."""
    monitor = user32.MonitorFromWindow(wintypes.HWND(hwnd), MONITOR_DEFAULTTONEAREST)
    info = MONITORINFOEXW()
    info.cbSize = ctypes.sizeof(info)
    if not monitor or not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        return 0, 0, 96, ""
    dpi = int(user32.GetDpiForWindow(wintypes.HWND(hwnd))) if hasattr(user32, "GetDpiForWindow") else 96
    return info.rcMonitor.left, info.rcMonitor.top, dpi or 96, info.szDevice
