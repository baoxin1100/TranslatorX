from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import time
import uuid
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import requests

from .models import TranslatorConfig


_logger = logging.getLogger("translatorx.translators")


class TranslationError(RuntimeError):
    pass


class TranslationCountError(TranslationError):
    """The model answered with a different number of items than it was given."""


LANGUAGE_NAMES = {
    "auto": "自动检测",
    "zh-CN": "简体中文",
    "zh-TW": "繁体中文",
    "en": "英语",
    "ja": "日语",
    "ko": "韩语",
}


PROVIDER_LANGUAGE_CODES = {
    "baidu": {"auto": "auto", "zh-CN": "zh", "zh-TW": "cht", "en": "en", "ja": "jp", "ko": "kor"},
    "baidu_llm": {"auto": "auto", "zh-CN": "zh", "zh-TW": "cht", "en": "en", "ja": "jp", "ko": "kor"},
    "tencent": {"auto": "auto", "zh-CN": "zh", "zh-TW": "zh-TW", "en": "en", "ja": "ja", "ko": "ko"},
}


def _batch_chunks(
    texts: list[str],
    max_chars: int = 1800,
    max_items: int | None = None,
) -> list[list[str]]:
    chunks: list[list[str]] = []
    current: list[str] = []
    current_chars = 0
    for text in texts:
        text_chars = len(text)
        full = current and (
            current_chars + text_chars > max_chars
            or (max_items is not None and len(current) >= max_items)
        )
        if full:
            chunks.append(current)
            current = []
            current_chars = 0
        current.append(text)
        current_chars += text_chars
    if current:
        chunks.append(current)
    return chunks


_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def is_ollama_base_url(base_url: str | None) -> bool:
    """True for the default Ollama port, which accepts Ollama-only fields."""
    try:
        parsed = urlparse(str(base_url or ""))
    except ValueError:
        return False
    return (parsed.hostname or "").casefold() in _LOCAL_HOSTS and parsed.port == 11434


def is_local_base_url(base_url: str | None) -> bool:
    """True for a loopback endpoint; a local server needs no API key."""
    try:
        host = urlparse(str(base_url or "")).hostname or ""
    except ValueError:
        return False
    return host.casefold() in _LOCAL_HOSTS


def _response_detail(response: requests.Response, limit: int = 240) -> str:
    """Return a short excerpt of an error body, for a readable failure message."""
    text = str(getattr(response, "text", "") or "").strip()
    if not text:
        return ""
    return f"；接口返回：{text[:limit]}"


def _looks_untranslated(source: str, result: str, target_language: str) -> bool:
    """True when a model echoed a line that clearly needed translating."""
    if str(source).strip() != str(result).strip():
        return False
    target = str(target_language or "").strip().lower()
    if target.startswith("zh"):
        return bool(re.search(r"[A-Za-z]", source))
    if target.startswith("en"):
        return bool(re.search(r"[\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af]", source))
    return False


def _translation_value(item: object, target_language: str, source: str = "") -> str:
    """Extract one translated string from a model answer element.

    Small models sometimes swap the keys ("english" holds the Chinese, "zh"
    holds the source). A candidate that is just the source text only wins when
    nothing else is available.
    """
    if isinstance(item, str):
        return item
    if item is None:
        return ""
    if isinstance(item, list):
        return " ".join(str(part) for part in item if part is not None)
    if isinstance(item, dict):
        target = str(target_language or "").strip().casefold()
        strings = [value for value in item.values() if isinstance(value, str)]
        preferred: list[str] = []
        for key, value in item.items():
            if not isinstance(value, str):
                continue
            key_text = str(key).casefold()
            if target.startswith("zh") and ("zh" in key_text or "中文" in key_text):
                preferred.append(value)
            elif target.startswith("en") and "en" in key_text:
                preferred.append(value)
            elif any(
                word in key_text
                for word in ("translation", "translated", "text", "dst", "result", "译文")
            ):
                preferred.append(value)
        candidates = preferred or strings
        translated = [value for value in candidates if value.strip() != str(source).strip()]
        chosen = translated or candidates
        return chosen[0] if chosen else str(item)
    return str(item)


