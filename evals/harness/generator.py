"""OpenAI-compatible 聊天生成适配器。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from evals.harness.agent_schema import AGENT_RESPONSE_SCHEMA, parse_agent_output


class GeneratorError(RuntimeError):
    """聊天接口失败或无法得到合法 JSON。"""


@dataclass(slots=True)
class GeneratorConfig:
    """聊天网关配置。密钥不得写入评测报告。"""

    base_url: str
    api_key: str
    model: str
    timeout_seconds: float = 90.0


class HttpGenerator:
    """调用 /v1/chat/completions，并按 Schema 解析 Agent JSON。"""

    def __init__(self, config: GeneratorConfig, client: httpx.Client | None = None) -> None:
        # 允许测试注入 MockTransport。
        self.config = config
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=config.timeout_seconds)
        self.json_mode = "prompt_only"

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def generate(self, messages: list[dict[str, str]], response_schema: dict[str, Any] | None = None) -> dict[str, Any]:
        """优先结构化 JSON，失败后再退回仅提示约束。"""

        schema = response_schema or AGENT_RESPONSE_SCHEMA
        attempts = (
            ("json_schema", {"type": "json_schema", "json_schema": {"name": "agent_reply", "schema": schema}}),
            ("json_object", {"type": "json_object"}),
            ("prompt_only", None),
        )
        last_error: Exception | None = None
        for mode, response_format in attempts:
            try:
                # 1. 按当前模式请求聊天接口。
                payload: dict[str, Any] = {
                    "model": self.config.model,
                    "temperature": 0,
                    "messages": messages,
                }
                if response_format is not None:
                    payload["response_format"] = response_format
                response = self._client.post(
                    f"{self.config.base_url.rstrip('/')}/chat/completions",
                    headers={"Authorization": f"Bearer {self.config.api_key}"},
                    json=payload,
                )
                response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"]
                # 2. 只接受纯 JSON，不剥 Markdown。
                parsed = parse_agent_output(content)
                self.json_mode = mode
                return parsed
            except (httpx.HTTPStatusError, KeyError, IndexError, TypeError) as exc:
                last_error = exc
                continue
            except Exception as exc:
                last_error = exc
                continue
        raise GeneratorError(f"unable to generate valid JSON: {last_error}")
