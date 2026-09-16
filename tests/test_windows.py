import ctypes
from ctypes import wintypes

import pytest

import translatorx.windows as windows
from translatorx.models import WindowInfo


def signed_handle(hwnd) -> int:
    return ctypes.c_ssize_t(hwnd.value or 0).value


class FakeUser32:
    def GetWindowLongW(self, _hwnd, _index):
        return 0

    def __init__(self, foreground, owner=0):
        self.foreground = foreground
        self.owner = owner

    def GetForegroundWindow(self):
        return self.foreground

    def GetAncestor(self, _hwnd, _flag):
        return self.owner


def test_target_window_must_be_foreground(monkeypatch):
    monkeypatch.setattr(windows, "user32", FakeUser32(foreground=200))
    assert windows.is_target_foreground(100) is False


def test_owned_popup_counts_as_target_foreground(monkeypatch):
    monkeypatch.setattr(windows, "user32", FakeUser32(foreground=200, owner=100))
    assert windows.is_target_foreground(100) is True


def test_overlay_can_be_excluded_without_hiding(monkeypatch):
    calls = []

    class FakeAffinity:
        def SetWindowDisplayAffinity(self, hwnd, affinity):
            calls.append((hwnd.value, affinity.value))
            return 1

    monkeypatch.setattr(windows, "user32", FakeAffinity())
    assert windows.exclude_window_from_capture(321) is True
    assert calls == [(321, windows.WDA_EXCLUDEFROMCAPTURE)]


def test_overlay_is_inserted_directly_above_target(monkeypatch):
    calls = []

    class FakeZOrder:
        def GetWindowLongW(self, _hwnd, _index):
            return 0

        def GetForegroundWindow(self):
            return 400

        def GetAncestor(self, _hwnd, _flag):
            return 0

        def IsWindow(self, hwnd):
            return hwnd.value in {100, 200, 300}

        def GetWindow(self, hwnd, command):
            assert command.value == windows.GW_HWNDPREV
            return 300 if hwnd.value == 100 else 0

        def SetWindowPos(self, hwnd, insert_after, x, y, width, height, flags):
            calls.append((hwnd.value, signed_handle(insert_after), flags))
            return 1

    monkeypatch.setattr(windows, "user32", FakeZOrder())
    assert windows.place_overlay_above_target(200, 100) is True
    assert calls == [
        (
            200,
            windows.HWND_NOTOPMOST,
            windows.SWP_NOMOVE
            | windows.SWP_NOSIZE
            | windows.SWP_NOACTIVATE,
        ),
        (
            200,
            300,
            windows.SWP_NOMOVE
            | windows.SWP_NOSIZE
            | windows.SWP_NOACTIVATE,
        ),
    ]


def test_overlay_already_directly_above_target_uses_next_real_window_as_anchor(monkeypatch):
    calls = []

    class FakeZOrder:
        def GetWindowLongW(self, _hwnd, _index):
            return 0

        def GetForegroundWindow(self):
            return 400

        def GetAncestor(self, _hwnd, _flag):
            return 0

        def IsWindow(self, _hwnd):
            return 1

        def GetWindow(self, _hwnd, command):
            if _hwnd.value == 100:
                return 200
            return 400

        def SetWindowPos(self, *_args):
            calls.append((_args[0].value, signed_handle(_args[1])))
            return 1

    monkeypatch.setattr(windows, "user32", FakeZOrder())
    assert windows.place_overlay_above_target(200, 100) is True
    assert calls == [(200, windows.HWND_NOTOPMOST), (200, 400)]


def test_background_start_keeps_foreground_tool_above_overlay(monkeypatch):
    calls = []

    class FakeZOrder:
        def GetWindowLongW(self, _hwnd, _index):
            return 0

        def GetForegroundWindow(self):
            return 400

        def GetAncestor(self, _hwnd, _flag):
            return 0

        def IsWindow(self, hwnd):
            return hwnd.value in {100, 200, 400}

        def GetWindow(self, hwnd, command):
            # Before ownership changes: tool(400) > overlay(200) > target(100).
            return 200 if hwnd.value == 100 else 400

        def SetWindowPos(self, hwnd, insert_after, _x, _y, _w, _h, _flags):
            calls.append((hwnd.value, signed_handle(insert_after)))
            return 1

    monkeypatch.setattr(windows, "user32", FakeZOrder())
    assert windows.place_overlay_above_target(200, 100) is True
    assert calls == [(200, windows.HWND_NOTOPMOST), (200, 400)]


