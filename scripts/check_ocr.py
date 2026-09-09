"""Release gate: real OCR inference must use OpenVINO for both models."""
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from translatorx.ocr import OnnxOcrService

image = np.full((240, 960, 3), 255, dtype=np.uint8)
cv2.putText(image, 'HELLO TRANSLATORX', (30, 140), cv2.FONT_HERSHEY_SIMPLEX,
            2, (0, 0, 0), 3, cv2.LINE_AA)
service = OnnxOcrService(enable_openvino=True)
assert service.using_openvino, 'OpenVINO detector/recognizer not active'
texts = [item.text for item in service.recognize(image)]
assert 'TRANSLATORX' in ''.join(texts).upper().replace(' ', ''), texts
print('OpenVINO OCR passed:', texts)
