from __future__ import annotations

import time
import logging
from pathlib import Path

from PySide6.QtCore import QPoint, QSettings, QSize, QThread, QTimer, Qt, Signal
from PySide6.QtGui import QAction, QColor, QCloseEvent, QIcon, QMouseEvent, QPainter
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QPushButton,
    QRadioButton,
    QSlider,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QStyle,
    QSystemTrayIcon,
)

from .models import LayoutMode, TranslatorConfig, WindowInfo
from .overlay import TranslationOverlay, capture_window_bgr
from .wgc_capture import close_wgc_capture
from .settings import CredentialDialog, app_settings
from .windows import (
    WindowedState,
    get_window_info,
    install_f8_hook,
    is_target_foreground,
    list_windows,
    make_borderless_fullscreen,
    restore_windowed_state,
    uninstall_f8_hook,
)
from .worker import ProcessingWorker


APP_STYLE = """
QWidget { color: #f3f6f8; font-family: "Segoe UI", "Microsoft YaHei UI"; font-size: 13px; }
QMainWindow { background: transparent; }
QWidget#root { background: #090b0f; border-radius: 16px; }
QFrame#titlebar { background: #090b0f; border-bottom: 1px solid #20252c; border-top-left-radius: 16px; border-top-right-radius: 16px; }
QFrame#footer { background: #090b0f; border: none; border-bottom-left-radius: 16px; border-bottom-right-radius: 16px; }
QLabel#windowTitle { font-weight: 700; font-size: 18px; }
QLabel#settingsDialogTitle { font-weight: 700; font-size: 14px; color: #f3f6f8; }
QLabel#statusLabel, QLabel#hintLabel { color: #748090; font-size: 12px; }
QLabel#fieldLabel { color: #a6b0bd; font-weight: 600; }
QComboBox {
  min-height: 44px; padding: 0 38px 0 13px; background: #101318;
  border: 1px solid #20252c; border-radius: 9px; selection-background-color: #24528f;
}
QComboBox:hover { border-color: #323a45; background: #15191f; }
QComboBox:focus { border: 2px solid #4f83c2; padding-left: 12px; }
QComboBox::drop-down { width: 34px; border: none; }
QComboBox::down-arrow { image: url(assets/chevron-down.svg); width: 14px; height: 14px; }
QComboBox QAbstractItemView {
  background: #101318; border: 1px solid #323a45;
  selection-background-color: #24528f; selection-color: #ffffff; outline: 0;
}
QComboBox QAbstractItemView::item:selected { background: #24528f; color: #ffffff; }
QPushButton#refreshButton, QToolButton#titleButton, QToolButton#closeButton {
  background: transparent; border: 1px solid transparent; border-radius: 8px;
}
QPushButton#refreshButton { min-width: 44px; max-width: 44px; min-height: 44px; background: #101318; border-color: #20252c; font-size: 18px; }
QPushButton#refreshButton:hover, QToolButton#titleButton:hover { color: #7ea7d2; background: #15191f; border-color: #323a45; }
QToolButton#closeButton:hover { color: #ffffff; background: rgba(255,112,112,0.16); border-color: rgba(255,112,112,0.42); }
QToolButton#titleButton, QToolButton#closeButton { min-width: 30px; max-width: 30px; min-height: 30px; max-height: 30px; }
QToolButton#titleButton { font-size: 17px; }
QPushButton#runButton {
  min-height: 52px; color: white; background: #24528f; border: 1px solid #24528f;
  border-radius: 10px; font-weight: 700; font-size: 14px;
}
QPushButton#runButton:hover { background: #2f66aa; border-color: #2f66aa; }
QPushButton#runButton:pressed { background: #1d4478; border-color: #1d4478; }
QPushButton#runButton:disabled {
  color: #778292; background: #15191f; border-color: #262c35;
}
QPushButton#runButton[running="true"] { background: #101318; border-color: rgba(36,82,143,0.7); }
QDialog { background: #090b0f; }
QGroupBox { border: 1px solid #20252c; border-radius: 9px; margin-top: 10px; padding-top: 8px; font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; color: #a6b0bd; }
QLineEdit { min-height: 36px; padding: 0 10px; background: #101318; border: 1px solid #20252c; border-radius: 7px; }
QLineEdit:focus { border: 2px solid #4f83c2; }
QPlainTextEdit#testResults { padding: 8px; background: #07090c; border: 1px solid #20252c; border-radius: 7px; color: #a6b0bd; }
QPushButton#settingsActionButton { min-height: 34px; padding: 0 14px; color: #dceaff; background: #122038; border: 1px solid #274b78; border-radius: 7px; }
QPushButton#settingsActionButton:hover { background: #182b49; border-color: #3b6599; }
QPushButton#settingsActionButton:pressed { background: #0e1a2d; border-color: #4f83c2; }
QPushButton#settingsActionButton:disabled { color: #748090; background: #101318; border-color: #20252c; }
QRadioButton { min-height: 34px; spacing: 8px; color: #d7dde5; }
QRadioButton::indicator { width: 16px; height: 16px; border-radius: 9px; border: 1px solid #4a5665; background: #101318; }
QRadioButton::indicator:hover { border-color: #4f83c2; }
QRadioButton::indicator:checked {
  border-color: #4f83c2;
  background: qradialgradient(cx:0.5, cy:0.5, radius:0.45, fx:0.5, fy:0.5,
    stop:0 #4f83c2, stop:0.38 #4f83c2, stop:0.42 #101318, stop:1 #101318);
}
QSlider::groove:horizontal { height: 4px; background: #20252c; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #24528f; border-radius: 2px; }
QSlider::handle:horizontal { width: 12px; height: 12px; margin: -4px 0; background: #dceaff; border: 2px solid #24528f; border-radius: 6px; }
QSlider::handle:horizontal:hover { background: #ffffff; border-color: #4f83c2; }
QLabel#fontValue { min-width: 34px; color: #dceaff; font-weight: 600; }
QLabel#settingsNote { color: #748090; }
QToolButton#infoButton { min-width: 12px; max-width: 12px; min-height: 12px; max-height: 12px;
  padding: 0; color: #8fa6c0; background: transparent; border: 1px solid #60758d; border-radius: 6px;
  font-size: 7px; font-weight: 700; }
QToolButton#infoButton:hover { color: #dceaff; border-color: #4f83c2; background: #122038; }
QMenu { padding: 6px; background: #101318; border: 1px solid #323a45; border-radius: 7px; }
QMenu::item { min-width: 126px; padding: 7px 14px; border-radius: 5px; }
QMenu::item:selected { color: #ffffff; background: #24528f; }
QDialog#closeChoiceDialog { background: #0d1015; border: 1px solid #323a45; border-radius: 12px; }
QLabel#closeChoiceTitle { color: #f3f6f8; font-size: 16px; font-weight: 700; }
QLabel#closeChoiceMessage { color: #8fa0b3; font-size: 12px; }
QPushButton#trayChoiceButton, QPushButton#exitChoiceButton {
  min-height: 38px; padding: 0 16px; border-radius: 8px; font-weight: 600;
}
QPushButton#trayChoiceButton { color: #ffffff; background: #24528f; border: 1px solid #24528f; }
QPushButton#trayChoiceButton:hover { background: #2f66aa; border-color: #2f66aa; }
QPushButton#trayChoiceButton:pressed { background: #1d4478; }
QPushButton#exitChoiceButton { color: #e3e9f0; background: #15191f; border: 1px solid #323a45; }
QPushButton#exitChoiceButton:hover { color: #ffffff; background: rgba(255,112,112,0.14); border-color: rgba(255,112,112,0.50); }
"""