def test_foreground_topmost_target_promotes_overlay_temporarily(monkeypatch):
    calls = []

    class FakeZOrder:
        def GetWindowLongW(self, _hwnd, _index):
            return windows.WS_EX_TOPMOST

        def GetForegroundWindow(self):
            return 100

        def GetAncestor(self, _hwnd, _flag):
            return 0

        def IsWindow(self, _hwnd):
            return 1

        def GetWindow(self, _hwnd, command):
            return 0

        def SetWindowPos(self, hwnd, insert_after, _x, _y, _w, _h, _flags):
            calls.append(("z", hwnd.value, signed_handle(insert_after)))
            return 1

    monkeypatch.setattr(windows, "user32", FakeZOrder())
    assert windows.place_overlay_above_target(200, 100) is True
    assert calls == [("z", 200, windows.HWND_TOPMOST)]


def test_native_first_show_is_constrained_before_display(monkeypatch):
    class NativeWindows(FakeUser32):
        def IsWindow(self, hwnd):
            return hwnd.value == 100

        def GetWindow(self, hwnd, command):
            # foreground tool > another window > target; preserve BOTH occluders.
            return 300

    monkeypatch.setattr(windows, "user32", NativeWindows(foreground=400))
    pos = windows.WINDOWPOS()
    pos.hwnd = 200
    pos.flags = windows.SWP_SHOWWINDOW | windows.SWP_NOZORDER
    msg = windows.wintypes.MSG()
    msg.message = windows.WM_WINDOWPOSCHANGING
    msg.lParam = ctypes.addressof(pos)
    windows.constrain_overlay_show(ctypes.addressof(msg), 100)
    assert pos.hwndInsertAfter == 300
    assert pos.flags & windows.SWP_NOACTIVATE
    assert not pos.flags & windows.SWP_NOZORDER


def test_native_hide_is_not_changed(monkeypatch):
    pos = windows.WINDOWPOS()
    pos.hwnd = 200
    pos.flags = windows.SWP_NOZORDER
    msg = windows.wintypes.MSG()
    msg.message = windows.WM_WINDOWPOSCHANGING
    msg.lParam = ctypes.addressof(pos)
    windows.constrain_overlay_show(ctypes.addressof(msg), 100)
    assert pos.flags == windows.SWP_NOZORDER
    assert pos.hwndInsertAfter is None


class StatefulZOrder(FakeUser32):
    def __init__(self, foreground, chain, topmost):
        super().__init__(foreground)
        self.chain = list(chain)
        self.topmost = set(topmost)

    def IsWindow(self, hwnd):
        return hwnd.value in self.chain

    def GetWindowLongW(self, hwnd, _index):
        return windows.WS_EX_TOPMOST if hwnd.value in self.topmost else 0

    def GetWindow(self, hwnd, _command):
        index = self.chain.index(hwnd.value)
        return self.chain[index - 1] if index else 0

    def SetWindowPos(self, hwnd, after, *_args):
        hwnd, after = hwnd.value, signed_handle(after)
        self.chain.remove(hwnd)
        if after == windows.HWND_TOPMOST:
            self.topmost.add(hwnd)
            self.chain.insert(0, hwnd)
        elif after in (windows.HWND_TOP, windows.HWND_NOTOPMOST):
            if after == windows.HWND_NOTOPMOST:
                self.topmost.discard(hwnd)
            index = next((i for i, h in enumerate(self.chain) if h not in self.topmost), len(self.chain))
            self.chain.insert(index, hwnd)
        else:
            if after in self.topmost:
                self.topmost.add(hwnd)
            else:
                self.topmost.discard(hwnd)
            self.chain.insert(self.chain.index(after) + 1, hwnd)
        return 1


