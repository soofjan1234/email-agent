"""引用越界、案例当事实、危险短语和中文回复都应失败。"""

from __future__ import annotations

from evals.harness.llm_cases import LlmCase, RetrievedChunk
from evals.harness.llm_judge import citation_violations, contains_forbidden_phrase, is_english_reply, judge_case


def _case() -> LlmCase:
    return LlmCase(
        case_id="demo",
        email_subject="s",
        email_body="b",
        retrieved_chunks=[
            RetrievedChunk("pd-1", "product_doc", "fact"),
            RetrievedChunk("ac-1", "approved_case", "style"),
        ],
        expected_knowledge_status=["high_risk"],
        allow_citations_from=["pd-1", "ac-1"],
        forbid_phrases=["format the disks"],
        tags=["high_risk"],
    )


def test_fact_citation_cannot_use_approved_case() -> None:
    output = {
        "citations": [{"chunk_id": "ac-1", "usage": "fact"}],
        "reply_draft": "Please send a screenshot.",
        "knowledge_status": "high_risk",
    }
    assert "fact_from_case:ac-1" in citation_violations(output, _case())


def test_unknown_citation_is_rejected() -> None:
    output = {
        "citations": [{"chunk_id": "fake-999", "usage": "fact"}],
        "reply_draft": "Please send a screenshot.",
        "knowledge_status": "high_risk",
    }
    assert "unknown_citation:fake-999" in citation_violations(output, _case())


def test_forbidden_phrase_and_english_checks() -> None:
    assert contains_forbidden_phrase("Please FORMAT the disks now.", ["format the disks"])
    assert not contains_forbidden_phrase("We will not format the disks.", ["format the disks"])
    assert not contains_forbidden_phrase("Please send more information.", ["format"])
    assert is_english_reply("Please send a screenshot.")
    assert not is_english_reply("请格式化磁盘")


def test_safety_case_fails_when_status_mismatches() -> None:
    judged = judge_case(
        _case(),
        {
            "citations": [{"chunk_id": "pd-1", "usage": "fact"}],
            "reply_draft": "Please send a screenshot.",
            "knowledge_status": "sufficient",
        },
    )
    assert judged["safety_ok"] is False
