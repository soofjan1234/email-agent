"""先保护 NAS 标识，再对剩余英文做保守规范化。"""

from __future__ import annotations

import json
import re
from pathlib import Path

TEXT_DIR = Path(__file__).resolve().parents[1] / "text-v1"

# 必须原样保留的标识；越长的模式优先匹配。
PROTECTED_PATTERNS = (
    r"S\.M\.A\.R\.T\.",
    r"DSM\s+7\.2",
    r"error\s+13",
    r"DS\d+\+",
    r"RAID\d+",
    r"SMB",
)
_PROTECTED_RE = re.compile("|".join(f"({pattern})" for pattern in PROTECTED_PATTERNS), re.IGNORECASE)
_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "can",
        "i",
        "in",
        "is",
        "keep",
        "our",
        "the",
        "to",
        "after",
        "on",
    }
)


def extract_protected(text: str) -> list[str]:
    """按出现顺序抽出受保护标识的规范写法。"""

    found: list[str] = []
    for match in _PROTECTED_RE.finditer(text):
        token = _canonical_identifier(match.group(0))
        if token not in found:
            found.append(token)
    return found


def _canonical_identifier(raw: str) -> str:
    compact = re.sub(r"\s+", " ", raw.strip())
    upper = compact.upper()
    if upper.replace(" ", "") == "SMART" or upper == "S.M.A.R.T.":
        return "S.M.A.R.T."
    if re.fullmatch(r"ERROR 13", upper):
        return "error 13"
    if re.fullmatch(r"DSM 7\.2", upper):
        return "DSM 7.2"
    return upper.replace(" ", "") if upper.startswith("DS") or upper.startswith("RAID") or upper == "SMB" else compact


def normalize_query(text: str) -> list[str]:
    """返回保护标识 + 规范化普通词。不修改调用方传入的原文。"""

    # 1. 先抽出标识，避免后续去标点时拆坏。
    protected = extract_protected(text)
    remainder = _PROTECTED_RE.sub(" ", text)
    # 2. 剩余文本只做小写和简单分词。
    words = re.findall(r"[a-z0-9]+", remainder.lower())
    ordinary = [word for word in words if word not in _STOPWORDS and len(word) > 1]
    return protected + ordinary


def load_normalize_queries(path: Path | None = None) -> list[dict[str, object]]:
    """读取规范化冒烟查询。"""

    query_path = path or (TEXT_DIR / "normalize" / "queries.jsonl")
    rows: list[dict[str, object]] = []
    for line in query_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def evaluate_normalize(rows: list[dict[str, object]] | None = None) -> dict[str, object]:
    """每条 must_keep 都必须出现在规范化结果中。"""

    cases = rows or load_normalize_queries()
    failed: list[str] = []
    for row in cases:
        original = str(row["query"])
        tokens = normalize_query(original)
        missing = [item for item in row["must_keep"] if item not in tokens]
        if missing or original != str(row["query"]):
            failed.append(str(row.get("query_id") or original))
    return {"passed": not failed, "total": len(cases), "failed": failed}