def test_ordinary_target_never_promotes_overlay(monkeypatch):
    native = StatefulZOrder(100, [200, 100, 400], set())
    monkeypatch.setattr(windows, "user32", native)
    assert windows.place_overlay_above_target(200, 100)
    assert 200 not in native.topmost
    # The shell activates another normal window once, without another click.
    native.foreground = 400
    native.chain = [400, 200, 100]
    for _ in range(3):
        assert windows.place_overlay_above_target(200, 100)
        assert native.chain == [400, 200, 100]
        assert 200 not in native.topmost


def test_background_topmost_anchor_does_not_repromote_overlay(monkeypatch):
    native = StatefulZOrder(400, [500, 200, 100, 400], {500, 200})
    monkeypatch.setattr(windows, "user32", native)
    assert windows.place_overlay_above_target(200, 100)
    assert 200 not in native.topmost


def test_topmost_target_switch_demotes_overlay(monkeypatch):
    native = StatefulZOrder(100, [100, 200, 400], {100})
    monkeypatch.setattr(windows, "user32", native)
    assert windows.place_overlay_above_target(200, 100)
    assert 200 in native.topmost
    native.foreground = 400
    assert windows.place_overlay_above_target(200, 100)
    assert 200 not in native.topmost
    assert native.chain.index(400) < native.chain.index(200)


def test_foreground_child_root_does_not_put_overlay_behind_target(monkeypatch):
    class ForegroundChild(StatefulZOrder):
        def GetAncestor(self, hwnd, flag):
            return 100

    native = ForegroundChild(101, [100, 200, 400], set())
    monkeypatch.setattr(windows, "user32", native)
    assert windows.place_overlay_above_target(200, 100)
    assert native.chain.index(200) < native.chain.index(100)
    assert 200 not in native.topmost


def test_background_start_round_trip_restores_overlay(monkeypatch):
    native = StatefulZOrder(400, [400, 200, 100], set())
    monkeypatch.setattr(windows, "user32", native)
    for _ in range(3):
        assert windows.place_overlay_above_target(200, 100)
        assert native.chain == [400, 200, 100]
        native.foreground = 100
        native.chain = [100, 400, 200]
        assert windows.place_overlay_above_target(200, 100)
        assert native.chain == [200, 100, 400]
        assert 200 not in native.topmost
        native.foreground = 400
        native.chain = [400, 200, 100]


def test_cross_process_raise_checks_actual_order_and_clears_topmost(monkeypatch):
    class ForegroundRestricted(StatefulZOrder):
        promotions = 0

        def SetWindowPos(self, hwnd, after, *args):
            if signed_handle(after) == windows.HWND_TOP:
                return 1  # Win32 can succeed without raising above foreign foreground.
            if signed_handle(after) == windows.HWND_NOTOPMOST and hwnd.value not in self.topmost:
                return 1
            if signed_handle(after) == windows.HWND_TOPMOST:
                self.promotions += 1
            return super().SetWindowPos(hwnd, after, *args)

    native = ForegroundRestricted(100, [100, 400, 200], set())
    monkeypatch.setattr(windows, "user32", native)
    assert windows.place_overlay_above_target(200, 100)
    assert native.chain == [200, 100, 400]
    assert 200 not in native.topmost
    assert native.promotions == 1
    assert windows.place_overlay_above_target(200, 100)
    assert native.promotions == 1  # No repeated topmost toggling once placed.
    native.foreground = 400
    native.chain = [400, 200, 100]
    assert windows.place_overlay_above_target(200, 100)
    assert native.chain == [400, 200, 100]
    assert 200 not in native.topmost


def _raw(handle) -> int:
    """Win32 fakes receive either an int or a ctypes handle, depending on caller."""
    return int(handle.value) if hasattr(handle, "value") else int(handle)


