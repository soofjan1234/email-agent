# 检索、草稿与审核评估实施子计划

## 目标、前置条件与不做事项

本计划落实 [检索、草稿与人工审核评估设计](../design/retrieval-draft-review-evaluation.md)。完成后，应能在隔离数据库中复算以下结果：

1. 32 封真实未回复邮件与 508 封 synthetic v2 待回复邮件的关键词、向量、RRF 检索效果；
2. Codex 初标、人工抽检及更正后指标；
3. 127 封垃圾邮件的归档覆盖，540 封业务评估集的草稿链路耗时和审核结果；
4. 真实来源、合成来源和总体结果的独立报告。

前置条件如下：

- 只使用既有隔离数据库、`imap-shadow-20260918` 真实基线和新建的 `imap-shadow-20260918-synthetic-v2`；不重新读取 IMAP。
- 资料集必须先达到 8–12 份官方 Markdown 文档并冻结，随后才允许生成检索、草稿或标注结果。
- 所有运行保持 SMTP 未配置，禁止调用 `ReviewService.submit` 自动批准，禁止向真实邮箱写入。
- `data/knowledge/`、`data/evaluation-artifacts/`、`data/synthetic-shadow-mailbox-20260918-v2/` 是受控本地数据；报告只能输出脱敏 ID、计数、模型身份、耗时与标注，不能输出邮件正文、地址或凭据。

执行以下测试前统一设置：

```powershell
$env:PYTHONPATH = (Resolve-Path ./src).Path
$env:PYTHONUTF8 = '1'
.venv/Scripts/python.exe -m pytest <测试文件> -q
```

## 阶段 1：补齐并冻结官方产品资料集

**依赖**：无。后续所有阶段依赖本阶段通过。

**先写失败测试**：新增 `tests/integration/test_product_knowledge_freeze.py`。在仅有当前三份产品资料或资料缺少官方 URL、抓取日期、型号、适用范围时，断言导入和冻结操作失败；测试应先失败，因为当前导入清单只有三项且没有冻结清单。

**修改与新增文件**：

- 修改 `scripts/import_product_knowledge.py`，将固定导入清单扩充至恰好 8 份资料；保留现有三份文件并新增：
  - `data/knowledge/lincstation-e1-lincos-download-upgrade.md`
  - `data/knowledge/lincstation-e1-services-docker.md`
  - `data/knowledge/lincstation-e1-install-network-access.md`
  - `data/knowledge/lincstation-s1-boot-recovery-migration.md`
  - `data/knowledge/lincstation-n1-n2-storage-nvme-thermal-accessories.md`
- 新增上述五份 UTF-8 Markdown。每份首段记录官方 URL、抓取日期、适用型号和适用范围；内容只整理受控支持步骤，不复制长段官网、评论或客户邮件。
- 新增 `scripts/freeze_product_knowledge.py`，查询 active `product_doc`，生成不可覆盖的 `data/evaluation-artifacts/<freeze-id>/knowledge-freeze.json`。文件写入文档 ID/版本/内容哈希、片段数、文档 SHA-256、分块器版本、Embedding 完整身份和索引版本。

**最小实现步骤**：

1. 以 `research.md` 已记录的官方入口为来源，按五个新增主题写受控资料；不将 `research-derived` 内容导入官方知识库。
2. 让 `PRODUCT_DOCUMENTS` 成为唯一导入清单；导入结果中返回标题、版本、状态、来源类型与片段数，但不输出原文。
3. 冻结脚本拒绝少于 8 或多于 12 份 active `product_doc`、重复内容哈希、缺失来源元数据或目录已存在的 freeze ID。
4. 记录 freeze JSON 的 SHA-256，后续 `evaluation_run` 只接受该哈希，不接受可变的“当前知识库”。

