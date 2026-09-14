# email-agent

面向海外 NAS 客服与售后人员的英文邮件 Agent。它对客户邮件进行分类和风险识别，检索内部知识，通过 LangGraph 编排查询改写、证据评估、回复生成、质量校验与人工审核，最终生成可追溯的英文回复草稿。

当前仓库只完成项目初始化与 MVP 范围定义，尚未包含业务代码。

## 文档

- [MVP 范围与验收标准](docs/mvp.md)
- [总体设计](docs/my-skills/designs/2026-09-10-nas-after-sales-email-agent-design.md)
- [技术选型](docs/tech-design.md)
- [数据库设计](docs/database-design.md)
- [接口设计](docs/api-design.md)

## 核心边界

- 不允许模型直接发送邮件或执行不可逆业务动作。
- 每个建议必须保留检索依据、模型决策和人工处理结果的审计记录。
- 置信度不足、知识依据缺失或涉及敏感信息时，必须进入人工队列。
