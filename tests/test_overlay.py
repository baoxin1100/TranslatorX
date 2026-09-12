import numpy as np
from PySide6.QtCore import QPoint
from PySide6.QtGui import QFont, QFontMetricsF
from PySide6.QtWidgets import QApplication

from translatorx.models import LayoutMode, OcrItem, WindowInfo
from translatorx.overlay import (
    BELOW_WIDTH_FACTOR,
    MIN_BELOW_WIDTH,
    _is_usable_capture,
    _is_valid_wgc_capture,
    _normalize_qt_capture,
    build_render_items,
    native_rect_to_qt,
)


def _app():
    return QApplication.instance() or QApplication([])


def test_below_layout_is_clamped_inside_window():
    _app()
    item = OcrItem(
        box=((900, 930), (995, 930), (995, 995), (900, 995)),
        text="source",
        confidence=0.99,
        translation="这是一段靠近窗口右下角的译文",
    )
    rendered = build_render_items([item], LayoutMode.BELOW, 1000, 1000, 500, 400, QFont())
    rect = rendered[0].rect
    assert rect.left() >= 0
    assert rect.top() >= 0
    assert rect.right() <= 500
    assert rect.bottom() <= 400


def test_right_layout_is_clamped_inside_window():
    _app()
    item = OcrItem(
        box=((480, 10), (500, 10), (500, 70), (480, 70)),
        text="source",
        confidence=0.99,
        translation="translated text",
    )
    rendered = build_render_items([item], LayoutMode.RIGHT, 500, 400, 500, 400, QFont())
    rect = rendered[0].rect
    assert rect.left() >= 0
    assert rect.right() <= 500
    assert rect.bottom() <= 400


def test_below_layout_is_centered_on_source_text():
    _app()
    item = OcrItem(
        box=((400, 200), (600, 200), (600, 260), (400, 260)),
        text="source",
        confidence=0.99,
        translation="居中译文",
    )
    rendered = build_render_items([item], LayoutMode.BELOW, 1000, 1000, 500, 400, QFont())
    assert rendered[0].centered is True
    assert abs(rendered[0].rect.center().x() - 250.0) < 0.01


def test_right_layout_keeps_left_aligned_text():
    _app()
    item = OcrItem(
        box=((100, 100), (220, 100), (220, 160), (100, 160)),
        text="source",
        confidence=0.99,
        translation="translated text",
    )
    rendered = build_render_items([item], LayoutMode.RIGHT, 500, 400, 500, 400, QFont())
    assert rendered[0].centered is False


def test_translation_font_uses_the_selected_size_for_each_item():
    _app()
    small = OcrItem(
        box=((100, 100), (300, 100), (300, 120), (100, 120)),
        text="small",
        confidence=0.99,
        translation="小字号",
    )
    large = OcrItem(
        box=((100, 200), (300, 200), (300, 280), (100, 280)),
        text="large",
        confidence=0.99,
        translation="大字号",
    )
    rendered = build_render_items(
        [small, large], LayoutMode.BELOW, 500, 400, 500, 400, QFont("Microsoft YaHei UI", 12)
    )
    assert rendered[0].font.pixelSize() == rendered[1].font.pixelSize() == 12


def test_below_translation_sits_close_to_source():
    _app()
    item = OcrItem(
        box=((100, 100), (300, 100), (300, 140), (100, 140)),
        text="source",
        confidence=0.99,
        translation="译文",
    )
    rendered = build_render_items([item], LayoutMode.BELOW, 500, 400, 500, 400, QFont())
    assert rendered[0].rect.top() == 135


def test_below_layout_follows_the_source_width_past_the_old_cap():
    _app()
    item = OcrItem(
        box=((100, 100), (700, 100), (700, 140), (100, 140)),
        text="source",
        confidence=0.99,
        translation="A translation line that is longer than the old 360 pixel cap allowed",
    )
    rendered = build_render_items([item], LayoutMode.BELOW, 1000, 500, 1000, 500, QFont())
    rect = rendered[0].rect
    # Wide enough for the 600 px source line, past the old fixed 360 px cap.
    assert rect.width() >= 600.0
    assert rect.width() <= 1000 - 8
    # One line: the source box is wide enough, so nothing wraps.
    assert rect.height() <= QFontMetricsF(rendered[0].font).height() + 2


def test_below_layout_is_bounded_by_the_window_edge():
    _app()
    item = OcrItem(
        box=((100, 100), (900, 100), (900, 140), (100, 140)),
        text="source",
        confidence=0.99,
        translation="译文",
    )
    rendered = build_render_items([item], LayoutMode.BELOW, 1000, 500, 500, 500, QFont())
    rect = rendered[0].rect
    assert rect.width() <= 500 - 8
    assert rect.left() >= 0
    assert rect.right() <= 500