def parse_translation_lines(content: str, expected: int) -> list[str] | None:
    """Fallback parser: one translation per line, no JSON at all.

    A 3B model handles "one line per item" far more reliably than a JSON array,
    and OCR lines never contain newlines themselves.
    """
    lines = [line.strip() for line in str(content or "").splitlines() if line.strip()]
    cleaned: list[str] = []
    for line in lines:
        line = re.sub(r"^\s*(?:\d+[.)、]|[-*•])\s*", "", line).strip()
        line = line.strip('"').strip("“”").strip()
        if line and not line.startswith("[") and not line.startswith("{"):
            cleaned.append(line)
    return cleaned if len(cleaned) == expected else None


def _repair_json(text: str) -> str:
    """Fix the two ways small models break their own JSON.

    qwen2.5:3b closes strings with a Chinese quote and leaves a trailing comma
    before the bracket, which makes an otherwise perfect answer unparsable.
    """
    repaired = text
    for quote in ("“", "”", "„", "‟"):
        repaired = repaired.replace(quote, '"')
    return re.sub(r",\s*([\]}])", r"\1", repaired)


def parse_translation_list(
    content: str,
    target_language: str,
    sources: list[str] | None = None,
) -> list[str] | None:
    """Parse a model answer into translated strings.

    Small local models answer with objects ({"zh": "你好"}), wrap the array in
    prose or a code fence, or nest it under a key. None means the answer is not
    a usable array at all.
    """
    text = str(content or "").strip()
    if not text:
        return None
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE).strip()
    data: object = None
    try:
        data = json.loads(text)
    except ValueError:
        repaired = _repair_json(text)
        try:
            data = json.loads(repaired)
        except ValueError:
            match = re.search(r"\[[\s\S]*\]", repaired)
            if match is None:
                return None
            try:
                data = json.loads(match.group(0))
            except ValueError:
                return None
    if isinstance(data, dict):
        for key in ("translations", "translated", "results", "result", "data", "output"):
            nested = data.get(key)
            if isinstance(nested, list):
                data = nested
                break
    if not isinstance(data, list):
        return None
    values = [item for item in data if item is not None]
    if values and all(isinstance(item, list) for item in values):
        # [[...], [...]] - one nested array per line.
        flattened: list[object] = []
        for item in values:
            flattened.extend(item)
        values = flattened
    elif len(values) == 1 and isinstance(values[0], list):
        # qwen2.5:3b answers [["a","b","c"], null, null, null]: the whole array
        # lands in the first slot and the rest is padding.
        values = values[0]
    translated = [
        _translation_value(item, target_language, sources[index] if sources and index < len(sources) else "")
        for index, item in enumerate(values)
    ]
    if any(not text.strip() or text.strip().lower() in {"none", "null"} for text in translated):
        return None
    return translated


def _require(credentials: dict[str, str], key: str, label: str) -> str:
    value = credentials.get(key, "").strip()
    if not value:
        raise TranslationError(f"请在设置中填写{label}")
    return value


class Translator(ABC):
    def __init__(self, config: TranslatorConfig, session: requests.Session | None = None) -> None:
        self.config = config
        self.session = session or requests.Session()

    def request_timeout(self, default: float) -> float:
        try:
            return max(1.0, float(self.config.credentials.get("_timeout", default)))
        except (TypeError, ValueError):
            return default

    @abstractmethod
    def translate_batch(self, texts: list[str]) -> list[str]:
        raise NotImplementedError

    def _checked_json(self, response: requests.Response) -> dict[str, Any]:
        try:
            response.raise_for_status()
        except requests.RequestException as exc:
            # Providers put the real reason in the body ("身份验证失败",
            # "model not found"), and a bare 401 leaves the user guessing.
            raise TranslationError(f"翻译请求失败：{exc}{_response_detail(response)}") from exc
        try:
            data = response.json()
        except ValueError as exc:
            raise TranslationError(f"翻译请求失败：{exc}{_response_detail(response)}") from exc
        return data


