"""评测集必须满足英文 Embedding truth test 的规模和覆盖契约。"""

from __future__ import annotations

from evals.harness.dataset import DATASET_DIR, load_dataset


def test_dataset_meets_english_scale_and_coverage() -> None:
    dataset = load_dataset(DATASET_DIR)

    product_chunks = [chunk for chunk in dataset.chunks if chunk.source_type == "product_doc"]
    case_chunks = [chunk for chunk in dataset.chunks if chunk.source_type == "approved_case"]
    scored_queries = [query for query in dataset.queries if query.relevant_chunk_ids]
    oos_queries = [query for query in dataset.queries if not query.relevant_chunk_ids]
    identifier_queries = [query for query in dataset.queries if "identifier" in query.tags]

    assert len(dataset.chunks) >= 14
    assert len(product_chunks) >= 8
    assert len(case_chunks) >= 6
    assert len(dataset.queries) >= 12
    assert all(chunk.language == "en" for chunk in dataset.chunks)
    assert all(query.language == "en" for query in dataset.queries)
    assert {query.source_type for query in scored_queries} == {"product_doc", "approved_case"}
    assert oos_queries
    assert len(identifier_queries) >= 4
    assert all(query.relevant_chunk_ids for query in identifier_queries)
