# 阶段 C：英文页面与整体交付验收

依据[整体计划](../plan.md)，范围与验收以其上游设计为准。以下路径均为拟实施路径；命令在对应文件与依赖建立后执行。

## C1：用页面完成知识管理和客服审核

**依赖**：A3、B3 接口可用。

**文件**：创建 `web/package.json`、`web/package-lock.json`、`web/vite.config.ts`、`web/tsconfig.json`、`web/index.html`、`web/src/main.ts`、`web/src/App.vue`、`web/src/router.ts`、`web/src/api/client.ts`、`web/src/views/MailList.vue`、`web/src/views/MailReview.vue`、`web/src/views/SyncJobs.vue`、`web/src/views/Knowledge.vue`、`web/src/views/CaseReview.vue`、`web/src/views/Outbox.vue`、`web/src/views/MailReview.test.ts`、`web/src/views/CaseReview.test.ts`。

**先写失败测试**：先写组件测试：引用区分产品与案例，编辑后提交最终文本，重复点击不重复请求，409 后提示刷新，初始化时无历史时间选择。无页面时失败。

**最小实施步骤**：按既定 Vue 3、TypeScript、Vite、Element Plus 实现英文界面。提供列表、详情、风险提示、四种审核动作、同步与初始化进度、配对确认和候选发布归档、可信路径产品导入、模拟发件箱。状态以 API 返回为准，不在浏览器补建业务状态机。为测试固定可访问标签与稳定定位；配置 npm test、typecheck、build、test:e2e 脚本。

**验证命令**：

```powershell
npm --prefix web ci
npm --prefix web run test -- --run
npm --prefix web run typecheck
npm --prefix web run build
```

**通过条件**：英文关键操作与错误反馈可用；不能发布未审核案例，不能把过期审核成功显示为已发送；构建及组件检查通过。

## C2：部署并执行固定场景的闭环与真实模型验收

**依赖**：A、B、C1 检查通过。

**文件**：创建 `web/playwright.config.ts`、`web/e2e/mail-flow.spec.ts`、`web/e2e/knowledge-flow.spec.ts`、`tests/acceptance/test_mvp_scenarios.py`、`tests/acceptance/test_audit_privacy.py`、`tests/acceptance/test_live_models.py`、`evals/mvp-v1/cases.json`、`evals/mvp-v1/README.md`、`deploy/mvp/README.md`、`deploy/mvp/web.Dockerfile`；修改 Compose、根 README、`docs/mvp/validation.md`、`docs/mvp/status.md`。

**先写失败测试**：先写完整场景：首次启动历史初始化→人工发布案例→导入产品→新增模拟邮件→生成草稿→编辑批准→查询唯一模拟发件。再写重启待审核恢复、无依据转人工、拒绝、复杂关系排除和敏感信息检查；不依赖真实模型才可稳定复现失败。

**最小实施步骤**：Compose 完成 api/worker/web 启动、独立迁移与健康检查，默认连接本机 PostgreSQL，postgres 容器只作备用 profile。Playwright 用 Fake 模型及真实数据库覆盖 UI 闭环，配置安装 Chromium 并等待服务就绪。固定样例带预期引用、允许/禁止事实和数据哈希，逐项映射总验收。另用显式 live 模型配置运行本地候选 Embedding 与 LLM 的真实检索生成，保存模型身份、输入版本、契约与事实核对结果；无凭据时明确记录未运行。部署文档写启动、迁移、重试、备份恢复和停止命令，停止保留本机数据库及备用卷；验证已有库升级与数据保留，不进行未经授权的业务库清空。

**验证命令**：

```powershell
docker compose --env-file .env -f deploy/mvp/compose.yaml config --quiet
docker compose --env-file .env -f deploy/mvp/compose.yaml build api web
docker compose --env-file .env -f deploy/mvp/compose.yaml run --rm api alembic upgrade head
docker compose --env-file .env -f deploy/mvp/compose.yaml up -d api worker web
docker compose --env-file .env -f deploy/mvp/compose.yaml run --rm api python -m pytest -q
npm --prefix web exec -- playwright install chromium
npm --prefix web run test:e2e
docker compose --env-file .env -f deploy/mvp/compose.yaml run --rm -e RUN_LIVE_MODELS=1 api python -m pytest tests/acceptance/test_live_models.py -q
git diff --check
```

**通过条件**：固定场景全部有结果，真实数据库重启与业务幂等有证据，日志无敏感内容。live 命令在缺少显式配置时应明确失败，不能 skip 后宣称通过。生产冻结所需外部验证未完成时仍保留待验证，不混同本机功能闭环完成。

本阶段目标测试通过后运行整体计划约定的相关回归，记录证据再更新状态账本。不要将本阶段通过等同于整个 MVP 或生产验证通过。
