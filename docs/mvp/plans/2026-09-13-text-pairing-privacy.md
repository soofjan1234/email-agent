# 规范化、配对与脱敏实施计划

适用范围：第一版专项验证；[MVP 入口](../README.md) · [验证记录](../validation.md)。

依据已确认设计 [规范化/配对/脱敏验证](../designs/2026-09-13-text-pairing-privacy-design.md)。

## 任务

### T1 规范化

- 新增：`evals/text-v1/normalize/queries.jsonl`、`evals/harness/normalize.py`
- 测试：`tests/eval/test_normalize.py`
- 验证：`pytest tests/eval/test_normalize.py -q`

### T2 历史配对

- 新增：`evals/text-v1/pairing/*.eml`、`expected.jsonl`、`evals/harness/pairing.py`
- 测试：`tests/eval/test_pairing.py`
- 验证：`pytest tests/eval/test_pairing.py -q`

### T3 脱敏

- 新增：`evals/text-v1/privacy/samples.jsonl`、`evals/harness/redact.py`
- 测试：`tests/eval/test_redact.py`
- 验证：`pytest tests/eval/test_redact.py -q`

### T4 运行器

- 新增：`evals/harness/text_cli.py`
- 验证：`PYTHONPATH=. .venv/bin/python -m evals.harness.text_cli`
- 三条都通过才写 `evals/text-v1/freeze.json`
