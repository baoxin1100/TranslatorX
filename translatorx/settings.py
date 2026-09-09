from __future__ import annotations

import base64
import ctypes
import os
import shutil
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from ctypes import wintypes
from time import perf_counter

import requests
from PySide6.QtCore import QSettings, QThread, Signal, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


def configure_settings_storage() -> None:
    """Keep settings outside the source tree replaced by launcher updates."""
    root = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "TranslatorX"
    destination = root / "TranslatorX" / "TranslatorX.ini"
    legacy = Path.cwd() / "TranslatorX" / "TranslatorX.ini"
    if legacy.is_file() and not destination.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(legacy, destination)
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(root))


def app_settings() -> QSettings:
    configure_settings_storage()
    return QSettings(
        QSettings.Format.IniFormat,
        QSettings.Scope.UserScope,
        "TranslatorX",
        "TranslatorX",
    )

from .models import TranslatorConfig
from .translators import create_translator


CRYPTPROTECT_UI_FORBIDDEN = 0x01


class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def _protect_secret(value: str) -> str:
    if not value:
        return ""
    raw = value.encode("utf-8")
    buffer = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw)
    source = DATA_BLOB(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    protected = DATA_BLOB()
    success = ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(source),
        "TranslatorX saved credential",
        None,
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(protected),
    )
    if not success:
        raise OSError("Windows 无法加密密钥")
    try:
        encrypted = ctypes.string_at(protected.pbData, protected.cbData)
        return base64.b64encode(encrypted).decode("ascii")
    finally:
        ctypes.windll.kernel32.LocalFree(protected.pbData)


def _unprotect_secret(value: str) -> str:
    if not value:
        return ""
    try:
        raw = base64.b64decode(value, validate=True)
        buffer = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw)
        source = DATA_BLOB(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
        unprotected = DATA_BLOB()
        success = ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(source),
            None,
            None,
            None,
            None,
            CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(unprotected),
        )
        if not success:
            return ""
        try:
            return ctypes.string_at(unprotected.pbData, unprotected.cbData).decode("utf-8")
        finally:
            ctypes.windll.kernel32.LocalFree(unprotected.pbData)
    except (ValueError, UnicodeDecodeError):
        return ""


class InterfaceTestThread(QThread):
    completed = Signal(object)

    def __init__(self, credentials: dict[str, str], parent=None) -> None:
        super().__init__(parent)
        self.credentials = dict(credentials)

    def run(self) -> None:
        providers = [
            (
                "百度翻译",
                "baidu",
                bool(self.credentials.get("baidu_app_id") and self.credentials.get("baidu_secret")),
            ),
            (
                "腾讯翻译",
                "tencent",
                bool(self.credentials.get("tencent_secret_id") and self.credentials.get("tencent_secret_key")),
            ),
            (
                "OpenAI 兼容接口",
                "openai",
                bool(self.credentials.get("openai_api_key") and self.credentials.get("openai_model")),
            ),
        ]
        results: list[tuple[str, str, int | None, str] | None] = [None] * len(providers)
        test_credentials = dict(self.credentials)
        test_credentials["_timeout"] = "10"

        def test_one(label: str, engine: str) -> tuple[str, str, int | None, str]:
            started = perf_counter()
            try:
                translator = create_translator(TranslatorConfig(engine, "en", "zh-CN", test_credentials))
                translated = translator.translate_batch(["Hello"])[0]
                latency = round((perf_counter() - started) * 1000)
                return label, "可用", latency, translated[:40]
            except Exception as exc:
                latency = round((perf_counter() - started) * 1000)
                return label, "失败", latency, str(exc)

        futures = {}
        with ThreadPoolExecutor(max_workers=3, thread_name_prefix="translatorx-interface-test") as pool:
            for index, (label, engine, configured) in enumerate(providers):
                if configured:
                    futures[pool.submit(test_one, label, engine)] = index
                else:
                    results[index] = (label, "未配置", None, "")
            for future in as_completed(futures):
                results[futures[future]] = future.result()

        self.completed.emit([item for item in results if item is not None])