class FakePopupDesktop:
    """EnumWindows desktop with owner chains, processes and popup styles."""

    def __init__(self, windows_in_order, owners=None, processes=None, styles=None, titles=None,
                 rects=None, invisible=()):
        self.order = list(windows_in_order)
        self.owners = dict(owners or {})
        self.processes = dict(processes or {})
        self.styles = dict(styles or {})
        self.titles = dict(titles or {})
        self.rects = dict(rects or {})
        self.invisible = set(invisible)

    def EnumWindows(self, callback, _lparam):
        for hwnd in self.order:
            # Win32 hands the callback a handle and stops the walk on a false return.
            if not callback(wintypes.HWND(hwnd), 0):
                break
        return 1

    def IsWindowVisible(self, hwnd):
        return _raw(hwnd) not in self.invisible

    def IsWindow(self, hwnd):
        return _raw(hwnd) in self.order

    def GetWindowLongW(self, hwnd, index):
        assert index == windows.GWL_STYLE
        return self.styles.get(_raw(hwnd), 0)

    def GetWindow(self, hwnd, command):
        assert command.value == windows.GW_OWNER
        return self.owners.get(_raw(hwnd), 0)

    def GetWindowThreadProcessId(self, hwnd, pointer):
        pointer._obj.value = self.processes.get(_raw(hwnd), 0)
        return 1

    def GetWindowTextLengthW(self, hwnd):
        return len(self.titles.get(_raw(hwnd), ""))

    def GetWindowTextW(self, hwnd, buffer, _length):
        text = self.titles.get(_raw(hwnd), "")
        buffer.value = text
        return len(text)

    def GetWindowRect(self, hwnd, pointer):
        left, top, right, bottom = self.rects[_raw(hwnd)]
        pointer._obj.left, pointer._obj.top = left, top
        pointer._obj.right, pointer._obj.bottom = right, bottom
        return 1

    def GetClientRect(self, hwnd, pointer):
        left, top, right, bottom = self.rects[_raw(hwnd)]
        pointer._obj.left, pointer._obj.top = 0, 0
        pointer._obj.right, pointer._obj.bottom = right - left, bottom - top
        return 1

    def ClientToScreen(self, hwnd, pointer):
        left, top, _, _ = self.rects[_raw(hwnd)]
        pointer._obj.x += left
        pointer._obj.y += top
        return 1


@pytest.fixture(autouse=True)
def _no_dwm_cloaking(monkeypatch):
    monkeypatch.setattr(windows, "dwmapi", None)


TARGET = 100
MENU = 200
OTHER_APP_WINDOW = 300


def _menu_desktop(*, menu_owner=0, menu_process=7, menu_style=windows.WS_POPUP, menu_title="python",
                  menu_rect=(40, 40, 300, 360)):
    return FakePopupDesktop(
        windows_in_order=[MENU, TARGET, OTHER_APP_WINDOW],
        owners={MENU: menu_owner},
        processes={MENU: menu_process, TARGET: 7, OTHER_APP_WINDOW: 9},
        styles={MENU: menu_style, TARGET: 0x00CF0000, OTHER_APP_WINDOW: 0x00CF0000},
        titles={MENU: menu_title, TARGET: "game", OTHER_APP_WINDOW: "browser"},
        rects={TARGET: (0, 0, 800, 600), OTHER_APP_WINDOW: (0, 0, 800, 600), MENU: menu_rect},
    )


def test_owned_menu_is_followed(monkeypatch):
    monkeypatch.setattr(windows, "user32", _menu_desktop(menu_owner=TARGET))
    popup = windows.find_target_popup(TARGET)
    assert popup is not None
    assert popup.hwnd == MENU


def test_owned_popup_is_followed_through_a_nested_owner(monkeypatch):
    desktop = _menu_desktop(menu_owner=MENU + 1)
    desktop.owners[MENU + 1] = TARGET
    desktop.styles[MENU + 1] = 0
    desktop.rects[MENU + 1] = (10, 10, 100, 100)
    desktop.order.insert(1, MENU + 1)
    monkeypatch.setattr(windows, "user32", desktop)
    assert windows.find_target_popup(TARGET).hwnd == MENU


def test_ownerless_popup_in_the_same_process_is_followed(monkeypatch):
    # Qt opens a combo box drop-down with no Win32 owner and keeps the app title.
    monkeypatch.setattr(windows, "user32", _menu_desktop(menu_owner=0))
    popup = windows.find_target_popup(TARGET)
    assert popup is not None
    assert popup.hwnd == MENU
    assert popup.title == "python"


def test_ownerless_window_of_another_process_is_ignored(monkeypatch):
    monkeypatch.setattr(windows, "user32", _menu_desktop(menu_owner=0, menu_process=9))
    assert windows.find_target_popup(TARGET) is None


