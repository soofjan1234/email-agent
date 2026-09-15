# embedding-v1

英文 NAS 售后 Embedding 阻断性评测集。`chunks.jsonl` 和 `queries.jsonl` 是评测输入；`corpus/` 仅供人工阅读。

运行：

```text
python -m evals.harness.cli --env-file .env
```

当前冻结为 `text-embedding-3-small` / 1536，先用这一套继续推进。其他 Embedding 等有可用 key 后再跑同一评测集补测。

过线后才会写入 `freeze.json`。`last-run.json` 保存最近一次摘要，不含向量全文。
