"""把案例候选中的敏感值替换为英文类型占位符。"""

from __future__ import annotations

import json
import re
from pathlib import Path

from evals.harness.normalize import TEXT_DIR

PLACEHOLDERS = (
    "[email]",
    "[phone]",
    "[device serial]",
    "[public ip]",
    "[account]",
    "[access token]",
    "[street address]",
)

_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PHONE_RE = re.compile(r"\b\+?\d[\d\s().-]{7,}\d\b")
_SERIAL_RE = re.compile(r"\b(?:SN|SERIAL)[- ]?[A-Z0-9]{6,}\b", re.IGNORECASE)
_IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_TOKEN_RE = re.compile(r"\b(?:sk-|tok_)[A-Za-z0-9]{8,}\b")
_ACCOUNT_RE = re.compile(r"\b(?:account|username|user)\s*[:=]\s*([A-Za-z0-9._-]+)", re.IGNORECASE)
_ADDRESS_RE = re.compile(r"\b\d{1,5}\s+[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)?\s+(?:Street|St|Avenue|Ave|Road|Rd)\b")
_SIGNATURE_RE = re.compile(r"\n-- \n.*", re.DOTALL)
_QUOTE_RE = re.compile(r"^\s*>.*$", re.MULTILINE)


def redact_case_text(source_text: str, *, strip_mail_noise: bool = True) -> tuple[str, str]:
    """返回 (案例文本, 原文)。原文不做破坏性修改。"""

    original = source_text
    # 1. 先去掉签名和引用链，只作用于案例候选。
    cleaned = _SIGNATURE_RE.sub("", source_text) if strip_mail_noise else source_text
    cleaned = _QUOTE_RE.sub("", cleaned) if strip_mail_noise else cleaned
    # 2. 再按类型替换敏感值。
    cleaned = _EMAIL_RE.sub("[email]", cleaned)
    cleaned = _SERIAL_RE.sub("[device serial]", cleaned)
    cleaned = _TOKEN_RE.sub("[access token]", cleaned)
    cleaned = _ACCOUNT_RE.sub("account: [account]", cleaned)
    cleaned = _ADDRESS_RE.sub("[street address]", cleaned)
    cleaned = _IP_RE.sub("[public ip]", cleaned)
    cleaned = _PHONE_RE.sub("[phone]", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned, original


def load_privacy_samples(path: Path | None = None) -> list[dict[str, object]]:
    """读取脱敏样例。"""

    sample_path = path or (TEXT_DIR / "privacy" / "samples.jsonl")
    rows: list[dict[str, object]] = []
    for line in sample_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def evaluate_redact(rows: list[dict[str, object]] | None = None) -> dict[str, object]:
    """案例文本不得残留原始敏感值，且必须出现要求的占位符。"""

    cases = rows or load_privacy_samples()
    failed: list[str] = []
    seen_placeholders: set[str] = set()
    for row in cases:
        redacted, original = redact_case_text(str(row["source_text"]))
        if original != str(row["source_text"]):
            failed.append(str(row["sample_id"]))
            continue
        leftover = [item for item in row["must_not_appear"] if item in redacted]
        missing = [item for item in row["required_placeholders"] if item not in redacted]
        if leftover or missing:
            failed.append(str(row["sample_id"]))
        seen_placeholders.update(item for item in PLACEHOLDERS if item in redacted)
    required_types = {"[email]", "[phone]", "[device serial]", "[public ip]", "[account]", "[access token]"}
    coverage_ok = required_types.issubset(seen_placeholders)
    return {
        "passed": not failed and coverage_ok,
        "total": len(cases),
        "failed": failed,
        "placeholder_coverage": sorted(seen_placeholders),
    }
