# NAS 售后邮件回复 Agent：接口设计

## 1. 通用约定

- 接口统一使用 `/api/v1` 前缀和 JSON。
- 资源 ID 使用 UUID。
- 分页接口使用 `page` 和 `page_size`。
- 参数校验失败返回 `400`，资源不存在返回 `404`，幂等键内容冲突或状态冲突返回 `409`。
- 错误响应至少包含 `code`、`message` 和 `request_id`。
- 修改状态的接口必须携带幂等键或预期旧状态。
- 接口不得返回模型密钥、未脱敏凭据或不必要的完整审计数据。

## 2. 邮件同步

### `POST /api/v1/mail-sync-jobs`

请求字段：

- `sync_request_id`：同步请求幂等键；
- `mode`：`incremental` 或 `historical_backfill`；
- `start_time`、`end_time`：历史回溯的时间范围。

`incremental` 从上次成功同步位置拉取新邮件，不接受时间范围。`historical_backfill` 必须提供合法的 `start_time` 和 `end_time`，并同时拉取该范围内的历史收件和已发送邮件。

第一版调用 `MockMailboxAdapter` 从模拟邮箱数据源主动拉取；第二版替换为真实邮箱适配器，接口契约保持不变。

首次提交返回 `202` 和同步任务 ID。相同幂等键及相同参数返回已有任务；相同幂等键但参数不同返回 `409`。同一邮箱存在范围重叠的运行中任务时返回 `409`，避免重复并发拉取。

### `GET /api/v1/mail-sync-jobs/{id}`

返回：

- 同步模式和时间范围；
- `pending`、`running`、`succeeded` 或 `failed` 状态；
- 已扫描、已新增、已跳过和失败的邮件数量；
- 最新同步游标或历史回溯进度；
- 失败类型和可重试信息。

增量同步成功后，新邮件自动进入 Agent 处理流程。历史回溯成功后，系统自动启动收件与人工回复配对，但不会直接向量化原始邮件。

## 3. 邮件查询

### `GET /api/v1/emails`

支持按 `status`、`category` 和 `priority` 过滤，并使用 `page`、`page_size` 分页。`status` 是查询投影，不作为 LangGraph 流程控制依据。

### `GET /api/v1/emails/{id}`

返回原邮件、当前状态、Agent 建议、引用、回复草稿和审核历史。

## 4. 人工审核

### `POST /api/v1/emails/{id}/reviews`

请求包含：

- `review_request_id`；
- `graph_thread_id` 和 `checkpoint_id`，用于定位当前待处理 interrupt；
- 审核动作；
- 最终回复内容；
- 人工修正后的分类、优先级和风险；
- 审核意见。

重复请求使用 `review_request_id` 幂等。服务端必须确认指定 thread 当前停在匹配的人工审核 interrupt；不匹配、已经恢复或存在并发审核时返回 `409`。审核结果落库后，使用同一 `thread_id` 和 `Command(resume=...)` 恢复 Graph；`emails.status` 只用于页面列表展示，不能代替 interrupt 校验。

## 5. 模拟发件箱

- `GET /api/v1/outbox`；
- `GET /api/v1/outbox/{id}`。

模拟发送只写数据库，不执行任何网络请求。只有审核批准的回复才能生成模拟发件记录。

## 6. 产品知识导入

### `POST /api/v1/knowledge/import`

仅供本地管理操作使用。请求指定受信任的仓库内相对路径；后端禁止绝对路径、路径穿越和工作区外文件。

## 7. 历史邮件配对

### `GET /api/v1/case-pairs`

通过 `sync_job_id` 和 `status` 查询历史回溯任务产生的自动配对及待人工确认结果。

### `POST /api/v1/case-pairs/{id}/confirm`

确认或修正配对关系，生成候选案例。重复确认不得创建重复配对和候选案例。

## 8. 候选案例审核与发布

### 查询

- `GET /api/v1/case-candidates?status=`；
- `GET /api/v1/case-candidates/{id}`。

### 审核

`POST /api/v1/case-candidates/{id}/review`

保存清洗、脱敏、适用条件和事实来源审核结果。

### 发布

`POST /api/v1/case-candidates/{id}/publish`

只有 `reviewed` 候选可以发布。发布后生成 `active approved_case`，并触发切分与嵌入。

### 归档

`POST /api/v1/case-candidates/{id}/archive`

停止检索已发布案例，但保留历史引用和审计记录。已发布案例的修改必须生成新版本。

数据库实体和幂等约束见[数据库设计](database-design.md)，总体流程见[技术设计](my-skills/designs/2026-09-10-nas-after-sales-email-agent-design.md)。
