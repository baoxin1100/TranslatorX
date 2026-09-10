from __future__ import annotations

import ctypes
import logging
from dataclasses import dataclass
from ctypes import wintypes

from PySide6.QtCore import QPoint, QRect, QRectF, QTimer, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QFontMetricsF, QPainter
from PySide6.QtWidgets import QApplication, QWidget

from .models import LayoutMode, OcrItem, WindowInfo
from .wgc_capture import capture_window_wgc
from .windows import (
    constrain_overlay_show,
    exclude_window_from_capture,
    get_window_monitor_metrics,
    include_window_in_capture,
    place_overlay_above_target,
)


_capture_logger = logging.getLogger("translatorx.capture")


@dataclass(frozen=True, slots=True)
class OverlayRenderItem:
    rect: QRectF
    text: str
    font: QFont
    centered: bool = False


def overlay_font_family() -> str:
    """Prefer Source Han Sans when installed, with a safe Windows fallback."""
    installed = set(QFontDatabase.families())
    for family in ("Source Han Sans CN", "思源黑体 CN", "思源黑体", "Microsoft YaHei UI"):
        if family in installed:
            return family
    return "Microsoft YaHei UI"


def native_rect_to_qt(
    target: WindowInfo,
    monitor_left: int,
    monitor_top: int,
    dpi: int,
    qt_monitor_origin: QPoint,
) -> QRect:
    """Convert Win32 physical pixels to Qt device-independent screen coordinates."""
    scale = max(1.0, dpi / 96.0)
    return QRect(
        qt_monitor_origin.x() + round((target.left - monitor_left) / scale),
        qt_monitor_origin.y() + round((target.top - monitor_top) / scale),
        max(1, round(target.width / scale)),
        max(1, round(target.height / scale)),
    )


def _screen_and_logical_rect(target: WindowInfo):
    monitor_left, monitor_top, dpi, device_name = get_window_monitor_metrics(target.hwnd)
    screens = QApplication.screens()
    screen = next((item for item in screens if item.name().casefold() == device_name.casefold()), None)
    if screen is None:
        screen = QApplication.primaryScreen()
    origin = screen.geometry().topLeft() if screen is not None else QPoint(0, 0)
    return screen, native_rect_to_qt(target, monitor_left, monitor_top, dpi, origin)


def _source_bounds(item: OcrItem, scale_x: float, scale_y: float) -> QRectF:
    xs = [point[0] * scale_x for point in item.box]
    ys = [point[1] * scale_y for point in item.box]
    return QRectF(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))


def _clamp_rect(rect: QRectF, width: float, height: float, margin: float = 4.0) -> QRectF:
    available_width = max(1.0, width - margin * 2)
    available_height = max(1.0, height - margin * 2)
    clamped_width = min(rect.width(), available_width)
    clamped_height = min(rect.height(), available_height)
    x = min(max(rect.x(), margin), width - margin - clamped_width)
    y = min(max(rect.y(), margin), height - margin - clamped_height)
    return QRectF(x, y, clamped_width, clamped_height)


def _avoid_translation_collisions(
    rect: QRectF,
    occupied: list[QRectF],
    width: float,
    height: float,
) -> QRectF:
    """Move a lower translation away from already placed translation boxes."""
    candidate = QRectF(rect)
    for previous in occupied:
        if candidate.intersects(previous):
            candidate.moveTop(previous.bottom() + 1.0)
    candidate = _clamp_rect(candidate, width, height)
    if any(candidate.intersects(previous) for previous in occupied):
        overlapping = [previous for previous in occupied if candidate.intersects(previous)]
        if overlapping:
            candidate.moveTop(min(previous.top() for previous in overlapping) - candidate.height() - 1.0)
            candidate = _clamp_rect(candidate, width, height)
    return candidate


