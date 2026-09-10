import ctypes

import translatorx.windows as windows


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
