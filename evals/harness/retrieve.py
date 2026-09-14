"""在单一知识路上用余弦相似度取 Top-K。"""

from __future__ import annotations

import numpy as np

from evals.harness.dataset import Chunk


def l2_normalize(vector: np.ndarray) -> np.ndarray:
    """零向量保持原样，避免除零。"""

    norm = np.linalg.norm(vector)
    if norm == 0:
        return vector
    return vector / norm


def cosine_similarity(left: np.ndarray, right: np.ndarray) -> float:
    """L2 归一化后的点积就是余弦。"""

    return float(np.dot(l2_normalize(left), l2_normalize(right)))


def rank_chunks(
    query_vector: np.ndarray,
    chunks: list[Chunk],
    source_type: str,
    k: int = 3,
) -> list[Chunk]:
    """只比较同一 source_type，并按余弦从高到低截断。"""

    scored: list[tuple[float, Chunk]] = []
    for chunk in chunks:
        if chunk.source_type != source_type or chunk.embedding is None:
            continue
        scored.append((cosine_similarity(query_vector, chunk.embedding), chunk))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [chunk for _score, chunk in scored[:k]]