def _model_endpoint(base_url: str) -> str:
    """Return the OpenAI-compatible model listing endpoint."""
    base = base_url.strip().rstrip("/")
    for suffix in ("/chat/completions", "/responses"):
        if base.casefold().endswith(suffix):
            base = base[: -len(suffix)]
    return f"{base}/models"


def _parse_model_ids(payload: object) -> list[str]:
    """Parse common OpenAI-compatible /models response shapes."""
    if isinstance(payload, dict):
        entries = payload.get("data", payload.get("models", []))
    else:
        entries = payload
    if not isinstance(entries, list):
        return []
    model_ids: list[str] = []
    for entry in entries:
        if isinstance(entry, str):
            model_id = entry.strip()
        elif isinstance(entry, dict):
            model_id = str(entry.get("id", entry.get("name", ""))).strip()
        else:
            model_id = ""
        if model_id and model_id not in model_ids:
            model_ids.append(model_id)
    return sorted(model_ids, key=str.casefold)


class ModelFetchThread(QThread):
    completed = Signal(object)

    def __init__(self, base_url: str, api_key: str, parent=None) -> None:
        super().__init__(parent)
        self.base_url = base_url.strip()
        self.api_key = api_key.strip()

    def run(self) -> None:
        started = perf_counter()
        try:
            if not self.base_url:
                raise ValueError("请先填写 Base URL")
            headers = {"Accept": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            response = requests.get(
                _model_endpoint(self.base_url),
                headers=headers,
                timeout=10,
            )
            latency = round((perf_counter() - started) * 1000)
            response.raise_for_status()
            models = _parse_model_ids(response.json())
            if not models:
                raise ValueError("接口返回成功，但没有找到模型列表")
            self.completed.emit({"ok": True, "models": models, "latency": latency})
        except Exception as exc:
            latency = round((perf_counter() - started) * 1000)
            self.completed.emit({"ok": False, "error": str(exc), "latency": latency})


class CredentialDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("settingsDialog")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setWindowTitle("翻译服务设置")
        self.setMinimumWidth(500)
        self._settings = app_settings()
        self._test_thread: InterfaceTestThread | None = None
        self._model_thread: ModelFetchThread | None = None

        self.baidu_app_id = self._field("TRANSLATORX_BAIDU_APP_ID")
        self.baidu_secret = self._secret_field("TRANSLATORX_BAIDU_SECRET")
        self.tencent_secret_id = self._field("TRANSLATORX_TENCENT_SECRET_ID")
        self.tencent_secret_key = self._secret_field("TRANSLATORX_TENCENT_SECRET_KEY")
        self.tencent_region = self._field("TRANSLATORX_TENCENT_REGION", "ap-guangzhou")
        self.openai_base_url = self._field("TRANSLATORX_OPENAI_BASE_URL", "https://api.openai.com/v1")
        self.openai_api_key = self._secret_field("TRANSLATORX_OPENAI_API_KEY")
        self.openai_model = self._model_field("TRANSLATORX_OPENAI_MODEL", "gpt-4.1-mini")

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 16)
        root.setSpacing(14)
        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(8)
        header_title = QLabel("翻译服务设置")
        header_title.setObjectName("settingsDialogTitle")
        header_layout.addWidget(header_title)
        header_layout.addStretch(1)
        root.addWidget(header)
        note = QLabel("密钥使用 Windows 当前用户加密后保存；也可通过 TRANSLATORX_* 环境变量提供。")
        note.setObjectName("settingsNote")
        note.setWordWrap(True)
        root.addWidget(note)
        root.addWidget(self._group("百度翻译", [("APP ID", self.baidu_app_id), ("密钥", self.baidu_secret)]))
        root.addWidget(
            self._group(
                "腾讯翻译",
                [("SecretId", self.tencent_secret_id), ("SecretKey", self.tencent_secret_key), ("地域", self.tencent_region)],
            )
        )
        model_row = QWidget()
        model_layout = QHBoxLayout(model_row)
        model_layout.setContentsMargins(0, 0, 0, 0)
        model_layout.setSpacing(8)
        model_layout.addWidget(self.openai_model, 1)
        self.fetch_models_button = QPushButton("获取模型")
        self.fetch_models_button.setObjectName("settingsActionButton")
        self.fetch_models_button.setAccessibleName("从接口获取模型列表")
        self.fetch_models_button.setToolTip("请求 Base URL/models，填充可选模型")
        self.fetch_models_button.clicked.connect(self._start_model_fetch)
        model_layout.addWidget(self.fetch_models_button)
        root.addWidget(
            self._group(
                "OpenAI 兼容接口",
                [("Base URL", self.openai_base_url), ("API Key", self.openai_api_key), ("模型", model_row)],
            )
        )
        self.test_results = QPlainTextEdit()
        self.test_results.setObjectName("testResults")
        self.test_results.setReadOnly(True)
        self.test_results.setPlaceholderText("点击“接口测试”查看已配置接口的连通状态与延迟")
        self.test_results.setFixedHeight(116)
        root.addWidget(self.test_results)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.test_button = QPushButton("接口测试")
        self.test_button.setAccessibleName("测试翻译接口连通情况")
        buttons.addButton(self.test_button, QDialogButtonBox.ButtonRole.ActionRole)
        save_button = buttons.button(QDialogButtonBox.StandardButton.Save)
        cancel_button = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        save_button.setText("保存")
        cancel_button.setText("取消")
        save_button.setAccessibleName("保存翻译服务设置")
        cancel_button.setAccessibleName("取消翻译服务设置")
        for button in (self.test_button, save_button, cancel_button):
            button.setObjectName("settingsActionButton")
        self.test_button.clicked.connect(self._start_interface_test)
        buttons.accepted.connect(self._save_and_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _field(self, env_name: str, default: str = "") -> QLineEdit:
        value = os.environ.get(env_name, str(self._settings.value(env_name, default)))
        return QLineEdit(value)

    def _model_field(self, env_name: str, default: str = "") -> QComboBox:
        value = os.environ.get(env_name, str(self._settings.value(env_name, default)))
        field = QComboBox()
        field.setEditable(True)
        field.addItem(value)
        field.setCurrentText(value)
        field.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        return field

    def _secret_field(self, env_name: str) -> QLineEdit:
        environment_value = os.environ.get(env_name)
        saved_value = str(self._settings.value(f"{env_name}_DPAPI", ""))
        value = environment_value if environment_value is not None else _unprotect_secret(saved_value)
        field = QLineEdit(value)
        field.setEchoMode(QLineEdit.EchoMode.Password)
        return field

    @staticmethod
    def _readonly_field(value: str) -> QLineEdit:
        field = QLineEdit(value)
        field.setReadOnly(True)
        return field

    @staticmethod
    def _group(title: str, rows: list[tuple[str, QWidget]]) -> QGroupBox:
        group = QGroupBox(title)
        form = QFormLayout(group)
        form.setContentsMargins(14, 16, 14, 14)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(10)
        for label, widget in rows:
            form.addRow(label, widget)
        return group

    def _save_and_accept(self) -> None:
        self._settings.setValue("TRANSLATORX_BAIDU_APP_ID", self.baidu_app_id.text().strip())
        self._settings.setValue("TRANSLATORX_BAIDU_SECRET_DPAPI", _protect_secret(self.baidu_secret.text().strip()))
        self._settings.setValue("TRANSLATORX_TENCENT_SECRET_ID", self.tencent_secret_id.text().strip())
        self._settings.setValue(
            "TRANSLATORX_TENCENT_SECRET_KEY_DPAPI",
            _protect_secret(self.tencent_secret_key.text().strip()),
        )
        self._settings.setValue("TRANSLATORX_TENCENT_REGION", self.tencent_region.text().strip())
        self._settings.setValue("TRANSLATORX_OPENAI_BASE_URL", self.openai_base_url.text().strip())
        self._settings.setValue("TRANSLATORX_OPENAI_API_KEY_DPAPI", _protect_secret(self.openai_api_key.text().strip()))
        self._settings.setValue("TRANSLATORX_OPENAI_MODEL", self._model_text())
        self._settings.sync()
        self.accept()

    def _start_interface_test(self) -> None:
        if self._test_thread is not None and self._test_thread.isRunning():
            return
        self.test_button.setEnabled(False)
        self.test_button.setText("测试中…")
        self.test_results.setPlainText("正在测试已配置接口，请稍候…")
        self._test_thread = InterfaceTestThread(self.credentials(), self)
        self._test_thread.completed.connect(self._show_test_results)
        self._test_thread.finished.connect(self._finish_interface_test)
        self._test_thread.start()

    def _start_model_fetch(self) -> None:
        if self._model_thread is not None and self._model_thread.isRunning():
            return
        self.fetch_models_button.setEnabled(False)
        self.fetch_models_button.setText("获取中…")
        self.test_results.setPlainText("正在获取模型列表，请稍候…")
        self._model_thread = ModelFetchThread(
            self.openai_base_url.text(), self.openai_api_key.text(), self
        )
        self._model_thread.completed.connect(self._show_model_results)
        self._model_thread.finished.connect(self._finish_model_fetch)
        self._model_thread.start()

    def _show_model_results(self, result: dict[str, object]) -> None:
        latency = result.get("latency", 0)
        if result.get("ok"):
            models = [str(item) for item in result.get("models", [])]
            current = self._model_text()
            self.openai_model.clear()
            self.openai_model.addItems(models)
            if current and current in models:
                self.openai_model.setCurrentText(current)
            else:
                self.openai_model.setCurrentText(models[0])
            # After a successful discovery, make this a real selection control.
            # Manual editing remains available again if a later request fails.
            self.openai_model.setEditable(False)
            self.test_results.setPlainText(f"获取到 {len(models)} 个模型 · {latency} ms")
        else:
            self.openai_model.setEditable(True)
            self.test_results.setPlainText(f"获取模型失败 · {latency} ms\n{result.get('error', '未知错误')}")

    def _finish_model_fetch(self) -> None:
        self.fetch_models_button.setEnabled(True)
        self.fetch_models_button.setText("获取模型")
        thread = self._model_thread
        self._model_thread = None
        if thread is not None:
            thread.deleteLater()

    def _model_text(self) -> str:
        return self.openai_model.currentText().strip()

    def _show_test_results(self, results: list[tuple[str, str, int | None, str]]) -> None:
        lines = []
        for label, status, latency, detail in results:
            timing = f" · {latency} ms" if latency is not None else ""
            suffix = f" · {detail}" if detail else ""
            lines.append(f"{label}：{status}{timing}{suffix}")
        self.test_results.setPlainText("\n".join(lines))

    def _finish_interface_test(self) -> None:
        self.test_button.setEnabled(True)
        self.test_button.setText("接口测试")
        thread = self._test_thread
        self._test_thread = None
        if thread is not None:
            thread.deleteLater()

    def shutdown(self) -> None:
        if self._test_thread is not None and self._test_thread.isRunning():
            self._test_thread.requestInterruption()
            self._test_thread.wait(11000)
        if self._model_thread is not None and self._model_thread.isRunning():
            self._model_thread.requestInterruption()
            self._model_thread.wait(11000)

    def credentials(self) -> dict[str, str]:
        return {
            "baidu_app_id": self.baidu_app_id.text().strip(),
            "baidu_secret": self.baidu_secret.text().strip(),
            "tencent_secret_id": self.tencent_secret_id.text().strip(),
            "tencent_secret_key": self.tencent_secret_key.text().strip(),
            "tencent_region": self.tencent_region.text().strip(),
            "openai_base_url": self.openai_base_url.text().strip(),
            "openai_api_key": self.openai_api_key.text().strip(),
            "openai_model": self._model_text(),
        }
