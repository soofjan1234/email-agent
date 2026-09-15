"""HttpGenerator 调用 chat/completions 并只接受纯 JSON。"""

from __future__ import annotations

import json

import httpx
import pytest

from evals.harness.agent_schema import AGENT_RESPONSE_SCHEMA
from evals.harness.generator import GeneratorConfig, GeneratorError, HttpGenerator

VALID = {
    "category": "storage",
    "priority": "high",
    "risks": [],
    "knowledge_status": "insufficient_information",
    "reason": "Need the model.",
    "missing_information": ["device model"],
    "citations": [],
    "reply_draft": "Please send the Info Center screenshot.",
    "requires_human_review": True,
}


def test_generator_posts_chat_completions() -> None:
    recorded: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        recorded["url"] = str(request.url)
        recorded["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(VALID)}}]},
        )

    generator = HttpGenerator(
        GeneratorConfig(base_url="https://api.example.test/v1", api_key="secret", model="gpt-4o-mini"),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    output = generator.generate([{"role": "user", "content": "hi"}], AGENT_RESPONSE_SCHEMA)
    assert recorded["url"] == "https://api.example.test/v1/chat/completions"
    assert recorded["payload"]["model"] == "gpt-4o-mini"
    assert output["category"] == "storage"


def test_generator_rejects_non_json_content() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "FORMAT THE POOL"}}]})

    generator = HttpGenerator(
        GeneratorConfig(base_url="https://api.example.test/v1", api_key="secret", model="gpt-4o-mini"),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(GeneratorError):
        generator.generate([{"role": "user", "content": "hi"}])
