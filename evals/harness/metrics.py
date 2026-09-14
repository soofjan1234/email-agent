"""计算分路 Recall、MRR 和标识查询命中。"""

from __future__ import annotations

from typing import Iterable

# 与每路最多保留 3 条候选一致。
DEFAULT_K = 3


def recall_at_k(relevant_ids: Iterable[str], ranked_ids: Iterable[str], k: int = DEFAULT_K) -> float | None:
    """相关集为空时返回 None，不进入 Recall 分母。"""

    relevant = set(relevant_ids)
    if not relevant:
        return None
    top = set(list(ranked_ids)[:k])
    return len(relevant & top) / len(relevant)


def mean_reciprocal_rank(relevant_ids: Iterable[str], ranked_ids: Iterable[str]) -> float | None:
    """相关集为空时返回 None；未命中返回 0。"""

    relevant = set(relevant_ids)
    if not relevant:
        return None
    for rank, chunk_id in enumerate(ranked_ids, start=1):
        if chunk_id in relevant:
            return 1.0 / rank
    return 0.0


def identifier_hits(rows: list[dict[str, object]], k: int = DEFAULT_K) -> dict[str, list[str]]:
    """标识查询必须在 Top-K 中至少命中 1 个相关片段。"""

    passed: list[str] = []
    failed: list[str] = []
    for row in rows:
        query_id = str(row["query_id"])
        score = recall_at_k(row["relevant_chunk_ids"], row["ranked_ids"], k=k)
        if score is None or score <= 0:
            failed.append(query_id)
        else:
            passed.append(query_id)
    return {"passed": passed, "failed": failed}


def summarize_scores(rows: list[dict[str, object]], k: int = DEFAULT_K) -> dict[str, dict[str, float]]:
    """按 source_type 汇总 Recall@K 与 MRR，忽略空相关集。"""

    grouped: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        grouped.setdefault(str(row["source_type"]), []).append(row)

    summary: dict[str, dict[str, float]] = {}
    for source_type, items in grouped.items():
        recalls = [
            value
            for value in (recall_at_k(item["relevant_chunk_ids"], item["ranked_ids"], k=k) for item in items)
            if value is not None
        ]
        mrrs = [
            value
            for value in (mean_reciprocal_rank(item["relevant_chunk_ids"], item["ranked_ids"]) for item in items)
            if value is not None
        ]
        summary[source_type] = {
            "recall_at_1": (
                sum(recall_at_k(item["relevant_chunk_ids"], item["ranked_ids"], k=1) or 0.0 for item in items if item["relevant_chunk_ids"])
                / max(len(recalls), 1)
            ),
            f"recall_at_{k}": sum(recalls) / max(len(recalls), 1),
            "mrr": sum(mrrs) / max(len(mrrs), 1),
            "scored_queries": float(len(recalls)),
        }
    return summary
