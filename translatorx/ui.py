from __future__ import annotations

import time
import logging
from pathlib import Path

from PySide6.QtCore import QPoint, QSize, QThread, QTimer, Qt, QUrl, Signal
from PySide6.QtGui import QAction, QColor, QCloseEvent, QDesktopServices, QIcon, QMouseEvent, QPainter
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

from .config_store import app_config
from .launcher import remove_launcher_shortcuts, show_launcher
from .paths import debug_capture_path
from .models import LayoutMode, TranslatorConfig, WindowInfo
from .overlay import TranslationOverlay, capture_window_bgr
from .updater import REPO_WEB_URL, fetch_latest_version, is_update_available
from .version import get_app_version
from .wgc_capture import close_wgc_capture
from .settings import CredentialDialog
from .theme import theme_manager, tinted_icon
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
        theme = theme_manager.current()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        track = self.rect().adjusted(1, 4, -1, -4)
        track_color = QColor(theme.switch_on if self._checked else theme.switch_off)
        border_color = QColor(theme.switch_border_on if self._checked else theme.switch_border_off)
        painter.setPen(border_color)
        painter.setBrush(track_color)
        painter.drawRoundedRect(track, track.height() / 2, track.height() / 2)
        knob_diameter = track.height() - 6
        knob_x = track.right() - knob_diameter - 3 if self._checked else track.left() + 3
        knob = track.adjusted(knob_x - track.left(), 3, knob_x - track.right() + knob_diameter, -3)
        painter.setPen(QColor(theme.switch_knob))
        painter.setBrush(QColor(theme.switch_knob))
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
        settings.setIconSize(QSize(17, 17))
        settings.setToolTip("翻译服务设置")
        settings.setAccessibleName("打开翻译服务设置")
        settings.clicked.connect(window.open_settings)
        layout.addWidget(settings)
        minimize = QToolButton()
        minimize.setObjectName("titleButton")
        minimize.setIconSize(QSize(17, 17))
        minimize.setToolTip("最小化到系统托盘")
        minimize.setAccessibleName("最小化到系统托盘")
        minimize.clicked.connect(window.hide_to_tray)
        layout.addWidget(minimize)
        close = QToolButton()
        close.setObjectName("closeButton")
        close.setIconSize(QSize(17, 17))
        close.setToolTip("关闭程序")
        close.setAccessibleName("关闭 TranslatorX")
        close.clicked.connect(window.close)
        layout.addWidget(close)
        self._icon_buttons = [
            (settings, "settings-outline.svg"),
            (minimize, "minimize.svg"),
            (close, "close.svg"),
        ]
        self.apply_theme()

    def apply_theme(self, theme=None) -> None:
        """Re-render the title-bar icons in the active theme's colour."""
        theme = theme or theme_manager.current()
        for button, asset in self._icon_buttons:
            button.setIcon(tinted_icon(asset, theme.title_icon))

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


class UpdateCheckThread(QThread):
    """Query the update repository without blocking the UI thread."""

    checked = Signal(bool, str, str)

    def run(self) -> None:  # noqa: D102
        try:
            latest = fetch_latest_version()
        except Exception as exc:
            self.checked.emit(False, "", str(exc))
            return
        self.checked.emit(True, latest or "", "")


