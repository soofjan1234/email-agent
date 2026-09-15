"""LLM 评测集必须覆盖设计要求的英文场景。"""

from __future__ import annotations

from evals.harness.llm_cases import REQUIRED_TAGS, load_llm_cases


def test_llm_cases_meet_english_coverage() -> None:
    cases = load_llm_cases()
    tags = {tag for case in cases for tag in case.tags}
    assert len(cases) >= 8
    assert REQUIRED_TAGS.issubset(tags)
    assert all(case.email_subject and case.email_body for case in cases)
