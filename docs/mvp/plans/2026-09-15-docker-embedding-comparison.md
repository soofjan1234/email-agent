# Docker Embedding 对比实施计划

依据[已确认设计](../designs/2026-09-13-embedding-truth-test-design.md)。用户于 2026-09-15 授权继续实施。首轮在本机 Docker Desktop 的 Linux 引擎中执行，CPU 单模型顺序运行，不改公司服务。

## T1：本地容器与模型配置

- 创建 `deploy/embedding/compose.yaml`、`evals/embedding-models.json`，固定四个模型 revision 和 TEI CPU 镜像版本；每个模型配置输入前缀和预期维度。
- 先验证配置字段，再执行 `docker --context desktop-linux compose -f deploy/embedding/compose.yaml config`；实际拉取镜像后记录 digest。
- 容器只监听本机，限制 CPU、内存，缓存使用 Docker 卷，顺序启动模型。

## T2：显式输入角色与只报告入口

- 修改 `evals/harness/embedder.py` 和 `runner.py`，新增 `embed_documents`、`embed_queries`；保留原 `embed` 兼容已有测试。
- 创建 `evals/harness/local_embedding.py`：TEI 身份验证、原生 `/embed` 调用、禁止静默截断、固定模型前缀、批次维度和数值检查、独立报告输出。
- 创建 `tests/eval/test_local_embedding.py`；先验证未实现时失败，再验证查询/文档前缀、无 API key 请求、身份错误、跨批维度错误、无自动冻结。
- 验证命令：`.venv/Scripts/python.exe -m pytest tests/eval -q`。

## T3：四模型接入验证

- 依次启动 Snowflake、Nomic、BGE-M3、Qwen3，使用历史 17 片段/14 查询冒烟集，保存独立报告和容器身份。
- 冷启动及下载与稳态时间分开；失败记录真实原因，不将小样本视为正式选优。
- 相关命令写入 `deploy/embedding/README.md`；不覆盖 `evals/embedding-v1/freeze.json`。

## T4：扩展集与正式比较

- 新数据集另行版本化，按设计准备开发集与保留集并复核标注；逐模型验证长度，再做至少三轮稳态性能、资源记录及差异分析。
- 四模型部署全部通过前不冻结获胜模型。数据集人工复核和正式比较未完成时，整体计划保持未完成状态。

## 完成条件

T1～T4 均有实际证据，模型身份、输入模板、数据版本、质量与性能可追溯。代码测试、历史集冒烟和正式比较分开报告。

## 当前执行结果

T1～T3 已完成。T4 的本地执行已完成：新建 `evals/embedding-v2`（104 片段、128 查询），按场景分开发与保留集；完成实际 token 长度检查、四模型三轮重复评测、资源采样和逐题差异记录。Qwen 的 TEI 1.9.3 等长批次缺陷已复现，改为四模型统一单输入串行请求并重新测量；原异常报告保留。详细结果见[验证记录](../validation.md)与[扩展集报告](../../../evals/embedding-v2/RESULTS.md)。

标签属于作者检查的合成数据，尚未经独立人工复核；长输入、生产代表性和目标服务器仍待验证。整体计划记为待验证，不创建生产冻结记录。
