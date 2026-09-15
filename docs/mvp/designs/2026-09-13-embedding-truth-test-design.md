# Embedding 阻断性验证设计

适用范围：第一版专项验证；[MVP 入口](../README.md) · [验证记录](../validation.md)。

## 1. 背景与当前事实

技术选型 15.1 第 1 条要求：在建库前用小规模固定 NAS 查询集比较可用 Embedding 模型，确认基本 Recall@K 后冻结模型和向量维度。Embedding 或维度变更会触发全量重嵌入，不能在同一向量列混用。

本地已提供 OpenAI-compatible 网关配置（`.env`，不入库）：`OPENAI_BASE_URL` 指向 `https://api.ztoken.pro/v1`。2026-09-13 英文评测已通过：`text-embedding-3-small`，1536 维，两路 Recall@3 均为 1.0。同网关对 BGE 返回「无可用渠道」。当前先冻结并继续用这一个模型推进后续工作；其他 Embedding 等拿到可用 key 后再用同一评测集补测。冻结记录见 `evals/embedding-v1/freeze.json`。

已冻结、本验证不得改动的约束：

- 目标用户为海外售后；客户邮件、知识库、回复草稿和本次评测全部使用英文。
- 生产接入走 `Embedder.embed(texts)`，底层使用 OpenAI-compatible HTTP。
- 检索按 `product_doc` 和 `approved_case` 分路，每路最多 3 条。
- MVP 向量检索是 pgvector 精确余弦；本验证只证明模型本身的召回，不比较关键词、RRF 或重排。
- 测试夹具不得存放真实客户数据。

## 2. 目标与非目标

### 2.1 目标

- 冻结第一版唯一 Embedding 模型名、向量维度和索引版本标签。
- 证明该模型在固定英文 NAS 样例上，对产品文档和已审核案例都能达到基本 Recall@3。
- 证明英文查询中的产品标识（型号、错误码、`RAID5`、`S.M.A.R.T.`、`SMB`）不会导致相关片段掉出 Top-3。
- 留下可重复运行的评测集、脚本和冻结记录，供后续换模型时对照。

### 2.2 非目标

- 不搭建 FastAPI、PostgreSQL、LangGraph 或审核页面。
- 不比较分词方案、RRF 参数、召回数量或重排模型。
- 不把中文查询纳入评测集或冻结条件。
- 不把本次分数表述为全局最优，只判定是否越过建库门槛。
- 不在未获凭据时虚构“已验证通过”的模型名。

## 3. 候选方案

### 3.1 怎么跑

| 方案 | 做法 | 优点 | 代价 | 结论 |
| --- | --- | --- | --- | --- |
| A. 离线评测脚本 + 内存余弦 | 评测集入库外文件；同一 `Embedder` 适配器对语料和查询编码；NumPy 余弦取 Top-K | 与“建库前验证”一致；不引入表结构；和生产接口同协议 | 不证明 pgvector 索引行为 | **已确认** |
| B. 先建最小 pgvector | 为本次验证单独建库和 `vector(N)` 列 | 更接近上线检索 | 维度未冻结就建列，正好踩中要避免的重嵌入 | 不采用 |
| C. 仅本地 sentence-transformers | 不走 HTTP，直接加载开源权重 | 无凭据也能出数 | 和生产 `Embedder` 不是同一路径，冻结结果可能作废 | 仅当生产也改为本地模型时才考虑 |

### 3.2 比哪些模型

只比较**同一网关上实际可用**、且能通过 OpenAI-compatible `/v1/embeddings` 调用的模型。下表是预调研候选，不是已冻结名单。