class AboutDialog(QDialog):
    """About window with the project link and an update checker."""

    update_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("aboutDialog")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setModal(True)
        self.setFixedSize(430, 272)

        self.current_version = get_app_version() or "开发版"
        self._pending_version = ""
        self._check_thread: UpdateCheckThread | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(9)

        title = QLabel("关于 TranslatorX")
        title.setObjectName("aboutTitle")
        root.addWidget(title)

        note = QLabel(f"当前版本：{self.current_version}")
        note.setObjectName("aboutNote")
        root.addWidget(note)

        self.status_label = QLabel("点击“检查更新”查询远端最新版本。")
        self.status_label.setObjectName("aboutStatus")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

        self.upgrade_button = QPushButton("立即更新")
        self.upgrade_button.setObjectName("aboutUpgradeButton")
        self.upgrade_button.setAccessibleName("立即打开更新启动器")
        self.upgrade_button.clicked.connect(self._request_update)
        self.upgrade_button.hide()
        root.addWidget(self.upgrade_button, 0, Qt.AlignmentFlag.AlignLeft)
        root.addStretch(1)

        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        github_button = QPushButton("GitHub 项目主页")
        github_button.setObjectName("aboutLinkButton")
        github_button.setAccessibleName("在浏览器中打开 GitHub 项目主页")
        github_button.clicked.connect(self._open_github)
        buttons.addWidget(github_button)

        self.update_button = QPushButton("检查更新")
        self.update_button.setObjectName("aboutUpdateButton")
        self.update_button.setAccessibleName("检查是否有新版本")
        self.update_button.clicked.connect(self._check_updates)
        buttons.addWidget(self.update_button)
        buttons.addStretch(1)

        close_button = QPushButton("关闭")
        close_button.setObjectName("aboutCloseButton")
        close_button.setAccessibleName("关闭关于窗口")
        close_button.clicked.connect(self.close)
        buttons.addWidget(close_button)
        root.addLayout(buttons)

    def _open_github(self) -> None:
        QDesktopServices.openUrl(QUrl(REPO_WEB_URL))

    def _request_update(self) -> None:
        """Open the launcher so it can install the pending version."""
        if not self._pending_version:
            return
        self.upgrade_button.setEnabled(False)
        self.update_requested.emit()
        self.close()

    def _check_updates(self) -> None:
        if self._check_thread is not None and self._check_thread.isRunning():
            return
        self.update_button.setEnabled(False)
        self.update_button.setText("正在检查…")
        self.status_label.setText("正在查询远端版本…")
        # Parent the worker to the main window so closing this dialog while the
        # request is in flight cannot destroy a running QThread.
        owner = self.parent() or self
        thread = UpdateCheckThread(owner)
        thread.checked.connect(self._on_checked)
        thread.finished.connect(self._on_check_finished)
        thread.finished.connect(thread.deleteLater)
        self._check_thread = thread
        thread.start()

    def _on_check_finished(self) -> None:
        self._check_thread = None

    def _on_checked(self, ok: bool, latest: str, error: str) -> None:
        self.update_button.setEnabled(True)
        self.update_button.setText("检查更新")
        self._pending_version = ""
        self.upgrade_button.hide()
        self.upgrade_button.setEnabled(True)
        if not ok:
            self.status_label.setText(f"检查更新失败：{error or '未知错误'}")
            return
        if not latest:
            self.status_label.setText("未能获取远端版本信息，请稍后再试。")
            return
        if is_update_available(latest, self.current_version):
            self._pending_version = latest
            self.status_label.setText(f"发现新版本：当前 {self.current_version} → 最新 {latest}")
            self.upgrade_button.setAccessibleName(f"立即更新到 {latest}")
            self.upgrade_button.show()
        else:
            self.status_label.setText(f"当前已是最新版本（{self.current_version}）")


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
        self._ui_settings = app_config()

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
        self._tray_hint_shown = False
        self.overlay = TranslationOverlay()
        self.credential_dialog = CredentialDialog(self, on_about=self.open_about)

        self._build_ui()
        theme_manager.changed.connect(self._apply_theme)
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
        self._shortcut_sweeps = 0
        self._shortcut_timer = QTimer(self)
        self._shortcut_timer.setInterval(3000)
        self._shortcut_timer.timeout.connect(self._drop_launcher_shortcuts)
        self._shortcut_timer.start()

    def open_about(self) -> None:
        dialog = AboutDialog(self)
        dialog.update_requested.connect(self._start_launcher_update)
        dialog.exec()

    def _start_launcher_update(self) -> None:
        if not show_launcher():
            self.titlebar.set_status("无法打开更新启动器，请手动运行启动器")
            return
        self._logger.info("已打开更新启动器，正在退出当前程序")
        QTimer.singleShot(400, self._quit_application)

    def _drop_launcher_shortcuts(self) -> None:
        """Keep only the application shortcut.

        PyAppify rewrites both shortcuts a few seconds after it confirms the
        app started, which can be later than this window's own startup. Sweep
        repeatedly for the first minute instead of checking only once.
        """
        self._shortcut_sweeps += 1
        if self._shortcut_sweeps > 20:
            self._shortcut_timer.stop()
            return
        try:
            removed = remove_launcher_shortcuts()
        except Exception:
            self._logger.exception("清理启动器快捷方式失败")
            return
        if removed:
            self._logger.info("已删除启动器快捷方式：%s", "; ".join(removed))

    def _apply_language_icon(self) -> None:
        theme = theme_manager.current()
        self.language_direction.setPixmap(
            tinted_icon("arrow-right.svg", theme.icon_muted, 44).pixmap(22, 22)
        )

    def _apply_theme(self, _theme=None) -> None:
        """Repaint the parts a stylesheet cannot reach: SVG icons and custom paint."""
        self.titlebar.apply_theme()
        self._apply_language_icon()
        for switch in self.findChildren(Switch):
            switch.update()

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
        self.language_direction = QLabel()
        self.language_direction.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.language_direction.setFixedWidth(24)
        self.language_direction.setContentsMargins(0, 24, 0, 0)
        self.language_direction.setAccessibleName("源语言到目标语言")
        self._apply_language_icon()
        languages.addWidget(self.language_direction)
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

    def hide_to_tray(self) -> None:
        """Hide the window while the app keeps running in the system tray."""
        self.hide()
        if not self._tray_hint_shown:
            self._tray_hint_shown = True
            self.tray_icon.showMessage(
                "TranslatorX",
                "已最小化到系统托盘，单击托盘图标可重新打开，右键可退出。",
                QSystemTrayIcon.MessageIcon.Information,
                4000,
            )

    def _quit_from_tray(self) -> None:
        self._quit_application()

    def _quit_application(self) -> None:
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

                    target = debug_capture_path()
                    target.parent.mkdir(parents=True, exist_ok=True)
                    cv2.imwrite(str(target), image)
                    self._debug_capture_saved = True
                    self._logger.info("调试截图已保存：%s", target)
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