class Switch(QWidget):
    toggled = Signal(bool)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._checked = False
        self.setFixedSize(48, 28)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName("开关")

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, checked: bool) -> None:
        checked = bool(checked)
        if checked == self._checked:
            return
        self._checked = checked
        self.update()
        self.toggled.emit(self._checked)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.setChecked(not self._checked)
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.setChecked(not self._checked)
            event.accept()
            return
        super().keyPressEvent(event)

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        track = self.rect().adjusted(1, 4, -1, -4)
        track_color = QColor("#24528f" if self._checked else "#252b33")
        border_color = QColor("#4f83c2" if self._checked else "#596572")
        painter.setPen(border_color)
        painter.setBrush(track_color)
        painter.drawRoundedRect(track, track.height() / 2, track.height() / 2)
        knob_diameter = track.height() - 6
        knob_x = track.right() - knob_diameter - 3 if self._checked else track.left() + 3
        knob = track.adjusted(knob_x - track.left(), 3, knob_x - track.right() + knob_diameter, -3)
        painter.setPen(QColor("#f7fbff"))
        painter.setBrush(QColor("#f7fbff"))
        painter.drawEllipse(knob)
        painter.end()


class TitleBar(QFrame):
    def __init__(self, window: "MainWindow") -> None:
        super().__init__(window)
        self._window = window
        self._drag_offset: QPoint | None = None
        self.setObjectName("titlebar")
        self.setFixedHeight(52)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(24, 0, 24, 0)
        layout.setSpacing(4)
        logo = QLabel()
        logo.setPixmap(window.windowIcon().pixmap(24, 24))
        logo.setFixedSize(24, 24)
        logo.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(logo)
        title = QLabel("TranslatorX")
        title.setObjectName("windowTitle")
        title.setTextFormat(Qt.TextFormat.RichText)
        title.setText(
            '<span style="font-family: Baskerville, \'Book Antiqua\', Georgia, serif; '
            'font-style: italic; font-weight: 700;">Translator</span>'
            '<span style="font-family: Baskerville, \'Book Antiqua\', Georgia, serif; '
            'font-style: italic; font-weight: 700; color: #24528f;">X</span>'
        )
        title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setParent(self)
        title.setGeometry(0, 0, window.width(), self.height())
        title.raise_()
        layout.addStretch(1)

        self.status_label = QLabel("正在加载 OCR")
        self.status_label.setObjectName("statusLabel")
        self.status_label.hide()

        settings = QToolButton()
        settings.setObjectName("titleButton")
        settings_icon = Path(__file__).resolve().parent.parent / "assets" / "settings-outline.svg"
        settings.setIcon(QIcon(str(settings_icon)))
        settings.setIconSize(QSize(17, 17))
        settings.setToolTip("翻译服务设置")
        settings.setAccessibleName("打开翻译服务设置")
        settings.clicked.connect(window.open_settings)
        layout.addWidget(settings)
        close = QToolButton()
        close.setObjectName("closeButton")
        close_icon = Path(__file__).resolve().parent.parent / "assets" / "close.svg"
        close.setIcon(QIcon(str(close_icon)))
        close.setIconSize(QSize(17, 17))
        close.setToolTip("最小化到系统托盘")
        close.setAccessibleName("最小化到系统托盘")
        close.clicked.connect(window.close)
        layout.addWidget(close)

    def set_status(self, text: str) -> None:
        self.status_label.setText(text)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self._window.frameGeometry().topLeft()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self._window.move(event.globalPosition().toPoint() - self._drag_offset)

    def mouseReleaseEvent(self, _event: QMouseEvent) -> None:  # noqa: N802
        self._drag_offset = None


