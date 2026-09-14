"""运行器只在两路 Recall@3 和标识检查都过线时写入 freeze.json。"""

from __future__ import annotations

import json
from pathlib import Path

import httpx

from evals.harness.dataset import Chunk, Dataset, Query
from evals.harness.embedder import EmbedderConfig, HttpEmbedder
from evals.harness.runner import PASS_RECALL_AT_3, evaluate_model, write_freeze_record


def _dataset() -> Dataset:
    return Dataset(
        chunks=[
            Chunk("pd-1", "product_doc", "RAID5", None, "en", "RAID5 degraded writes"),
            Chunk("ac-1", "approved_case", "tone", None, "en", "Do not tell the customer to format"),
            Chunk("ac-2", "approved_case", "other", None, "en", "Ask for the DSM version screenshot"),
            Chunk("ac-3", "approved_case", "other", None, "en", "Confirm the power adapter first"),
            Chunk("ac-4", "approved_case", "other", None, "en", "Collect the office network diagram"),
        ],
        queries=[
            Query("q-pd", "Can I write after RAID5 degrades?", "product_doc", "en", ["pd-1"], ["identifier"]),
            Query("q-ac", "Do not format", "approved_case", "en", ["ac-1"], []),
        ],
    )


def _embedder(vectors: dict[str, list[float]]) -> HttpEmbedder:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": index, "embedding": vectors[text]}
                    for index, text in enumerate(payload["input"])
                ]
            },
        )

    return HttpEmbedder(
        EmbedderConfig(base_url="https://api.example.test/v1", api_key="k", model="demo"),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


PASSING_VECTORS = {
    "RAID5 degraded writes": [1.0, 0.0],
    "Do not tell the customer to format": [0.0, 1.0],
    "Ask for the DSM version screenshot": [0.1, 0.2],
    "Confirm the power adapter first": [0.2, 0.1],
    "Collect the office network diagram": [0.15, 0.1],
    "Can I write after RAID5 degrades?": [1.0, 0.0],
    "Do not format": [0.0, 1.0],
}

FAILING_VECTORS = {
    **PASSING_VECTORS,
    "Do not format": [1.0, 0.0],
    "Ask for the DSM version screenshot": [1.0, 0.0],
    "Confirm the power adapter first": [0.99, 0.01],
    "Collect the office network diagram": [0.98, 0.02],
    "Do not tell the customer to format": [0.0, 1.0],
}


def test_evaluate_model_passes_when_recall_and_identifiers_clear() -> None:
    report = evaluate_model(_dataset(), _embedder(PASSING_VECTORS))
    assert report.passed is True
    assert report.summary["product_doc"]["recall_at_3"] >= PASS_RECALL_AT_3
    assert report.summary["approved_case"]["recall_at_3"] >= PASS_RECALL_AT_3
    assert report.identifier_hits["failed"] == []


def test_write_freeze_record_only_when_passed(tmp_path: Path) -> None:
    freeze_path = tmp_path / "freeze.json"
    failed = evaluate_model(_dataset(), _embedder(FAILING_VECTORS))
    assert failed.passed is False
    assert write_freeze_record(failed, freeze_path) is False
    assert not freeze_path.exists()

    passed = evaluate_model(_dataset(), _embedder(PASSING_VECTORS))
    assert write_freeze_record(passed, freeze_path) is True
    payload = json.loads(freeze_path.read_text(encoding="utf-8"))
    assert payload["model"] == "demo"
    assert payload["primary_language"] == "en"
    assert payload["distance"] == "cosine"