class BaiduTranslator(Translator):
    endpoint = "https://fanyi-api.baidu.com/api/trans/vip/translate"

    def _translate_one(self, text: str) -> str:
        app_id = _require(self.config.credentials, "baidu_app_id", "百度 APP ID")
        secret = _require(self.config.credentials, "baidu_secret", "百度密钥")
        salt = uuid.uuid4().hex
        sign = hashlib.md5(f"{app_id}{text}{salt}{secret}".encode("utf-8")).hexdigest()
        payload = {
            "q": text,
            "from": PROVIDER_LANGUAGE_CODES["baidu"][self.config.source_language],
            "to": PROVIDER_LANGUAGE_CODES["baidu"][self.config.target_language],
            "appid": app_id,
            "salt": salt,
            "sign": sign,
        }
        data = self._checked_json(self.session.post(self.endpoint, data=payload, timeout=self.request_timeout(20)))
        if "error_code" in data:
            raise TranslationError(f"百度翻译错误 {data['error_code']}：{data.get('error_msg', '未知错误')}")
        try:
            return "\n".join(str(item["dst"]) for item in data["trans_result"])
        except (KeyError, TypeError) as exc:
            raise TranslationError(f"百度翻译返回异常：{data}") from exc

    def translate_batch(self, texts: list[str]) -> list[str]:
        if not texts:
            return []
        app_id = _require(self.config.credentials, "baidu_app_id", "百度 APP ID")
        secret = _require(self.config.credentials, "baidu_secret", "百度密钥")
        results: list[str] = []
        for chunk in _batch_chunks(texts):
            query = "\n".join(chunk)
            salt = uuid.uuid4().hex
            sign = hashlib.md5(f"{app_id}{query}{salt}{secret}".encode("utf-8")).hexdigest()
            payload = {
                "q": query,
                "from": PROVIDER_LANGUAGE_CODES["baidu"][self.config.source_language],
                "to": PROVIDER_LANGUAGE_CODES["baidu"][self.config.target_language],
                "appid": app_id,
                "salt": salt,
                "sign": sign,
            }
            data = self._checked_json(self.session.post(self.endpoint, data=payload, timeout=self.request_timeout(20)))
            if "error_code" in data:
                raise TranslationError(f"百度翻译错误 {data['error_code']}：{data.get('error_msg', '未知错误')}")
            try:
                translated = [str(item["dst"]) for item in data["trans_result"]]
            except (KeyError, TypeError) as exc:
                raise TranslationError(f"百度翻译返回异常：{data}") from exc
            if len(translated) != len(chunk):
                # Some older accounts do not enable multi-line q; preserve correctness.
                translated = [self._translate_one(text) for text in chunk]
            results.extend(translated)
        return results


