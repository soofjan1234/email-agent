"""OpenAI-compatible Embedding 适配器。"""

from __future__ import annotations

from dataclasses import dataclass

import httpx
import numpy as np


class InconsistentEmbeddingDimensionError(ValueError):
    """同一次调用返回了不同长度的向量。"""


@dataclass(slots=True)
class EmbedderConfig:
    """网关地址、密钥和模型名。密钥不得写入评测报告。"""

    base_url: str
    api_key: str
    model: str
    timeout_seconds: float = 60.0


class HttpEmbedder:
    """通过 POST /v1/embeddings 批量编码文本。"""

    def __init__(self, config: EmbedderConfig, client: httpx.Client | None = None) -> None:
        # 允许测试注入 MockTransport，避免真实网络。
        self.config = config
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=config.timeout_seconds)
        self.dimensions: int | None = None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def embed(self, texts: list[str]) -> list[np.ndarray]:
        """按输入顺序返回固定维度向量。"""

        if not texts:
            return []

        # 1. 调用 OpenAI-compatible embeddings 接口。
        response = self._client.post(
            f"{self.config.base_url.rstrip('/')}/embeddings",
            headers={"Authorization": f"Bearer {self.config.api_key}"},
            json={"model": self.config.model, "input": texts},
        )
        response.raise_for_status()
        payload = response.json()
        rows = sorted(payload.get("data") or [], key=lambda item: item.get("index", 0))
        if len(rows) != len(texts):
            raise ValueError(f"expected {len(texts)} embeddings, got {len(rows)}")

        # 2. 校验同一批次维度一致后再交给检索。
        vectors = [np.asarray(row["embedding"], dtype=np.float64) for row in rows]
        lengths = {int(vector.size) for vector in vectors}
        if len(lengths) != 1:
            raise InconsistentEmbeddingDimensionError(f"mixed dimensions: {sorted(lengths)}")
        self.dimensions = lengths.pop()
        return vectors
