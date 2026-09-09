from __future__ import annotations

from dataclasses import replace
import logging
import re
import statistics
import threading
import time
import unicodedata

from PySide6.QtCore import QObject, Signal, Slot

from .models import OcrItem, TranslatorConfig
from .ocr import OnnxOcrService
from .logging_setup import process_memory_mb
from .translators import TranslationError, create_translator


_CONTINUATION_WORDS = {
    "and", "or", "but", "so", "to", "of", "for", "with", "from", "in", "on",
    "at", "by", "the", "a", "an", "that", "which", "as", "than", "because",
    "who", "where", "what", "when", "why", "how",
    # Common transitive/progressive verbs that normally need a following
    # object or complement.  Keep this explicit instead of treating every
    # '-ing' word as incomplete: labels such as "Loading" can be complete.
    "getting", "making", "taking", "using", "trying", "going", "coming",
    "doing", "having", "being", "keeping", "looking", "moving", "holding",
    "turning", "working", "waiting",
}
_MENU_PREFIX = re.compile(r"^\s*(?:[+×✚*•·]|\d+[.)]|[A-Z]\)|[-–—])\s*[:：]?")
_HARD_END = re.compile(r"[.!?。！？]$")


def _item_rect(item: OcrItem) -> tuple[float, float, float, float]:
    xs = [float(point[0]) for point in item.box]
    ys = [float(point[1]) for point in item.box]
    return min(xs), min(ys), max(xs), max(ys)


def _is_menu_item(text: str) -> bool:
    return bool(_MENU_PREFIX.match(text))


def _has_unclosed_delimiter(text: str) -> bool:
    pairs = (("(", ")"), ("[", "]"), ("{", "}"))
    if any(text.count(open_char) > text.count(close_char) for open_char, close_char in pairs):
        return True
    # An odd number of straight double quotes means the quoted phrase
    # continues on a following OCR line.  Do not treat apostrophes in words
    # such as don't as quote delimiters.
    if text.count('"') % 2:
        return True
    if text.count("“") > text.count("”") or text.count("‘") > text.count("’"):
        return True
    return False


def _is_continuation(previous: str, following: str) -> bool:
    previous = previous.strip()
    following = following.strip()
    if not previous or not following:
        return False
    if _has_unclosed_delimiter(previous):
        return True
    if _HARD_END.search(previous):
        return False
    if previous[-1] in ",，、:：;；-–—…（([\":'“‘":
        return True
    words = re.findall(r"[A-Za-z]+(?:['’][A-Za-z]+)?", previous.casefold())
    if words and words[-1] in _CONTINUATION_WORDS:
        return True
    return bool(following[:1].islower())


def group_translation_items(items: list[OcrItem]) -> list[OcrItem]:
    """Conservatively join OCR lines that are clearly one wrapped sentence."""
    if len(items) < 2:
        return items
    ordered = sorted(items, key=lambda item: (_item_rect(item)[1], _item_rect(item)[0]))
    heights = [max(1.0, _item_rect(item)[3] - _item_rect(item)[1]) for item in ordered]
    median_height = statistics.median(heights)
    result: list[OcrItem] = []
    group: list[OcrItem] = []

    def flush() -> None:
        if not group:
            return
        if len(group) == 1:
            result.append(group[0])
            return
        boxes = [point for item in group for point in item.box]
        left = min(point[0] for point in boxes)
        top = min(point[1] for point in boxes)
        right = max(point[0] for point in boxes)
        bottom = max(point[1] for point in boxes)
        texts = [item.text.strip() for item in group]
        contains_cjk = any(any("\u2e80" <= char <= "\u9fff" for char in text) for text in texts)
        separator = "" if contains_cjk else " "
        result.append(OcrItem(
            box=((left, top), (right, top), (right, bottom), (left, bottom)),
            text=separator.join(texts),
            confidence=min(item.confidence for item in group),
        ))

    for item in ordered:
        if not group:
            group = [item]
            continue
        previous = group[-1]
        px1, py1, px2, py2 = _item_rect(previous)
        x1, y1, x2, y2 = _item_rect(item)
        vertical_gap = y1 - py2
        previous_center = (px1 + px2) / 2.0
        current_center = (x1 + x2) / 2.0
        center_delta = abs(current_center - previous_center)
        close_lines = vertical_gap <= max(10.0, median_height * 0.75)
        centered = center_delta <= max(median_height * 1.5, (px2 - px1) * 0.35)
        menu_like = _is_menu_item(previous.text) or _is_menu_item(item.text)
        continuation = _is_continuation(previous.text, item.text)
        previous_width = max(1.0, px2 - px1)
        current_width = max(1.0, x2 - x1)
        horizontal_overlap = max(0.0, min(px2, x2) - max(px1, x1))
        # Wrapped paragraphs are often left aligned rather than center aligned.
        # Permit that shape only when the text itself strongly indicates an
        # unfinished phrase ("a", "getting", comma, open bracket, etc.).
        left_aligned = abs(px1 - x1) <= max(10.0, median_height * 0.8)
        overlapping = horizontal_overlap >= min(previous_width, current_width) * 0.35
        compatible_alignment = centered or (continuation and (left_aligned or overlapping))
        if close_lines and compatible_alignment and not menu_like and continuation:
            group.append(item)
        else:
            flush()
            group = [item]
    flush()
    return result


