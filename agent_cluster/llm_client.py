"""
OpenAI 兼容 LLM 客户端
支持文本对话 + vision（图片理解）+ function calling（为 MCP 预留）
"""

import json
import time
from typing import Any

from openai import OpenAI

from .config import config


class LLMClient:
    """封装 OpenAI 兼容接口的轻量客户端"""

    def __init__(self):
        self._client = OpenAI(
            base_url=config.llm_base_url,
            api_key=config.llm_api_key,
        )
        self._model = config.llm_model

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------

    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        temperature: float | None = None,
    ) -> dict:
        """
        发送对话请求，返回统一格式:
        {
            "content": str | None,
            "tool_calls": list | None,
            "usage": {"prompt_tokens": int, "completion_tokens": int},
            "model": str,
            "elapsed_ms": float,
        }
        """
        t0 = time.perf_counter()
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature if temperature is not None else config.llm_temperature,
        }
        if tools:
            kwargs["tools"] = tools

        resp = self._client.chat.completions.create(**kwargs)
        elapsed = (time.perf_counter() - t0) * 1000

        choice = resp.choices[0]
        msg = choice.message

        return {
            "content": msg.content,
            "tool_calls": _serialize_tool_calls(msg.tool_calls),
            "usage": {
                "prompt_tokens": resp.usage.prompt_tokens if resp.usage else 0,
                "completion_tokens": resp.usage.completion_tokens if resp.usage else 0,
            },
            "model": resp.model,
            "elapsed_ms": round(elapsed, 1),
        }

    def chat_json(
        self,
        messages: list[dict],
        temperature: float | None = None,
    ) -> dict:
        """
        请求 LLM 返回 JSON。自动追加格式指令，并尝试解析。
        返回 {"ok": True, "data": {...}} 或 {"ok": False, "raw": str}
        """
        instructed = list(messages)
        instructed.append(
            {
                "role": "system",
                "content": "请以纯 JSON 格式回复，不要包含 markdown 代码块标记。",
            }
        )
        result = self.chat(instructed, temperature=temperature)
        raw = (result.get("content") or "").strip()

        # 移除可能包裹的 ```json ... ```
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

        try:
            return {"ok": True, "data": json.loads(raw)}
        except json.JSONDecodeError:
            return {"ok": False, "raw": raw}

    def vision_chat(
        self,
        text_prompt: str,
        image_paths: list[str],
        detail: str = "auto",
    ) -> dict:
        """
        多模态对话：传入图片路径列表 + 文本提示。
        图片通过 base64 编码后以 image_url 形式发送。
        """
        import base64
        import mimetypes

        content: list[dict] = [{"type": "text", "text": text_prompt}]

        for path in image_paths:
            mime_type = mimetypes.guess_type(path)[0] or "image/jpeg"
            with open(path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("utf-8")
            content.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{mime_type};base64,{b64}",
                        "detail": detail,
                    },
                }
            )

        messages = [{"role": "user", "content": content}]
        return self.chat(messages)


# ------------------------------------------------------------------
# 内部工具
# ------------------------------------------------------------------


def _serialize_tool_calls(tool_calls: Any) -> list[dict] | None:
    """将 OpenAI tool_calls 对象序列化为 dict 列表"""
    if not tool_calls:
        return None
    result = []
    for tc in tool_calls:
        try:
            args = json.loads(tc.function.arguments)
        except (json.JSONDecodeError, AttributeError):
            args = {}
        result.append(
            {
                "id": tc.id,
                "name": tc.function.name,
                "arguments": args,
            }
        )
    return result
