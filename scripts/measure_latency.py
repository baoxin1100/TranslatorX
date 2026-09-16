"""Measure every stage of the real pipeline: capture -> OCR -> render.

Only the network translation is stubbed, so the numbers come from the real
capture backend, the real OpenVINO OCR and the real overlay render.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys

sys.path.insert(0, os.getcwd())

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QLabel, QMainWindow, QVBoxLayout, QWidget

CONFIG = pathlib.Path("config/translatorx.json")
BACKUP = CONFIG.read_text(encoding="utf-8") if CONFIG.exists() else None

import translatorx.worker as worker_module


class FakeTranslator:
    def translate_batch(self, texts):
        return [f"[{text[:24]}]" for text in texts]


worker_module.create_translator = lambda config: FakeTranslator()

from translatorx.ui import MainWindow  # noqa: E402

app = QApplication(sys.argv)

target = QMainWindow()
target.setWindowTitle("OCR 目标窗口")
central = QWidget()
layout = QVBoxLayout(central)
for line in (
    "HELLO TRANSLATORX",
    "THIS IS A TEST SUBTITLE LINE",
    "PLAY THE GAME WITH YOUR FRIENDS TONIGHT",
):
    label = QLabel(line)
    label.setFont(QFont("Segoe UI", 22))
    layout.addWidget(label)
target.setCentralWidget(central)
target.resize(720, 320)
target.move(120, 120)
target.show()

window = MainWindow()
window.show()

frames: list[dict] = []
original_finish = window._finish_frame_timing


def spy(render_entered_at: float) -> None:
    original_finish(render_entered_at)
    frames.append(dict(window._last_timing))


window._finish_frame_timing = spy
state = {"started": False, "deadline": None}


def start_when_ready() -> None:
    if not window._ocr_ready:
        return
    window.refresh_windows()
    index = window.window_combo.findData(int(target.winId()))
    if index < 0:
        print("目标窗口不在窗口列表里，测试中止")
        app.quit()
        return
    window.window_combo.setCurrentIndex(index)
    window.latency_switch.setChecked(True)
    window.toggle_running()
    state["started"] = True
    print(f"已开始翻译：hwnd={int(target.winId()):#x}")
    QTimer.singleShot(9000, stop)


def stop() -> None:
    window.toggle_running()
    app.quit()


ready_timer = QTimer()
ready_timer.setInterval(500)
ready_timer.timeout.connect(lambda: start_when_ready() if not state["started"] else None)
ready_timer.start()
QTimer.singleShot(120000, app.quit)

app.exec()

print(f"\n共收集 {len(frames)} 帧计时\n")
header = (f"{'#':>2} {'等待':>6} {'截图':>6} {'WGC':>6} {'兜底':>5} {'派发':>5} {'OCR':>6} "
          f"{'预处理':>6} {'检测':>6} {'识别':>6} {'清洗':>5} {'装配':>5} {'翻译':>5} "
          f"{'回调':>5} {'渲染':>6} {'往返':>7} {'跳过':>4}")
print(header)
print("-" * len(header))
keys = ("wait_ms", "capture_ms", "capture_wgc_ms", "capture_fallback_ms", "dispatch_ms", "ocr_ms",
        "det_ms", "rec_ms", "clean_ms", "cache_ms", "translation_ms", "callback_ms", "render_ms",
        "roundtrip_ms", "skipped_ticks")
for number, frame in enumerate(frames, 1):
    prepare = max(0.0, frame.get("ocr_ms", 0.0) - frame.get("det_ms", 0.0) - frame.get("rec_ms", 0.0))
    row = (f"{number:>2} {frame.get('wait_ms', 0):>6.0f} {frame.get('capture_ms', 0):>6.0f} "
           f"{frame.get('capture_wgc_ms', 0):>6.0f} {frame.get('capture_fallback_ms', 0):>5.0f} "
           f"{frame.get('dispatch_ms', 0):>5.0f} {frame.get('ocr_ms', 0):>6.0f} {prepare:>6.0f} "
           f"{frame.get('det_ms', 0):>6.0f} {frame.get('rec_ms', 0):>6.0f} {frame.get('clean_ms', 0):>5.0f} "
           f"{frame.get('cache_ms', 0):>5.0f} {frame.get('translation_ms', 0):>5.0f} "
           f"{frame.get('callback_ms', 0):>5.0f} {frame.get('render_ms', 0):>6.0f} "
           f"{frame.get('roundtrip_ms', 0):>7.0f} {int(frame.get('skipped_ticks', 0)):>4}")
    print(row)

if frames:
    print("\n各阶段平均 / 最大（ms）：")
    for key in keys:
        values = [float(frame.get(key, 0.0)) for frame in frames]
        print(f"  {key:<22} 平均 {sum(values) / len(values):>8.1f}   最大 {max(values):>8.1f}")
    print("\noverlay 显示的三行文本：")
    from translatorx.worker import format_latency

    print(format_latency(frames[-1]))

if BACKUP is not None:
    CONFIG.write_text(BACKUP, encoding="utf-8")
    print("\n配置已还原")
elif CONFIG.exists():
    CONFIG.unlink()
    print("\n已删除测试期间生成的配置")
