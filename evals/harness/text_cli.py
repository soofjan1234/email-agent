"""运行 15.1 第 3–5 条离线验证并在全过时冻结。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from evals.harness.normalize import TEXT_DIR, evaluate_normalize
from evals.harness.pairing import evaluate_pairing
from evals.harness.redact import PLACEHOLDERS, evaluate_redact


def main() -> int:
    normalize = evaluate_normalize()
    pairing = evaluate_pairing()
    privacy = evaluate_redact()
    print(
        f"normalize passed={normalize['passed']} failed={normalize['failed']} "
        f"pairing passed={pairing['passed']} failed={pairing['failed']} "
        f"privacy passed={privacy['passed']} failed={privacy['failed']}"
    )
    run_path = TEXT_DIR / "last-run.json"
    run_path.write_text(
        json.dumps(
            {
                "normalize": normalize,
                "pairing": pairing,
                "privacy": privacy,
                "evaluated_at": datetime.now(timezone.utc).isoformat(),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    if not (normalize["passed"] and pairing["passed"] and privacy["passed"]):
        print("text-v1 blocking checks failed; freeze.json was not written")
        return 1
    freeze = {
        "index_version": "text-v1",
        "normalizer": "protect_identifiers_then_english",
        "pairing": "header_first",
        "redaction_placeholders": list(PLACEHOLDERS),
        "primary_language": "en",
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
    }
    Path(TEXT_DIR / "freeze.json").write_text(json.dumps(freeze, indent=2) + "\n", encoding="utf-8")
    print(f"froze text-v1 path={TEXT_DIR / 'freeze.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
