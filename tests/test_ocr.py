import numpy as np

from translatorx.ocr import OnnxOcrService


class FakeOcrEngine:
    def __init__(self):
        self.received_shape = None

    def ocr(self, image, cls=False):
        self.received_shape = image.shape
        return [
            [
                [
                    [[200.0, 200.0], [400.0, 200.0], [400.0, 280.0], [200.0, 280.0]],
                    ["Visible text", 0.95],
                ]
            ]
        ]


def test_small_capture_is_upscaled_and_boxes_are_mapped_back():
    service = OnnxOcrService.__new__(OnnxOcrService)
    service._engine = FakeOcrEngine()
    service._confidence_threshold = 0.4
    image = np.zeros((360, 640, 3), dtype=np.uint8)

    items = service.recognize(image)

    assert service._engine.received_shape[:2] == (720, 1280)
    assert items[0].box[0] == (100.0, 100.0)
    assert items[0].box[2] == (200.0, 140.0)
