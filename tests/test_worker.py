import numpy as np

from translatorx.models import OcrItem
import translatorx.worker as worker_module
from translatorx.worker import ProcessingWorker, group_translation_items, should_translate_text


def test_skips_only_isolated_latin_letters():
    for text in ("12345", "12.5%", "1,234", "A", "é", " X ", "...?!", "★ → ※"):
        assert should_translate_text(text) is False


def test_keeps_every_other_nonempty_fragment():
    for text in ("CONTINUE", "New Game", "中", "ゲーム開始", "HP恢复"):
        assert should_translate_text(text) is True


def test_groups_wrapped_sentence_but_not_menu_rows():
    sentence = [
        OcrItem(box=((100, 100), (300, 100), (300, 125), (100, 125)), text="between offense,", confidence=0.9),
        OcrItem(box=((105, 128), (295, 128), (295, 153), (105, 153)), text="defense, and mobility.", confidence=0.9),
    ]
    grouped = group_translation_items(sentence)
    assert len(grouped) == 1
    assert grouped[0].text == "between offense, defense, and mobility."

    menu = [
        OcrItem(box=((20, 100), (180, 100), (180, 125), (20, 125)), text="+:Use Item", confidence=0.9),
        OcrItem(box=((20, 130), (260, 130), (260, 155), (20, 155)), text="+:Cycle Quick Items", confidence=0.9),
    ]
    assert len(group_translation_items(menu)) == 2


def test_groups_lines_with_unclosed_english_quote_or_bracket():
    items = [
        OcrItem(box=((100, 100), (300, 100), (300, 125), (100, 125)), text='Use "Quick', confidence=0.9),
        OcrItem(box=((105, 128), (295, 128), (295, 153), (105, 153)), text='Items" here.', confidence=0.9),
    ]
    assert len(group_translation_items(items)) == 1

    bracketed = [
        OcrItem(box=((100, 100), (300, 100), (300, 125), (100, 125)), text="Effect [when", confidence=0.9),
        OcrItem(box=((105, 128), (295, 128), (295, 153), (105, 153)), text="equipped].", confidence=0.9),
    ]
    assert len(group_translation_items(bracketed)) == 1


def test_groups_lines_ending_with_question_words_without_terminal_punctuation():
    items = [
        OcrItem(box=((100, 100), (300, 100), (300, 125), (100, 125)), text="Choose where", confidence=0.9),
        OcrItem(box=((105, 128), (295, 128), (295, 153), (105, 153)), text="the item appears.", confidence=0.9),
    ]
    assert len(group_translation_items(items)) == 1

    complete = [
        OcrItem(box=((100, 100), (300, 100), (300, 125), (100, 125)), text="Where?", confidence=0.9),
        OcrItem(box=((105, 128), (295, 128), (295, 153), (105, 153)), text="Continue", confidence=0.9),
    ]
    assert len(group_translation_items(complete)) == 2


def test_groups_lines_ending_with_articles():
    for article in ("a", "an"):
        items = [
            OcrItem(box=((100, 100), (300, 100), (300, 125), (100, 125)), text=f"Choose {article}", confidence=0.9),
            OcrItem(box=((105, 128), (295, 128), (295, 153), (105, 153)), text="different item.", confidence=0.9),
        ]
        grouped = group_translation_items(items)
        assert len(grouped) == 1


def test_groups_lines_ending_with_incomplete_progressive_verbs():
    items = [
        OcrItem(box=((100, 100), (300, 100), (300, 125), (100, 125)), text="Getting", confidence=0.9),
        OcrItem(box=((105, 128), (295, 128), (295, 153), (105, 153)), text="ready.", confidence=0.9),
    ]
    assert len(group_translation_items(items)) == 1

    complete_label = [
        OcrItem(box=((100, 100), (300, 100), (300, 125), (100, 125)), text="Loading", confidence=0.9),
        OcrItem(box=((105, 128), (295, 128), (295, 153), (105, 153)), text="Continue", confidence=0.9),
    ]
    assert len(group_translation_items(complete_label)) == 2


def test_groups_left_aligned_short_wrap_after_long_article_line():
    items = [
        OcrItem(
            box=((100, 100), (700, 100), (700, 125), (100, 125)),
            text="When surrounded, use this attack to slice open a",
            confidence=0.9,
        ),
        OcrItem(
            box=((100, 128), (180, 128), (180, 153), (100, 153)),
            text="path.",
            confidence=0.9,
        ),
    ]
    grouped = group_translation_items(items)
    assert len(grouped) == 1
    assert grouped[0].text.endswith("a path.")


def test_processing_does_not_drop_items_after_the_first_sixteen(monkeypatch):
    source_items = [
        OcrItem(
            box=((0, index * 10), (100, index * 10), (100, index * 10 + 8), (0, index * 10 + 8)),
            text=f"Line {index}",
            confidence=0.99,
        )
        for index in range(24)
    ]

    class FakeOcr:
        def recognize(self, _image):
            return source_items

    class FakeTranslator:
        def translate_batch(self, texts):
            return [f"译文 {text}" for text in texts]

    monkeypatch.setattr(worker_module, "create_translator", lambda _config: FakeTranslator())
    worker = ProcessingWorker()
    worker._ocr = FakeOcr()
    completed = []
    worker.completed.connect(lambda items, width, height: completed.append((items, width, height)))

    worker.process(
        np.zeros((300, 400, 3), dtype=np.uint8),
        {"engine": "baidu", "source_language": "en", "target_language": "zh-CN", "credentials": {}},
    )

    assert len(completed[0][0]) == 24
    assert completed[0][0][-1].text == "Line 23"
