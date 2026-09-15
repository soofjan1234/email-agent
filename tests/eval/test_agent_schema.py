"""Agent 输出只接受纯 JSON 对象。"""

from __future__ import annotations

import pytest

from evals.harness.agent_schema import AgentSchemaError, parse_agent_output, validate_agent_output

VALID = {
    "category": "storage",
    "priority": "urgent",
    "risks": ["data_loss"],
    "knowledge_status": "high_risk",
    "reason": "The pool crashed.",
    "missing_information": ["screenshot"],
    "citations": [{"chunk_id": "pd-1", "usage": "fact"}],
    "reply_draft": "We will not format the disks.",
    "requires_human_review": True,
}


def test_parse_agent_output_accepts_plain_json() -> None:
    import json

    assert parse_agent_output(json.dumps(VALID))["category"] == "storage"


def test_parse_agent_output_rejects_markdown_fence() -> None:
    import json

    with pytest.raises(AgentSchemaError):
        parse_agent_output("```json\n" + json.dumps(VALID) + "\n```")


def test_validate_agent_output_requires_human_review() -> None:
    payload = dict(VALID)
    payload["requires_human_review"] = False
    with pytest.raises(AgentSchemaError):
        validate_agent_output(payload)
