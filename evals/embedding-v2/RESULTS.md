# 扩展集四模型对比结果（2026-09-15）

## 结论与当前建议

**当前英文短文本、CPU 单请求方案，优先采用 Snowflake Arctic M v1.5 作为后续候选。** 它在保留集的两条路由均达到 Recall@3=100%，84/84 道计分题完整覆盖；单输入查询 P95 约 58 ms，采样最大内存约 803 MiB，也是本轮最快、内存占用最低的配置。生产模型暂不冻结，先做独立标签复核与目标环境验证。

Nomic 和 BGE-M3 均在 DDNS/运营商 NAT 双问题中漏掉后半个所需片段；Qwen 规避推理异常后只漏掉一条整卷满的批准回复。四模型的保留集标识查询均为 19/19 命中，最终三轮全部 128 条查询的 Top-3 排名一致。BGE-M3 的产品路首位排名指标略高于 Snowflake，因此不能声称 Snowflake 每个质量指标都最优；选择依据是本任务 Top-3 完整覆盖、延迟和内存的综合结果。

**以下全部采用规避后的统一单输入、单并发重测数据。** 初轮 Qwen 的低分受到 TEI 1.9.3 等长批次缺陷影响，不能用于模型权重优劣判断；已保留[复现及规避证据](QWEN-BATCH-ISSUE.md)。没有根据保留集调提示词或标签。缺陷排查使用了部分保留输入，最终集因此应理解为未用于语义调参的合成保留分区，而不是完全未触碰的外部盲测。

本地结果支持当前候选选择，不等于真实客户邮件准确率或生产验收。合成数据由 AI 编写并自检，未做独立人工复核；目标服务器、长输入、多语言与并发吞吐尚未验证。

## 测试对象与方法

- 104 条英文知识片段（产品说明 52、批准回复 52），128 条查询；开发集 40、保留集 88。两区共享完全相同的语料，按 26 组场景隔离查询。
- 有答案查询共 120 条：开发两路各 18，保留两路各 42；8 条无答案查询不进入 Recall/MRR 分母。16 条双问题各需两个片段。
- 同一作者构造的虚构 ArcNAS 夹具，含型号、故障近邻、口语、拼写错误和否定；不是独立盲测或真实客户标注，未做独立人工复核。首次运行前固定全部标签与哈希，之后未改标签或输入模板。
- 每个模型实际调用三轮，保持相同数据、Top-3、分路余弦、单输入串行请求、float32；每轮固定预热 4 文档与 4 查询，预热不计入请求时间。
- Windows Docker Desktop Linux，Intel i7-11700F，容器限制 4 CPU / 8 GiB，TEI 1.9.3。模型身份/revision 已由 `/info` 验证，镜像与限额留在部署报告。
- 查询前缀沿用固定清单。本轮没有在开发集调优，也没有根据保留集反馈改变前缀；Qwen 使用指令版，未把历史裸查询消融分数混入。
- [数据与标签定义](README.md) · [完整机器可读汇总](reports/docker-2026-09-15-serial/summary.json) · [环境](reports/docker-2026-09-15-serial/environment.json) · [固定输入](reports/docker-2026-09-15-serial/inputs.json)

## 保留集质量

下表每条路由有 42 条计分查询。MRR 指 Top-3 内首个相关片段的倒数排名均值。Recall@1 按相关片段比例计算，含 6 条双答案问题时理论上限为 92.86%，不能当作普通首位命中率。

| 模型 | 产品 R@1 | 产品 R@3 | 产品 MRR@3 | 回复 R@1 | 回复 R@3 | 回复 MRR@3 | 标识 Top-3 | 完整覆盖问题 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Snowflake Arctic M v1.5 | 80.95% | 100.00% | 0.9405 | 85.71% | 100.00% | 0.9643 | 19/19 | 84/84 |
| Nomic Embed Text v1.5 | 83.33% | 98.81% | 0.9484 | 80.95% | 100.00% | 0.9365 | 19/19 | 83/84 |
| BGE-M3 | 83.33% | 98.81% | 0.9524 | 82.14% | 100.00% | 0.9405 | 19/19 | 83/84 |
| Qwen3 Embedding 0.6B | 76.19% | 100.00% | 0.9167 | 85.71% | 97.62% | 0.9524 | 19/19 | 83/84 |

