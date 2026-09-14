"""命令行入口：比较网关上的可用 Embedding 模型。"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from dotenv import load_dotenv

from evals.harness.dataset import DATASET_DIR, load_dataset
from evals.harness.embedder import EmbedderConfig, HttpEmbedder
from evals.harness.runner import evaluate_model, write_freeze_record, write_run_report

# 按设计优先级探测；网关没有的模型会被跳过。
DEFAULT_MODEL_CANDIDATES = (
    "text-embedding-3-small",
    "bge-m3",
    "BAAI/bge-m3",
    "bge-large-en-v1.5",
    "BAAI/bge-large-en-v1.5",
)


def _load_env(env_file: Path) -> None:
    if env_file.exists():
        load_dotenv(env_file, override=False)


def _select_freeze_report(reports: list) -> object | None:
    passed = [report for report in reports if report.passed]
    if not passed:
        return None
    return sorted(passed, key=lambda report: (report.dimensions or 10**9, report.model))[0]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the English embedding truth test.")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--dataset-dir", default=str(DATASET_DIR))
    parser.add_argument("--models", nargs="*", default=None)
    args = parser.parse_args(argv)

    _load_env(Path(args.env_file))
    api_key = os.environ.get("OPENAI_API_KEY", "")
    base_url = os.environ.get("OPENAI_BASE_URL", "")
    if not api_key or not base_url:
        print("missing OPENAI_API_KEY or OPENAI_BASE_URL")
        return 2

    dataset = load_dataset(Path(args.dataset_dir))
    model_names = args.models or list(DEFAULT_MODEL_CANDIDATES)
    reports = []
    for model_name in model_names:
        embedder = HttpEmbedder(EmbedderConfig(base_url=base_url, api_key=api_key, model=model_name))
        try:
            # 1. 先用单条文本探测模型是否存在，避免整集失败后才发现 404。
            embedder.embed(["ping"])
            report = evaluate_model(dataset, embedder)
        except Exception as exc:  # noqa: BLE001 - 网关错误只跳过该模型
            print(f"skip model={model_name} reason={type(exc).__name__}")
            continue
        finally:
            embedder.close()
        reports.append(report)
        print(
            f"model={report.model} dim={report.dimensions} passed={report.passed} "
            f"product_r@3={report.summary.get('product_doc', {}).get('recall_at_3')} "
            f"case_r@3={report.summary.get('approved_case', {}).get('recall_at_3')} "
            f"identifier_failed={report.identifier_hits['failed']}"
        )

    run_path = Path(args.dataset_dir) / "last-run.json"
    write_run_report(reports, run_path)
    freeze_report = _select_freeze_report(reports)
    freeze_path = Path(args.dataset_dir) / "freeze.json"
    if freeze_report is None:
        print("no model passed the blocking bar; freeze.json was not written")
        return 1
    write_freeze_record(freeze_report, freeze_path)
    print(f"froze model={freeze_report.model} dim={freeze_report.dimensions} path={freeze_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