**验证命令与通过条件**：

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_product_knowledge_freeze.py tests/integration/test_knowledge_publish.py -q
.venv/Scripts/python.exe scripts/import_product_knowledge.py
.venv/Scripts/python.exe scripts/freeze_product_knowledge.py --freeze-id product-support-v1
```

测试证明资料元数据、受信路径、版本和片段计数正确；实际冻结清单证明 active 产品资料为 8–12 份，且任何后续评估都能引用固定 SHA-256。

## 阶段 2：建立不可变评估运行与结果存储

**依赖**：阶段 1 的冻结清单已生成。

**先写失败测试**：新增 `tests/integration/test_evaluation_persistence.py`，先断言同一 `evaluation_run_id` 不能改变资料集哈希、样本成员、模型身份或 Prompt 版本；当前没有评估表和服务，测试应失败。

**修改与新增文件**：

- 修改 `src/models.py`，新增 `EvaluationRun`、`EvaluationSample`、`RetrievalObservation`、`RetrievalJudgment`、`EvaluationExecution`、`EvaluationSpan` 映射。
- 新增 `migrations/versions/0008_evaluation_runs.py`，为上述表创建外键、唯一键、来源/状态检查约束和按 `evaluation_run_id` 查询的索引。
- 新增 `src/services/evaluation.py`，集中创建运行、冻结样本、记录候选/标注/耗时和只读加载结果。
- 新增 `tests/unit/test_evaluation_contract.py`，覆盖纯数据校验、JSONL 行模式和指标输入边界。

**最小实现步骤**：

1. `EvaluationRun` 保存唯一 ID、目的（`retrieval`、`draft_latency`、`review`）、知识冻结哈希、Embedding 身份、Generator 身份、Prompt 版本、Codex 判定身份、固定随机种子、代码版本与创建时间。
2. `EvaluationSample` 固定关联源 `Email`、`sample_source=real|synthetic_v2`、纳入或排除状态及原因。样本一旦写入运行，不允许增删或换源邮件。
3. `RetrievalObservation` 保存每种检索方式、原始名次、候选片段 ID、耗时和失败状态；`RetrievalJudgment` 保存盲化名次、Codex 初标、置信度、简短依据、抽检状态和最终更正标签。
4. `EvaluationExecution` 保存一次草稿运行与其只读源邮件、尝试序号、结果状态和生成的隔离执行邮件；`EvaluationSpan` 保存该执行的阶段名称、开始时间、持续时间、状态与重试计数。
5. 服务层拒绝未知样本来源、跨运行引用、重复候选标注、缺失必填标签和对已冻结记录的更新；失败、超时和空结果也写入记录。

**验证命令与通过条件**：

```powershell
.venv/Scripts/python.exe -m pytest tests/unit/test_evaluation_contract.py tests/integration/test_evaluation_persistence.py -q
.venv/Scripts/python.exe -m alembic upgrade head
```

测试数据库迁移后，运行、样本、候选、判定和 span 可以审计；重复创建或修改冻结运行均被拒绝，且测试不得修改真实 IMAP 历史任务。

## 阶段 3：生成并安全投影 synthetic v2

**依赖**：阶段 2 的评估存储可用。资料冻结后才可进入草稿分支。

**先写失败测试**：新增 `tests/integration/test_synthetic_shadow_v2.py`。先断言 v2 与 v1 使用不同 mailbox/目录，文件总量仍为 Inbox 1,346、Sent 711，635 封无回复 Inbox 中恰有 127 封触发 `SPAM_MARKERS`、508 封可作为售后输入；当前不存在 v2 生成器，测试应失败。

**新增文件**：

- `scripts/seed_synthetic_shadow_mailbox_v2.py`
- `data/synthetic-shadow-mailbox-20260918-v2/{inbox,sent}/`（运行时生成，Git 忽略）
- `tests/integration/test_synthetic_shadow_v2.py`

**最小实现步骤**：

1. 复用 v1 的稳定配额、`example.invalid` 地址、固定时间窗和 711 组收发关系；v2 文件使用新的 `X-Synthetic-Source` 与 `imap-shadow-20260918-synthetic-v2`，绝不覆写 v1 目录或历史任务。
2. 635 封无回复邮件中写入 127 封符合现有 `SPAM_MARKERS` 的受控垃圾模板；其余 508 封保持 65% 核心 NAS 支持、35% `research-derived` 的匿名售后主题。
3. 加载 v2 历史任务后调用 `MailSyncService.project_unmatched_history()`，只投影 635 封明确 unmatched Inbox；711 组已配对邮件继续只保留为历史候选。
4. 用注入的受控检索/生成替身在测试中调用 `WorkflowDispatcher.dispatch_pending()`：127 封必须归档且 `retrieval_attempts=generation_attempts=0`；508 封到达 `awaiting_review` 或留下可追溯失败记录；不调用审核提交和不创建 `SimulatedOutbox`。

**验证命令与通过条件**：

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_synthetic_shadow_v2.py tests/integration/test_history_init.py tests/unit/test_graph_routes.py -q
.venv/Scripts/python.exe scripts/seed_synthetic_shadow_mailbox_v2.py --output data/synthetic-shadow-mailbox-20260918-v2 --load-and-project
```