class BaiduLlmTranslator(Translator):
    endpoint = "https://fanyi-api.baidu.com/ait/api/aiTextTranslate"

    def _request(self, text: str) -> dict[str, Any]:
        app_id = _require(self.config.credentials, "baidu_app_id", "百度 APP ID")
        api_key = _require(self.config.credentials, "baidu_llm_api_key", "百度大模型翻译 API Key")
        payload: dict[str, Any] = {
            "appid": app_id,
            "q": text,
            "from": PROVIDER_LANGUAGE_CODES["baidu_llm"][self.config.source_language],
            "to": PROVIDER_LANGUAGE_CODES["baidu_llm"][self.config.target_language],
            "model_type": "llm",
        }
        reference = self.config.credentials.get("baidu_llm_reference", "").strip()
        if reference:
            payload["reference"] = reference[:500]
        data = self._checked_json(self.session.post(
            self.endpoint,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=self.request_timeout(30),
        ))
        if "error_code" in data:
            raise TranslationError(
                f"百度大模型翻译错误 {data['error_code']}：{data.get('error_msg', '未知错误')}"
            )
        return data

    def _translate_one(self, text: str) -> str:
        data = self._request(text)
        try:
            return "\n".join(str(item["dst"]) for item in data["trans_result"])
        except (KeyError, TypeError) as exc:
            raise TranslationError(f"百度大模型翻译返回异常：{data}") from exc

    def translate_batch(self, texts: list[str]) -> list[str]:
        if not texts:
            return []
        results: list[str] = []
        for chunk in _batch_chunks(texts):
            data = self._request("\n".join(chunk))
            try:
                translated = [str(item["dst"]) for item in data["trans_result"]]
            except (KeyError, TypeError) as exc:
                raise TranslationError(f"百度大模型翻译返回异常：{data}") from exc
            if len(translated) != len(chunk):
                translated = [self._translate_one(text) for text in chunk]
            results.extend(translated)
        return results


