import hashlib

from translatorx.models import TranslatorConfig
from translatorx.translators import (
    BaiduLlmTranslator,
    BaiduTranslator,
    OpenAICompatibleTranslator,
    TencentTranslator,
    TranslationError,
    create_translator,
)


class FakeResponse:
    def __init__(self, data, status_code=200):
        self._data = data
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self._data


class FakeSession:
    def __init__(self, response, status_code=200):
        self.response = response
        self.status_code = status_code
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return FakeResponse(self.response, self.status_code)

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return FakeResponse(self.response, self.status_code)


def config(engine, credentials):
    return TranslatorConfig(engine, "auto", "zh-CN", credentials)


def test_baidu_signature_uses_unescaped_source_text():
    session = FakeSession({"trans_result": [{"dst": "你好"}]})
    translator = BaiduTranslator(config("baidu", {"baidu_app_id": "app", "baidu_secret": "secret"}), session)
    assert translator.translate_batch(["hello world"]) == ["你好"]
    _, kwargs = session.calls[0]
    payload = kwargs["data"]
    expected = hashlib.md5(f"apphello world{payload['salt']}secret".encode()).hexdigest()
    assert payload["sign"] == expected


def test_baidu_batch_joins_lines_in_one_request():
    session = FakeSession({"trans_result": [{"dst": "你好"}, {"dst": "世界"}]})
    translator = BaiduTranslator(config("baidu", {"baidu_app_id": "app", "baidu_secret": "secret"}), session)
    assert translator.translate_batch(["hello", "world"]) == ["你好", "世界"]
    assert len(session.calls) == 1
    assert session.calls[0][1]["data"]["q"] == "hello\nworld"


def test_baidu_llm_uses_bearer_api_key_and_llm_model():
    session = FakeSession({"from": "en", "to": "zh", "trans_result": [{"src": "hello", "dst": "你好"}]})
    translator = BaiduLlmTranslator(config("baidu_llm", {
        "baidu_app_id": "app",
        "baidu_llm_api_key": "api-key",
        "baidu_llm_reference": "使用游戏界面风格",
    }), session)

    assert translator.translate_batch(["hello"]) == ["你好"]
    url, kwargs = session.calls[0]
    assert url == "https://fanyi-api.baidu.com/ait/api/aiTextTranslate"
    assert kwargs["headers"]["Authorization"] == "Bearer api-key"
    assert kwargs["json"] == {
        "appid": "app",
        "q": "hello",
        "from": "auto",
        "to": "zh",
        "model_type": "llm",
        "reference": "使用游戏界面风格",
    }


def test_baidu_llm_reports_api_errors():
    session = FakeSession({"error_code": "54001", "error_msg": "token错误"})
    translator = BaiduLlmTranslator(config("baidu_llm", {
        "baidu_app_id": "app",
        "baidu_llm_api_key": "bad-key",
    }), session)

    try:
        translator.translate_batch(["hello"])
    except TranslationError as exc:
        assert "54001" in str(exc)
        assert "token错误" in str(exc)
    else:
        raise AssertionError("expected TranslationError")


def test_baidu_llm_is_available_from_factory():
    translator = create_translator(config("baidu_llm", {
        "baidu_app_id": "app",
        "baidu_llm_api_key": "api-key",
    }), FakeSession({"trans_result": []}))
    assert isinstance(translator, BaiduLlmTranslator)


def test_openai_compatible_parses_json_array():
    session = FakeSession({"choices": [{"message": {"content": "```json\n[\"你好\"]\n```"}}]})
    translator = OpenAICompatibleTranslator(
        config("openai", {"openai_api_key": "key", "openai_base_url": "http://localhost:8000/v1", "openai_model": "model"}),
        session,
    )
    assert translator.translate_batch(["hello"]) == ["你好"]
    assert session.calls[0][0] == "http://localhost:8000/v1/chat/completions"


def test_deepseek_translation_disables_thinking_mode():
    session = FakeSession({"choices": [{"message": {"content": '["你好"]'}}]})
    translator = OpenAICompatibleTranslator(
        config("openai", {
            "openai_api_key": "key",
            "openai_base_url": "https://api.deepseek.com/v1",
            "openai_model": "deepseek-chat",
        }),
        session,
    )
    assert translator.translate_batch(["hello"]) == ["你好"]
    assert session.calls[0][1]["json"]["thinking"] == {"type": "disabled"}


