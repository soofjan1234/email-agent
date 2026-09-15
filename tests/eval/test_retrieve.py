"""分路检索只在同一 source_type 内取余弦 Top-K。"""

from __future__ import annotations

import numpy as np

from evals.harness.dataset import Chunk
from evals.harness.retrieve import rank_chunks


def _chunk(chunk_id: str, source_type: str, vector: list[float]) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        source_type=source_type,
        title=chunk_id,
        product_model=None,
        language="en",
        content=chunk_id,
        embedding=np.asarray(vector, dtype=np.float64),
    )


def test_rank_chunks_keeps_source_types_isolated() -> None:
    chunks = [
        _chunk("pd-1", "product_doc", [1.0, 0.0]),
        _chunk("pd-2", "product_doc", [0.8, 0.2]),
        _chunk("ac-1", "approved_case", [1.0, 0.0]),
    ]
    ranked = rank_chunks(np.asarray([1.0, 0.0]), chunks, source_type="product_doc", k=3)
    assert [item.chunk_id for item in ranked] == ["pd-1", "pd-2"]


def test_rank_chunks_orders_by_cosine_similarity() -> None:
    chunks = [
        _chunk("near", "product_doc", [0.9, 0.1]),
        _chunk("far", "product_doc", [0.1, 0.9]),
        _chunk("mid", "product_doc", [0.7, 0.3]),
    ]
    ranked = rank_chunks(np.asarray([1.0, 0.0]), chunks, source_type="product_doc", k=2)
    assert [item.chunk_id for item in ranked] == ["near", "mid"]
