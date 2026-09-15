"""HttpEmbedder 只通过 OpenAI-compatible embeddings 接口取固定维度向量。"""

from __future__ import annotations

import json

import httpx
import pytest

from evals.harness.embedder import EmbedderConfig, HttpEmbedder, InconsistentEmbeddingDimensionError


def test_http_embedder_posts_openai_compatible_payload() -> None:
    recorded: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        recorded["url"] = str(request.url)
        recorded["authorization"] = request.headers["Authorization"]
        recorded["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 0, "embedding": [1.0, 0.0]},
                    {"index": 1, "embedding": [0.0, 1.0]},
                ]
            },
        )

    embedder = HttpEmbedder(
        EmbedderConfig(
            base_url="https://api.example.test/v1",
            api_key="secret-key",
            model="text-embedding-3-small",
        ),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    vectors = embedder.embed(["alpha", "beta"])

    assert recorded["url"] == "https://api.example.test/v1/embeddings"
    assert recorded["authorization"] == "Bearer secret-key"
    assert recorded["payload"] == {"model": "text-embedding-3-small", "input": ["alpha", "beta"]}
    assert [vector.tolist() for vector in vectors] == [[1.0, 0.0], [0.0, 1.0]]
    assert embedder.dimensions == 2


def test_http_embedder_rejects_mixed_dimensions() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 0, "embedding": [1.0, 0.0]},
                    {"index": 1, "embedding": [0.0, 1.0, 0.0]},
                ]
            },
        )

    embedder = HttpEmbedder(
        EmbedderConfig(
            base_url="https://api.example.test/v1",
            api_key="secret-key",
            model="text-embedding-3-small",
        ),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(InconsistentEmbeddingDimensionError):
        embedder.embed(["alpha", "beta"])
