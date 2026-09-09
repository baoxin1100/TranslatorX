import translatorx.windows as windows


class FakeUser32:
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