def test_below_layout_stops_at_1_3_times_the_source_width():
    _app()
    font = QFont("Microsoft YaHei UI", 12)
    item = OcrItem(
        box=((100, 100), (500, 100), (500, 140), (100, 140)),
        text="source",
        confidence=0.99,
        translation="A translation that is far too long to fit on one line inside the allowance",
    )
    rendered = build_render_items([item], LayoutMode.BELOW, 1920, 1080, 1920, 1080, font)
    rect = rendered[0].rect
    expected = 400.0 * BELOW_WIDTH_FACTOR
    assert abs(rect.width() - expected) < 0.01
    # Longer than the allowance, so it wraps.
    assert rect.height() > QFontMetricsF(rendered[0].font).height() + 2


def test_below_layout_keeps_a_readable_minimum_for_a_narrow_source():
    _app()
    font = QFont("Microsoft YaHei UI", 12)
    item = OcrItem(
        box=((100, 100), (120, 100), (120, 140), (100, 140)),
        text="source",
        confidence=0.99,
        translation="这是一段会很长很长的译文用来测试窄原文框的下限",
    )
    rendered = build_render_items([item], LayoutMode.BELOW, 1920, 1080, 1920, 1080, font)
    assert rendered[0].rect.width() == MIN_BELOW_WIDTH


def test_right_layout_keeps_its_own_width_cap():
    _app()
    item = OcrItem(
        box=((100, 100), (300, 100), (300, 140), (100, 140)),
        text="source",
        confidence=0.99,
        translation="A reasonably long translation that would exceed the right layout cap",
    )
    rendered = build_render_items([item], LayoutMode.RIGHT, 1920, 1080, 1920, 1080, QFont())
    assert rendered[0].rect.width() == 300.0


def test_below_translations_avoid_long_wrapped_translation():
    _app()
    items = [
        OcrItem(
            box=((80, 100), (300, 100), (300, 140), (80, 140)),
            text="first",
            confidence=0.99,
            translation="第一行很长的译文会换行显示并占用更多高度",
        ),
        OcrItem(
            box=((80, 150), (300, 150), (300, 190), (80, 190)),
            text="second",
            confidence=0.99,
            translation="第二行译文",
        ),
    ]
    rendered = build_render_items(items, LayoutMode.BELOW, 400, 400, 400, 400, QFont())
    assert not rendered[0].rect.intersects(rendered[1].rect)


def test_native_window_rect_is_scaled_for_125_percent_dpi():
    target = WindowInfo(1, "game", 0, 0, 1824, 1068)
    logical = native_rect_to_qt(target, 0, 0, 120, QPoint(0, 0))
    assert logical.width() == 1459
    assert logical.height() == 854


def test_native_window_rect_preserves_monitor_relative_origin():
    target = WindowInfo(1, "game", 2100, 100, 1000, 800)
    logical = native_rect_to_qt(target, 1920, 0, 120, QPoint(1536, 0))
    assert logical.x() == 1680
    assert logical.y() == 80


def test_capture_validation_rejects_blank_and_binary_fallback_frames():
    blank = np.zeros((32, 48, 3), dtype=np.uint8)
    binary = np.zeros((32, 48, 3), dtype=np.uint8)
    binary[:, 24:] = 255
    assert not _is_usable_capture(blank, 48, 32)
    assert not _is_usable_capture(binary, 48, 32)


def test_capture_validation_accepts_a_realistic_color_frame():
    frame = np.zeros((32, 48, 3), dtype=np.uint8)
    for y in range(32):
        for x in range(48):
            frame[y, x] = (x * 5, y * 7, (x + y) * 3)
    assert _is_usable_capture(frame, 48, 32)


def test_wgc_validation_accepts_black_scene_with_sparse_subtitle():
    frame = np.zeros((1600, 2560, 3), dtype=np.uint8)
    frame[795:805, 1160:1400] = 255

    assert not _is_usable_capture(frame, 2560, 1600)
    assert _is_valid_wgc_capture(frame, 2560, 1600)


def test_wgc_validation_rejects_wrong_shape_or_type():
    assert not _is_valid_wgc_capture(np.zeros((10, 10, 3), dtype=np.uint8), 20, 10)
    assert not _is_valid_wgc_capture(np.zeros((10, 20, 3), dtype=np.float32), 20, 10)


def test_qt_capture_normalization_removes_rounding_pixel():
    frame = np.full((1601, 2561, 3), 127, dtype=np.uint8)
    normalized = _normalize_qt_capture(frame, 2560, 1600)
    assert normalized.shape == (1600, 2560, 3)


def test_qt_capture_normalization_handles_150_percent_dpi():
    frame = np.full((2400, 3840, 3), 127, dtype=np.uint8)
    normalized = _normalize_qt_capture(frame, 2560, 1600)
    assert normalized.shape == (1600, 2560, 3)


def test_qt_capture_normalization_rejects_wrong_aspect_ratio():
    frame = np.full((1200, 3840, 3), 127, dtype=np.uint8)
    normalized = _normalize_qt_capture(frame, 2560, 1600)
    assert normalized.shape == frame.shape
