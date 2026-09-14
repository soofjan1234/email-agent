"""加载并校验英文 Embedding 评测集。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

# 评测集根目录与设计文档中的 evals/embedding-v1 保持一致。
DATASET_DIR = Path(__file__).resolve().parents[1] / "embedding-v1"


@dataclass(slots=True)
class Chunk:
    """一条预先切好的知识片段。"""

    chunk_id: str
    source_type: str
    title: str
    product_model: str | None
    language: str
    content: str
    embedding: np.ndarray | None = None


@dataclass(slots=True)
class Query:
    """一条英文检索查询及其期望片段。"""

    query_id: str
    query: str
    source_type: str
    language: str
    relevant_chunk_ids: list[str]
    tags: list[str]


@dataclass(slots=True)
class Dataset:
    """完整评测集。"""

    chunks: list[Chunk]
    queries: list[Query]


def _require(record: dict[str, Any], field: str) -> Any:
    if field not in record:
        raise ValueError(f"missing field: {field}")
    return record[field]


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def load_dataset(dataset_dir: Path = DATASET_DIR) -> Dataset:
    """从 jsonl 读取 chunks 和 queries，并检查引用完整性。"""

    # 1. 读取预先切好的片段，避免评测时现场切分漂移。
    chunks = [
        Chunk(
            chunk_id=_require(row, "chunk_id"),
            source_type=_require(row, "source_type"),
            title=_require(row, "title"),
            product_model=row.get("product_model"),
            language=_require(row, "language"),
            content=_require(row, "content"),
        )
        for row in _load_jsonl(dataset_dir / "chunks.jsonl")
    ]
    chunk_ids = {chunk.chunk_id for chunk in chunks}

    # 2. 读取查询，并确认相关片段都存在于语料中。
    queries = [
        Query(
            query_id=_require(row, "query_id"),
            query=_require(row, "query"),
            source_type=_require(row, "source_type"),
            language=_require(row, "language"),
            relevant_chunk_ids=list(_require(row, "relevant_chunk_ids")),
            tags=list(row.get("tags") or []),
        )
        for row in _load_jsonl(dataset_dir / "queries.jsonl")
    ]
    unknown = [
        chunk_id
        for query in queries
        for chunk_id in query.relevant_chunk_ids
        if chunk_id not in chunk_ids
    ]
    if unknown:
        raise ValueError(f"unknown relevant chunk ids: {sorted(set(unknown))}")
    return Dataset(chunks=chunks, queries=queries)
