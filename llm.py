"""
agent_core — LLM 调用抽象

定义 LLMProvider 抽象接口，内置 OpenAI 兼容协议的实现。
业务层可实现自定义 Provider 对接其他协议（Anthropic / Google 等）。
"""

import asyncio
import json
from abc import ABC, abstractmethod
from typing import Any, Optional

import httpx

from .config import LLMConfig
from .schema import ChatResult, ToolCall


class LLMProvider(ABC):
    """LLM 调用抽象接口"""

    @abstractmethod
    async def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> ChatResult:
        """调用 LLM，返回响应"""
        ...


class OpenAILLM(LLMProvider):
    """OpenAI 兼容协议实现（vLLM / Ollama / 天池 / OpenAI 等）"""

    def __init__(
        self,
        config: Optional[LLMConfig] = None,
        base_url: str = "",
        api_key: str = "",
        model: str = "",
        timeout: int = 120,
    ):
        if config:
            cfg = config
        else:
            cfg = LLMConfig(
                base_url=base_url,
                api_key=api_key,
                model=model,
                timeout=timeout,
            )
        self.base_url = cfg.base_url.rstrip("/")
        self.api_key = cfg.api_key
        self.model = cfg.model
        self.timeout = cfg.timeout
        self.max_retries = cfg.max_retries
        self.proxy = cfg.proxy

    async def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> ChatResult:
        """调用 OpenAI 兼容 API（支持重试和代理）"""
        body: dict[str, Any] = {"model": self.model, "messages": messages}
        if tools:
            body["tools"] = tools

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        client_kwargs: dict[str, Any] = {"timeout": self.timeout}
        if self.proxy:
            client_kwargs["proxies"] = self.proxy

        last_exc = None
        for attempt in range(max(1, self.max_retries + 1)):
            try:
                async with httpx.AsyncClient(**client_kwargs) as client:
                    resp = await client.post(
                        f"{self.base_url}/chat/completions",
                        json=body,
                        headers=headers,
                    )
                    if resp.status_code >= 400:
                        body_text = resp.text[:500]
                        raise RuntimeError(
                            f"LLM API 错误 ({resp.status_code}): {body_text}"
                        )
                    data = resp.json()
                    break  # success
            except (httpx.RequestError, RuntimeError) as e:
                if attempt < self.max_retries:
                    await asyncio.sleep(1 * (attempt + 1))  # 退避
                    last_exc = e
                    continue
                raise e from last_exc

        choice = data["choices"][0]["message"]  # type: ignore[possibly-undefined]
        content = choice.get("content", "") or ""

        usage = data.get("usage", {})  # type: ignore[possibly-undefined]
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)

        raw_calls = choice.get("tool_calls")

        tool_calls = None
        if raw_calls:
            tool_calls = []
            for tc in raw_calls:
                try:
                    args = json.loads(tc["function"]["arguments"])
                except json.JSONDecodeError:
                    args = {}
                tool_calls.append(
                    ToolCall(
                        id=tc["id"],
                        name=tc["function"]["name"],
                        arguments=args,
                    )
                )

        return ChatResult(
            content=content,
            tool_calls=tool_calls,
            usage={"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens},
        )