实际运行的脱敏汇总严格显示 2,057 源邮件、711 配对、127 归档垃圾邮件、508 待回复业务邮件和 0 条模拟发件；真实 `imap-shadow-20260918` 与 synthetic v1 计数不变。

## 阶段 4：执行三通道检索并生成 Codex 初标输入

**依赖**：阶段 1 的 freeze JSON、阶段 2 的存储、阶段 3 的 508 封待回复邮件。

**先写失败测试**：新增 `tests/integration/test_retrieval_evaluation.py` 与 `tests/unit/test_retrieval_evaluation_metrics.py`。先断言关键词、向量、RRF 在同一 frozen sample 上各保存 Top-3 产品片段和独立耗时，且查询改写次数为零；当前 `RetrievalService.retrieve()` 只暴露融合候选，测试应失败。

**修改与新增文件**：

- 修改 `src/services/retrieval.py`，增加仅供评估调用的三通道读取入口；复用现有 metadata 过滤、向量身份验证、`CHANNEL_CANDIDATE_LIMIT` 与 RRF 常量。
- 修改 `src/services/evaluation.py`，从真实 32 封与 v2 的 508 封中创建固定 540 样本并写入 `RetrievalObservation`。
- 新增 `scripts/run_retrieval_evaluation.py`，只接受 freeze ID、显式 evaluation run ID 和三个固定检索参数；拒绝可变 Top-K、查询改写、approved case 和未冻结资料集。
- 新增 `scripts/export_codex_judge_inputs.py`，在 `data/evaluation-artifacts/<run-id>/` 生成受控 JSONL；每条包含脱敏样本 ID、邮件问题、随机化后的三个候选、稳定映射 ID 和内容哈希，不包含检索通道名称、客户地址或运行凭据。
- 新增 `tests/integration/test_retrieval_evaluation.py`、`tests/unit/test_retrieval_evaluation_metrics.py`。

**最小实现步骤**：

1. 只检索 active `product_doc`；关键词、向量和 RRF 共享同一查询文本、冻结资料、metadata 过滤和 Top-K=3，禁止该运行启用查询改写。
2. 每个通道先记录原始排名、候选 ID、片段版本和 span，再写入不可变观察结果；向量编码、关键词查询、向量查询和 RRF 融合分别计时。
3. 导出脚本对每个“样本 × 检索通道”随机排列三个候选，输出映射哈希；同一运行与随机种子可复现，不同运行不得覆盖已有输入目录。
4. 运行完成但任一标注或检索失败时仍保留失败记录；不把无结果填成相关结果。