def build_render_items(
    items: list[OcrItem],
    layout: LayoutMode,
    image_width: int,
    image_height: int,
    window_width: int,
    window_height: int,
    font: QFont | None = None,
) -> list[OverlayRenderItem]:
    if image_width <= 0 or image_height <= 0 or window_width <= 0 or window_height <= 0:
        return []
    font = font or QFont(overlay_font_family(), 12)
    base_font_size = font.pointSize() if font.pointSize() > 0 else 12
    scale_x = window_width / image_width
    scale_y = window_height / image_height
    rendered: list[OverlayRenderItem] = []
    occupied: list[QRectF] = []

    for item in items:
        text = item.translation.strip()
        if not text:
            continue
        source = _source_bounds(item, scale_x, scale_y)
        item_font = QFont(font)
        item_font.setPixelSize(max(9, min(54, base_font_size)))
        item_font.setWeight(QFont.Weight.Normal)
        metrics = QFontMetricsF(item_font)
        natural_width = metrics.horizontalAdvance(text) + 8.0
        if layout == LayoutMode.BELOW:
            max_width = min(360.0, window_width - 8.0)
            preferred_width = min(max_width, max(48.0, source.width(), natural_width))
            x = source.center().x() - preferred_width / 2.0
            # OCR boxes often include a little extra descent below the glyphs.
            # Let the translation sit slightly inside that lower edge so the
            # two lines look visually attached instead of widely separated.
            y = source.bottom() - 5.0
            centered = True
        else:
            max_width = min(300.0, window_width - 8.0)
            preferred_width = min(max_width, max(60.0, natural_width))
            x = source.right() + 2.0
            y = source.y()
            centered = False

        text_rect = metrics.boundingRect(
            QRectF(0, 0, max(40.0, preferred_width - 4.0), 1000),
            Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignLeft,
            text,
        )
        height = max(float(item_font.pixelSize() + 2), text_rect.height() + 2.0)
        rect = _clamp_rect(QRectF(x, y, preferred_width, height), window_width, window_height)
        if layout == LayoutMode.BELOW:
            rect = _avoid_translation_collisions(rect, occupied, window_width, window_height)
        rendered.append(OverlayRenderItem(rect=rect, text=text, font=item_font, centered=centered))
        occupied.append(rect)
    return rendered


