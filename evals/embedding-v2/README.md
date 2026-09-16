# 英文 NAS Embedding 扩展集 v2

2026-09-15 新建，用于固定四模型 Docker 对比。历史 [v1](../embedding-v1/README.md) 的 17 条片段、14 条查询和冻结记录保持原样。

## 数据与边界

| 项目 | 数量 |
| --- | --- |
| 共享语料 | 104 条，产品说明与批准回复各 52 条 |
| 混淆场景组 | 26 组，每组两个条件不同的场景 |
| 开发查询 | 40 条，其中 36 条有答案、4 条无答案 |
| 保留查询 | 88 条，其中 84 条有答案、4 条无答案 |
| 全部查询 | 128 条，其中 104 条单问题、16 条双问题、8 条无答案 |

这是**虚构 ArcNAS 产品的合成夹具**，包含虚构的型号、错误码和支持政策；`approved_case` 表示测试用的批准回复类别，并非真实客户批准记录。没有导入客户邮件。数据及相关性由 AI 编写并自检，**尚未经独立人工复核**，也不保证代表生产流量。

覆盖 RAID 故障数量、SMART 介质与接口错误、SMB 凭据与权限、LAN/DNS、快照恢复与空间、备份错误码、A210/A210+ 型号、二次验证、NFS、iSCSI、配额、TLS、DDNS/运营商 NAT、同步冲突、SATA/NVMe、UPS、固件、SMTP、加密目录、缓存模式、VLAN、防火墙、复制、校验、支持套餐、日志与搜索。部分查询采用口语、错别字、缩写、否定条件；双问题要求检索两个不同条件的处理方法。

## 分区和标注

- `dev` 与 `heldout` 的语料字节完全相同；查询按整组隔离：g01～g08 为开发组，g09～g26 为保留组。同组产品问题、回复问题及双问题不会跨区。
- 此分区不是外部盲测：数据由同一作者构造。模型权重与输入前缀沿用已固定配置，不根据保留集结果调参或改标签。
- 每条查询保存 `scenario_group`、`split`、`rationale`、`label_status`、`hard_negative_chunk_ids`。单问题的同组另一个条件是硬负例；双问题的两个片段都是相关答案。
- 无答案包含域外问题与域内缺失事实，例如价格、订单、型号温度范围。空相关集不进入 Recall/MRR 分母；保留其候选及相似度，未校准拒答阈值，不计算拒答准确率。
- 原始 JSONL 是版本化事实源；[manifest.json](manifest.json) 保存数量、审查状态和 SHA-256。新增标签或改动查询后应更新版本/哈希并重跑所有候选，不能选择性改掉某个模型的错误。

## 运行与指标

```powershell
# 自动顺序启动四模型、验证身份和 token 长度、预热、各跑三轮并停止容器。
.venv/Scripts/python.exe evals/embedding-v2/run_comparison.py --output evals/embedding-v2/reports/new-comparison
.venv/Scripts/python.exe evals/embedding-v2/summarize.py evals/embedding-v2/reports/new-comparison

# 只对已启动的一个服务跑某个分区，也可使用原入口（报告标签仍为历史冒烟入口）。
.venv/Scripts/python.exe -m evals.harness.local_embedding --model snowflake --dataset-dir evals/embedding-v2/heldout --output evals/embedding-v2/reports/manual-snowflake-heldout.json
```

每轮对共享语料编码一次，并对 128 条查询编码一次，然后分别统计两个分区、两条检索路由的 Recall@1、Recall@3、MRR@3、标识命中及失败例。多标签 Recall 按找回的相关片段比例计分，MRR 只衡量首个相关结果，不能代替双问题完整覆盖。

各模型实际 `/tokenize` 包含输入前缀和特殊 token；`/embed` 显式 `truncate:false`。长度覆盖仅限当前短文本集。每轮前预热固定的 4 条文档和 4 条查询；三轮批次请求时间排除预热、下载、启动与检索计算。P50/P95 是单输入串行请求的客户端耗时，**不是单邮件端到端耗时或生产 SLA**。资源使用通过运行期间 Docker stats 采样，仅报告采样最大值，不能称为精确峰值。

三轮相同查询不会变成 384 条独立样本。质量是否稳定按逐题排名核对；模型选择还需要独立标注复核、真实业务代表性、目标服务器与长输入验证。

## Qwen 批次一致性问题与规避

首轮扩展实验发现 Qwen 重复排名不稳定。本机探针复现了与 [TEI #882](https://github.com/huggingface/text-embeddings-inference/issues/882) 相符的等长批次缺陷。Compose 现同时限制 HTTP 输入批次和服务并发为 1，客户端逐条串行请求，四模型统一重跑。`max-batch-requests=1` 会被该镜像预热覆盖，不用它作为规避保证。数据和前缀不变；原实验保留为排查证据，最终比较采用规避后的运行。

```powershell
# 验证单输入串行配置：探针会顺序启动 Qwen、执行并停止服务。
.venv/Scripts/python.exe evals/embedding-v2/batch_probe.py evals/embedding-v2/reports/new-probe.json 1
```

将最后一个参数改为 `4` 可复现原等长批次异常，仅用于诊断；不要用该配置发布 Qwen 质量结论。输出文件必须不存在。原配置探针对比单条、原顺序、逆序和复制等长批次；规避配置将这些逻辑输入全部拆为单条串行发送，并验证原始多输入请求被拒绝。保留向量和相似度。
