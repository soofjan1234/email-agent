# MVP 专项验证记录

本页汇总已有评测证据及本地回归结果，不重新定义验收标准。专项通过条件见 [MVP 入口中的验证设计](README.md#专项验证材料)，整体完成条件见 [MVP 范围](README.md)。工作进度以[状态账本](../status/2026/09.md)为准。

## 2026-09-13 已提交的评测记录

| 专项 | 仓库记录 | 证据 |
| --- | --- | --- |
| Embedding | `text-embedding-3-small`，1536 维；产品文档与案例 Recall@3 均为 1.0 | [冻结记录](../../evals/embedding-v1/freeze.json) |
| LLM JSON | `gpt-4o-mini`，`json_schema`；Schema 合法率 1.0，引用和安全检查通过 | [冻结记录](../../evals/llm-json-v1/freeze.json) |
| 英文规范化、配对与脱敏 | 保存了英文规则版本、协议头优先配对及脱敏占位符 | [冻结记录](../../evals/text-v1/freeze.json) |

以上为周末提交中保存的结果，2026-09-15 未重新调用真实模型网关。冻结文件仅保留摘要，不能据此宣称大规模效果、生产稳定性或端到端集成已验证。运行方式与夹具分别见 [Embedding](../../evals/embedding-v1/README.md)、[LLM JSON](../../evals/llm-json-v1/README.md)、[文本处理](../../evals/text-v1/README.md)。

## 2026-09-15 本地回归

在 Windows、Python 3.12 的项目虚拟环境中执行：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

结果：32 项测试通过。该结果证明现有自动测试在本机通过，不代表真实网关评测重跑。

PostgreSQL 检索、LangGraph Checkpointer、审核恢复、有限循环和业务副作用幂等仍需在业务实现中完成集成验证，具体要求见[技术选型第 15 节](tech-design.md#15-分阶段技术验证)。
