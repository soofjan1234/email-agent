"""按邮件协议头做确定配对，歧义进入人工确认。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from email import message_from_bytes
from email.message import Message
from pathlib import Path

from evals.harness.normalize import TEXT_DIR


@dataclass(slots=True)
class ParsedEmail:
    """一条用于配对的英文邮件。"""

    filename: str
    message_id: str
    in_reply_to: list[str]
    references: list[str]
    subject: str
    from_addr: str
    to_addr: str


def _parse_id_list(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.replace("\n", " ").split() if item.strip().startswith("<")]


def parse_eml(path: Path) -> ParsedEmail:
    """从 .eml 读取配对所需协议头。"""

    message: Message = message_from_bytes(path.read_bytes())
    message_id = (message.get("Message-ID") or "").strip()
    return ParsedEmail(
        filename=path.name,
        message_id=message_id,
        in_reply_to=_parse_id_list(message.get("In-Reply-To")),
        references=_parse_id_list(message.get("References")),
        subject=message.get("Subject") or "",
        from_addr=message.get("From") or "",
        to_addr=message.get("To") or "",
    )


def pair_reply(reply: ParsedEmail, inbounds: list[ParsedEmail]) -> dict[str, object]:
    """只根据协议头配对；0 个或多个命中都进入 needs_review。"""

    wanted = set(reply.in_reply_to) | set(reply.references)
    matches = [item for item in inbounds if item.message_id and item.message_id in wanted]
    if len(matches) == 1:
        return {
            "reply_file": reply.filename,
            "inbound_files": [matches[0].filename],
            "status": "paired",
            "pairing_method": "header",
        }
    return {
        "reply_file": reply.filename,
        "inbound_files": [item.filename for item in matches],
        "status": "needs_review",
        "pairing_method": "header" if matches else "none",
    }


def load_expected_pairs(path: Path | None = None) -> list[dict[str, object]]:
    """读取配对期望。"""

    expected_path = path or (TEXT_DIR / "pairing" / "expected.jsonl")
    rows: list[dict[str, object]] = []
    for line in expected_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def evaluate_pairing(pairing_dir: Path | None = None) -> dict[str, object]:
    """确定性样例必须配对正确，歧义样例不得自动 paired。"""

    root = pairing_dir or (TEXT_DIR / "pairing")
    emails = [parse_eml(path) for path in sorted(root.glob("*.eml"))]
    inbounds = [item for item in emails if item.filename.startswith("inbox-")]
    replies = [item for item in emails if item.filename.startswith("sent-")]
    actual = {reply.filename: pair_reply(reply, inbounds) for reply in replies}
    failed: list[str] = []
    for expected in load_expected_pairs(root / "expected.jsonl"):
        got = actual.get(str(expected["reply_file"]))
        if got is None or got["status"] != expected["status"]:
            failed.append(str(expected["reply_file"]))
            continue
        if expected["status"] == "paired" and got["inbound_files"] != expected["inbound_files"]:
            failed.append(str(expected["reply_file"]))
        if expected["status"] == "needs_review" and got["status"] == "paired":
            failed.append(str(expected["reply_file"]))
    return {"passed": not failed, "total": len(actual), "failed": failed}