class Field(QWidget):
    def __init__(self, label: str, control: QWidget, hint: QLabel | None = None) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(7)
        header = QHBoxLayout()
        title = QLabel(label)
        title.setObjectName("fieldLabel")
        header.addWidget(title)
        header.addStretch(1)
        if hint is not None:
            hint.setObjectName("hintLabel")
            header.addWidget(hint)
        layout.addLayout(header)
        layout.addWidget(control)


class CloseChoiceDialog(QDialog):
    HIDE_TO_TRAY = 1
    EXIT_APPLICATION = 2

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("closeChoiceDialog")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setModal(True)
        self.setFixedSize(340, 156)

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(9)
        title = QLabel("关闭 TranslatorX")
        title.setObjectName("closeChoiceTitle")
        root.addWidget(title)
        message = QLabel("请选择退出程序，或让程序继续在系统托盘中运行。")
        message.setObjectName("closeChoiceMessage")
        message.setWordWrap(True)
        root.addWidget(message)
        root.addStretch(1)

        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        exit_button = QPushButton("退出程序")
        exit_button.setObjectName("exitChoiceButton")
        exit_button.setAccessibleName("退出 TranslatorX")
        exit_button.clicked.connect(lambda: self.done(self.EXIT_APPLICATION))
        tray_button = QPushButton("隐藏到系统托盘")
        tray_button.setObjectName("trayChoiceButton")
        tray_button.setAccessibleName("隐藏 TranslatorX 到系统托盘")
        tray_button.clicked.connect(lambda: self.done(self.HIDE_TO_TRAY))
        tray_button.setDefault(True)
        buttons.addWidget(exit_button)
        buttons.addWidget(tray_button)
        root.addLayout(buttons)


