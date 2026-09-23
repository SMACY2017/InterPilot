"""Text and image requests with isolated, cancellable streams."""
import base64
import threading
from openai import OpenAI
from src.settings import load_settings


def safe_error(exc, secret=""):
    status = getattr(exc, "status_code", None)
    if status:
        return f"API 请求失败（HTTP {status}），请检查密钥、模型权限、额度和请求大小。"
    message = str(exc).replace(secret, "[已隐藏]") if secret else str(exc)
    if type(exc).__module__.startswith(("openai", "httpx", "httpcore")):
        return f"连接失败：{type(exc).__name__}，请检查网络或超时设置。"
    return message[:400]


def image_content(data, mime="image/png"):
    return {"type": "image_url", "image_url": {
        "url": f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}",
        "detail": "high"}}


class LLMClient:
    def __init__(self, api_url=None, api_key=None, model=None, settings=None, client=None):
        self.settings = settings or load_settings()
        self.model = model or self.settings.model
        self.client = client or OpenAI(
            # The SDK requires a non-empty value even when a local
            # OpenAI-compatible server does not authenticate requests.
            api_key=(api_key if api_key is not None else self.settings.api_key) or "not-required",
            base_url=api_url or self.settings.api_url,
            timeout=self.settings.timeout, max_retries=0,
        )

    def close(self):
        self.client.close()

    def list_models(self):
        return sorted(item.id for item in self.client.models.list().data)

    def get_response(self, prompt, callback=None, *, image=None, cancel=None,
                     system_prompt=None, activity_callback=None):
        cancel = cancel or threading.Event()
        if cancel.is_set():
            return ""
        content = prompt
        if image:
            content = [image_content(image), {"type": "text", "text": prompt}]
        messages = [
            {"role": "system", "content": self.settings.system_prompt if system_prompt is None else system_prompt},
            {"role": "user", "content": content},
        ]
        parts = []
        request_options = {}
        if ("siliconflow" in self.settings.api_url.lower() or
                self.settings.enable_thinking):
            extra_body = {"enable_thinking": self.settings.enable_thinking}
            if self.settings.enable_thinking:
                extra_body["thinking_budget"] = self.settings.thinking_budget
            request_options["extra_body"] = extra_body
        stream = self.client.chat.completions.create(
            model=self.model, messages=messages, stream=True,
            max_tokens=self.settings.max_tokens,
            **request_options,
        )
        try:
            for chunk in stream:
                if cancel.is_set():
                    break
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                reasoning = getattr(delta, "reasoning_content", None)
                if reasoning and activity_callback:
                    activity_callback()
                text = getattr(delta, "content", None)
                if text:
                    parts.append(text)
                    if callback:
                        callback(text)
        finally:
            stream.close()
        return "".join(parts)
