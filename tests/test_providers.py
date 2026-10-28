from translatorx.providers import (
    CUSTOM_PROVIDER_KEY,
    PROVIDERS,
    get_provider,
    normalize_base_url,
    provider_for_base_url,
    provider_keys,
    provider_name,
    resolve_provider,
)


def test_every_provider_preset_has_a_unique_key_and_a_name():
    keys = provider_keys()
    assert len(keys) == len(set(keys))
    assert len(keys) == len(PROVIDERS)
    for preset in PROVIDERS:
        assert preset.name
        if preset.key != CUSTOM_PROVIDER_KEY:
            assert preset.base_url.startswith(("https://", "http://127.0.0.1", "http://localhost"))


def test_zhipu_is_reachable_and_ships_free_models():
    preset = get_provider("zhipu")
    assert preset.base_url == "https://open.bigmodel.cn/api/paas/v4"
    free = [model.model for model in preset.models if model.free]
    assert "glm-4.7-flash" in free
    assert preset.models[0].label.endswith("（免费）")


def test_volcengine_and_openai_are_offered_as_presets():
    assert get_provider("volcengine").base_url == "https://ark.cn-beijing.volces.com/api/v3"
    names = {preset.name for preset in PROVIDERS}
    assert "智谱 BigModel" in names
    assert any("火山方舟" in name for name in names)


def test_unknown_provider_key_falls_back_to_custom():
    assert get_provider("no-such-provider").key == CUSTOM_PROVIDER_KEY
    assert get_provider(None).key == CUSTOM_PROVIDER_KEY


def test_provider_for_base_url_ignores_trailing_slash_and_chat_path():
    assert provider_for_base_url("https://open.bigmodel.cn/api/paas/v4/").key == "zhipu"
    assert (
        provider_for_base_url("https://open.bigmodel.cn/api/paas/v4/chat/completions").key
        == "zhipu"
    )
    assert provider_for_base_url("https://example.test/v1").key == CUSTOM_PROVIDER_KEY
    assert provider_for_base_url("").key == CUSTOM_PROVIDER_KEY


def test_resolve_provider_prefers_the_saved_key():
    assert resolve_provider("deepseek", "https://open.bigmodel.cn/api/paas/v4").key == "deepseek"
    assert resolve_provider("", "https://api.deepseek.com/v1").key == "deepseek"
    assert resolve_provider(None, "https://api.deepseek.com/v1").key == "deepseek"


def test_normalize_base_url_strips_chat_suffix():
    assert normalize_base_url(" https://a.test/v1/chat/completions/ ") == "https://a.test/v1"
    assert normalize_base_url("https://a.test/v1/") == "https://a.test/v1"


def test_provider_name_is_human_readable():
    assert provider_name("zhipu") == "智谱 BigModel"
    assert provider_name("unknown") == "自定义（OpenAI 兼容）"

def test_local_providers_are_offered_with_loopback_urls():
    ollama = get_provider("ollama")
    assert ollama.base_url == "http://127.0.0.1:11434/v1"
    assert ollama.name == "本地 Ollama"
    lmstudio = get_provider("lmstudio")
    assert lmstudio.base_url == "http://127.0.0.1:1234/v1"
    # No preset models: the 获取模型 button reads them from the local server.
    assert ollama.models == () and lmstudio.models == ()
    assert provider_for_base_url("http://127.0.0.1:11434/v1").key == "ollama"
