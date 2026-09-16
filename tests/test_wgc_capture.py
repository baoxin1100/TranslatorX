from __future__ import annotations

import threading
import time

import numpy as np
import pytest

import translatorx.wgc_capture as wgc_capture
from translatorx.models import WindowInfo

WINDOW = WindowInfo(1, "target", 0, 0, 8, 6)
FRAME = np.zeros((6, 8, 3), dtype=np.uint8)


class FakePool:
    """Stands in for the WinRT frame pool: one frame, drained on each take."""

    def __init__(self, frame) -> None:
        self.frame = frame
        self.taken = 0

    def TryGetNextFrame(self):
        self.taken += 1
        return self.frame


@pytest.fixture
def capture(monkeypatch):
    monkeypatch.setattr(wgc_capture, "_FRESH_FRAME_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(wgc_capture, "_FRAME_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(wgc_capture, "_CACHE_REFRESH_SECONDS", 0.25)
    instance = wgc_capture.WgcCapture()
    monkeypatch.setattr(instance, "_start", lambda window: True)
    monkeypatch.setattr(instance, "_crop_to_client", lambda frame, width, height: frame)
    monkeypatch.setattr(instance, "_copy_frame", lambda frame: frame)
    return instance


def test_first_frame_of_a_session_has_nothing_to_reuse(capture):
    capture._fresh_session = True
    started = time.perf_counter()
    assert capture.get_frame(WINDOW) is None
    assert time.perf_counter() - started >= 0.05
    assert capture._last_frame is None


def test_arriving_frame_completes_a_pending_request(capture):
    capture._fresh_session = True
    capture._frame_pool = FakePool(FRAME)

    def deliver() -> None:
        time.sleep(0.01)
        capture._on_frame_arrived()

    worker = threading.Thread(target=deliver)
    worker.start()
    assert capture.get_frame(WINDOW) is FRAME
    worker.join()
    # The pooled frame is taken even though nothing was asking for it yet.
    assert capture._frame_pool.taken == 1


def test_cached_frame_is_reused_without_waiting_the_long_timeout(capture):
    capture._last_frame = FRAME
    capture._fresh_session = False

    started = time.perf_counter()
    assert capture.get_frame(WINDOW) is FRAME
    elapsed = time.perf_counter() - started
    # Only the short freshness wait, not the two second session timeout.
    assert elapsed < 0.25
    assert capture._last_frame is FRAME


def test_frame_arriving_between_captures_refreshes_a_stale_cache(capture):
    capture._frame_pool = FakePool("new")
    capture._last_frame = "old"
    capture._last_frame_at = 0.0
    capture._frame_requested = False

    capture._on_frame_arrived()

    assert capture._last_frame == "new"
    assert capture._last_frame_at > 0.0


def test_frame_arriving_between_captures_does_not_copy_every_frame(capture):
    capture._frame_pool = FakePool("new")
    capture._last_frame = "recent"
    capture._last_frame_at = time.monotonic()
    capture._frame_requested = False

    capture._on_frame_arrived()

    # A 60 fps window must not pay a full frame copy per frame.
    assert capture._last_frame == "recent"


def test_closed_capture_forgets_the_cached_frame(capture):
    capture._last_frame = object()
    capture._last_frame_at = 123.0
    capture._fresh_session = False

    capture.close()

    assert capture._last_frame is None
    assert capture._last_frame_at == 0.0
    assert capture._fresh_session is True
