from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
import uuid
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Any

import requests

from .models import TranslatorConfig


class TranslationError(RuntimeError):
    pass


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


def _batch_chunks(texts: list[str], max_chars: int = 1800) -> list[list[str]]:
    chunks: list[list[str]] = []
    current: list[str] = []
    current_chars = 0
    for text in texts:
        text_chars = len(text)
        if current and current_chars + text_chars > max_chars:
            chunks.append(current)
            current = []
            current_chars = 0
        current.append(text)
        current_chars += text_chars
    if current:
        chunks.append(current)
    return chunks


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
            data = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise TranslationError(f"翻译请求失败：{exc}") from exc
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
            raise TranslationError(f"腾讯翻译返回异常：{data}") from exc

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
    def translate_batch(self, texts: list[str]) -> list[str]:
        api_key = _require(self.config.credentials, "openai_api_key", "大模型 API Key")
        base_url = self.config.credentials.get("openai_base_url", "https://api.openai.com/v1").rstrip("/")
        model = _require(self.config.credentials, "openai_model", "模型名称")
        source_name = LANGUAGE_NAMES.get(self.config.source_language, self.config.source_language)
        target_name = LANGUAGE_NAMES.get(self.config.target_language, self.config.target_language)
        prompt = (
            f"把下面的 {source_name} 文本逐条翻译为{target_name}。"
            "只返回一个 JSON 字符串数组，元素数量和顺序必须与输入一致，不要解释。\n"
            + json.dumps(texts, ensure_ascii=False)
        )
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
        data = self._checked_json(
            self.session.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
                timeout=self.request_timeout(45),
            )
        )
        try:
            content = str(data["choices"][0]["message"]["content"]).strip()
            content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.IGNORECASE)
            translated = json.loads(content)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise TranslationError(f"大模型返回的内容不是有效译文数组：{data}") from exc
        if not isinstance(translated, list) or len(translated) != len(texts):
            raise TranslationError("大模型返回的译文数量与 OCR 文本数量不一致")
        return [str(item) for item in translated]


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
