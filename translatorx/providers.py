from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ModelPreset:
    """One suggested model id for a provider."""

    model: str
    free: bool = False

    @property
    def label(self) -> str:
        return f"{self.model}（免费）" if self.free else self.model


@dataclass(frozen=True, slots=True)
class ProviderPreset:
    """Everything the settings dialog needs to prefill for one 服务商."""

    key: str
    name: str
    base_url: str
    docs_url: str = ""
    docs_text: str = ""
    models: tuple[ModelPreset, ...] = ()
    note: str = ""

    @property
    def model_ids(self) -> list[str]:
        return [preset.model for preset in self.models]


CUSTOM_PROVIDER_KEY = "custom"


PROVIDERS: tuple[ProviderPreset, ...] = (
    ProviderPreset(
        key="zhipu",
        name="智谱 BigModel",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        docs_url="https://bigmodel.cn/usercenter/proj-mgmt/apikeys",
        docs_text="前往智谱开放平台申请 API Key",
        models=(
            ModelPreset("glm-4.7-flash", free=True),
            ModelPreset("glm-4-flash-250414", free=True),
            ModelPreset("glm-z1-flash", free=True),
            ModelPreset("glm-5.3-flash"),
        ),
        note=(
            "GLM-4.7-Flash 目前免费。请用『标准 API Key』——"
            "编程套餐(Coding Plan)的 Key 与标准端点不通用，会 401"
        ),
    ),
    ProviderPreset(
        key="volcengine",
        name="火山方舟（豆包）",
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        docs_url="https://console.volcengine.com/ark/region:ark+cn-beijing/apiKey",
        docs_text="前往火山方舟控制台申请 API Key",
        models=(
            ModelPreset("doubao-seed-2.0-lite"),
            ModelPreset("doubao-seed-2.0-pro"),
            ModelPreset("deepseek-v4-flash"),
            ModelPreset("deepseek-v4-pro"),
        ),
        note="模型 ID 也可以填控制台里的接入点 ID（ep- 开头），免费额度以控制台为准",
    ),
    ProviderPreset(
        key="dashscope",
        name="阿里云百炼（通义千问）",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        docs_url="https://bailian.console.aliyun.com/",
        docs_text="前往阿里云百炼控制台申请 API Key",
        models=(
            ModelPreset("qwen-flash"),
            ModelPreset("qwen-plus"),
            ModelPreset("qwen-turbo"),
        ),
        note="百炼会给新账号送免费额度，qwen-flash 单价最低",
    ),
    ProviderPreset(
        key="siliconflow",
        name="硅基流动 SiliconFlow",
        base_url="https://api.siliconflow.cn/v1",
        docs_url="https://cloud.siliconflow.cn/account/ak",
        docs_text="前往硅基流动控制台申请 API Key",
        models=(),
        note="上面的「获取模型」可以列出全部可用模型，带 Free 后缀的通常免费",
    ),
    ProviderPreset(
        key="deepseek",
        name="DeepSeek 官方",
        base_url="https://api.deepseek.com/v1",
        docs_url="https://platform.deepseek.com/api_keys",
        docs_text="前往 DeepSeek 开放平台申请 API Key",
        models=(
            ModelPreset("deepseek-chat"),
            ModelPreset("deepseek-reasoner"),
        ),
    ),
    ProviderPreset(
        key="moonshot",
        name="月之暗面 Kimi",
        base_url="https://api.moonshot.cn/v1",
        docs_url="https://platform.moonshot.cn/console/api-keys",
        docs_text="前往 Moonshot 开放平台申请 API Key",
        models=(
            ModelPreset("kimi-k3"),
            ModelPreset("kimi-k2.6"),
        ),
    ),
    ProviderPreset(
        key="spark",
        name="讯飞星火",
        base_url="https://spark-api-open.xf-yun.com/v1",
        docs_url="https://console.xfyun.cn/services/chat",
        docs_text="前往讯飞开放平台申请 API Key",
        models=(
            ModelPreset("lite"),
            ModelPreset("generalv3.5"),
            ModelPreset("4.0Ultra"),
        ),
        note="Lite 版本免费，便宜够用",
    ),
    ProviderPreset(
        key="hunyuan",
        name="腾讯混元",
        base_url="https://api.hunyuan.cloud.tencent.com/v1",
        docs_url="https://console.cloud.tencent.com/hunyuan/api-key",
        docs_text="前往腾讯云混元控制台申请 API Key",
        models=(
            ModelPreset("hunyuan-lite"),
            ModelPreset("hunyuan-turbos-latest"),
        ),
        note="hunyuan-lite 免费，额度以控制台为准",
    ),
    ProviderPreset(
        key="qianfan",
        name="百度千帆（文心）",
        base_url="https://qianfan.baidubce.com/v2",
        docs_url="https://console.bce.baidu.com/qianfan/ais/console/applicationConsole/application",
        docs_text="前往百度智能云千帆控制台申请 API Key",
        models=(
            ModelPreset("ernie-speed-128k"),
            ModelPreset("ernie-4.5-turbo-128k"),
        ),
        note="ernie-speed 系列有免费额度，模型 ID 以千帆控制台为准",
    ),
    ProviderPreset(
        key="openrouter",
        name="OpenRouter",
        base_url="https://openrouter.ai/api/v1",
        docs_url="https://openrouter.ai/keys",
        docs_text="前往 OpenRouter 申请 API Key",
        models=(),
        note="模型名后带 :free 的条目免费，可用「获取模型」查看",
    ),
    ProviderPreset(
        key="openai",
        name="OpenAI 官方",
        base_url="https://api.openai.com/v1",
        docs_url="https://platform.openai.com/api-keys",
        docs_text="前往 OpenAI 平台申请 API Key",
        models=(
            ModelPreset("gpt-4.1-mini"),
            ModelPreset("gpt-4.1"),
        ),
    ),
    ProviderPreset(
        key="ollama",
        name="本地 Ollama",
        base_url="http://127.0.0.1:11434/v1",
        docs_url="https://ollama.com/library",
        docs_text="前往 Ollama 模型库挑选模型",
        models=(),
        note="先运行 ollama serve；点「获取模型」读取本机已下载的模型，API Key 留空即可",
    ),
    ProviderPreset(
        key="lmstudio",
        name="本地 LM Studio",
        base_url="http://127.0.0.1:1234/v1",
        docs_url="https://lmstudio.ai/",
        docs_text="前往 LM Studio 官网下载",
        models=(),
        note="先在 LM Studio 里 Start Server；点「获取模型」读取已加载的模型，API Key 留空即可",
    ),
    ProviderPreset(
        key=CUSTOM_PROVIDER_KEY,
        name="自定义（OpenAI 兼容）",
        base_url="",
        note="填写任意兼容 /chat/completions 的 Base URL，本机自建服务也可以",
    ),
)