class MainWindow(QMainWindow):
    process_requested = Signal(object, object)

    ENGINE_ITEMS = [
        ("百度翻译", "baidu"),
        ("百度大模型翻译", "baidu_llm"),
        ("腾讯翻译", "tencent"),
        ("OpenAI 兼容接口", "openai"),
    ]
    LANGUAGE_ITEMS = [
        ("自动检测", "auto"),
        ("简体中文", "zh-CN"),
        ("繁体中文", "zh-TW"),
        ("英语", "en"),
        ("日语", "ja"),
        ("韩语", "ko"),
    ]

    def __init__(self) -> None:
        super().__init__()
        icon_path = Path(__file__).resolve().parent.parent / "icons" / "icon.ico"
        self.setWindowIcon(QIcon(str(icon_path)))
        self._logger = logging.getLogger("translatorx.ui")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(400)
        self.resize(400, 500)
        self.setWindowTitle("TranslatorX")
        self._ui_settings = app_settings()

        self._running = False
        self._worker_busy = False
        self._ocr_ready = False
        self._empty_frame_count = 0
        self._last_items = []
        self._last_image_size = (0, 0)
        self._last_timing: dict[str, float] = {}
        self._capture_started_at = 0.0
        self._debug_capture_saved = False
        self._discard_worker_result = False
        self._refreshing_windows = False
        self._selected_window: WindowInfo | None = None
        self._borderless_state: WindowedState | None = None
        self._borderless_hwnd = 0
        self._f8_registered = False
        self._force_quit = False
        self.overlay = TranslationOverlay()
        self.credential_dialog = CredentialDialog(self)

        self._build_ui()
        self._setup_tray()
        self._restore_main_settings()
        self._start_worker()

        self.track_timer = QTimer(self)
        self.track_timer.setInterval(160)
        self.track_timer.timeout.connect(self._track_target)
        self.capture_timer = QTimer(self)
        self.capture_timer.setInterval(900)
        self.capture_timer.timeout.connect(self._capture)
        self.hotkey_timer = QTimer(self)
        self.hotkey_timer.setInterval(120)
        self.hotkey_timer.timeout.connect(self._sync_f8_hotkey)
        self.hotkey_timer.start()
        QTimer.singleShot(0, self.refresh_windows)

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.titlebar = TitleBar(self)
        outer.addWidget(self.titlebar)

        content = QVBoxLayout()
        content.setContentsMargins(24, 16, 24, 14)
        content.setSpacing(12)
        outer.addLayout(content)

        self.engine_combo = QComboBox()
        for label, value in self.ENGINE_ITEMS:
            self.engine_combo.addItem(label, value)
        content.addWidget(Field("翻译引擎", self.engine_combo, QLabel("选择在线翻译服务")))
        self.engine_combo.currentIndexChanged.connect(self._save_main_settings)

        self.window_combo = QComboBox()
        self.window_hint = QLabel("等待刷新")
        refresh = QPushButton()
        refresh.setObjectName("refreshButton")
        refresh.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload))
        refresh.setToolTip("刷新窗口列表")
        refresh.setAccessibleName("刷新窗口列表")
        refresh.clicked.connect(self.refresh_windows)
        window_row = QWidget()
        window_layout = QHBoxLayout(window_row)
        window_layout.setContentsMargins(0, 0, 0, 0)
        window_layout.setSpacing(8)
        window_layout.addWidget(self.window_combo, 1)
        window_layout.addWidget(refresh)
        content.addWidget(Field("目标窗口", window_row, self.window_hint))
        self.window_combo.currentIndexChanged.connect(self._save_main_settings)

        self.source_combo = QComboBox()
        self.target_combo = QComboBox()
        for label, value in self.LANGUAGE_ITEMS:
            self.source_combo.addItem(label, value)
            if value != "auto":
                self.target_combo.addItem(label, value)
        self.target_combo.setCurrentIndex(self.target_combo.findData("zh-CN"))
        languages = QHBoxLayout()
        languages.setSpacing(10)
        languages.addWidget(Field("源语言", self.source_combo), 1)
        language_direction = QLabel()
        language_direction.setAlignment(Qt.AlignmentFlag.AlignCenter)
        arrow_icon = Path(__file__).resolve().parent.parent / "assets" / "arrow-right.svg"
        language_direction.setPixmap(QIcon(str(arrow_icon)).pixmap(22, 22))
        language_direction.setFixedWidth(24)
        language_direction.setContentsMargins(0, 24, 0, 0)
        language_direction.setAccessibleName("源语言到目标语言")
        languages.addWidget(language_direction)
        languages.addWidget(Field("目标语言", self.target_combo), 1)
        content.addLayout(languages)
        self.source_combo.currentIndexChanged.connect(self._save_main_settings)
        self.target_combo.currentIndexChanged.connect(self._save_main_settings)

        layout_options = QWidget()
        layout_row = QHBoxLayout(layout_options)
        layout_row.setContentsMargins(0, 0, 0, 0)
        layout_row.setSpacing(24)
        self.below_layout_radio = QRadioButton("下方布局")
        self.below_layout_radio.setChecked(True)
        self.below_layout_radio.setAccessibleName("译文使用下方布局")
        self.right_layout_radio = QRadioButton("右侧布局")
        self.right_layout_radio.setAccessibleName("译文使用右侧布局")
        layout_row.addWidget(self.below_layout_radio)
        layout_row.addWidget(self.right_layout_radio)
        layout_row.addStretch(1)
        self.below_layout_radio.toggled.connect(self._refresh_overlay_layout)
        self.below_layout_radio.toggled.connect(self._save_main_settings)
        self.right_layout_radio.toggled.connect(self._save_main_settings)

        font_control = QWidget()
        font_row = QHBoxLayout(font_control)
        font_row.setContentsMargins(0, 0, 0, 0)
        font_row.setSpacing(8)
        self.font_slider = QSlider(Qt.Orientation.Horizontal)
        self.font_slider.setRange(9, 28)
        try:
            saved_font_size = int(self._ui_settings.value("overlay_font_size", 12))
        except (TypeError, ValueError):
            saved_font_size = 12
        self.font_slider.setValue(max(9, min(28, saved_font_size)))
        self.font_slider.setToolTip("调整译文基准字号")
        self.font_slider.setAccessibleName("译文基准字号")
        self.font_value = QLabel(f"{self.font_slider.value()} 号")
        self.font_value.setObjectName("fontValue")
        font_row.addWidget(self.font_slider, 1)
        font_row.addWidget(self.font_value)
        self.overlay.set_base_font_size(self.font_slider.value())
        self.font_slider.valueChanged.connect(self._font_size_changed)

        display_options = QHBoxLayout()
        display_options.setSpacing(14)
        display_options.addWidget(Field("译文布局", layout_options), 3)
        display_options.addWidget(Field("字体大小", font_control), 2)
        content.addLayout(display_options)

        self.latency_switch = Switch()
        self.latency_switch.setObjectName("latencySwitch")
        self.latency_switch.setAccessibleName("显示延迟信息")
        self.latency_switch.setChecked(bool(self._ui_settings.value("show_latency", False, type=bool)))
        self.latency_switch.toggled.connect(self._latency_toggled)
        self.borderless_switch = Switch()
        self.borderless_switch.setAccessibleName("目标窗口转非独占全屏")
        self.borderless_switch.setChecked(bool(
            self._ui_settings.value("auto_borderless_fullscreen", False, type=bool)
        ))
        self.borderless_switch.toggled.connect(self._borderless_toggled)
        borderless_field = QWidget()
        borderless_layout = QHBoxLayout(borderless_field)
        borderless_layout.setContentsMargins(0, 0, 0, 0)
        borderless_layout.setSpacing(7)
        borderless_title = QLabel("目标窗口转非独占全屏")
        borderless_title.setObjectName("fieldLabel")
        borderless_layout.addWidget(borderless_title)
        info = QToolButton()
        info.setObjectName("infoButton")
        info.setText("i")
        info.setToolTip("独占全屏无法显示译文时，将目标窗口化后开启此按钮")
        info.setAccessibleName("无边框全屏使用说明")
        borderless_layout.addWidget(info)
        borderless_layout.addWidget(self.borderless_switch)

        latency_field = QWidget()
        latency_layout = QHBoxLayout(latency_field)
        latency_layout.setContentsMargins(0, 0, 0, 0)
        latency_layout.setSpacing(8)
        latency_title = QLabel("显示延迟")
        latency_title.setObjectName("fieldLabel")
        latency_layout.addWidget(latency_title)
        latency_layout.addWidget(self.latency_switch)

        secondary_options = QHBoxLayout()
        secondary_options.setContentsMargins(0, 0, 0, 0)
        secondary_options.addWidget(latency_field, 0, Qt.AlignmentFlag.AlignLeft)
        secondary_options.addStretch(1)
        secondary_options.addWidget(borderless_field, 0, Qt.AlignmentFlag.AlignRight)
        content.addLayout(secondary_options)

        outer.addStretch(1)
        footer = QFrame()
        footer.setObjectName("footer")
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(24, 10, 24, 18)
        footer_layout.setSpacing(0)
        self.run_button = QPushButton("正在初始化 OCR…")
        self.run_button.setObjectName("runButton")
        self.run_button.setEnabled(False)
        self.run_button.clicked.connect(self.toggle_running)
        footer_layout.addWidget(self.run_button)
        outer.addWidget(footer)

    def _start_worker(self) -> None:
        self.worker_thread = QThread(self)
        self.worker = ProcessingWorker(enable_openvino=True)
        self.worker.moveToThread(self.worker_thread)
        self.worker_thread.started.connect(self.worker.initialize)
        self.process_requested.connect(self.worker.process)
        self.worker.ready.connect(self._on_worker_ready)
        self.worker.completed.connect(self._on_processed)
        self.worker.timing.connect(self._on_timing)
        self.worker.failed.connect(self._on_process_failed)
        self.worker_thread.start()

    def _setup_tray(self) -> None:
        self.tray_icon = QSystemTrayIcon(self.windowIcon(), self)
        self.tray_icon.setToolTip("TranslatorX")
        tray_menu = QMenu(self)
        show_action = QAction("显示 TranslatorX", self)
        show_action.triggered.connect(self._restore_from_tray)
        quit_action = QAction("退出", self)
        quit_action.triggered.connect(self._quit_from_tray)
        tray_menu.addAction(show_action)
        tray_menu.addSeparator()
        tray_menu.addAction(quit_action)
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self._tray_activated)
        self.tray_icon.show()

    def _tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self._restore_from_tray()

    def _restore_from_tray(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _quit_from_tray(self) -> None:
        self._quit_application()

    def _quit_application(self) -> None:
        self._force_quit = True
        self.tray_icon.hide()
        self.close()
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def _restore_main_settings(self) -> None:
        def restore_combo(combo: QComboBox, key: str, default: str) -> None:
            value = str(self._ui_settings.value(key, default))
            index = combo.findData(value)
            if index >= 0:
                combo.setCurrentIndex(index)

        restore_combo(self.engine_combo, "engine", self.ENGINE_ITEMS[0][1])
        restore_combo(self.source_combo, "source_language", "auto")
        restore_combo(self.target_combo, "target_language", "zh-CN")
        layout = str(self._ui_settings.value("layout_mode", LayoutMode.BELOW.value))
        self.right_layout_radio.setChecked(layout == LayoutMode.RIGHT.value)
        self.below_layout_radio.setChecked(layout != LayoutMode.RIGHT.value)

    def _save_main_settings(self, *_args) -> None:
        if not hasattr(self, "engine_combo") or self._refreshing_windows:
            return
        self._ui_settings.setValue("engine", self.engine_combo.currentData() or "")
        self._ui_settings.setValue("source_language", self.source_combo.currentData() or "auto")
        self._ui_settings.setValue("target_language", self.target_combo.currentData() or "zh-CN")
        self._ui_settings.setValue("layout_mode", self._layout_mode().value)
        if self.window_combo.currentData():
            self._ui_settings.setValue("window_hwnd", int(self.window_combo.currentData()))
            self._ui_settings.setValue("window_title", self.window_combo.currentText())
        self._ui_settings.sync()

    def _on_worker_ready(self) -> None:
        self._ocr_ready = True
        self._logger.info("主界面收到 OCR ready 信号")
        self.run_button.setText("开始实时翻译  (F8)")
        self.run_button.setEnabled(self.window_combo.count() > 0)
        self.titlebar.set_status("已就绪")

    def open_settings(self) -> None:
        self.credential_dialog.exec()

    def refresh_windows(self) -> None:
        previous = self.window_combo.currentData()
        saved_hwnd = self._ui_settings.value("window_hwnd", 0, type=int)
        saved_title = str(self._ui_settings.value("window_title", ""))
        own_hwnd = int(self.winId())
        windows = list_windows({own_hwnd})
        self._refreshing_windows = True
        self.window_combo.clear()
        for item in windows:
            self.window_combo.addItem(item.title, item.hwnd)
        selected = False
        if previous:
            index = self.window_combo.findData(previous)
            if index >= 0:
                self.window_combo.setCurrentIndex(index)
                selected = True
        if not selected and saved_hwnd:
            index = self.window_combo.findData(saved_hwnd)
            if index >= 0:
                self.window_combo.setCurrentIndex(index)
                selected = True
        if not selected and saved_title:
            index = self.window_combo.findText(saved_title)
            if index >= 0:
                self.window_combo.setCurrentIndex(index)
                selected = True
        self._refreshing_windows = False
        self._save_main_settings()
        self.window_hint.setText(f"检测到 {len(windows)} 个窗口")
        self.run_button.setEnabled(self._ocr_ready and bool(windows))

    def _config(self) -> TranslatorConfig:
        return TranslatorConfig(
            engine=str(self.engine_combo.currentData()),
            source_language=str(self.source_combo.currentData()),
            target_language=str(self.target_combo.currentData()),
            credentials=self.credential_dialog.credentials(),
        )

    def _layout_mode(self) -> LayoutMode:
        return LayoutMode.BELOW if self.below_layout_radio.isChecked() else LayoutMode.RIGHT

    def _refresh_overlay_layout(self, checked: bool) -> None:
        if not checked or not self._running or self._selected_window is None or not self._last_items:
            return
        if is_target_foreground(self._selected_window.hwnd):
            self.overlay.update_content(
                self._selected_window,
                self._last_items,
                self._layout_mode(),
                *self._last_image_size,
            )

    def _font_size_changed(self, value: int) -> None:
        self.font_value.setText(f"{value} 号")
        self.overlay.set_base_font_size(value)
        self._ui_settings.setValue("overlay_font_size", value)
        self._ui_settings.sync()
        self._refresh_overlay_layout(True)

    def _latency_toggled(self, enabled: bool) -> None:
        self._ui_settings.setValue("show_latency", enabled)
        self._ui_settings.sync()
        if not enabled:
            self.overlay.set_latency_text("")
        else:
            self._apply_latency()

    def _borderless_toggled(self, enabled: bool) -> None:
        self._ui_settings.setValue("auto_borderless_fullscreen", enabled)
        self._ui_settings.sync()
        if enabled:
            hwnd = int(self.window_combo.currentData() or 0)
            if hwnd:
                self._enable_borderless(hwnd)
        else:
            self._restore_borderless()

    def _enable_borderless(self, hwnd: int) -> None:
        if self._borderless_state is not None and self._borderless_hwnd == hwnd:
            return
        self._restore_borderless()
        state = make_borderless_fullscreen(hwnd)
        if state is None:
            self._logger.warning("目标窗口转换为无边框全屏失败：hwnd=%s", hwnd)
            self.titlebar.set_status("无边框全屏转换失败")
            return
        self._borderless_state = state
        self._borderless_hwnd = hwnd
        # A style/monitor-size transition can invalidate the WGC frame pool even
        # though the top-level HWND stays the same. Recreate it on the next frame
        # and immediately refresh the client geometry used for cropping.
        close_wgc_capture()
        if self._selected_window is not None and self._selected_window.hwnd == hwnd:
            self._selected_window = get_window_info(hwnd) or self._selected_window
        self._logger.info("目标窗口已转换为无边框全屏：hwnd=%s", hwnd)

    def _restore_borderless(self) -> None:
        if self._borderless_state is None:
            return
        hwnd = self._borderless_hwnd
        restored = restore_windowed_state(hwnd, self._borderless_state)
        close_wgc_capture()
        if self._selected_window is not None and self._selected_window.hwnd == hwnd:
            self._selected_window = get_window_info(hwnd) or self._selected_window
        self._logger.info("恢复目标窗口样式：hwnd=%s success=%s", hwnd, restored)
        self._borderless_state = None
        self._borderless_hwnd = 0

    def _apply_latency(self) -> None:
        if not getattr(self, "latency_switch", None) or not self.latency_switch.isChecked():
            return
        timing = self._last_timing
        if not timing:
            return
        text = (
            f"OCR {timing.get('ocr_ms', 0.0):.0f} ms（检测 {timing.get('det_ms', 0.0):.0f} / 识别 {timing.get('rec_ms', 0.0):.0f}）  ·  "
            f"翻译 {timing.get('translation_ms', 0.0):.0f} ms  ·  "
            f"总计 {timing.get('total_ms', 0.0):.0f} ms"
        )
        self.overlay.set_latency_text(text)

    def toggle_running(self) -> None:
        if not self.run_button.isEnabled():
            return
        if self._running:
            self._stop()
            return
        hwnd = int(self.window_combo.currentData() or 0)
        target = get_window_info(hwnd)
        if target is None:
            self.titlebar.set_status("目标窗口不可用")
            self.refresh_windows()
            return
        # A new run must never inherit text or a WGC session from the previous
        # target. An old in-flight worker result is discarded when it arrives.
        close_wgc_capture()
        self.overlay.clear()
        self._last_items = []
        self._last_image_size = (0, 0)
        self._last_timing = {}
        self._empty_frame_count = 0
        self._debug_capture_saved = False
        if not self._worker_busy:
            self._discard_worker_result = False
        self._selected_window = target
        if self.borderless_switch.isChecked():
            self._enable_borderless(target.hwnd)
            target = get_window_info(target.hwnd) or target
            self._selected_window = target
        self._logger.info("开始实时翻译：hwnd=%s title=%r client=(%s,%s,%sx%s)", target.hwnd, target.title, target.left, target.top, target.width, target.height)
        self._running = True
        self._empty_frame_count = 0
        self.run_button.setProperty("running", True)
        self.run_button.style().unpolish(self.run_button)
        self.run_button.style().polish(self.run_button)
        self.run_button.setText("停止实时翻译  (F8)")
        self.engine_combo.setEnabled(False)
        self.window_combo.setEnabled(False)
        self.source_combo.setEnabled(False)
        self.target_combo.setEnabled(False)
        self.track_timer.start()
        self.capture_timer.start()
        self._track_target()
        self._capture()

    def _f8_available(self) -> bool:
        target_hwnd = int(self.window_combo.currentData() or 0)
        return bool(
            self._ocr_ready
            and target_hwnd
            and QApplication.activeModalWidget() is None
        )

    def _sync_f8_hotkey(self) -> None:
        should_register = self._f8_available()
        if should_register == self._f8_registered:
            return
        if should_register:
            self._f8_registered = install_f8_hook(self._on_f8_hotkey)
            if self._f8_registered:
                self._logger.info("F8 钩子已安装：target=%s", self.window_combo.currentData())
            else:
                self._logger.warning("F8 钩子安装失败")
        else:
            uninstall_f8_hook()
            self._f8_registered = False
            self._logger.info("F8 钩子已卸载")

    def _on_f8_hotkey(self) -> None:
        if self._f8_registered and self._f8_available():
            QTimer.singleShot(0, self._toggle_from_f8)

    def _toggle_from_f8(self) -> None:
        if self._f8_available():
            self.toggle_running()

    def _stop(self) -> None:
        self._running = False
        close_wgc_capture()
        if self._worker_busy:
            self._discard_worker_result = True
        self._empty_frame_count = 0
        self._last_items = []
        self._last_image_size = (0, 0)
        self._last_timing = {}
        self.track_timer.stop()
        self.capture_timer.stop()
        self.overlay.clear()
        self.run_button.setProperty("running", False)
        self.run_button.style().unpolish(self.run_button)
        self.run_button.style().polish(self.run_button)
        self.run_button.setText("开始实时翻译  (F8)")
        self.engine_combo.setEnabled(True)
        self.window_combo.setEnabled(True)
        self.source_combo.setEnabled(True)
        self.target_combo.setEnabled(True)
        self.titlebar.set_status("已就绪")
        self._save_main_settings()

    def _track_target(self) -> None:
        if not self._running or self._selected_window is None:
            return
        target = get_window_info(self._selected_window.hwnd)
        if target is None:
            self.titlebar.set_status("目标窗口已关闭")
            self._stop()
            self.refresh_windows()
            return
        self._selected_window = target
        self._logger.debug("跟踪目标窗口：hwnd=%s client=(%s,%s,%sx%s)", target.hwnd, target.left, target.top, target.width, target.height)
        self.overlay.sync_target_z_order(target.hwnd)
        self.titlebar.set_status(
            "翻译运行中" if is_target_foreground(target.hwnd) else "目标窗口位于后台"
        )
        if self._last_items and not self.overlay.isVisible():
            self.overlay.update_content(
                target,
                self._last_items,
                self._layout_mode(),
                *self._last_image_size,
            )

    def _capture(self) -> None:
        if not self._running or self._worker_busy or self._selected_window is None:
            return
        try:
            self._capture_started_at = time.perf_counter()
            self._logger.info("开始截图：hwnd=%s rect=(%s,%s,%sx%s)", self._selected_window.hwnd, self._selected_window.left, self._selected_window.top, self._selected_window.width, self._selected_window.height)
            image = capture_window_bgr(self._selected_window, int(self.overlay.winId()))
            capture_ms = (time.perf_counter() - self._capture_started_at) * 1000.0
            if not self._debug_capture_saved:
                try:
                    import cv2

                    cv2.imwrite(str(Path.cwd() / "logs" / "debug_capture.png"), image)
                    self._debug_capture_saved = True
                    self._logger.info("调试截图已保存：logs/debug_capture.png")
                except Exception:
                    self._logger.exception("保存调试截图失败")
            self._logger.info(
                "截图完成：shape=%s min=%s max=%s std=%.2f capture_ms=%.1f",
                getattr(image, "shape", None),
                int(image.min()) if getattr(image, "size", 0) else -1,
                int(image.max()) if getattr(image, "size", 0) else -1,
                float(image.std()) if getattr(image, "size", 0) else 0.0,
                capture_ms,
            )
        except Exception as exc:
            self._logger.exception("窗口截图失败")
            self.titlebar.set_status(str(exc))
            return
        self._worker_busy = True
        config = self._config().to_dict()
        config["_capture_ms"] = capture_ms
        self._logger.info("提交 OCR 帧：capture_ms=%.1f", capture_ms)
        self.process_requested.emit(image, config)

    def _on_timing(self, timing: dict) -> None:
        self._last_timing = {str(key): float(value) for key, value in timing.items()}
        self._apply_latency()

    def _on_processed(self, items: list, image_width: int, image_height: int) -> None:
        self._logger.info("收到处理结果：items=%s image=%sx%s", len(items), image_width, image_height)
        self._worker_busy = False
        if self._discard_worker_result:
            self._discard_worker_result = False
            self._logger.info("丢弃上一运行会话的迟到 OCR 结果")
            if self._running:
                QTimer.singleShot(0, self._capture)
            return
        if not self._running or self._selected_window is None:
            return
        # Retain the previous translation through a transient empty OCR frame.
        if not items:
            self._empty_frame_count += 1
            if self._empty_frame_count >= 3:
                self._last_items = []
                self.overlay.clear()
            return
        self._empty_frame_count = 0
        self._last_items = items
        self._last_image_size = (image_width, image_height)
        self.overlay.update_content(
            self._selected_window,
            items,
            self._layout_mode(),
            image_width,
            image_height,
        )

    def _on_process_failed(self, message: str) -> None:
        self._worker_busy = False
        if self._discard_worker_result:
            self._discard_worker_result = False
            if self._running:
                QTimer.singleShot(0, self._capture)
            return
        if not self._ocr_ready:
            self.run_button.setText("OCR 初始化失败")
            self.run_button.setEnabled(False)
        self.titlebar.set_status(message)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if not self._force_quit:
            event.ignore()
            choice = CloseChoiceDialog(self).exec()
            if choice == CloseChoiceDialog.HIDE_TO_TRAY:
                self.hide()
            elif choice == CloseChoiceDialog.EXIT_APPLICATION:
                QTimer.singleShot(0, self._quit_application)
            return
        self.hotkey_timer.stop()
        uninstall_f8_hook()
        self._f8_registered = False
        self._save_main_settings()
        self._running = False
        self._restore_borderless()
        self.overlay.close()
        self.credential_dialog.shutdown()
        self.worker_thread.quit()
        self.worker_thread.wait(3000)
        event.accept()