**验证命令与通过条件**：

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_retrieval_evaluation.py tests/unit/test_retrieval_evaluation_metrics.py tests/integration/test_retrieval.py -q
.venv/Scripts/python.exe scripts/run_retrieval_evaluation.py --freeze-id product-support-v1 --evaluation-run-id retrieval-v1
.venv/Scripts/python.exe scripts/export_codex_judge_inputs.py --evaluation-run-id retrieval-v1
```

输出可审计地包含 540 个样本的三通道 Top-3、耗时、失败与盲化映射；运行不调用 Generator、Review 或 SMTP。

## 阶段 5：导入 Codex 初标并执行人工抽检校准

**依赖**：阶段 4 的盲化 JSONL 已生成。

**先写失败测试**：新增 `tests/integration/test_codex_judgment_import.py`。先断言缺失候选、映射哈希不匹配、重复标签、未知标签或越权更正会被拒绝；当前没有判定导入器，测试应失败。

**新增文件**：

- `scripts/import_codex_judgments.py`
- `scripts/export_retrieval_audit_sample.py`
- `scripts/import_retrieval_audits.py`
- `scripts/report_retrieval_evaluation.py`
- `tests/integration/test_codex_judgment_import.py`
- `tests/unit/test_retrieval_judgment_metrics.py`

**最小实现步骤**：

1. Codex 仅在受控本地 JSONL 上对每个候选输入 `relevant`、`partially_relevant`、`not_relevant` 或 `no_answer`，并提交置信度和简短依据。导入命令要求显式 `judge_model`、Prompt 版本和 `judge_run_id`，同时校验运行、输入哈希和全部候选的恰好一次覆盖。
2. 抽检导出器选择全部低置信度与 `no_answer`，再按 `sample_source`、检索通道和四类初标结果分层，以冻结随机种子抽取其余 10%。同一输入运行只能导出同一抽检集合。
3. 人工抽检结果只允许 `confirmed`、`corrected`、`unable_to_judge`；`corrected` 必须给出最终标签。导入后不覆盖 Codex 原标签，而是追加审计事实。
4. 指标脚本按“有至少一个相关片段”计算 Recall@1/Recall@3，按第一个相关片段位置计算 MRR@3，并输出 `no_answer` 误命中率、无依据片段率、Codex 与人工一致率和使用更正标签后的指标；总评估集、真实来源和合成来源各自一组。

**验证命令与通过条件**：

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_codex_judgment_import.py tests/unit/test_retrieval_judgment_metrics.py -q
.venv/Scripts/python.exe scripts/import_codex_judgments.py --evaluation-run-id retrieval-v1 --input data/evaluation-artifacts/retrieval-v1/codex-judgments.jsonl --judge-model codex --prompt-version retrieval-judge-v1
.venv/Scripts/python.exe scripts/export_retrieval_audit_sample.py --evaluation-run-id retrieval-v1
.venv/Scripts/python.exe scripts/import_retrieval_audits.py --evaluation-run-id retrieval-v1 --input data/evaluation-artifacts/retrieval-v1/human-audits.jsonl
.venv/Scripts/python.exe scripts/report_retrieval_evaluation.py --evaluation-run-id retrieval-v1 --format markdown
```

报告明确区分“Codex 判定”与“人工抽检校准后”指标。若规定抽检未完成，报告只输出成功率、返回数量和耗时，不把初标写成已校准的检索正确率。

## 阶段 6：采集草稿链路 P95 并汇总人工审核事实

**依赖**：阶段 3、阶段 4 完成；实际 Generator 身份、Prompt 与并发度已固定并写入 `EvaluationRun`。

**先写失败测试**：新增 `tests/integration/test_draft_evaluation_runner.py` 与 `tests/integration/test_evaluation_review_report.py`。先断言每个执行记录拥有完整 span、垃圾邮件没有检索/生成 span、普通样本只到 `awaiting_review`、运行不会创建 `SimulatedOutbox`；当前没有评估执行器和 span 记录，测试应失败。

**修改与新增文件**：

- 修改 `src/workflow/nodes.py`，为 `SafeDraftProcessor` 增加可选评估 tracer，覆盖风险预检、向量编码、三通道检索/RRF、查询改写、Generator、输出校验与草稿持久化；非评估路径行为保持不变。
- 修改 `src/services/dispatch.py`，让评估执行器能够在独立 `EvaluationExecution` 上创建新的 Graph thread 并采集端到端 span，不重放或覆盖源邮件已有 checkpoint。
- 修改 `src/services/evaluation.py`，创建受控执行邮件、保存 attempt 与结果，并关联一份源邮件的人工最终 `Review`。
- 新增 `scripts/run_draft_evaluation.py` 与 `scripts/report_draft_review_evaluation.py`。
- 新增 `tests/integration/test_draft_evaluation_runner.py`、`tests/integration/test_evaluation_review_report.py`。

**最小实现步骤**：

1. 对每个纳入样本创建新的隔离执行邮件和唯一 graph thread；源 `Email`、真实 mailbox、v1 历史和 v2 原始历史均不更新。执行器从不提交 `Review`，因此不会产生模拟发件。
2. 总体 P50/P95 只使用每个纳入样本的一次主执行，确保真实 32 封与合成 508 封各占一个样本权重。真实功能组在主执行外额外运行 8 次，连同主执行构成每封 9 次正式记录；这些额外记录只用于真实组的稳定性和重试分析，不混入 540 样本的总体 P95。
3. 127 封垃圾邮件各运行一次，只验证归档和零检索/零生成；508 封 v2 待回复邮件各运行一次，形成容量组。每次重跑必须使用新的 `evaluation_run_id`，不覆盖已有结果。
4. 报告分别输出总体、真实功能组、v2 容量组的端到端和分段 P50/P95/最大值、失败数、重试数及耗时最高的单个可测步骤；不得将各步骤 P95 相加。
5. 真实与 v2 原始邮件在人工界面审核后，报告按关联 `Review.action` 计算直接批准、编辑后批准、拒绝、转人工、总可接受率和免编辑批准率；等待审核、失败、归档和无最终 Review 单独列出。编辑成本只对 `edit_and_approve` 的 `original_draft` 与 `final_content` 计算。

