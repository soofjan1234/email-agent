"""确定性协议头应配对，歧义不得自动 paired。"""

from __future__ import annotations

from evals.harness.normalize import TEXT_DIR
from evals.harness.pairing import evaluate_pairing, pair_reply, parse_eml


def test_header_reply_pairs_to_single_inbound() -> None:
    inbound = parse_eml(TEXT_DIR / "pairing" / "inbox-raid5.eml")
    reply = parse_eml(TEXT_DIR / "pairing" / "sent-raid5.eml")
    result = pair_reply(reply, [inbound])
    assert result["status"] == "paired"
    assert result["inbound_files"] == ["inbox-raid5.eml"]


def test_ambiguous_and_headerless_need_review() -> None:
    inbounds = [
        parse_eml(TEXT_DIR / "pairing" / "inbox-amb-a.eml"),
        parse_eml(TEXT_DIR / "pairing" / "inbox-amb-b.eml"),
    ]
    ambiguous = pair_reply(parse_eml(TEXT_DIR / "pairing" / "sent-ambiguous.eml"), inbounds)
    headerless = pair_reply(parse_eml(TEXT_DIR / "pairing" / "sent-noheader.eml"), inbounds)
    assert ambiguous["status"] == "needs_review"
    assert headerless["status"] == "needs_review"


def test_pairing_fixture_set_passes() -> None:
    result = evaluate_pairing()
    assert result["total"] >= 4
    assert result["passed"] is True
