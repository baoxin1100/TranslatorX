from __future__ import annotations

import logging
import time
from typing import Any

import numpy as np

from .models import OcrItem


class OnnxOcrService:
    """Thin adapter around the ONNXPaddleOcr package installed in oknikke."""

    def __init__(self, confidence_threshold: float = 0.40, enable_openvino: bool = True) -> None:
        from onnxocr.onnx_paddleocr import ONNXPaddleOcr

        logger = logging.getLogger("translatorx.ocr")
        use_openvino = bool(enable_openvino)
        logger.info("开始创建 OCR 模型，OpenVINO=%s", use_openvino)
        self._engine = ONNXPaddleOcr(
            logger=logger,
            # onnxocr defaults to ONNX Runtime in this version.  OpenVINO's
            # CPU backend is substantially faster for the repeated desktop
            # OCR workload and is available in the oknikke environment.
            use_openvino=use_openvino,
            # Do not probe the optional NPU path from the desktop worker.  The
            # oknikke machine exposes CPU/GPU plugins, but an onnxocr build
            # compiled with NPU support can still enter a native NPU probe and
            # crash during the first inference.  OpenVINO CPU remains enabled.
            use_npu=False,
            use_angle_cls=False,
            rec_batch_num=16,
            det_limit_side_len=1600,
            det_db_thresh=0.20,
            det_db_box_thresh=0.60,
            det_db_unclip_ratio=1.8,
            drop_score=0.35,
        )
        self.using_openvino = bool(
            getattr(self._engine.text_detector, "is_openvino", False)
            and getattr(self._engine.text_recognizer, "is_openvino", False)
        )
        logger.info(
            "OCR 模型创建完成：OpenVINO det=%s rec=%s",
            getattr(self._engine.text_detector, "is_openvino", False),
            getattr(self._engine.text_recognizer, "is_openvino", False),
        )
        self._confidence_threshold = confidence_threshold

    def recognize(self, image_bgr: np.ndarray) -> list[OcrItem]:
        items, _timing = self.recognize_timed(image_bgr)
        return items

    def recognize_timed(self, image_bgr: np.ndarray) -> tuple[list[OcrItem], dict[str, float]]:
        if image_bgr.size == 0:
            return [], {"det_ms": 0.0, "rec_ms": 0.0, "ocr_ms": 0.0}
        height, width = image_bgr.shape[:2]
        # Keep the detector input near a 720p-equivalent speed/accuracy point.
        # The aspect ratio is preserved, so a 1920x1080 capture becomes
        # 1280x720 for OCR while overlay coordinates still use the source size.
        analysis_scale = min(2.0, 1280.0 / max(height, width))
        analysis_image = image_bgr
        if abs(analysis_scale - 1.0) > 0.05:
            import cv2

            analysis_image = cv2.resize(
                image_bgr,
                None,
                fx=analysis_scale,
                fy=analysis_scale,
                interpolation=cv2.INTER_CUBIC if analysis_scale > 1.0 else cv2.INTER_AREA,
            )
        analysis_height, analysis_width = analysis_image.shape[:2]

        det_started = time.perf_counter()
        if not hasattr(self._engine, "text_detector") or not hasattr(self._engine, "text_recognizer"):
            result: list[Any] = self._engine.ocr(analysis_image, cls=False)
            parts = {
                "det_ms": 0.0,
                "rec_ms": 0.0,
                "ocr_ms": (time.perf_counter() - det_started) * 1000.0,
                "analysis_width": float(analysis_width),
                "analysis_height": float(analysis_height),
            }
            return self._parse_result(result, analysis_scale, parts)

        original_detector = self._engine.text_detector
        original_recognizer = self._engine.text_recognizer
        parts = {"det_ms": 0.0, "rec_ms": 0.0}

        def timed_detector(*args, **kwargs):
            started = time.perf_counter()
            try:
                return original_detector(*args, **kwargs)
            finally:
                parts["det_ms"] += (time.perf_counter() - started) * 1000.0

        def timed_recognizer(*args, **kwargs):
            started = time.perf_counter()
            try:
                return original_recognizer(*args, **kwargs)
            finally:
                parts["rec_ms"] += (time.perf_counter() - started) * 1000.0

        self._engine.text_detector = timed_detector
        self._engine.text_recognizer = timed_recognizer
        try:
            result: list[Any] = self._engine.ocr(analysis_image, cls=False)
        finally:
            self._engine.text_detector = original_detector
            self._engine.text_recognizer = original_recognizer
        parts["ocr_ms"] = (time.perf_counter() - det_started) * 1000.0
        parts["analysis_width"] = float(analysis_width)
        parts["analysis_height"] = float(analysis_height)
        return self._parse_result(result, analysis_scale, parts)

    def _parse_result(
        self,
        result: list[Any],
        analysis_scale: float,
        timing: dict[str, float],
    ) -> tuple[list[OcrItem], dict[str, float]]:
        if not result or not result[0]:
            return [], timing

        items: list[OcrItem] = []
        for raw_box, recognition in result[0]:
            text, score = recognition
            cleaned = str(text).strip()
            confidence = float(score)
            if not cleaned or confidence < self._confidence_threshold:
                continue
            box = tuple(
                (float(point[0]) / analysis_scale, float(point[1]) / analysis_scale)
                for point in raw_box
            )
            items.append(OcrItem(box=box, text=cleaned, confidence=confidence))
        return items, timing