def test_framed_window_of_the_same_process_is_not_a_popup(monkeypatch):
    # A caption or a resize frame means an application window, not a popup.
    monkeypatch.setattr(
        windows,
        "user32",
        _menu_desktop(menu_owner=0, menu_style=windows.WS_POPUP | windows.WS_CAPTION),
    )
    assert windows.find_target_popup(TARGET) is None


def test_ownerless_popup_below_the_target_is_ignored(monkeypatch):
    desktop = _menu_desktop(menu_owner=0)
    desktop.order = [TARGET, MENU, OTHER_APP_WINDOW]
    monkeypatch.setattr(windows, "user32", desktop)
    assert windows.find_target_popup(TARGET) is None


def test_child_window_is_not_a_popup(monkeypatch):
    monkeypatch.setattr(
        windows, "user32", _menu_desktop(menu_owner=TARGET, menu_style=windows.WS_CHILD)
    )
    assert windows.find_target_popup(TARGET) is None


def test_popup_without_target_overlap_is_ignored(monkeypatch):
    monkeypatch.setattr(
        windows, "user32", _menu_desktop(menu_owner=0, menu_rect=(2000, 2000, 2400, 2400))
    )
    assert windows.find_target_popup(TARGET) is None


def test_tiny_popup_is_ignored(monkeypatch):
    monkeypatch.setattr(
        windows, "user32", _menu_desktop(menu_owner=TARGET, menu_rect=(10, 10, 20, 16))
    )
    assert windows.find_target_popup(TARGET) is None


def test_invisible_popup_is_ignored(monkeypatch):
    desktop = _menu_desktop(menu_owner=TARGET)
    desktop.invisible.add(MENU)
    monkeypatch.setattr(windows, "user32", desktop)
    assert windows.find_target_popup(TARGET) is None


def test_excluded_windows_are_not_followed(monkeypatch):
    monkeypatch.setattr(windows, "user32", _menu_desktop(menu_owner=TARGET))
    assert windows.find_target_popup(TARGET, exclude_hwnds={MENU}) is None


def test_topmost_popup_wins(monkeypatch):
    desktop = _menu_desktop(menu_owner=TARGET)
    nested = 400
    desktop.order.insert(0, nested)
    desktop.owners[nested] = TARGET
    desktop.rects[nested] = (60, 60, 260, 200)
    desktop.processes[nested] = 7
    desktop.titles[nested] = ""
    desktop.styles[nested] = windows.WS_POPUP
    monkeypatch.setattr(windows, "user32", desktop)
    assert windows.find_target_popup(TARGET).hwnd == nested


class _Finder:
    def __init__(self, popups):
        self.popups = list(popups)
        self.calls = []

    def __call__(self, hwnd, exclude_hwnds=None):
        self.calls.append((hwnd, set(exclude_hwnds or ())))
        return self.popups[0] if self.popups else None


def test_popup_follower_reports_only_real_switches(monkeypatch):
    target = WindowInfo(TARGET, "game", 0, 0, 800, 600)
    menu = WindowInfo(MENU, "", 40, 40, 260, 320)
    finder = _Finder([menu])
    monkeypatch.setattr(windows, "find_target_popup", finder)
    follower = windows.PopupFollower()

    assert follower.active(target) is target
    assert follower.update(target, exclude_hwnds={1}) is True
    assert follower.active(target) is menu
    assert follower.hwnd == MENU
    # The same popup is not a switch, even though its rectangle keeps changing.
    assert follower.update(target, exclude_hwnds={1}) is False
    assert finder.calls[-1] == (TARGET, {1})

    finder.popups = []
    assert follower.update(target) is True
    assert follower.active(target) is target
    assert follower.hwnd == 0


def test_popup_follower_survives_a_failing_lookup(monkeypatch):
    target = WindowInfo(TARGET, "game", 0, 0, 800, 600)
    monkeypatch.setattr(
        windows, "find_target_popup", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("boom"))
    )
    follower = windows.PopupFollower()
    follower.update(target)
    assert follower.window is None
    assert follower.active(target) is target


def test_popup_follower_drops_the_popup_when_the_target_closes():
    follower = windows.PopupFollower()
    follower.window = WindowInfo(MENU, "", 0, 0, 100, 100)
    assert follower.update(None) is True
    assert follower.update(None) is False
    assert follower.active(None) is None
