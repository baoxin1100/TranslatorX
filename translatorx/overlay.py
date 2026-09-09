from __future__ import annotations

import ctypes
from dataclasses import dataclass
from ctypes import wintypes

from PySide6.QtCore import QPoint, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QFontMetricsF, QPainter
from PySide6.QtWidgets import QApplication, QWidget

from .models import LayoutMode, OcrItem, WindowInfo
from .wgc_capture import capture_window_wgc
from .windows import (
    exclude_window_from_capture,
    get_window_monitor_metrics,
    include_window_in_capture,
    keep_overlay_above_fullscreen,
)


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
            | Qt.WindowType.WindowStaysOnTopHint
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
            self.raise_()
            keep_overlay_above_fullscreen(int(self.winId()))
        else:
            self.hide()

    def clear(self) -> None:
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
    import cv2
    import numpy as np

    frame = capture_window_wgc(window)
    if frame is not None:
        return frame

    screen, logical_rect = _screen_and_logical_rect(window)
    if screen is None:
        raise RuntimeError("无法确定目标窗口所在显示器")
    # Capture the target HWND, not the desktop.  The translation overlay is a
    # separate top-level window, so HWND capture excludes it while a desktop
    # recorder still sees the final composed overlay.
    window_rect = wintypes.RECT()
    user32 = ctypes.windll.user32
    got_rect = bool(user32.GetWindowRect(wintypes.HWND(int(window.hwnd)), ctypes.byref(window_rect)))
    if not got_rect:
        raise RuntimeError("无法获取目标窗口边框")
    client_offset_x = int(window.left - window_rect.left)
    client_offset_y = int(window.top - window_rect.top)
    # Capture through the window DC first, matching ok-script-kes.  On some
    # Windows/Qt combinations grabWindow(HWND) returns a non-null but stale
    # or empty image for hardware-rendered windows.
    frame = _capture_hwnd_bitblt(
        int(window.hwnd),
        client_offset_x,
        client_offset_y,
        int(window.width),
        int(window.height),
    )
    if frame is not None and frame.size and int(frame.max()) > 0 and float(frame.std()) >= 1.0:
        return frame

    pixmap = screen.grabWindow(
        int(window.hwnd),
        client_offset_x,
        client_offset_y,
        int(window.width),
        int(window.height),
    )
    if not pixmap.isNull():
        image = pixmap.toImage().convertToFormat(image_format_rgba())
        height = image.height()
        width = image.width()
        bytes_per_line = image.bytesPerLine()
        buffer = np.frombuffer(image.bits(), dtype=np.uint8, count=image.sizeInBytes())
        rgba = buffer.reshape((height, bytes_per_line))[:, : width * 4].reshape((height, width, 4))
        frame = cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGR).copy()
        if frame.size and int(frame.max()) > 0 and float(frame.std()) >= 1.0:
            return frame

    # Some GPU-rendered windows expose only a blank surface to HWND capture.
    # Exclude the overlay only during the desktop fallback capture.
    excluded = bool(overlay_hwnd) and exclude_window_from_capture(int(overlay_hwnd))
    try:
        frame = _capture_desktop_bitblt(
            int(window.left),
            int(window.top),
            int(window.width),
            int(window.height),
        )
        if frame is not None and frame.size:
            return frame

        screen_geometry = screen.geometry()
        pixmap = screen.grabWindow(
            0,
            logical_rect.x() - screen_geometry.x(),
            logical_rect.y() - screen_geometry.y(),
            logical_rect.width(),
            logical_rect.height(),
        )
        if pixmap.isNull():
            raise RuntimeError("无法截取目标窗口客户区实时画面")
        image = pixmap.toImage().convertToFormat(image_format_rgba())
        height = image.height()
        width = image.width()
        bytes_per_line = image.bytesPerLine()
        buffer = np.frombuffer(image.bits(), dtype=np.uint8, count=image.sizeInBytes())
        rgba = buffer.reshape((height, bytes_per_line))[:, : width * 4].reshape((height, width, 4))
        return cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGR).copy()
    finally:
        if excluded:
            include_window_in_capture(int(overlay_hwnd))


