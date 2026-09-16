# 阶段 B：新邮件到审核模拟发送

依据[整体计划](../plan.md)，范围与验收以其上游设计为准。以下路径均为拟实施路径；命令在对应文件与依赖建立后执行。

## B1：证明新邮件能够持久化启动并中断恢复

**依赖**：A1 可先做最小恢复探针；正式切片依赖 A2。

**文件**：创建 `src/workflow/graph.py`、`src/workflow/state.py`、`src/services/dispatch.py`、`src/api/emails.py`、`tests/integration/test_graph_recovery.py`、`tests/integration/test_incremental_sync.py`；修改 `src/worker.py`、`src/services/mail_sync.py`。

**先写失败测试**：先用最小 Fake 节点运行到 interrupt，退出进程后用新进程连接同一数据库恢复同一 thread；当前未接入 Checkpointer，应失败。并发两个调度进程必须只执行同一邮件一次。

**最小实施步骤**：接入 PostgreSQL Checkpointer 与稳定 thread/generation。增量同步幂等保存新收件，薄调度器发现未启动任务并启动 Graph；不维护第二套节点状态机。邮件状态仅查询投影，恢复以 checkpoint 为准。覆盖初始化边界之后的新增文件，不把旧历史邮件送进 Graph。实现失败节点重放、投影修复及保留策略验证。

**验证命令**：

```powershell
docker compose --env-file .env -f deploy/mvp/compose.yaml build api
docker compose --env-file .env -f deploy/mvp/compose.yaml run --rm api python -m pytest tests/integration/test_incremental_sync.py tests/integration/test_graph_recovery.py -q
```

**通过条件**：真实进程重启后仍定位同一 interrupt；同 thread 不并发，增量重复提交无重复邮件，投影损坏不改变 Graph 路径。

## B2：基于知识生成可审核的安全草稿

**依赖**：A4、B1。

**文件**：创建 `src/workflow/nodes.py`、`src/adapters/generator.py`、`src/services/output_validation.py`、`src/prompts/agent.txt`、`tests/unit/test_graph_routes.py`、`tests/integration/test_grounded_draft.py`、`tests/fixtures/agent/cases.json`；修改 `src/workflow/graph.py`；复用已验证 JSON schema 与评测检查规则。

**先写失败测试**：先用固定 Fake 响应覆盖 spam、VIP、普通邮件、仅案例、无答案、冲突、高风险、非法 JSON、越界引用和提示注入；断言具体路径及最终结果，未实现节点时失败。计数器达到上限必须终止，不能只检测文本含警告。

**最小实施步骤**：实现分类、证据评估、查询改写、生成与后端校验。产品事实只允许产品片段支持，案例只供措辞；校验引用属于本次检索并实际支持结论。网络临时重试、查询改写和重新生成分别计数并有上限。不足或风险生成限定草稿；持续非法输出转人工并保留失败原因，不把非法结果送到审核 interrupt。通过校验后等待人工。

**验证命令**：

```powershell
docker compose --env-file .env -f deploy/mvp/compose.yaml build api
docker compose --env-file .env -f deploy/mvp/compose.yaml run --rm api python -m pytest tests/unit/test_graph_routes.py tests/integration/test_grounded_draft.py tests/eval/test_agent_schema.py tests/eval/test_llm_judge.py -q
```

**通过条件**：各既定路径可复现，计数不越限，高风险无危险步骤，无产品依据不生成确定性方案；假模型检查和真实模型抽测分别记录。

## B3：审核恢复、模拟发送和新案例生成

**依赖**：B2。

**文件**：创建 `src/services/reviews.py`、`src/repositories/reviews.py`、`src/api/reviews.py`、`src/api/outbox.py`、`tests/integration/test_review_idempotency.py`、`tests/integration/test_send_replay.py`；修改 Graph 节点和候选服务。

**先写失败测试**：先测试四种审核动作、旧 checkpoint、并发批准、重复请求，以及审核落库后恢复前和模拟发送写入后 checkpoint 前崩溃。没有跨恢复幂等处理时应观察到失败，不用同进程内存去重掩盖问题。

**最小实施步骤**：校验真实 interrupt 和 thread/checkpoint 身份，审核事实幂等落库，再由恢复入口推进 Graph。实现落库与恢复之间中断的重试，重复请求不能丢失未完成恢复。批准及编辑批准写模拟发件记录并生成唯一候选；拒绝/转人工不写发件。候选不自动 active。审计包含动作、最终内容引用、模型和 Prompt 版本，日志脱敏。

**验证命令**：

```powershell
docker compose --env-file .env -f deploy/mvp/compose.yaml build api
docker compose --env-file .env -f deploy/mvp/compose.yaml run --rm api python -m pytest tests/integration/test_review_idempotency.py tests/integration/test_send_replay.py tests/integration/test_graph_recovery.py -q
```

**通过条件**：每个审核最多一条发件和一个来源候选；重放能补齐中断步骤，重复/冲突返回符合契约，真实网络发件次数为零。

本阶段目标测试通过后运行整体计划约定的相关回归，记录证据再更新状态账本。不要将本阶段通过等同于整个 MVP 或生产验证通过。
