# email-agent

面向海外 NAS 客服与售后人员的英文邮件 Agent。它对客户邮件进行分类和风险识别，检索内部知识，通过 LangGraph 编排查询改写、证据评估、回复生成、质量校验与人工审核，最终生成可追溯的英文回复草稿。

当前仓库已提供应用与数据库底座、A2 历史初始化、A3 案例审核发布与产品文档导入、A4 双路知识检索，以及 Embedding、LLM JSON、文本处理评测代码；增量邮件处理、Agent 和审核页面仍待实现。启动方式见 [本地运行说明](deploy/mvp/README.md)。

## 文档

- [MVP 文档入口](docs/mvp/README.md)
- [总体设计](docs/mvp/design.md)
- [技术选型](docs/mvp/architecture/tech-design.md)
- [数据库设计](docs/mvp/architecture/database-design.md)
- [接口设计](docs/mvp/architecture/api-design.md)
- [验证记录](docs/mvp/validation.md)
- [MVP 整体实施计划](docs/mvp/plan.md)
- [MVP 设计与计划状态](docs/mvp/status.md)

## 核心边界

- 不允许模型直接发送邮件或执行不可逆业务动作。
- 每个建议必须保留检索依据、模型决策和人工处理结果的审计记录。
- 置信度不足、知识依据缺失或涉及敏感信息时，必须进入人工队列。