**验证命令与通过条件**：

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_draft_evaluation_runner.py tests/integration/test_evaluation_review_report.py tests/integration/test_grounded_draft.py tests/integration/test_review_idempotency.py -q
.venv/Scripts/python.exe scripts/run_draft_evaluation.py --evaluation-run-id draft-v1 --freeze-id product-support-v1
.venv/Scripts/python.exe scripts/report_draft_review_evaluation.py --evaluation-run-id draft-v1 --format markdown
```

测试和实际报告均证明：127 封垃圾邮件归档且零检索/零生成，508 封待回复邮件到达待审核或有可追溯失败，所有评估执行的 `SimulatedOutbox` 数量为 0。人工审核报告只统计真实人工最终动作，Codex 不得批准或发送。

## 阶段 7：生成脱敏总报告并完成回归验证

**依赖**：阶段 1 至阶段 6 均通过，或明确记录无法继续的受控失败。

**先写失败测试**：新增 `tests/integration/test_evaluation_reports.py`。先断言报告遗漏来源拆分、冻结身份、失败数、抽检一致率、垃圾邮件零调用或泄露正文/地址时失败。

**修改文件**：

- 修改 `scripts/report_retrieval_evaluation.py`、`scripts/report_draft_review_evaluation.py`，生成 JSON 与 Markdown 两种脱敏报告。
- 修改 `docs/changes/2026-09-18-real-imap-shadow-test/validation.md`，只记录实际命令、运行 ID、资料冻结 SHA、计数、耗时、抽检结果、未测项和失败原因。
- 修改 `docs/changes/2026-09-18-real-imap-shadow-test/status.md`，将本子计划状态更新为实际达到的阶段，不把计划或局部测试写成生产结论。
- 新增 `tests/integration/test_evaluation_reports.py`。

**最小实现步骤**：

1. JSON 报告供复算，Markdown 报告供阅读；两者都按总体、`real`、`synthetic_v2` 三个口径分节。
2. 检查报告不含原始主题、正文、地址、凭据、草稿正文、目录绝对路径和数据库 URL。
3. 用同一运行 ID 的冻结哈希、样本计数、观察记录、判定记录、抽检记录、执行记录和 Review 记录交叉校验总数；任何不一致在报告中作为失败，不静默丢弃。

**验证命令与通过条件**：

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_evaluation_reports.py tests/eval tests/unit -q
git diff --check
$forbidden = ('TO' + 'DO', 'TB' + 'D') -join '|'
rg -n $forbidden docs/changes/2026-09-18-real-imap-shadow-test/plans/2026-09-18-retrieval-draft-review-evaluation.md
```

最终报告可回答：各检索方式在固定资料集上的相关性与耗时、Codex 初标和人工校准差异、草稿链路 P95 瓶颈、127/508 流程覆盖，以及人工审核动作分布；不会将合成结论表述成真实客户效果或执行真实发信。

## 停止条件与交付顺序

- 产品资料少于 8 份、缺少官方来源元数据或冻结哈希不一致时，停止阶段 2 之后的全部评估。
- v2 目录、mailbox ID、历史任务或源邮件计数与 v1/真实基线发生交叉时，停止并保留数据库和本地文件供审计。
- Codex 标注输入映射、标签覆盖或人工抽检不完整时，只报告非质量指标，不发布 Recall/MRR 等正确率结论。
- 任何尝试连接 IMAP、SMTP，或在评估执行中创建 `SimulatedOutbox` 时，停止该运行并标记失败。

推荐交付顺序为：阶段 1 → 阶段 2 → 阶段 3 → 阶段 4 → 阶段 5 → 阶段 6 → 阶段 7。每个阶段通过后再执行下一个阶段，避免未冻结资料、未审计样本或未校准标注污染后续结论。
