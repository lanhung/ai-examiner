"""Bounded audio transport. No provider credentials or audio URLs reach clients."""

from __future__ import annotations

import base64
import io
import time
from urllib.parse import urlsplit, urlunsplit

import httpx
from mutagen.mp3 import MP3

from ..config import Settings
from ..providers.base import ProviderResult

MAX_AUDIO_BYTES = 2 * 1024 * 1024
MAX_AUDIO_SECONDS = 60
MAX_SPEECH_BYTES = 6 * 1024 * 1024
SEGMENT_CHARS = 500


class SpeechError(RuntimeError):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


def validate_recording(content: bytes) -> float:
    if not content or len(content) > MAX_AUDIO_BYTES:
        raise SpeechError("录音为空或超过 2 MB，请分段回答", 413)
    try:
        info = MP3(io.BytesIO(content)).info
        duration = info.length
        if not 0.3 <= duration <= MAX_AUDIO_SECONDS + 2:
            raise ValueError("duration")
        if info.channels != 1 or info.sample_rate != 16000:
            raise ValueError("format")
    except Exception:
        raise SpeechError("录音须为 16 kHz 单声道 MP3，长度为 0.3 至 60 秒", 422) from None
    return duration


def audio_result_url(value: str) -> str:
    parts = urlsplit(value)
    # Provider-issued OSS results only. No redirects or bearer header on downloads.
    hosts = {
        "dashscope-result-bj.oss-cn-beijing.aliyuncs.com",
        "dashscope-result-sh.oss-cn-shanghai.aliyuncs.com",
        "dashscope-result-sg.oss-ap-southeast-1.aliyuncs.com",
    }
    if (
        parts.scheme not in {"https", "http"} or parts.hostname not in hosts
        or parts.username or parts.password or parts.port not in (None, 443)
        or parts.fragment
    ):
        raise SpeechError("语音服务返回了不支持的音频地址")
    return urlunsplit(("https", parts.netloc, parts.path, parts.query, ""))


def call_speech(settings: Settings, *, operation: str, content: bytes | str) -> ProviderResult:
    started = time.monotonic()
    model = settings.wechat_asr_model if operation == "asr" else settings.wechat_tts_model
    headers = {"Authorization": f"Bearer {settings.dashscope_api_key}"}
    try:
        with httpx.Client(timeout=settings.wechat_speech_timeout_seconds, follow_redirects=False) as http:
            if operation == "asr":
                encoded = base64.b64encode(content).decode("ascii")
                result = http.post(
                    settings.dashscope_base_url.rstrip("/") + "/chat/completions",
                    headers=headers,
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": [{
                            "type": "input_audio",
                            "input_audio": {"data": "data:audio/mpeg;base64," + encoded},
                        }]}],
                        "stream": False,
                        "asr_options": {"enable_itn": False},
                    },
                )
                result.raise_for_status()
                body = result.json()
                text = body["choices"][0]["message"]["content"]
                if not isinstance(text, str) or not text.strip():
                    raise SpeechError("没有识别到有效语音，请重录或输入文字", 422)
                if len(text) > 12000:
                    raise SpeechError("识别结果过长，请分段回答", 422)
                data = {"text": text.strip()}
            else:
                result = http.post(
                    settings.wechat_tts_base_url.rstrip("/")
                    + "/services/aigc/multimodal-generation/generation",
                    headers=headers,
                    json={"model": model, "input": {
                        "text": content, "voice": settings.wechat_tts_voice,
                        "language_type": "Auto",
                    }},
                )
                result.raise_for_status()
                body = result.json()
                url = audio_result_url(body["output"]["audio"]["url"])
                audio = bytearray()
                remaining = settings.wechat_speech_timeout_seconds - (time.monotonic() - started)
                if remaining <= 0:
                    raise SpeechError("语音服务超时，请稍后重试", 504)
                with http.stream("GET", url, timeout=remaining) as download:
                    download.raise_for_status()
                    for chunk in download.iter_bytes():
                        if time.monotonic() - started > settings.wechat_speech_timeout_seconds:
                            raise SpeechError("语音下载超时，请稍后重试", 504)
                        audio.extend(chunk)
                        if len(audio) > MAX_SPEECH_BYTES:
                            raise SpeechError("题目语音过长，请使用文字题目")
                if not audio.startswith(b"RIFF") or audio[8:12] != b"WAVE":
                    raise SpeechError("语音服务返回的音频格式无效")
                data = {"audio_base64": base64.b64encode(audio).decode("ascii"), "format": "wav"}
            usage = body.get("usage") or {}
            return ProviderResult(
                data=data, provider="qwen", model=model,
                input_tokens=int(usage.get("prompt_tokens", usage.get("input_tokens", 0))),
                output_tokens=int(usage.get("completion_tokens", usage.get("output_tokens", 0))),
                latency_ms=int((time.monotonic() - started) * 1000),
            )
    except SpeechError:
        raise
    except httpx.TimeoutException:
        raise SpeechError("语音服务超时，请重试或改用文字", 504) from None
    except httpx.HTTPStatusError as exc:
        status = 429 if exc.response.status_code == 429 else 502
        raise SpeechError("语音服务暂不可用，请检查模型权限、配额或稍后重试", status) from None
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
        raise SpeechError("语音服务响应异常，请改用文字或稍后重试") from None