_BY_KEY = {preset.key: preset for preset in PROVIDERS}
_CUSTOM = _BY_KEY[CUSTOM_PROVIDER_KEY]


def provider_keys() -> list[str]:
    return [preset.key for preset in PROVIDERS]


def get_provider(key: str | None) -> ProviderPreset:
    """Return the preset for the given key, or the custom preset when unknown."""
    return _BY_KEY.get(str(key or "").strip(), _CUSTOM)


def provider_name(key: str | None) -> str:
    return get_provider(key).name


def normalize_base_url(base_url: str | None) -> str:
    """Normalize a Base URL so trailing slashes and chat paths do not matter."""
    base = str(base_url or "").strip().rstrip("/")
    for suffix in ("/chat/completions", "/responses"):
        if base.casefold().endswith(suffix):
            base = base[: -len(suffix)]
            break
    return base.rstrip("/")


def provider_for_base_url(base_url: str | None) -> ProviderPreset:
    """Guess the provider from a saved Base URL, used when no key was stored."""
    wanted = normalize_base_url(base_url).casefold()
    if not wanted:
        return _CUSTOM
    for preset in PROVIDERS:
        if preset.base_url and normalize_base_url(preset.base_url).casefold() == wanted:
            return preset
    # A relay in front of a provider keeps the vendor path, so compare hosts too.
    for preset in PROVIDERS:
        if preset.base_url and _host(preset.base_url) == _host(wanted):
            return preset
    return _CUSTOM


def _host(url: str) -> str:
    without_scheme = str(url or "").split("://", 1)[-1]
    return without_scheme.split("/", 1)[0].casefold()


def resolve_provider(provider_key: str | None, base_url: str | None) -> ProviderPreset:
    """Prefer the stored provider key and fall back to the Base URL."""
    key = str(provider_key or "").strip()
    if key and key in _BY_KEY:
        return _BY_KEY[key]
    return provider_for_base_url(base_url)