完整覆盖问题要求该问题的所有相关片段都在 Top-3；双问题只找到一条算部分召回，不算完整覆盖。

## 开发集与重复性

| 模型 | 产品 R@3 / MRR@3 | 回复 R@3 / MRR@3 | 标识 Top-3 | 保留集第 2、3 轮排名变化题数 |
| --- | --- | --- | --- | --- |
| Snowflake Arctic M v1.5 | 100.00% / 0.9444 | 100.00% / 0.9722 | 13/13 | 0 / 0 |
| Nomic Embed Text v1.5 | 100.00% / 0.8889 | 97.22% / 0.9444 | 13/13 | 0 / 0 |
| BGE-M3 | 100.00% / 0.9444 | 97.22% / 0.9630 | 13/13 | 0 / 0 |
| Qwen3 Embedding 0.6B | 100.00% / 0.9167 | 97.22% / 0.9722 | 13/13 | 0 / 0 |

重复三次不扩大独立问题数。质量表采用首轮，另外两轮用于核对排名重复性；所有轮次均保留原始排名。阈值规则仍为两路 R@3 ≥ 0.8 且标识查询全部 Top-3 命中，过最低门槛不等于最优模型。

## 时间与资源

查询时间包括全部 128 条查询（含无答案），合并三轮共 384 个单输入请求；文档共 312 个单输入请求。P50/P95 是客户端单输入 HTTP 请求时间，不是完整邮件处理时间，不含检索计算、启动、下载和每轮显式预热。三轮连续运行，运行期间本机其他负载未隔离；这些数值属于当前部署的局部对比。

| 模型 | 查询请求 P50（ms） | 查询请求 P95（ms） | 文档请求 P95（ms） | 每轮编码秒数（1 / 2 / 3） | 采样最大内存（MiB） | 资源采样数 |
| --- | --- | --- | --- | --- | --- | --- |
| Snowflake Arctic M v1.5 | 38.8 | 58.0 | 59.5 | 10.13 / 10.02 / 10.16 | 803.3 | 12 |
| Nomic Embed Text v1.5 | 48.1 | 79.0 | 100.0 | 13.98 / 14.54 / 13.79 | 1041.4 | 16 |
| BGE-M3 | 116.6 | 205.1 | 224.3 | 34.28 / 33.82 / 33.14 | 1735.7 | 37 |
| Qwen3 Embedding 0.6B | 508.5 | 721.1 | 583.4 | 120.61 / 120.94 / 122.23 | 2569.2 | 133 |

内存来自预热和评测期间的 Docker stats 离散采样，保留原始单位与时间戳；不是精确峰值、权重文件大小或 GPU 显存。CPU 模型和后端配置不同，时间差不能只归因于模型参数量。

## 完整输入长度

| 模型 | 文档最大 token | 查询最大 token | 服务单输入上限 |
| --- | --- | --- | --- |
| Snowflake Arctic M v1.5 | 58 | 77 | 512 |
| Nomic Embed Text v1.5 | 62 | 73 | 512 |
| BGE-M3 | 63 | 72 | 512 |
| Qwen3 Embedding 0.6B | 56 | 84 | 512 |

以上由各服务实际 `/tokenize` 得到，包含对应前缀及特殊 token；每次 `/embed` 显式设置 `truncate:false`。所有当前输入均在限制内，仅证明短文本集合兼容，不证明长邮件能力。

## 保留集实际失败例

### Snowflake Arctic M v1.5

所有计分问题均完整覆盖 Top-3。仍有以下首位排名错误（最多展示两条）：

- `q-pd-quota-user`：Guys, I cant save but everyone else can, theres 2 TB left. My user gets quota exceeded. Buy disks?
  - 期望：`pd-quota-user`
  - 实际 Top-3：`pd-quota-volume` → `pd-quota-user` → `pd-backup-full`
- `q-ac-tls-name`：Approved reply for a certificate name mismatch even though the expiry date is in the future?
  - 期望：`ac-tls-name`
  - 实际 Top-3：`ac-tls-expired` → `ac-tls-name` → `ac-sync-conflict`