def should_translate_text(text: str) -> bool:
    """Reject numeric/symbol-only OCR noise and isolated Latin hotkeys."""
    compact = [character for character in text.strip() if not character.isspace()]
    if not compact:
        return False

    semantic = [
        character
        for character in compact
        if unicodedata.category(character)[0] not in {"P", "S"}
    ]
    if not semantic or all(character.isdigit() for character in semantic):
        return False
    if len(semantic) == 1 and semantic[0].isalpha() and "LATIN" in unicodedata.name(semantic[0], ""):
        return False
    return True


class ProcessingWorker(QObject):
    ready = Signal()
    completed = Signal(object, int, int)
    timing = Signal(object)
    failed = Signal(str)

    def __init__(self, enable_openvino: bool = True) -> None:
        super().__init__()
        self._logger = logging.getLogger("translatorx.worker")
        self._enable_openvino = enable_openvino
        self._ocr: OnnxOcrService | None = None
        self._cache: dict[tuple[str, str, str, str], str] = {}
        self._last_memory_log_at = 0.0

    def _log_memory_if_due(self) -> None:
        now = time.monotonic()
        if now - self._last_memory_log_at < 5.0:
            return
        self._last_memory_log_at = now
        memory_mb = process_memory_mb()
        if memory_mb is not None:
            self._logger.info("进程内存：working_set=%.1f MiB", memory_mb)

    def _recognize(self, image_bgr):
        """Run native OpenVINO inference outside the Qt event thread.

        The oknikke OpenVINO/PySide combination can raise an uncatchable
        access violation when inference is entered directly from a QThread.
        A plain Python worker thread keeps the UI and Qt event thread out of
        that native call while retaining the same single in-flight frame.
        """
        recognize_timed = getattr(self._ocr, "recognize_timed", None)
        if recognize_timed is None:
            started = time.perf_counter()
            items = self._ocr.recognize(image_bgr)
            return items, {"det_ms": 0.0, "rec_ms": 0.0, "ocr_ms": (time.perf_counter() - started) * 1000.0}
        if not self._enable_openvino:
            return recognize_timed(image_bgr)
        result = []
        error = []

        def run() -> None:
            try:
                result.append(recognize_timed(image_bgr))
            except BaseException as exc:  # propagate ordinary Python errors
                error.append(exc)

        thread = threading.Thread(target=run, name="translatorx-openvino", daemon=True)
        thread.start()
        thread.join()
        if error:
            raise error[0]
        return result[0] if result else ([], {"det_ms": 0.0, "rec_ms": 0.0, "ocr_ms": 0.0})

    @Slot()
    def initialize(self) -> None:
        try:
            try:
                self._ocr = OnnxOcrService(enable_openvino=True)
                self._enable_openvino = bool(getattr(self._ocr, "using_openvino", True))
            except Exception as openvino_error:
                self._logger.warning("OpenVINO OCR 初始化失败，自动回退 ONNX Runtime：%s", openvino_error)
                self._enable_openvino = False
                self._ocr = OnnxOcrService(enable_openvino=False)
            self._logger.info("OCR 工作线程初始化完成：OpenVINO=%s", self._enable_openvino)
            self._log_memory_if_due()
            self.ready.emit()
        except Exception as exc:  # startup failures must reach the UI
            self._logger.exception("OCR 初始化失败")
            self.failed.emit(f"OCR 初始化失败：{exc}")

    @Slot(object, object)
    def process(self, image_bgr, raw_config: dict) -> None:
        if self._ocr is None:
            self.failed.emit("OCR 模型尚未就绪")
            return
        started_at = time.perf_counter()
        try:
            config = TranslatorConfig.from_dict(raw_config)
            capture_ms = float(raw_config.get("_capture_ms", 0.0) or 0.0)
            ocr_started = time.perf_counter()
            self._logger.info("开始 OCR：source_shape=%s", getattr(image_bgr, "shape", None))
            items, ocr_parts = self._recognize(image_bgr)
            ocr_ms = (time.perf_counter() - ocr_started) * 1000.0
            self._logger.info(
                "OCR 完成：items=%s source_shape=%s analysis_shape=(%sx%s) ocr_ms=%.1f",
                len(items),
                getattr(image_bgr, "shape", None),
                int(ocr_parts.get("analysis_width", image_bgr.shape[1])),
                int(ocr_parts.get("analysis_height", image_bgr.shape[0])),
                ocr_ms,
            )
            self._log_memory_if_due()
            postprocess_started = time.perf_counter()
            items = [item for item in items if should_translate_text(item.text)]
            before_group_count = len(items)
            items = group_translation_items(items)
            if len(items) != before_group_count:
                self._logger.info("合并连续文本：%s -> %s 个翻译单元", before_group_count, len(items))
            if not items:
                self.completed.emit([], image_bgr.shape[1], image_bgr.shape[0])
                self.timing.emit({
                    "capture_ms": capture_ms,
                    "ocr_ms": ocr_ms,
                    "det_ms": float(ocr_parts.get("det_ms", 0.0)),
                    "rec_ms": float(ocr_parts.get("rec_ms", 0.0)),
                    "analysis_width": float(ocr_parts.get("analysis_width", image_bgr.shape[1])),
                    "analysis_height": float(ocr_parts.get("analysis_height", image_bgr.shape[0])),
                    "translation_ms": 0.0,
                    "postprocess_ms": (time.perf_counter() - postprocess_started) * 1000.0,
                    "total_ms": capture_ms + (time.perf_counter() - started_at) * 1000.0,
                })
                return

            missing_texts: list[str] = []
            for item in items:
                key = (config.engine, config.source_language, config.target_language, item.text)
                if key not in self._cache and item.text not in missing_texts:
                    missing_texts.append(item.text)

            if missing_texts:
                translation_started = time.perf_counter()
                self._logger.info("开始批量翻译：engine=%s count=%s", config.engine, len(missing_texts))
                translator = create_translator(config)
                translations = translator.translate_batch(missing_texts)
                for source, translated in zip(missing_texts, translations, strict=True):
                    key = (config.engine, config.source_language, config.target_language, source)
                    self._cache[key] = translated
                translation_ms = (time.perf_counter() - translation_started) * 1000.0
                self._logger.info("批量翻译完成：translation_ms=%.1f", translation_ms)
            else:
                translation_ms = 0.0

            translated_items: list[OcrItem] = []
            for item in items:
                key = (config.engine, config.source_language, config.target_language, item.text)
                translated_items.append(replace(item, translation=self._cache.get(key, "")))
            postprocess_ms = max(
                0.0,
                (time.perf_counter() - postprocess_started) * 1000.0 - translation_ms,
            )
            self.timing.emit({
                "capture_ms": capture_ms,
                "ocr_ms": ocr_ms,
                "det_ms": float(ocr_parts.get("det_ms", 0.0)),
                "rec_ms": float(ocr_parts.get("rec_ms", 0.0)),
                "analysis_width": float(ocr_parts.get("analysis_width", image_bgr.shape[1])),
                "analysis_height": float(ocr_parts.get("analysis_height", image_bgr.shape[0])),
                "translation_ms": translation_ms,
                "postprocess_ms": postprocess_ms,
                "total_ms": capture_ms + (time.perf_counter() - started_at) * 1000.0,
            })
            self.completed.emit(translated_items, image_bgr.shape[1], image_bgr.shape[0])
            self._logger.info("处理完成：translated_items=%s", len(translated_items))
        except TranslationError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            self._logger.exception("处理帧失败")
            self.failed.emit(f"处理失败：{exc}")