def _capture_desktop_bitblt(x: int, y: int, width: int, height: int):
    """Capture physical desktop pixels without Qt DPI scaling."""
    import cv2
    import numpy as np

    if width <= 0 or height <= 0:
        return None
    gdi32 = ctypes.windll.gdi32
    user32 = ctypes.windll.user32
    SRCCOPY = 0x00CC0020
    DIB_RGB_COLORS = 0

    class BitmapInfoHeader(ctypes.Structure):
        _fields_ = [
            ("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
            ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
            ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
            ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
            ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
            ("biClrImportant", wintypes.DWORD),
        ]

    class BitmapInfo(ctypes.Structure):
        _fields_ = [("bmiHeader", BitmapInfoHeader), ("bmiColors", wintypes.DWORD * 3)]

    desktop_dc = user32.GetDC(0)
    if not desktop_dc:
        return None
    memory_dc = gdi32.CreateCompatibleDC(desktop_dc)
    bitmap = gdi32.CreateCompatibleBitmap(desktop_dc, width, height)
    if not memory_dc or not bitmap:
        if memory_dc:
            gdi32.DeleteDC(memory_dc)
        user32.ReleaseDC(0, desktop_dc)
        return None
    previous = gdi32.SelectObject(memory_dc, bitmap)
    try:
        if not gdi32.BitBlt(memory_dc, 0, 0, width, height, desktop_dc, x, y, SRCCOPY):
            return None
        info = BitmapInfo()
        info.bmiHeader.biSize = ctypes.sizeof(BitmapInfoHeader)
        info.bmiHeader.biWidth = width
        info.bmiHeader.biHeight = -height
        info.bmiHeader.biPlanes = 1
        info.bmiHeader.biBitCount = 32
        pixels = (ctypes.c_ubyte * (width * height * 4))()
        copied = gdi32.GetDIBits(memory_dc, bitmap, 0, height, pixels, ctypes.byref(info), DIB_RGB_COLORS)
        if copied != height:
            return None
        bgra = np.frombuffer(pixels, dtype=np.uint8).reshape((height, width, 4))
        return cv2.cvtColor(bgra, cv2.COLOR_BGRA2BGR).copy()
    finally:
        if previous:
            gdi32.SelectObject(memory_dc, previous)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(memory_dc)
        user32.ReleaseDC(0, desktop_dc)


def _capture_hwnd_bitblt(hwnd: int, x: int, y: int, width: int, height: int):
    """Capture a client rectangle from one HWND, excluding other top-level windows."""
    import cv2
    import numpy as np

    if width <= 0 or height <= 0:
        return None
    gdi32 = ctypes.windll.gdi32
    user32 = ctypes.windll.user32
    SRCCOPY = 0x00CC0020
    DIB_RGB_COLORS = 0

    class BitmapInfoHeader(ctypes.Structure):
        _fields_ = [
            ("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
            ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
            ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
            ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
            ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
            ("biClrImportant", wintypes.DWORD),
        ]

    class BitmapInfo(ctypes.Structure):
        _fields_ = [("bmiHeader", BitmapInfoHeader), ("bmiColors", wintypes.DWORD * 3)]

    window_dc = user32.GetWindowDC(wintypes.HWND(hwnd))
    if not window_dc:
        return None
    memory_dc = gdi32.CreateCompatibleDC(window_dc)
    bitmap = gdi32.CreateCompatibleBitmap(window_dc, width, height)
    if not memory_dc or not bitmap:
        if memory_dc:
            gdi32.DeleteDC(memory_dc)
        user32.ReleaseDC(wintypes.HWND(hwnd), window_dc)
        return None
    previous = gdi32.SelectObject(memory_dc, bitmap)
    try:
        if not gdi32.BitBlt(memory_dc, 0, 0, width, height, window_dc, x, y, SRCCOPY):
            return None
        info = BitmapInfo()
        info.bmiHeader.biSize = ctypes.sizeof(BitmapInfoHeader)
        info.bmiHeader.biWidth = width
        info.bmiHeader.biHeight = -height
        info.bmiHeader.biPlanes = 1
        info.bmiHeader.biBitCount = 32
        info.bmiHeader.biCompression = 0
        pixels = (ctypes.c_ubyte * (width * height * 4))()
        copied = gdi32.GetDIBits(memory_dc, bitmap, 0, height, pixels, ctypes.byref(info), DIB_RGB_COLORS)
        if copied != height:
            return None
        bgra = np.frombuffer(pixels, dtype=np.uint8).reshape((height, width, 4))
        return cv2.cvtColor(bgra, cv2.COLOR_BGRA2BGR).copy()
    finally:
        if previous:
            gdi32.SelectObject(memory_dc, previous)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(memory_dc)
        user32.ReleaseDC(wintypes.HWND(hwnd), window_dc)


def image_format_rgba():
    from PySide6.QtGui import QImage

    return QImage.Format.Format_RGBA8888
