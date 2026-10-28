import hashlib
import json as json_module

from translatorx.models import TranslatorConfig
from translatorx.translators import (
    BaiduLlmTranslator,
    BaiduTranslator,
    OpenAICompatibleTranslator,
    TencentTranslator,
    TranslationCountError,
    TranslationError,
    _batch_chunks,
    create_translator,
    parse_translation_list,
    is_local_base_url,
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


def _request_batch(payload):
    """The texts a fake provider was asked to translate."""
    content = payload["messages"][-1]["content"]
    tail = content.rsplit("输入：", 1)[-1] if "输入：" in content else content.rsplit("\n", 1)[-1]
    return json_module.loads(tail.strip())

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

def test_openai_compatible_retries_a_transient_rate_limit(monkeypatch):
    calls = []

    class RetrySession:
        def post(self, url, **kwargs):
            calls.append(url)
            if len(calls) == 1:
                return FakeResponse({"error": "rate limited"}, status_code=429)
            return FakeResponse({"choices": [{"message": {"content": "[\"你好\"]"}}]})

    monkeypatch.setattr("translatorx.translators.time.sleep", lambda _seconds: None)
    translator = OpenAICompatibleTranslator(
        config("openai", {"openai_api_key": "key", "openai_base_url": "https://api.deepseek.com/v1", "openai_model": "deepseek-chat"}),
        RetrySession(),
    )
    assert translator.translate_batch(["hello"]) == ["你好"]
    assert len(calls) == 2

def test_zhipu_preset_free_model_disables_thinking():
    from translatorx.providers import get_provider

    preset = get_provider("zhipu")
    free_model = next(model for model in preset.models if model.free)
    session = FakeSession({"choices": [{"message": {"content": '["你好"]'}}]})
    translator = OpenAICompatibleTranslator(
        config("openai", {
            "openai_api_key": "key",
            "openai_base_url": preset.base_url,
            "openai_model": free_model.model,
        }),
        session,
    )

    assert translator.translate_batch(["hello"]) == ["你好"]
    assert session.calls[0][0] == "https://open.bigmodel.cn/api/paas/v4/chat/completions"
    assert session.calls[0][1]["json"]["thinking"] == {"type": "disabled"}

def test_http_error_message_includes_the_provider_body():
    class UnauthorizedResponse(FakeResponse):
        text = '{"error":{"code":"1000","message":"身份验证失败"}}'

    class UnauthorizedSession:
        def post(self, url, **kwargs):
            return UnauthorizedResponse({"error": {"code": "1000"}}, status_code=401)

    translator = OpenAICompatibleTranslator(
        config("openai", {
            "openai_api_key": "bad-key",
            "openai_base_url": "https://open.bigmodel.cn/api/paas/v4",
            "openai_model": "glm-4.7-flash",
        }),
        UnauthorizedSession(),
    )

    try:
        translator.translate_batch(["hello"])
    except TranslationError as exc:
        message = str(exc)
    else:
        raise AssertionError("expected TranslationError")

    assert "401" in message
    assert "身份验证失败" in message

def test_batch_echo_is_retried_for_the_untranslated_lines():
    class EchoThenTranslate:
        def __init__(self):
            self.calls = 0

        def post(self, url, **kwargs):
            self.calls += 1
            batch = _request_batch(kwargs["json"])
            if self.calls == 1:
                content = json_module.dumps(batch, ensure_ascii=False)
            else:
                content = json_module.dumps([f"译:{item}" for item in batch], ensure_ascii=False)
            return FakeResponse({"choices": [{"message": {"content": content}}]})

    session = EchoThenTranslate()
    translator = OpenAICompatibleTranslator(
        config("openai", {
            "openai_api_key": "key",
            "openai_base_url": "https://open.bigmodel.cn/api/paas/v4",
            "openai_model": "glm-4.7-flash",
        }),
        session,
    )

    # Only the English line needed translating; the Chinese one legitimately
    # comes back unchanged and must not trigger another request by itself.
    assert translator.translate_batch(["Settings", "打开设置"]) == ["译:Settings", "打开设置"]
    assert session.calls == 2


def test_a_translated_batch_is_not_requested_twice():
    session = FakeSession({"choices": [{"message": {"content": "[\"设置\"]"}}]})
    translator = OpenAICompatibleTranslator(
        config("openai", {
            "openai_api_key": "key",
            "openai_base_url": "https://open.bigmodel.cn/api/paas/v4",
            "openai_model": "glm-4.7-flash",
        }),
        session,
    )

    assert translator.translate_batch(["Settings"]) == ["设置"]
    assert len(session.calls) == 1

def test_a_miscounted_batch_is_split_until_the_model_answers_correctly():
    class CountDroppingSession:
        def __init__(self):
            self.calls = []

        def post(self, url, **kwargs):
            batch = _request_batch(kwargs["json"])
            self.calls.append(len(batch))
            # A small model that drops the tail of a long array.
            kept = batch[:6] if len(batch) > 6 else batch
            return FakeResponse({"choices": [{"message": {"content": json_module.dumps(
                [f"译:{item}" for item in kept], ensure_ascii=False
            )}}]})

    session = CountDroppingSession()
    translator = OpenAICompatibleTranslator(
        config("openai", {
            "openai_api_key": "key",
            "openai_base_url": "https://open.bigmodel.cn/api/paas/v4",
            "openai_model": "local-model",
        }),
        session,
    )
    texts = [f"line {index}" for index in range(12)]
    assert translator.translate_batch(texts) == [f"译:{text}" for text in texts]
    # The 12-line chunk fails through all three prompts, so the batch is split
    # once into 6 + 6 instead of cascading down to single lines.
    assert max(session.calls) == 12
    assert 6 in session.calls


def test_translation_count_error_is_raised_for_a_single_line():
    class AlwaysMiscounts:
        def post(self, url, **kwargs):
            return FakeResponse({"choices": [{"message": {"content": "[]"}}]})

    translator = OpenAICompatibleTranslator(
        config("openai", {
            "openai_api_key": "key",
            "openai_base_url": "http://127.0.0.1:11434/v1",
            "openai_model": "local-model",
        }),
        AlwaysMiscounts(),
    )
    try:
        translator.translate_batch(["only line"])
    except TranslationCountError as exc:
        assert "数量" in str(exc)
    else:
        raise AssertionError("expected TranslationCountError")

def test_local_endpoint_needs_no_api_key():
    session = FakeSession({"choices": [{"message": {"content": "[\"你好\"]"}}]})
    translator = OpenAICompatibleTranslator(
        config("openai", {
            "openai_api_key": "",
            "openai_base_url": "http://127.0.0.1:11434/v1",
            "openai_model": "qwen2.5:7b",
        }),
        session,
    )

    assert translator.translate_batch(["hello"]) == ["你好"]
    # No Authorization header is sent to a local server.
    assert "Authorization" not in session.calls[0][1]["headers"]


def test_remote_endpoint_still_requires_a_key():
    translator = OpenAICompatibleTranslator(
        config("openai", {
            "openai_api_key": "",
            "openai_base_url": "https://api.deepseek.com/v1",
            "openai_model": "deepseek-chat",
        }),
        FakeSession({"choices": [{"message": {"content": "[]"}}]}),
    )

    try:
        translator.translate_batch(["hello"])
    except TranslationError as exc:
        assert "API Key" in str(exc)
    else:
        raise AssertionError("expected TranslationError")


def test_local_url_detection():
    assert is_local_base_url("http://127.0.0.1:11434/v1")
    assert is_local_base_url("http://localhost:1234/v1")
    assert not is_local_base_url("https://open.bigmodel.cn/api/paas/v4")
    assert not is_local_base_url("")

def test_translation_parser_accepts_plain_arrays():
    assert parse_translation_list('["你好", "设置"]', "zh-CN") == ["你好", "设置"]


def test_translation_parser_accepts_object_rows_from_small_models():
    # qwen2.5:3b answers [{"zh": "你好"}, {"en": "Hello"}] instead of strings.
    parsed = parse_translation_list('[{"zh": "你好"}, {"en": "Hello"}]', "zh-CN")
    assert parsed == ["你好", "Hello"]
    assert parse_translation_list('[{"translation": "设置"}]', "zh-CN") == ["设置"]
    assert parse_translation_list('[{"a": "一", "b": "二"}]', "zh-CN") == ["一"]


def test_translation_parser_strips_code_fences_and_prose():
    fence = chr(96) * 3
    fenced = fence + "json\n" + '["你好"]' + "\n" + fence
    assert parse_translation_list(fenced, "zh-CN") == ["你好"]
    assert parse_translation_list('结果如下：\n["你好"]\n以上。', "zh-CN") == ["你好"]
    assert parse_translation_list('{"translations": ["你好", "设置"]}', "zh-CN") == ["你好", "设置"]


def test_translation_parser_rejects_unusable_answers():
    assert parse_translation_list("我不知道", "zh-CN") is None
    assert parse_translation_list("", "zh-CN") is None
    assert parse_translation_list('{"a": 1}', "zh-CN") is None


def test_object_rows_are_understood_without_a_second_request():
    class ObjectsOnly:
        def __init__(self):
            self.calls = 0

        def post(self, url, **kwargs):
            self.calls += 1
            batch = _request_batch(kwargs["json"])
            content = json_module.dumps([{"zh": item} for item in batch], ensure_ascii=False)
            return FakeResponse({"choices": [{"message": {"content": content}}]})

    session = ObjectsOnly()
    translator = OpenAICompatibleTranslator(
        config("openai", {
            "openai_api_key": "key",
            "openai_base_url": "http://127.0.0.1:11434/v1",
            "openai_model": "qwen2.5:3b",
        }),
        session,
    )

    assert translator.translate_batch(["Hello", "Settings"]) == ["Hello", "Settings"]
    assert session.calls == 1


def test_a_count_mismatch_escalates_to_the_strict_prompt():
    class WrongCount:
        def __init__(self):
            self.calls = 0

        def post(self, url, **kwargs):
            self.calls += 1
            if self.calls == 1:
                content = json_module.dumps(["一", "二", "三"], ensure_ascii=False)
            else:
                content = json_module.dumps(["译"], ensure_ascii=False)
            return FakeResponse({"choices": [{"message": {"content": content}}]})

    session = WrongCount()
    translator = OpenAICompatibleTranslator(
        config("openai", {
            "openai_api_key": "key",
            "openai_base_url": "http://127.0.0.1:11434/v1",
            "openai_model": "qwen2.5:3b",
        }),
        session,
    )

    assert translator.translate_batch(["Hello"]) == ["译"]
    assert session.calls == 2


def test_an_unparsable_answer_raises_after_the_strict_retry():
    class NeverJson:
        def __init__(self):
            self.calls = 0

        def post(self, url, **kwargs):
            self.calls += 1
            return FakeResponse({"choices": [{"message": {"content": "抱歉，我无法完成"}}]})

    session = NeverJson()
    translator = OpenAICompatibleTranslator(
        config("openai", {
            "openai_api_key": "key",
            "openai_base_url": "http://127.0.0.1:11434/v1",
            "openai_model": "qwen2.5:3b",
        }),
        session,
    )

    try:
        translator.translate_batch(["Hello"])
    except TranslationError as exc:
        assert "有效译文数组" in str(exc)
    else:
        raise AssertionError("expected TranslationError")
    assert session.calls == 2

def test_translation_parser_flattens_a_nested_padded_answer():
    # qwen2.5:3b answered [["设置","已安装的模组"], null, null].
    assert parse_translation_list('[["设置", "已安装的模组"], null, null]', "zh-CN") == [
        "设置",
        "已安装的模组",
    ]
    assert parse_translation_list('[[\"设置\"], [\"已安装的模组\"]]', "zh-CN") == [
        "设置",
        "已安装的模组",
    ]
    assert parse_translation_list('["设置", null, ""]', "zh-CN") is None

def test_chunks_respect_the_item_limit():
    texts = [f"line {index}" for index in range(25)]
    chunks = _batch_chunks(texts, max_chars=1800, max_items=10)
    assert [len(chunk) for chunk in chunks] == [10, 10, 5]
    assert sum(chunks, []) == texts


def test_local_endpoint_sends_keep_alive_and_smaller_chunks():
    class Recording:
        def __init__(self):
            self.payloads = []

        def post(self, url, **kwargs):
            batch = _request_batch(kwargs["json"])
            self.payloads.append(kwargs["json"])
            content = json_module.dumps([f"译:{item}" for item in batch], ensure_ascii=False)
            return FakeResponse({"choices": [{"message": {"content": content}}]})

    session = Recording()
    translator = OpenAICompatibleTranslator(
        config("openai", {
            "openai_api_key": "",
            "openai_base_url": "http://127.0.0.1:11434/v1",
            "openai_model": "qwen2.5:3b",
        }),
        session,
    )
    texts = [f"line {index}" for index in range(15)]

    assert translator.translate_batch(texts) == [f"译:{text}" for text in texts]
    # 15 lines are sent as two chunks so the first lines render sooner.
    assert len(session.payloads) == 2
    assert all(payload.get("keep_alive") == "60m" for payload in session.payloads)


def test_remote_endpoint_sends_no_keep_alive():
    session = FakeSession({"choices": [{"message": {"content": "[\"你好\"]"}}]})
    translator = OpenAICompatibleTranslator(
        config("openai", {
            "openai_api_key": "key",
            "openai_base_url": "https://open.bigmodel.cn/api/paas/v4",
            "openai_model": "glm-4.7-flash",
        }),
        session,
    )

    assert translator.translate_batch(["Hello"]) == ["你好"]
    assert "keep_alive" not in session.calls[0][1]["json"]

def test_translation_parser_repairs_curly_quotes_and_trailing_commas():
    # qwen2.5:3b closes strings with a Chinese quote and leaves a trailing comma.
    broken = '[{"en": "hide settings", "zh": "隐藏设置。”}, {"en": "next", "zh": "下一个"}, ]'
    assert parse_translation_list(broken, "zh-CN", ["hide settings", "next"]) == ["隐藏设置。", "下一个"]


def test_ollama_requests_ask_for_json_mode():
    session = FakeSession({"choices": [{"message": {"content": "[\"你好\"]"}}]})
    translator = OpenAICompatibleTranslator(
        config("openai", {
            "openai_api_key": "",
            "openai_base_url": "http://127.0.0.1:11434/v1",
            "openai_model": "qwen2.5:3b",
        }),
        session,
    )

    assert translator.translate_batch(["Hello"]) == ["你好"]
    payload = session.calls[0][1]["json"]
    assert payload["format"] == "json"
    assert payload["keep_alive"] == "60m"


def test_other_local_servers_do_not_get_ollama_only_fields():
    session = FakeSession({"choices": [{"message": {"content": "[\"你好\"]"}}]})
    translator = OpenAICompatibleTranslator(
        config("openai", {
            "openai_api_key": "x",
            "openai_base_url": "http://127.0.0.1:1234/v1",
            "openai_model": "local-model",
        }),
        session,
    )

    assert translator.translate_batch(["Hello"]) == ["你好"]
    payload = session.calls[0][1]["json"]
    assert "format" not in payload
    assert payload["keep_alive"] == "60m"