class TranslationOverlay(QWidget):
    def __init__(self) -> None:
        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowTransparentForInput
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        super().__init__(None, flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._font = QFont(overlay_font_family(), 12)
        self._font.setWeight(QFont.Weight.Normal)
        self._items: list[OverlayRenderItem] = []
        self._latency_text = ""
        self._target_hwnd = 0

    @property
    def capture_exclusion_applied(self) -> bool:
        return False

    def set_base_font_size(self, size: int) -> None:
        self._font.setPointSize(max(9, min(28, size)))

    def set_latency_text(self, text: str) -> None:
        self._latency_text = text
        self.update()

    def update_content(
        self,
        target: WindowInfo,
        items: list[OcrItem],
        layout: LayoutMode,
        image_width: int,
        image_height: int,
    ) -> None:
        self._target_hwnd = target.hwnd
        screen, logical_rect = _screen_and_logical_rect(target)
        self.setGeometry(logical_rect)
        self.winId()
        window_handle = self.windowHandle()
        if screen is not None and window_handle is not None:
            current_screen = window_handle.screen()
            if current_screen is None or current_screen.name() != screen.name():
                window_handle.setScreen(screen)
                self.setGeometry(logical_rect)
        self._items = build_render_items(
            items,
            layout,
            image_width,
            image_height,
            logical_rect.width(),
            logical_rect.height(),
            self._font,
        )
        self.update()
        if self._items:
            self.show()
            self.sync_target_z_order(target.hwnd)
            # QWidget.show() may finish native Tool-window ordering after this
            # method returns. Reapply once on the next Qt event-loop turn.
            QTimer.singleShot(0, lambda hwnd=target.hwnd: self.sync_target_z_order(hwnd))
        else:
            self.hide()

    def sync_target_z_order(self, target_hwnd: int) -> None:
        if self.isVisible():
            place_overlay_above_target(int(self.winId()), target_hwnd)

    def nativeEvent(self, event_type, message):  # noqa: N802
        constrain_overlay_show(message, getattr(self, "_target_hwnd", 0))
        return super().nativeEvent(event_type, message)

    def clear(self) -> None:
        self._target_hwnd = 0
        self._items.clear()
        self._latency_text = ""
        self.hide()

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setClipRect(self.rect())
        if self._latency_text:
            latency_font = QFont(overlay_font_family(), 10)
            latency_font.setWeight(QFont.Weight.Normal)
            painter.setFont(latency_font)
            latency_rect = QRectF(8, 6, max(1.0, self.width() - 16.0), 22.0)
            latency_flags = Qt.TextFlag.TextSingleLine | Qt.AlignmentFlag.AlignRight
            painter.setPen(QColor(0, 0, 0, 245))
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                painter.drawText(latency_rect.translated(dx, dy), latency_flags, self._latency_text)
            painter.setPen(QColor(230, 238, 248, 225))
            painter.drawText(latency_rect, latency_flags, self._latency_text)
        for item in self._items:
            painter.setFont(item.font)
            horizontal_alignment = (
                Qt.AlignmentFlag.AlignHCenter if item.centered else Qt.AlignmentFlag.AlignLeft
            )
            flags = Qt.TextFlag.TextWordWrap | horizontal_alignment | Qt.AlignmentFlag.AlignVCenter
            text_rect = item.rect.adjusted(1, 0, -1, 0)
            painter.setPen(QColor(0, 0, 0, 245))
            outline_offsets = (
                (-2, 0),
                (2, 0),
                (0, -2),
                (0, 2),
                (-1, -1),
                (1, -1),
                (-1, 1),
                (1, 1),
            )
            for dx, dy in outline_offsets:
                painter.drawText(text_rect.translated(dx, dy), flags, item.text)
            painter.setPen(QColor(248, 250, 252))
            painter.drawText(
                text_rect,
                flags,
                item.text,
            )

        painter.end()


def capture_window_bgr(window: WindowInfo, overlay_hwnd: int = 0):
    frame = capture_window_wgc(window)
    if _is_valid_wgc_capture(frame, window.width, window.height):
        _capture_logger.debug("截图后端=WGC hwnd=%s shape=%s", window.hwnd, frame.shape)
        return frame
    if frame is not None:
        _capture_logger.warning(
            "WGC 返回无效帧：hwnd=%s shape=%s，进入回退",
            window.hwnd,
            getattr(frame, "shape", None),
        )

    screen, logical_rect = _screen_and_logical_rect(window)
    if screen is None:
        raise RuntimeError("无法确定目标窗口所在显示器")

    # Qt is the only fallback. Prefer Qt's HWND capture so the target window
    # remains the source instead of silently accepting another desktop window.
    excluded = bool(overlay_hwnd) and exclude_window_from_capture(int(overlay_hwnd))
    try:
        window_rect = wintypes.RECT()
        user32 = ctypes.windll.user32
        got_rect = bool(
            user32.GetWindowRect(
                wintypes.HWND(int(window.hwnd)), ctypes.byref(window_rect)
            )
        )
        if got_rect:
            client_offset_x = int(window.left - window_rect.left)
            client_offset_y = int(window.top - window_rect.top)
            pixmap = screen.grabWindow(
                int(window.hwnd),
                client_offset_x,
                client_offset_y,
                int(window.width),
                int(window.height),
            )
            frame = _normalize_qt_capture(
                _qt_pixmap_to_bgr(pixmap), window.width, window.height
            )
            if _is_usable_capture(frame, window.width, window.height):
                _capture_logger.info("截图后端=qt-hwnd hwnd=%s shape=%s", window.hwnd, frame.shape)
                return frame
            _capture_logger.warning(
                "qt-hwnd 返回无效帧：hwnd=%s shape=%s",
                window.hwnd,
                getattr(frame, "shape", None),
            )
        else:
            _capture_logger.warning("无法获取目标窗口边框，跳过 qt-hwnd：hwnd=%s", window.hwnd)

        # If Qt cannot resolve the HWND frame, use Qt's screen grab for the
        # same client rectangle as a Qt-only fallback. No GDI path is allowed
        # here because it can return a valid-looking wrong surface.
        screen_geometry = screen.geometry()
        pixmap = screen.grabWindow(
            0,
            logical_rect.x() - screen_geometry.x(),
            logical_rect.y() - screen_geometry.y(),
            logical_rect.width(),
            logical_rect.height(),
        )
        frame = _normalize_qt_capture(
            _qt_pixmap_to_bgr(pixmap), window.width, window.height
        )
        if _is_usable_capture(frame, window.width, window.height):
            _capture_logger.info("截图后端=qt-screen hwnd=%s shape=%s", window.hwnd, frame.shape)
            return frame
        _capture_logger.warning(
            "qt-screen 返回无效帧：hwnd=%s shape=%s",
            window.hwnd,
            getattr(frame, "shape", None),
        )
        raise RuntimeError("WGC 和 Qt 均无法截取目标窗口客户区实时画面")
    finally:
        if excluded:
            include_window_in_capture(int(overlay_hwnd))


def _qt_pixmap_to_bgr(pixmap):
    import cv2
    import numpy as np

    if pixmap.isNull():
        return None
    image = pixmap.toImage().convertToFormat(image_format_rgba())
    height = image.height()
    width = image.width()
    bytes_per_line = image.bytesPerLine()
    buffer = np.frombuffer(image.bits(), dtype=np.uint8, count=image.sizeInBytes())
    rgba = buffer.reshape((height, bytes_per_line))[:, : width * 4].reshape((height, width, 4))
    return cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGR).copy()