### Nomic Embed Text v1.5

以下问题未在 Top-3 完整覆盖相关片段：

- `q-pd-g13-dual`：Two separate tickets need different guidance. First: From outside, today's public IP works but the DDNS name goes nowhere. Do my shares need recreating? Second: My router WAN is 100.72.4.9 and forwarding never works from outside. Will refreshing DDNS be enough?
  - 期望：`pd-ddns-stale`, `pd-wan-cgnat`
  - 实际 Top-3：`pd-ddns-stale` → `pd-lan-address` → `pd-lan-dns`

### BGE-M3

以下问题未在 Top-3 完整覆盖相关片段：

- `q-pd-g13-dual`：Two separate tickets need different guidance. First: From outside, today's public IP works but the DDNS name goes nowhere. Do my shares need recreating? Second: My router WAN is 100.72.4.9 and forwarding never works from outside. Will refreshing DDNS be enough?
  - 期望：`pd-ddns-stale`, `pd-wan-cgnat`
  - 实际 Top-3：`pd-ddns-stale` → `pd-tls-expired` → `pd-lan-dns`

### Qwen3 Embedding 0.6B

以下问题未在 Top-3 完整覆盖相关片段：

- `q-ac-quota-volume`：Which approved response handles all users losing write access because the volume itself is full?
  - 期望：`ac-quota-volume`
  - 实际 Top-3：`ac-nfs-root` → `ac-quota-user` → `ac-backup-full`

## 无答案与证据边界

每个分区均保留 4 条无答案查询及候选相似度。系统目前始终返回 Top-3，没有校准拒答阈值，因此不报告拒答准确率。域内缺失事实与域外查询都不能因命中主题相关段落而算回答正确。

本轮只测向量召回，没有测生成回复、引用正确率、关键词/RRF、重排或生产数据库。没有公司服务器部署或 GPU 验证。标签还需独立复核，真实业务分布、长输入和目标服务器是后续生产选型检查；本轮不改历史 `freeze.json`。

## 原始报告

| 模型 | 第 1 轮 | 第 2 轮 | 第 3 轮 | 资源 | 分词 |
| --- | --- | --- | --- | --- | --- |
| Snowflake Arctic M v1.5 | [查看](reports/docker-2026-09-15-serial/snowflake-round-1.json) | [查看](reports/docker-2026-09-15-serial/snowflake-round-2.json) | [查看](reports/docker-2026-09-15-serial/snowflake-round-3.json) | [采样](reports/docker-2026-09-15-serial/snowflake-resources.json) | [token](reports/docker-2026-09-15-serial/snowflake-tokens.json) |
| Nomic Embed Text v1.5 | [查看](reports/docker-2026-09-15-serial/nomic-round-1.json) | [查看](reports/docker-2026-09-15-serial/nomic-round-2.json) | [查看](reports/docker-2026-09-15-serial/nomic-round-3.json) | [采样](reports/docker-2026-09-15-serial/nomic-resources.json) | [token](reports/docker-2026-09-15-serial/nomic-tokens.json) |
| BGE-M3 | [查看](reports/docker-2026-09-15-serial/bge-m3-round-1.json) | [查看](reports/docker-2026-09-15-serial/bge-m3-round-2.json) | [查看](reports/docker-2026-09-15-serial/bge-m3-round-3.json) | [采样](reports/docker-2026-09-15-serial/bge-m3-resources.json) | [token](reports/docker-2026-09-15-serial/bge-m3-tokens.json) |
| Qwen3 Embedding 0.6B | [查看](reports/docker-2026-09-15-serial/qwen3-round-1.json) | [查看](reports/docker-2026-09-15-serial/qwen3-round-2.json) | [查看](reports/docker-2026-09-15-serial/qwen3-round-3.json) | [采样](reports/docker-2026-09-15-serial/qwen3-resources.json) | [token](reports/docker-2026-09-15-serial/qwen3-tokens.json) |

[结束与容器状态](reports/docker-2026-09-15-serial/completion.json)。实验服务已停止，模型缓存保留。新增结构、长度边界和汇总输入一致性检查后，全套自动测试 48 项通过。
