"""规范化必须保留 NAS 标识，且不得改写原文。"""

from __future__ import annotations

from evals.harness.normalize import evaluate_normalize, extract_protected, normalize_query


def test_protected_identifiers_survive_normalization() -> None:
    original = "Can I keep writing to a DS920+ volume after RAID5 degrades?"
    tokens = normalize_query(original)
    assert "DS920+" in tokens
    assert "RAID5" in tokens
    assert original == "Can I keep writing to a DS920+ volume after RAID5 degrades?"


def test_smart_and_error_codes_are_canonical() -> None:
    assert "S.M.A.R.T." in extract_protected("s.m.a.r.t. warning")
    assert "error 13" in normalize_query("Users get error 13 in DSM 7.2")
    assert "DSM 7.2" in normalize_query("Users get error 13 in DSM 7.2")


def test_normalize_fixture_set_passes() -> None:
    result = evaluate_normalize()
    assert result["total"] >= 8
    assert result["passed"] is True
