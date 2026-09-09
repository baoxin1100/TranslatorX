"""Manual integration check for Qt fallback capture across borderless resize."""
from __future__ import annotations

import time
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QApplication, QWidget

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import translatorx.overlay as overlay
from translatorx.ocr import OnnxOcrService
from translatorx.windows import get_window_info, make_borderless_fullscreen, restore_windowed_state
from translatorx.wgc_capture import close_wgc_capture


class CaptureTarget(QWidget):
    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#172554"))
        painter.fillRect(40, 40, self.width() - 80, self.height() - 80, QColor("#f8fafc"))
        painter.setPen(QColor("#0f172a"))
        painter.setFont(QFont("Arial", max(28, self.height() // 12), QFont.Weight.Bold))
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "HELLO TRANSLATORX\nBORDERLESS TEST")


def wait_for_paint(app: QApplication) -> None:
    deadline = time.monotonic() + 0.8
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.02)


def capture_and_ocr(service: OnnxOcrService, hwnd: int, label: str) -> None:
    target = get_window_info(hwnd)
    assert target is not None
    image = overlay.capture_window_bgr(target)
    text = " ".join(item.text for item in service.recognize(image)).upper().replace(" ", "")
    assert image.shape == (target.height, target.width, 3), (label, image.shape, target)
    assert "TRANSLATORX" in text, (label, text)
    print(f"{label}: capture + OCR passed shape={image.shape} text={text}")


def main() -> None:
    app = QApplication.instance() or QApplication([])
    target = CaptureTarget()
    target.setWindowTitle("TranslatorX Qt Borderless OCR Test")
    target.resize(960, 540)
    target.show()
    wait_for_paint(app)
    hwnd = int(target.winId())
    service = OnnxOcrService(enable_openvino=True)

    original_wgc = overlay.capture_window_wgc
    state = None
    try:
        capture_and_ocr(service, hwnd, "windowed-wgc")
        overlay.capture_window_wgc = lambda _window: None
        capture_and_ocr(service, hwnd, "windowed-qt")
        overlay.capture_window_wgc = original_wgc

        close_wgc_capture()
        state = make_borderless_fullscreen(hwnd)
        assert state is not None
        wait_for_paint(app)
        capture_and_ocr(service, hwnd, "borderless-wgc")
        overlay.capture_window_wgc = lambda _window: None
        capture_and_ocr(service, hwnd, "borderless-qt")
    finally:
        overlay.capture_window_wgc = original_wgc
        close_wgc_capture()
        if state is not None:
            restore_windowed_state(hwnd, state)
        target.close()
        app.processEvents()


if __name__ == "__main__":
    main()