def test_deepseek_relay_uses_model_name_to_disable_thinking():
    session = FakeSession({"choices": [{"message": {"content": '["你好"]'}}]})
    translator = OpenAICompatibleTranslator(
        config("openai", {
            "openai_api_key": "key",
            "openai_base_url": "https://relay.example/v1",
            "openai_model": "deepseek-v3",
        }),
        session,
    )
    assert translator.translate_batch(["hello"]) == ["你好"]
    assert session.calls[0][1]["json"]["thinking"] == {"type": "disabled"}


def test_kimi_k26_translation_disables_thinking_mode():
    session = FakeSession({"choices": [{"message": {"content": '["你好"]'}}]})
    translator = OpenAICompatibleTranslator(
        config("openai", {
            "openai_api_key": "key",
            "openai_base_url": "https://api.moonshot.cn/v1",
            "openai_model": "kimi-k2.6",
        }),
        session,
    )
    assert translator.translate_batch(["hello"]) == ["你好"]
    assert session.calls[0][1]["json"]["thinking"] == {"type": "disabled"}


def test_kimi_k3_translation_uses_low_reasoning_effort():
    session = FakeSession({"choices": [{"message": {"content": '["你好"]'}}]})
    translator = OpenAICompatibleTranslator(
        config("openai", {
            "openai_api_key": "key",
            "openai_base_url": "https://api.moonshot.cn/v1",
            "openai_model": "kimi-k3",
        }),
        session,
    )
    assert translator.translate_batch(["hello"]) == ["你好"]
    assert session.calls[0][1]["json"]["reasoning_effort"] == "low"


def test_glm_45_translation_disables_thinking_mode():
    session = FakeSession({"choices": [{"message": {"content": '["你好"]'}}]})
    translator = OpenAICompatibleTranslator(
        config("openai", {
            "openai_api_key": "key",
            "openai_base_url": "https://open.bigmodel.cn/api/paas/v4",
            "openai_model": "glm-4.5-flash",
        }),
        session,
    )
    assert translator.translate_batch(["hello"]) == ["你好"]
    assert session.calls[0][1]["json"]["thinking"] == {"type": "disabled"}


def test_minimax_m3_translation_disables_reasoning():
    session = FakeSession({"choices": [{"message": {"content": '["你好"]'}}]})
    translator = OpenAICompatibleTranslator(
        config("openai", {
            "openai_api_key": "key",
            "openai_base_url": "https://api.minimax.cn/v1",
            "openai_model": "MiniMax-M3",
        }),
        session,
    )
    assert translator.translate_batch(["hello"]) == ["你好"]
    assert session.calls[0][1]["json"]["reasoning"] == {"effort": "none"}


def test_tencent_request_uses_tc3_headers():
    session = FakeSession({"Response": {"TargetText": "你好", "RequestId": "request"}})
    translator = TencentTranslator(config("tencent", {"tencent_secret_id": "id", "tencent_secret_key": "key", "tencent_region": "ap-guangzhou"}), session)
    assert translator.translate_batch(["hello"]) == ["你好"]
    _, kwargs = session.calls[0]
    assert kwargs["headers"]["X-TC-Action"] == "TextTranslate"
    assert kwargs["headers"]["Authorization"].startswith("TC3-HMAC-SHA256 Credential=id/")


def test_tencent_batch_uses_source_text_list():
    session = FakeSession({"Response": {"TargetTextList": ["你好", "世界"]}})
    translator = TencentTranslator(config("tencent", {"tencent_secret_id": "id", "tencent_secret_key": "key"}), session)
    assert translator.translate_batch(["hello", "world"]) == ["你好", "世界"]
    assert len(session.calls) == 1
    _, kwargs = session.calls[0]
    assert kwargs["headers"]["X-TC-Action"] == "TextTranslateBatch"
    assert '"SourceTextList":["hello","world"]' in kwargs["data"].decode("utf-8")