| 方案 | 来源 | 默认维度 | 仍维护 | 英文售后 / 标识 | 部署风险 | 是否纳入本次 | 理由 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| OpenAI `text-embedding-3-small` | [OpenAI Embeddings](https://developers.openai.com/api/docs/guides/embeddings) | 1536 | 是 | 英文检索基线，支持型号和协议标识 | 依赖 OpenAI 或兼容代理 | 网关有则优先测 | 面向海外英文邮件，作为默认对照 |
| BGE-M3 | [Hugging Face 模型卡](https://huggingface.co/BAAI/bge-m3)；多家网关提供兼容接口 | 1024 | 是 | 英文与术语标识都强，长文本 8192 | 需确认网关是否提供 | 网关有则测 | 维度更小，适合作为 small 的对照 |
| 英文专用 BGE（如 `bge-large-en-v1.5`） | [BGE 模型卡](https://huggingface.co/BAAI/bge-large-en-v1.5) | 1024 | 是 | 英文检索成熟 | 需确认网关是否提供 | 网关有则测 | 现在用户是海外英文，不再因为中文不足而排除 |
| OpenAI `text-embedding-3-large` | 同上 OpenAI 文档 | 3072 | 是 | 通常优于 small | 向量宽，后续存储和备份更贵 | 默认不测 | 第一版没有证据需要 3072；small 不达标再补测 |
| 通义 `text-embedding-v3` / `v4` | [DashScope 文本向量](https://help.aliyun.com/zh/model-studio/text-embedding-synchronous-api)、[OpenAI 兼容接口](https://docs.qwencloud.com/api-reference/text-embedding/openai-embedding) | 1024（可缩短） | 是 | 中文更常见，英文可用 | 需 DashScope / 兼容代理 | 默认不测 | 不是海外英文场景的首选；仅当网关只有这类模型时才测 |
| 旧 ada-002 | OpenAI 旧模型 | 1536 | 维护优先级低 | 英文可用但已被 v3 替代 | 低 | 不测 | 已被 `text-embedding-3-small` 覆盖 |
| 重排 / BGE-M3 sparse·ColBERT | 各模型卡 | 不适用 | 是 | 可能改善排序 | 超出 MVP 检索形态 | 不测 | 属于 15.2 |

网关上只有一个可用模型时，仍跑完整评测；通过则冻结该模型，不补造其他厂商对比。

## 4. 已确认方案

2026-09-13 已确认采用方案 A，不采用 B、C。

1. 在仓库内放版本化英文评测集，不含真实客户数据。查询、产品文档和已审核案例均用英文撰写；`RAID5`、`S.M.A.R.T.`、`SMB`、型号和错误码保留原样。
2. 用最小 `HttpEmbedder` 调用 OpenAI-compatible 接口，批量得到固定维度向量。
3. 查询与片段都做 L2 归一化后算余弦；`product_doc` 与 `approved_case` 分开取 Top-3。
4. 输出每模型的 Recall@1、Recall@3、MRR，以及标识类查询是否全部命中。
5. 达到门槛的模型中，优先选维度更小、延迟和费用更低者；写入冻结记录后再允许建 `embedding` 列。

切分规则与主设计 9.4 一致：按标题和语义段落切，不按固定字数粗切。本验证语料预先切好并写上稳定 `chunk_id`，避免评测时现场切分漂移。

## 5. 评测集契约

建议路径：

```text
evals/embedding-v1/
  corpus/product_docs/*.md
  corpus/approved_cases/*.md
  chunks.jsonl
  queries.jsonl
  README.md
```

`chunks.jsonl` 每行：

```json
{
  "chunk_id": "pd-raid5-degraded-01",
  "source_type": "product_doc",
  "title": "RAID5 degraded-mode write limits",
  "product_model": "DS920+",
  "language": "en",
  "content": "..."
}
```

`queries.jsonl` 每行：

```json
{
  "query_id": "q-raid5-degraded",
  "query": "Can I keep writing to a DS920+ volume after RAID5 degrades?",
  "source_type": "product_doc",
  "language": "en",
  "relevant_chunk_ids": ["pd-raid5-degraded-01"],
  "tags": ["identifier", "raid"]
}
```

规模下限：

- 产品文档片段 ≥ 8，已审核案例片段 ≥ 6，合计约 20–30 条。
- 查询 ≥ 12，全部为英文，且同时覆盖：只查产品事实、只查案例表达、技术标识、易混型号/阵列级别、知识库外问题。
- 每条计入 Recall 的查询 `language` 必须为 `en`。
- 每条查询至少 1 个标注相关 `chunk_id`；知识库外查询的相关集为空，只报告误召回，不计入 Recall 分母。

语料由项目编写脱敏虚构的英文售后内容，不复制厂商未授权文档，不使用真实工单。

## 6. 通过标准

主指标只统计 `language=en` 的查询，按 `source_type` 分开计算，K 取 3（与每路最多 3 条一致）。

| 检查 | 通过线 |
| --- | --- |
| `product_doc` Recall@3 | ≥ 0.80 |
| `approved_case` Recall@3 | ≥ 0.80 |
| 带 `identifier` 标签的查询 | 每条至少 1 个相关片段进入该路 Top-3 |
| 向量维度 | 同一次运行内全部向量长度一致，并写入冻结记录 |
| 跨路污染 | 记录但不阻断；留给 15.2 混合检索 |

全部模型未过线时：不冻结、不建向量列，只保留报告和下一步候选（例如补测 `text-embedding-3-large` 或扩大易混负例）。

## 7. 冻结输出

通过后只追加一份机器可读记录，例如 `evals/embedding-v1/freeze.json`：

- `model`
- `dimensions`
- `index_version`（建议 `embedding-v1`）
- `distance`：`cosine`
- `recall_at_3`（分路，英文查询）
- `primary_language`：`en`
- `evaluated_at`
- `gateway`（仅主机名，不含密钥）

冻结记录是后续 Alembic `vector(N)` 和重嵌入策略的唯一依据。报告同时给出数量、关键字段和结果哈希，不把向量全文写入文档。

## 8. 风险与安全

- 没有可用网关就无法出冻结结论；脚本和评测集可以先写，冻结必须等真实调用。
- 密钥只进本地 `.env`，不进仓库、日志或冻结文件。
- 评测集禁止真实邮箱、电话、序列号和访问凭据。
- 不同模型维度不同，比较只看名次指标，不把向量写进同一列。

## 9. 已决策与剩余输入

已决策：

- 验证方式采用方案 A（离线评测脚本 + 内存余弦）。
- 目标用户为海外售后；客户邮件、知识库、回复草稿、审核页面和本次评测全部使用英文。
- 不先建 pgvector，不改用本地 sentence-transformers，除非生产接入也改为本地模型。

2026-09-13 已冻结：`text-embedding-3-small` / 1536 / `embedding-v1`。当前先用这一套推进建库和后续阻断性验证。BGE 等其他模型待有可用渠道或新 key 后再补测，不阻塞 15.1 其余条目。补测后若仍采用现模型，只需更新评测报告；若改选模型或维度，必须新建索引版本并全量重嵌入，不能在同一向量列混用。
