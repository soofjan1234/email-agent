# 英文规范化、历史配对与脱敏验证设计

> 历史验证边界：本文保留 2026-09-13 专项的样例与通过条件。2026-09-16 已确认的业务范围以[总体设计 9.1](../design.md#91-历史邮件配对与案例生产)为准：仅完整关联确定的一对一可生成案例，复杂或不确定关系留到第二版。本文的 `needs_review` 歧义拦截不代表允许人工将复杂关系纳入 MVP，也不证明启动初始化已实现。

适用范围：第一版专项验证；[MVP 入口](../README.md) · [验证记录](../validation.md)。

## 1. 背景与当前事实

技术选型 15.1 第 3–5 条要求在建 Graph 前完成：

3. 英文关键词规范化冒烟，确认 NAS 型号、错误码、协议和命令不被破坏。
4. 用确定性协议头的 `.eml` 验证历史邮件配对；模糊配对调优不阻塞第一版。
5. 用含个人信息和设备标识的样例验证清洗脱敏。

已冻结：产品语言为英文；LLM 为 `gpt-4o-mini`。2026-09-13 验证时的 Embedding 为 `text-embedding-3-small` / 1536，仅作为历史背景；2026-09-15 已转为 [Docker 开放模型对比](2026-09-13-embedding-truth-test-design.md)，本地扩展集三轮对比已完成，生产模型与维度尚未冻结。第 3–5 条离线验证已于 2026-09-13 通过，记录见 `evals/text-v1/freeze.json`，该结论不受 Embedding 路线变更影响。6–8 条仍依赖 Checkpointer 与业务副作用，本设计不覆盖。

主设计 9.3 的占位符示例仍是中文。本次按英文产品语言改为英文占位符。

## 2. 目标与非目标

### 2.1 目标

- 证明规范化会单独保留 `RAID5`、`S.M.A.R.T.`、`SMB`、型号和错误码。
- 证明 `In-Reply-To` / `References` / `Message-ID` 能确定配对；一对多或无协议头歧义进入 `needs_review`。
- 证明案例文本在发布前去掉邮箱、电话、地址、序列号、外网地址、账号和令牌，原文仍留给审计。
- 留下可重复夹具和纯函数，供后续关键词检索与案例生产复用。

### 2.2 非目标

- 不建 FastAPI、PostgreSQL、LangGraph 或审核页。
- 不比较多种分词/词干方案，不测模糊配对 Precision/Recall。
- 不调用大模型做配对或脱敏。
- 不做 15.1 第 6–8 条。

## 3. 候选方案

| 方案 | 做法 | 优点 | 代价 | 结论 |
| --- | --- | --- | --- | --- |
| A. 一批离线夹具 + 三个纯函数 | `normalize`、`pair_emails`、`redact` 共用 `evals/text-v1/` | 与前两次验证同形态；三条一起交付 | 不证明 PostgreSQL `english` 词干的真实行为 | **已确认** |
| B. 先起 PostgreSQL 只测 `tsvector` | 第 3 条更接近上线检索 | 为冒烟引入数据库 | 业务表未建，为本专项提前引入数据库 | 不采用 |
| C. 三条各做一套独立实验 | 边界更清晰 | 重复脚手架 | 无必要 | 不采用 |

## 4. 已确认方案

2026-09-13 已确认采用方案 A，不采用 B、C。三条共用一个评测包，分别冻结规则，不冻结新模型。

### 4.1 英文规范化

在应用侧先抽出并保护标识，再对其余英文做保守规范化（小写、去多余标点、去掉通用停用词）。保护项至少包括：

- 型号：`DS920+`、`DS220+`、`DS1821+`
- 阵列与协议：`RAID5`、`RAID6`、`SMB`、`S.M.A.R.T.`
- 错误码与版本：`error 13`、`DSM 7.2`

通过线：每条标识查询的保护项都出现在规范化 token 列表中；原文不被修改。

### 4.2 历史配对

夹具使用虚构英文 `.eml`，放在仓库评测目录，不进 `data/`。

规则：

1. 回复 `In-Reply-To` 或 `References` 命中唯一收件 `Message-ID` → `paired` / `header`。
2. 一个回复命中多个收件，或没有协议头且主题/双方无法唯一确定 → `needs_review`。
3. 不使用模型，不做模糊阈值调参。

通过线：确定性样例 100% 配对正确；歧义样例 100% 进入 `needs_review`，不得自动 `paired`。

### 4.3 清洗脱敏

输入是虚构英文邮件/回复，输出是案例候选文本。占位符使用英文类型名，例如 `[email]`、`[phone]`、`[device serial]`、`[public ip]`、`[account]`、`[access token]`。

必须移除或替换：邮箱、电话、街道地址、设备序列号、公网 IP、账号、访问令牌。签名和引用链从案例文本去掉，审计侧仍保留原文引用。

通过线：案例文本中检测不到上述原始值；每种敏感类型至少出现一次并被替换；原文字段仍可对照。

## 5. 评测集契约

```text
evals/text-v1/
  normalize/queries.jsonl
  pairing/*.eml
  pairing/expected.jsonl
  privacy/samples.jsonl
  README.md
```

`normalize/queries.jsonl` 每行含 `query`、`must_keep`。  
`pairing/expected.jsonl` 每行含收件/回复文件、期望 `status` 与 `pairing_method`。  
`privacy/samples.jsonl` 每行含 `source_text`、`must_not_appear`、`required_placeholders`。

规模下限：规范化 ≥ 8 条；配对 ≥ 4 对（至少 3 对确定、1 对歧义）；脱敏 ≥ 6 条，覆盖全部敏感类型。

## 6. 通过与输出

三条必须全部通过才算本批完成。通过后写入 `evals/text-v1/freeze.json`：

- `index_version`：`text-v1`
- `normalizer`：`protect_identifiers_then_english`
- `pairing`：`header_first`
- `redaction_placeholders`：英文类型名列表
- `primary_language`：`en`
- `evaluated_at`

不写模型名。失败不冻结。

## 7. 风险

- 夹具禁止真实客户数据。
- 脱敏只处理案例候选，不删除审计原文。
- 本批不证明 PostgreSQL `tsvector`；接入数据库后用同一 `must_keep` 集再做一次集成冒烟。

## 8. 已决策

- 第 3–5 条按方案 A 做成同一批离线验证。
- 不先起 PostgreSQL，不把 6–8 条纳入本批。
