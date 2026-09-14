# llm-json-v1

英文 Agent JSON 与安全降级评测集。`cases.jsonl` 是唯一评测输入。

```text
PYTHONPATH=. .venv/bin/python -m evals.harness.llm_cli --env-file .env
```

过线后才写入 `freeze.json`。
