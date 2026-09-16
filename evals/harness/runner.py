"""运行单模型评测，并在过线时写冻结记录。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from evals.harness.dataset import Dataset
from evals.harness.embedder import HttpEmbedder
from evals.harness.metrics import DEFAULT_K, identifier_hits, summarize_scores
from evals.harness.retrieve import rank_chunks

# 设计冻结的分路 Recall@3 门槛。
PASS_RECALL_AT_3 = 0.80
INDEX_VERSION = "embedding-v1"


@dataclass(slots=True)
class ModelReport:
    """单次模型评测的可序列化结果。"""

    model: str
    dimensions: int | None
    gateway: str
    summary: dict[str, dict[str, float]]
    identifier_hits: dict[str, list[str]]
    passed: bool
    evaluated_at: str
    rows: list[dict[str, object]] = field(default_factory=list)


def evaluate_model(dataset: Dataset, embedder: HttpEmbedder) -> ModelReport:
    """对全部片段和查询编码后，按 source_type 做内存余弦检索。"""

    # 1. 先编码知识片段，再编码查询，避免把查询向量写进语料。
    chunk_vectors = embedder.embed_documents([chunk.content for chunk in dataset.chunks])
    for chunk, vector in zip(dataset.chunks, chunk_vectors, strict=True):
        chunk.embedding = vector
    query_vectors = embedder.embed_queries([query.query for query in dataset.queries])

    rows: list[dict[str, object]] = []
    identifier_rows: list[dict[str, object]] = []
    for query, query_vector in zip(dataset.queries, query_vectors, strict=True):
        ranked = rank_chunks(query_vector, dataset.chunks, source_type=query.source_type, k=DEFAULT_K)
        row = {
            "query_id": query.query_id,
            "source_type": query.source_type,
            "relevant_chunk_ids": query.relevant_chunk_ids,
            "ranked_ids": [chunk.chunk_id for chunk in ranked],
            "tags": query.tags,
        }
        rows.append(row)
        if "identifier" in query.tags:
            identifier_rows.append(row)

    summary = summarize_scores(rows, k=DEFAULT_K)
    hits = identifier_hits(identifier_rows, k=DEFAULT_K)
    product_recall = summary.get("product_doc", {}).get("recall_at_3", 0.0)
    case_recall = summary.get("approved_case", {}).get("recall_at_3", 0.0)
    passed = (
        product_recall >= PASS_RECALL_AT_3
        and case_recall >= PASS_RECALL_AT_3
        and not hits["failed"]
        and embedder.dimensions is not None
    )
    return ModelReport(
        model=embedder.config.model,
        dimensions=embedder.dimensions,
        gateway=urlparse(embedder.config.base_url).hostname or "unknown",
        summary=summary,
        identifier_hits=hits,
        passed=passed,
        evaluated_at=datetime.now(timezone.utc).isoformat(),
        rows=rows,
    )


def write_freeze_record(report: ModelReport, path: Path) -> bool:
    """未过线时不写 freeze.json，避免把失败结果冻成建库依据。"""

    if not report.passed:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "model": report.model,
        "dimensions": report.dimensions,
        "index_version": INDEX_VERSION,
        "distance": "cosine",
        "recall_at_3": {
            source_type: values.get("recall_at_3")
            for source_type, values in report.summary.items()
        },
        "primary_language": "en",
        "evaluated_at": report.evaluated_at,
        "gateway": report.gateway,
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return True


def write_run_report(reports: list[ModelReport], path: Path) -> None:
    """保存最近一次运行摘要，不含向量全文。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "index_version": INDEX_VERSION,
        "primary_language": "en",
        "models": [
            {
                "model": report.model,
                "dimensions": report.dimensions,
                "passed": report.passed,
                "gateway": report.gateway,
                "summary": report.summary,
                "identifier_hits": report.identifier_hits,
                "evaluated_at": report.evaluated_at,
            }
            for report in reports
        ],
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
