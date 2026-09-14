"""检索指标按分路 Recall 和标识命中计算，空相关集不进入分母。"""

from __future__ import annotations

from evals.harness.metrics import identifier_hits, mean_reciprocal_rank, recall_at_k, summarize_scores


def test_recall_at_k_counts_relevant_in_top_k() -> None:
    assert recall_at_k(["a", "b"], ["b", "c", "a"], k=3) == 1.0
    assert recall_at_k(["a", "b"], ["b", "c", "d"], k=3) == 0.5
    assert recall_at_k(["a"], ["x", "y", "z"], k=3) == 0.0


def test_recall_at_k_returns_none_for_empty_relevant_set() -> None:
    assert recall_at_k([], ["a", "b"], k=3) is None


def test_mrr_uses_first_relevant_rank() -> None:
    assert mean_reciprocal_rank(["gold"], ["x", "gold", "y"]) == 0.5
    assert mean_reciprocal_rank(["gold"], ["x", "y", "z"]) == 0.0


def test_identifier_hits_require_one_relevant_in_top_k() -> None:
    hits = identifier_hits(
        [
            {"query_id": "q1", "relevant_chunk_ids": ["a"], "ranked_ids": ["x", "a", "y"]},
            {"query_id": "q2", "relevant_chunk_ids": ["b"], "ranked_ids": ["x", "y", "z"]},
        ],
        k=3,
    )
    assert hits == {"passed": ["q1"], "failed": ["q2"]}


def test_summarize_scores_splits_source_types() -> None:
    summary = summarize_scores(
        [
            {
                "source_type": "product_doc",
                "relevant_chunk_ids": ["a"],
                "ranked_ids": ["a", "b", "c"],
            },
            {
                "source_type": "approved_case",
                "relevant_chunk_ids": ["d"],
                "ranked_ids": ["x", "y", "d"],
            },
        ],
        k=3,
    )
    assert summary["product_doc"]["recall_at_3"] == 1.0
    assert summary["approved_case"]["recall_at_3"] == 1.0
    assert summary["approved_case"]["mrr"] == 1.0 / 3
