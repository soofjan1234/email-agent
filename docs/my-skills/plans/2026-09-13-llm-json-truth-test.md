# LLM JSON 与安全降级验证实施计划

依据已确认设计 [LLM JSON 与安全降级验证](../designs/2026-09-13-llm-json-truth-test-design.md)。

## 范围

落地方案 A：英文生成评测集、`HttpGenerator`、契约校验和冻结报告。不建 Graph。

## 任务

### T1 评测集与契约校验

- 新增：`evals/llm-json-v1/cases.jsonl`、`evals/harness/agent_schema.py`、`evals/harness/llm_cases.py`
- 测试：`tests/eval/test_llm_cases.py`、`tests/eval/test_agent_schema.py`
- 验证：`pytest tests/eval/test_llm_cases.py tests/eval/test_agent_schema.py -q`

### T2 引用、安全与英文判定

- 新增：`evals/harness/llm_judge.py`
- 测试：`tests/eval/test_llm_judge.py`
- 验证：`pytest tests/eval/test_llm_judge.py -q`

### T3 Generator 与运行器

- 新增：`evals/harness/generator.py`、`evals/harness/llm_runner.py`、`evals/harness/llm_cli.py`
- 测试：`tests/eval/test_generator.py`、`tests/eval/test_llm_runner.py`
- 验证：`pytest tests/eval -q`

### T4 真实网关评测

```text
PYTHONPATH=. .venv/bin/python -m evals.harness.llm_cli --env-file .env
```
