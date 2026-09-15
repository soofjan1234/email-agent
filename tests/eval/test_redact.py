"""脱敏必须去掉原始敏感值，并保留原文供审计。"""

from __future__ import annotations

from evals.harness.redact import evaluate_redact, redact_case_text


def test_redact_replaces_email_and_keeps_original() -> None:
    source = "Please reply to alex.rivera@example.test about the DS920+."
    redacted, original = redact_case_text(source)
    assert original == source
    assert "alex.rivera@example.test" not in redacted
    assert "[email]" in redacted


def test_redact_strips_signature_and_quotes() -> None:
    source = "Ship the spare to 221 Baker Street.\n-- \nAlex Rivera\n> quoted original"
    redacted, original = redact_case_text(source)
    assert original == source
    assert "Alex Rivera" not in redacted
    assert "quoted original" not in redacted
    assert "[street address]" in redacted


def test_privacy_fixture_set_passes() -> None:
    result = evaluate_redact()
    assert result["total"] >= 6
    assert result["passed"] is True