class TencentTranslator(Translator):
    endpoint = "https://tmt.tencentcloudapi.com"
    service = "tmt"
    version = "2018-03-21"

    def _authorization(
        self,
        payload: str,
        timestamp: int,
        secret_id: str,
        secret_key: str,
        action: str = "TextTranslate",
    ) -> tuple[str, str]:
        date = datetime.fromtimestamp(timestamp, UTC).strftime("%Y-%m-%d")
        canonical_headers = (
            "content-type:application/json; charset=utf-8\n"
            f"host:tmt.tencentcloudapi.com\nx-tc-action:{action.lower()}\n"
        )
        signed_headers = "content-type;host;x-tc-action"
        hashed_payload = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        canonical_request = f"POST\n/\n\n{canonical_headers}\n{signed_headers}\n{hashed_payload}"
        credential_scope = f"{date}/{self.service}/tc3_request"
        string_to_sign = (
            "TC3-HMAC-SHA256\n"
            f"{timestamp}\n{credential_scope}\n"
            f"{hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()}"
        )

        def sign(key: bytes, message: str) -> bytes:
            return hmac.new(key, message.encode("utf-8"), hashlib.sha256).digest()

        secret_date = sign(("TC3" + secret_key).encode("utf-8"), date)
        secret_service = sign(secret_date, self.service)
        secret_signing = sign(secret_service, "tc3_request")
        signature = hmac.new(secret_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
        authorization = (
            "TC3-HMAC-SHA256 "
            f"Credential={secret_id}/{credential_scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        )
        return authorization, date

    def _request(self, texts: list[str], action: str) -> dict[str, Any]:
        secret_id = _require(self.config.credentials, "tencent_secret_id", "腾讯云 SecretId")
        secret_key = _require(self.config.credentials, "tencent_secret_key", "腾讯云 SecretKey")
        region = self.config.credentials.get("tencent_region", "ap-guangzhou").strip() or "ap-guangzhou"
        payload: dict[str, Any] = {
            "Source": PROVIDER_LANGUAGE_CODES["tencent"][self.config.source_language],
            "Target": PROVIDER_LANGUAGE_CODES["tencent"][self.config.target_language],
            "ProjectId": 0,
        }
        if action == "TextTranslateBatch":
            payload["SourceTextList"] = texts
        else:
            payload["SourceText"] = texts[0]
        body = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        timestamp = int(time.time())
        authorization, _date = self._authorization(body, timestamp, secret_id, secret_key, action)
        headers = {
            "Authorization": authorization,
            "Content-Type": "application/json; charset=utf-8",
            "Host": "tmt.tencentcloudapi.com",
            "X-TC-Action": action,
            "X-TC-Version": self.version,
            "X-TC-Timestamp": str(timestamp),
            "X-TC-Region": region,
        }
        data = self._checked_json(
            self.session.post(
                self.endpoint,
                data=body.encode("utf-8"),
                headers=headers,
                timeout=self.request_timeout(20),
            )
        )
        return data.get("Response", {})

    def _translate_one(self, text: str) -> str:
        response = self._request([text], "TextTranslate")
        if "Error" in response:
            error = response["Error"]
            raise TranslationError(f"腾讯翻译错误 {error.get('Code', '')}：{error.get('Message', '')}")
        try:
            return str(response["TargetText"])
        except KeyError as exc:
            raise TranslationError(f"腾讯翻译返回异常：{response}") from exc

    def translate_batch(self, texts: list[str]) -> list[str]:
        if not texts:
            return []
        if len(texts) == 1:
            return [self._translate_one(texts[0])]
        results: list[str] = []
        for chunk in _batch_chunks(texts):
            try:
                response = self._request(chunk, "TextTranslateBatch")
                if "Error" in response:
                    error = response["Error"]
                    code = str(error.get("Code", ""))
                    if code not in {"InvalidAction", "UnsupportedOperation", "UnsupportedOperationException"}:
                        raise TranslationError(f"腾讯翻译错误 {code}：{error.get('Message', '')}")
                    translated = []
                else:
                    translated = [str(item) for item in response.get("TargetTextList", [])]
                if len(translated) != len(chunk):
                    translated = [self._translate_one(text) for text in chunk]
            except TranslationError:
                raise
            results.extend(translated)
        return results


class OpenAICompatibleTranslator(Translator):
    # Free tiers routinely answer 429 while a burst drains; one short retry is
    # the difference between "the free model does not work" and a translation.
    TRANSIENT_STATUS = frozenset({429, 500, 502, 503, 504})
    RETRY_DELAYS = (0.8, 2.0)
    # A realtime overlay cannot wait out a slow provider: the worker is
    # single-flight, so a 45 s timeout froze the whole pipeline.
    REQUEST_TIMEOUT = 20

    def _post_chat(
        self,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        response = self.session.post(
            url, headers=headers, json=payload, timeout=self.request_timeout(self.REQUEST_TIMEOUT)
        )
        for delay in self.RETRY_DELAYS:
            if response.status_code not in self.TRANSIENT_STATUS:
                break
            time.sleep(delay)
            response = self.session.post(
                url, headers=headers, json=payload, timeout=self.request_timeout(self.REQUEST_TIMEOUT)
            )
        return self._checked_json(response)

    def translate_batch(self, texts: list[str]) -> list[str]:
        if not texts:
            return []
        translated = self._translate_chunks(texts)
        echoed = [
            index
            for index, (source, result) in enumerate(zip(texts, translated, strict=True))
            if _looks_untranslated(source, result, self.config.target_language)
        ]
        if echoed and len(echoed) < len(texts):
            # A batch that mixes languages can come back unchanged - the model
            # mirrors the whole array. Asking again for only the lines it left
            # alone is reliable, and the caller caches the result.
            subset = [texts[index] for index in echoed]
            try:
                # One more attempt for the echoed lines, without the recursive
                # split: a model that echoes twice will not behave differently
                # in smaller pieces, and the retries cost real latency.
                retried = self._translate_chunks(subset)
            except TranslationError:
                retried = []
            if len(retried) == len(subset):
                for index, value in zip(echoed, retried, strict=True):
                    translated[index] = value
        return translated

    MAX_SPLIT_DEPTH = 1
    MIN_SPLIT_SIZE = 4

    def _translate_chunk(
        self,
        texts: list[str],
        base_url: str,
        api_key: str,
        model: str,
        local: bool,
        depth: int = 0,
    ) -> list[str]:
        """Translate one chunk, halving it once when the model keeps failing.

        A 10-line chunk that comes back unparsable is often fine as 5 + 5. The
        depth and size limits matter: splitting all the way down to single
        lines turned one frame into dozens of requests and stalled the overlay
        for half a minute.
        """
        try:
            return self._translate_once(texts, base_url, api_key, model, local)
        except TranslationError:
            if depth >= self.MAX_SPLIT_DEPTH or len(texts) < self.MIN_SPLIT_SIZE:
                raise
            middle = len(texts) // 2
            return self._translate_chunk(
                texts[:middle], base_url, api_key, model, local, depth + 1
            ) + self._translate_chunk(
                texts[middle:], base_url, api_key, model, local, depth + 1
            )

    EXAMPLES = {
        "zh-CN": ('["Hello","Settings"]', '["你好","设置"]'),
        "zh-TW": ('["Hello","Settings"]', '["你好","設定"]'),
        "en": ('["你好","设置"]', '["Hello","Settings"]'),
        "ja": ('["Hello","Settings"]', '["こんにちは","設定"]'),
        "ko": ('["Hello","Settings"]', '["안녕하세요","설정"]'),
    }

    def _prompt_for(
        self,
        texts: list[str],
        source_name: str,
        target_name: str,
        stage: int,
    ) -> str:
        if stage == 2:
            return (
                f"把下面 JSON 数组里的每条文本翻译成{target_name}，按原顺序每行输出一条译文。"
                "不要编号，不要 JSON，不要引号，不要解释，只输出译文本身。\n"
                + json.dumps(texts, ensure_ascii=False)
            )
        strict = stage == 1
        if not strict:
            return (
                f"把下面的 {source_name} 文本逐条翻译为{target_name}。"
                f"已经是{target_name}的条目原样返回；其他语言必须翻译，不要保留原文。"
                "只返回一个 JSON 字符串数组，元素数量和顺序必须与输入一致，不要解释。\n"
                + json.dumps(texts, ensure_ascii=False)
            )
        # A second, stricter attempt for the models that answer with objects or
        # wrap the array in prose; the worked example does most of the work.
        example_in, example_out = self.EXAMPLES.get(
            self.config.target_language, ('["Hello","Settings"]', '["你好","设置"]')
        )
        return (
            f"你是实时屏幕翻译器。把下面 JSON 数组里的每条文本翻译成{target_name}。\n"
            "要求：\n"
            "1. 只输出一个 JSON 字符串数组，长度必须与输入相同，顺序一致。\n"
            "2. 数组元素只能是字符串，不能是对象、注释或解释。\n"
            f"3. 已经是{target_name}的条目原样返回。\n"
            f"4. 例如：输入 {example_in} 输出 {example_out}。\n"
            "输入：" + json.dumps(texts, ensure_ascii=False)
        )

    # A local model needs roughly 2 s to load and ~0.16 s per line, so one big
    # request leaves the overlay empty for seconds. Small chunks let the first
    # lines appear while the rest is still being generated.
    LOCAL_MAX_ITEMS = 10
    REMOTE_MAX_ITEMS = 40

    def _translate_chunks(self, texts: list[str]) -> list[str]:
        base_url = self.config.credentials.get("openai_base_url", "https://api.openai.com/v1").rstrip("/")
        api_key = str(self.config.credentials.get("openai_api_key", "")).strip()
        local = is_local_base_url(base_url)
        if not api_key and not local:
            raise TranslationError("请在设置中填写大模型 API Key")
        model = _require(self.config.credentials, "openai_model", "模型名称")
        limit = self.LOCAL_MAX_ITEMS if local else self.REMOTE_MAX_ITEMS
        chunks = _batch_chunks(texts, max_chars=1800, max_items=limit)
        results: list[str] = []
        last_error: TranslationError | None = None
        failed = 0
        for chunk in chunks:
            try:
                results.extend(
                    self._translate_chunk(chunk, base_url, api_key, model, local)
                )
            except TranslationError as exc:
                # One stubborn chunk must not blank the whole frame: the lines
                # it covers stay untranslated and are retried on the next
                # capture, while the other chunks are shown right away.
                _logger.warning("本块翻译失败，留待下一帧重试：%s", exc)
                last_error = exc
                failed += 1
                results.extend([""] * len(chunk))
        if failed and failed == len(chunks) and last_error is not None:
            raise last_error
        return results

    def _translate_once(
        self,
        texts: list[str],
        base_url: str,
        api_key: str,
        model: str,
        local: bool,
        stage: int = 0,
    ) -> list[str]:
        source_name = LANGUAGE_NAMES.get(self.config.source_language, self.config.source_language)
        target_name = LANGUAGE_NAMES.get(self.config.target_language, self.config.target_language)
        prompt = self._prompt_for(texts, source_name, target_name, stage)
        payload = {
            "model": model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": "你是实时屏幕翻译器，准确简洁地翻译文本。"},
                {"role": "user", "content": prompt},
            ],
        }
        # DeepSeek enables thinking by default. Identify it by model name so
        # OpenAI-compatible relay endpoints are handled the same way.
        model_name = model.casefold().replace("_", "-")
        if model_name.startswith("deepseek"):
            payload["thinking"] = {"type": "disabled"}
        elif model_name.startswith("kimi-k2.6"):
            payload["thinking"] = {"type": "disabled"}
        elif model_name.startswith("kimi-k3"):
            payload["reasoning_effort"] = "low"
        elif re.match(r"glm-(?:[5-9](?:\.\d+)?|4\.[5-9])(?:$|[-.])", model_name):
            payload["thinking"] = {"type": "disabled"}
        elif model_name.startswith("minimax-m3"):
            payload["reasoning"] = {"effort": "none"}
        if local:
            # Ollama unloads an idle model after 5 minutes; keeping it resident
            # removes the ~2 s reload from the next translation.
            payload["keep_alive"] = "60m"
        if is_ollama_base_url(base_url):
            # Grammar-constrained decoding: qwen2.5:3b otherwise mixes curly
            # quotes and trailing commas into its answer.
            payload["format"] = "json"
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        data = self._post_chat(f"{base_url}/chat/completions", headers, payload)
        try:
            content = str(data["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as exc:
            raise TranslationError(f"大模型返回的内容不是有效译文数组：{data}") from exc
        translated = parse_translation_list(content, self.config.target_language, texts)
        if translated is None or len(translated) != len(texts):
            if stage == 1 and len(texts) <= 1:
                # A single line cannot be told apart from prose, so the line
                # fallback would happily accept "抱歉，我无法完成".
                if translated is not None:
                    raise TranslationCountError("大模型返回的译文数量与 OCR 文本数量不一致")
                raise TranslationError(
                    f"大模型返回的内容不是有效译文数组：{content.strip()[:200]}"
                )
            if stage < 2:
                # Stage 1 repeats the request with a worked example; stage 2
                # asks for plain lines, which a 3B model can follow even when it
                # keeps mangling its JSON.
                return self._translate_once(texts, base_url, api_key, model, local, stage + 1)
            lines = parse_translation_lines(content, len(texts))
            if lines is not None:
                return lines
            if translated is not None:
                raise TranslationCountError("大模型返回的译文数量与 OCR 文本数量不一致")
            raise TranslationError(
                f"大模型返回的内容不是有效译文数组：{content.strip()[:200]}"
            )
        return translated


def create_translator(config: TranslatorConfig, session: requests.Session | None = None) -> Translator:
    classes: dict[str, type[Translator]] = {
        "baidu": BaiduTranslator,
        "baidu_llm": BaiduLlmTranslator,
        "tencent": TencentTranslator,
        "openai": OpenAICompatibleTranslator,
    }
    try:
        return classes[config.engine](config, session=session)
    except KeyError as exc:
        raise TranslationError(f"不支持的翻译引擎：{config.engine}") from exc