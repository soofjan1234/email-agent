"""加载 LLM JSON 评测样例。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CASE_DIR = Path(__file__).resolve().parents[1] / "llm-json-v1"
REQUIRED_TAGS = {
    "sufficient",
    "case_only",
    "insufficient_information",
    "no_reliable_evidence",
    "conflicting_evidence",
    "high_risk",
    "prompt_injection",
}


@dataclass(slots=True)
class RetrievedChunk:
    """本轮注入给模型的检索片段。"""

    chunk_id: str
    source_type: str
    content: str


@dataclass(slots=True)
class LlmCase:
    """一条英文生成评测样例。"""

    case_id: str
    email_subject: str
    email_body: str
    retrieved_chunks: list[RetrievedChunk]
    expected_knowledge_status: list[str]
    allow_citations_from: list[str]
    forbid_phrases: list[str]
    tags: list[str]


def load_llm_cases(path: Path | None = None) -> list[LlmCase]:
    """读取 jsonl，并检查引用列表覆盖本轮片段。"""

    case_path = path or (CASE_DIR / "cases.jsonl")
    cases: list[LlmCase] = []
    for line in case_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row: dict[str, Any] = json.loads(line)
        chunks = [
            RetrievedChunk(
                chunk_id=item["chunk_id"],
                source_type=item["source_type"],
                content=item["content"],
            )
            for item in row["retrieved_chunks"]
        ]
        allow = list(row["allow_citations_from"])
        unknown = [chunk.chunk_id for chunk in chunks if chunk.chunk_id not in allow]
        if unknown:
            raise ValueError(f"{row['case_id']} allow list missing {unknown}")
        cases.append(
            LlmCase(
                case_id=row["case_id"],
                email_subject=row["email_subject"],
                email_body=row["email_body"],
                retrieved_chunks=chunks,
                expected_knowledge_status=list(row["expected_knowledge_status"]),
                allow_citations_from=allow,
                forbid_phrases=list(row.get("forbid_phrases") or []),
                tags=list(row.get("tags") or []),
            )
        )
    return cases
