# embedding-v1：历史冒烟集与评测证据

本目录保留原英文 NAS 售后夹具。`chunks.jsonl` 和 `queries.jsonl` 是评测输入；`corpus/` 供人工阅读。

## 当前路线

原来的 API key 网关选型说明已废弃。后续采用 [Docker 开放模型对比设计](../../docs/mvp/designs/2026-09-13-embedding-truth-test-design.md)，首轮比较 Qwen3 0.6B、Nomic v1.5、Snowflake M v1.5 和 BGE-M3。容器配置、查询/文档适配及新冒烟入口已实现，见[Docker 操作说明](../../deploy/embedding/README.md)。[v2 扩展集与三轮本地对比](../embedding-v2/RESULTS.md)已完成，独立标签复核与生产验收待完成。旧 Docker Qwen 结果受后续发现的批次缺陷影响，不用于指令优劣或正式选型；见[排查记录](../embedding-v2/QWEN-BATCH-ISSUE.md)。

## 历史证据

- `freeze.json`：2026-09-13 OpenAI small / 1536 的历史冻结摘要，保留追溯，不作为新部署的建库依据。
- [Qwen 补测报告](reports/2026-09-15-qwen3-embedding-0.6b.json)：公司现有 CPU 服务上的小样本结果，不代表新 Docker 对比已完成。
- [验证记录](../../docs/mvp/validation.md)：实际指标及限制。

## 旧工具边界

现有 `evals.harness.cli` 仍要求 `OPENAI_API_KEY` 和 `OPENAI_BASE_URL`，通过后会覆盖 `freeze.json`；它是尚未迁移的旧实现，不是新路线的推荐入口。本文撤下旧执行命令和密钥配置步骤，避免误操作。

新评测应先输出独立报告，选定模型后再创建新冻结记录。历史夹具保持不变，新数据集另行版本化。文档退役不会删除本地 `.env` 或改变已有程序行为。