def _normalize_qt_capture(frame, width: int, height: int):
    """Convert Qt's device-pixel result to the native client pixel size."""
    import cv2
    import numpy as np

    if not isinstance(frame, np.ndarray) or frame.ndim != 3 or not frame.size:
        return frame
    frame_height, frame_width = frame.shape[:2]
    if (frame_width, frame_height) == (width, height):
        return np.ascontiguousarray(frame)

    # Qt can round a logical screen rectangle outwards by one physical pixel.
    if 0 <= frame_width - width <= 2 and 0 <= frame_height - height <= 2:
        return np.ascontiguousarray(frame[:height, :width])

    # QScreen.grabWindow may return device pixels even though the requested
    # rectangle is expressed in native client pixels (for example 1.5x at
    # 150% display scaling). Only normalize a uniform DPI scale; mismatched
    # aspect ratios remain invalid and cannot be mistaken for the target.
    scale_x = frame_width / max(1, width)
    scale_y = frame_height / max(1, height)
    if 0.5 <= scale_x <= 3.0 and abs(scale_x - scale_y) <= 0.02:
        interpolation = cv2.INTER_AREA if scale_x > 1.0 else cv2.INTER_LINEAR
        return cv2.resize(frame, (width, height), interpolation=interpolation)
    return frame


def _is_usable_capture(frame, width: int, height: int) -> bool:
    """Reject blank, malformed, or effectively single-value fallback frames."""
    import numpy as np

    if not isinstance(frame, np.ndarray):
        return False
    if frame.dtype != np.uint8 or frame.ndim != 3 or frame.shape != (height, width, 3):
        return False
    if not frame.flags.c_contiguous or not frame.size:
        return False
    gray = (
        frame[:, :, 0].astype(np.uint16) * 29
        + frame[:, :, 1].astype(np.uint16) * 150
        + frame[:, :, 2].astype(np.uint16) * 77
    ) // 256
    sample = gray[:: max(1, height // 128), :: max(1, width // 128)]
    if sample.size == 0 or int(sample.max()) == 0:
        return False
    low, high = np.percentile(sample, (1, 99))
    if float(high - low) < 4.0 or float(sample.std()) < 1.0:
        return False
    # A failed GDI/Qt path can produce a binary mask with the expected size.
    # Real rendered frames contain anti-aliased shades even when mostly dark.
    if np.unique(sample).size < 8:
        return False
    return True


def _is_valid_wgc_capture(frame, width: int, height: int) -> bool:
    """Validate WGC transport and geometry without judging scene content."""
    import numpy as np

    return bool(
        isinstance(frame, np.ndarray)
        and frame.dtype == np.uint8
        and frame.ndim == 3
        and frame.shape == (height, width, 3)
        and frame.flags.c_contiguous
        and frame.size
    )


def image_format_rgba():
    from PySide6.QtGui import QImage

    return QImage.Format.Format_RGBA8888
