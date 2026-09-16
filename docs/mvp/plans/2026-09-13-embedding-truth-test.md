# Embedding 网关验证实施计划（已退役）

> 2026-09-15：本计划对应的 API key 网关选型路线已废弃，以下内容仅供历史追溯，命令不作为当前操作指南。新方向见 [Docker 开放模型对比设计](../designs/2026-09-13-embedding-truth-test-design.md)。原代码及历史测试完成状态保留，新部署转入 [Docker 实施计划](2026-09-15-docker-embedding-comparison.md)；不要按本计划自动覆盖冻结记录。

适用范围：第一版专项验证；[MVP 入口](../README.md) · [验证记录](../validation.md)。

依据已确认设计 [Embedding 阻断性验证](../designs/2026-09-13-embedding-truth-test-design.md)。产品语言已冻结为英文。

## 范围

落地方案 A：英文评测集、离线 `HttpEmbedder`、内存余弦检索和冻结报告。不建 PostgreSQL，不搭业务骨架。

## 任务

### T1 评测集契约

- 新增：`evals/embedding-v1/chunks.jsonl`、`evals/embedding-v1/queries.jsonl`、`evals/embedding-v1/corpus/**/*.md`、`evals/embedding-v1/README.md`
- 测试：`tests/eval/test_dataset_contract.py`
- 先写失败测试：规模、`language=en`、分路覆盖、标识查询、知识库外空相关集
- 预期失败：评测文件不存在或规模不足
- 验证：`pytest tests/eval/test_dataset_contract.py -q`
- 前置：无

### T2 指标与分路检索

- 新增：`evals/harness/metrics.py`、`evals/harness/retrieve.py`
- 测试：`tests/eval/test_metrics.py`、`tests/eval/test_retrieve.py`
- 先写失败测试：Recall@3、MRR、标识命中、按 `source_type` 隔离
- 验证：`pytest tests/eval/test_metrics.py tests/eval/test_retrieve.py -q`
- 前置：无

### T3 HTTP Embedder 与运行器

- 新增：`evals/harness/dataset.py`、`evals/harness/embedder.py`、`evals/harness/runner.py`、`evals/harness/cli.py`、`pyproject.toml`
- 测试：`tests/eval/test_embedder.py`、`tests/eval/test_runner.py`
- 先用 httpx mock 验证 `/v1/embeddings` 请求、维度一致性和过线才写 `freeze.json`
- 验证：`pytest tests/eval -q`
- 前置：T1、T2

### T4 真实网关评测

- 命令：`python -m evals.harness.cli --env-file .env`
- 预期：打印每模型 Recall@1 / Recall@3 / MRR、标识命中和维度；过线才写 `evals/embedding-v1/freeze.json`
- 失败时不冻结，只写 `evals/embedding-v1/last-run.json`
- 前置：T3，本地 `.env` 可用

## 最终验证

2026-09-15 补测完成：使用现有 `HttpEmbedder` 与 `evaluate_model` 调用 `local_server` 的 Qwen3 0.6B，独立保存结果，不调用自动冻结入口。真实接口结果与 12 项相关回归证据见[验证记录](../validation.md)，现有冻结记录保持不变。

```text
pytest tests/eval -q
python -m evals.harness.cli --env-file .env
```
