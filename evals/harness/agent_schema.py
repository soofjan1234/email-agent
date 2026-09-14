"""Agent 输出 JSON 契约与解析。"""

from __future__ import annotations

from typing import Any

CATEGORIES = (
    "device_offline",
    "storage",
    "network",
    "account_share",
    "sync_backup",
    "media_apps",
    "product_consult",
    "other",
)
PRIORITIES = ("urgent", "high", "normal", "low")
KNOWLEDGE_STATUSES = (
    "sufficient",
    "insufficient_information",
    "no_reliable_evidence",
    "high_risk",
    "conflicting_evidence",
)
CITATION_USAGES = ("fact", "style")

AGENT_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "category",
        "priority",
        "risks",
        "knowledge_status",
        "reason",
        "missing_information",
        "citations",
        "reply_draft",
        "requires_human_review",
    ],
    "properties": {
        "category": {"type": "string", "enum": list(CATEGORIES)},
        "priority": {"type": "string", "enum": list(PRIORITIES)},
        "risks": {"type": "array", "items": {"type": "string"}},
        "knowledge_status": {"type": "string", "enum": list(KNOWLEDGE_STATUSES)},
        "reason": {"type": "string"},
        "missing_information": {"type": "array", "items": {"type": "string"}},
        "citations": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["chunk_id", "usage"],
                "properties": {
                    "chunk_id": {"type": "string"},
                    "usage": {"type": "string", "enum": list(CITATION_USAGES)},
                },
            },
        },
        "reply_draft": {"type": "string"},
        "requires_human_review": {"type": "boolean"},
    },
}


class AgentSchemaError(ValueError):
    """输出不是可接受的 Agent JSON。"""


def parse_agent_output(raw: str) -> dict[str, Any]:
    """只接受纯 JSON 对象，拒绝 Markdown 围栏或前后缀文本。"""

    import json

    text = raw.strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AgentSchemaError("output is not JSON") from exc
    if not isinstance(payload, dict):
        raise AgentSchemaError("output is not a JSON object")
    return validate_agent_output(payload)


def validate_agent_output(payload: dict[str, Any]) -> dict[str, Any]:
    """按冻结枚举和必填字段校验 Agent 对象。"""

    missing = [field for field in AGENT_RESPONSE_SCHEMA["required"] if field not in payload]
    if missing:
        raise AgentSchemaError(f"missing fields: {missing}")
    if payload.get("category") not in CATEGORIES:
        raise AgentSchemaError("invalid category")
    if payload.get("priority") not in PRIORITIES:
        raise AgentSchemaError("invalid priority")
    if payload.get("knowledge_status") not in KNOWLEDGE_STATUSES:
        raise AgentSchemaError("invalid knowledge_status")
    if payload.get("requires_human_review") is not True:
        raise AgentSchemaError("requires_human_review must be true")
    if not isinstance(payload.get("reason"), str) or not payload["reason"].strip():
        raise AgentSchemaError("reason must be a non-empty string")
    if not isinstance(payload.get("reply_draft"), str) or not payload["reply_draft"].strip():
        raise AgentSchemaError("reply_draft must be a non-empty string")
    if not isinstance(payload.get("risks"), list) or not all(isinstance(item, str) for item in payload["risks"]):
        raise AgentSchemaError("risks must be a string list")
    if not isinstance(payload.get("missing_information"), list) or not all(
        isinstance(item, str) for item in payload["missing_information"]
    ):
        raise AgentSchemaError("missing_information must be a string list")
    citations = payload.get("citations")
    if not isinstance(citations, list):
        raise AgentSchemaError("citations must be a list")
    for item in citations:
        if not isinstance(item, dict):
            raise AgentSchemaError("citation must be an object")
        if item.get("usage") not in CITATION_USAGES or not isinstance(item.get("chunk_id"), str):
            raise AgentSchemaError("invalid citation")
    return payload
