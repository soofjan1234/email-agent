"""命令行入口：评测网关上的聊天模型。"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from dotenv import load_dotenv

from evals.harness.generator import GeneratorConfig, HttpGenerator
from evals.harness.llm_cases import CASE_DIR, load_llm_cases
from evals.harness.llm_runner import evaluate_llm, write_llm_freeze_record, write_llm_run_report

DEFAULT_CHAT_MODELS = (
    "gpt-4o-mini",
    "gpt-4o",
    "gpt-4.1-mini",
    "gpt-3.5-turbo",
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the English LLM JSON truth test.")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--dataset-dir", default=str(CASE_DIR))
    parser.add_argument("--models", nargs="*", default=None)
    args = parser.parse_args(argv)

    env_file = Path(args.env_file)
    if env_file.exists():
        load_dotenv(env_file, override=False)
    api_key = os.environ.get("OPENAI_API_KEY", "")
    base_url = os.environ.get("OPENAI_BASE_URL", "")
    if not api_key or not base_url:
        print("missing OPENAI_API_KEY or OPENAI_BASE_URL")
        return 2

    cases = load_llm_cases(Path(args.dataset_dir) / "cases.jsonl")
    reports = []
    for model_name in args.models or list(DEFAULT_CHAT_MODELS):
        generator = HttpGenerator(GeneratorConfig(base_url=base_url, api_key=api_key, model=model_name))
        try:
            report = evaluate_llm(cases, generator)
        except Exception as exc:  # noqa: BLE001
            print(f"skip model={model_name} reason={type(exc).__name__}")
            continue
        finally:
            generator.close()
        reports.append(report)
        print(
            f"model={report.model} mode={report.json_mode} passed={report.passed} "
            f"schema={report.schema_pass_rate:.2f} citation={report.citation_pass} "
            f"safety={report.safety_pass} english={report.english_pass} injection={report.injection_pass}"
        )

    write_llm_run_report(reports, Path(args.dataset_dir) / "last-run.json")
    passed = [report for report in reports if report.passed]
    if not passed:
        print("no model passed the blocking bar; freeze.json was not written")
        return 1
    chosen = passed[0]
    write_llm_freeze_record(chosen, Path(args.dataset_dir) / "freeze.json")
    print(f"froze model={chosen.model} mode={chosen.json_mode}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
