# 本机 Docker Embedding 冒烟验证

本入口使用 TEI CPU 1.9（Compose 固定镜像 digest），每次运行一个模型，4 CPU、8 GiB 内存上限，HTTP 仅绑定 `127.0.0.1:18080`。不读取公司的 API key。模型缓存保存在 Docker 命名卷中。

首轮 `max-batch-tokens=512`，限制 CPU 预热和批处理规模。客户端禁止截断，超过服务实际长度限制的输入会失败；本配置不验证模型标称的 8K/32K 长上下文能力。

## 运行

在仓库根目录 PowerShell 执行；Docker Desktop 必须已启动 Linux 引擎。

```powershell
./deploy/embedding/start.ps1 -Model snowflake
docker --context desktop-linux compose -f deploy/embedding/compose.yaml logs --tail 30
Invoke-RestMethod http://127.0.0.1:18080/health
./.venv/Scripts/python.exe -m evals.harness.local_embedding --model snowflake --output evals/embedding-v1/reports/docker-snowflake-run1.json
```

首次启动需下载模型。健康接口成功后再评测；容器退出时先查看日志，不能把启动命令成功当作加载成功。模型别名可选 `snowflake`、`nomic`、`bge-m3`、`qwen3`；启动和评测必须选择同一别名。重复评测需更换报告文件名，入口拒绝覆盖已有文件及 `freeze.json`。

`start.ps1` 从 [模型清单](../../evals/embedding-models.json) 读取完整 ID 与 revision，替换同一个实验容器，不并行运行四个模型。其他 Docker 环境可通过 `-Context` 指定已配置的 context。

Qwen 裸查询消融对照可在评测命令中增加 `--raw-query`，例如 `--model qwen3 --raw-query --output evals/embedding-v1/reports/docker-qwen3-raw-run1.json`。它只清空 Qwen 查询指令，文档、模型和其他规则保持一致，报告保存实际输入配置。

结束实验：

```powershell
docker --context desktop-linux compose -f deploy/embedding/compose.yaml stop
```

停止保留缓存；不需要执行删除卷命令。当前模型适配使用 TEI 原生 `/embed`，主动传 `truncate=false`，并通过 `/info` 校验模型及 revision。模型输入前缀在清单中固定，查询与文档调用分开。

## 结果边界

扩展集已复现 TEI 1.9.3 的 Qwen Candle 等长批次问题：同一输入单独编码和等长批量编码的向量显著不同，见[上游问题 #882](https://github.com/huggingface/text-embeddings-inference/issues/882)。当前 Compose 默认 `--max-client-batch-size 1 --max-concurrent-requests 1`，客户端同步单输入串行发送。`--max-batch-requests 1` 会被本镜像的预热结果覆盖为 4，不能作为规避保证。四模型正式重跑使用同一限制，不能混用限制前后的性能数据。新评测入口拒绝该版本 Qwen 未设置此规避参数的服务。此处是配置规避，不是修复上游代码。

扩展集命令、标签边界和分区见 [embedding-v2](../../evals/embedding-v2/README.md)。以下历史冒烟描述保留其原始运行口径；旧 Qwen Docker 分数不能作为可靠的模型质量或输入指令优劣结论。

默认是历史 17 条片段/14 条查询的冒烟集。报告包含输入模板、实际模型身份、数据哈希、逐查询结果及批次耗时，不自动冻结。首次推理批次可能包含运行时预热，当前报告不是正式稳态性能对比。

推理引擎在 CPU 下优先尝试 ONNX；Qwen 仓库缺少 ONNX 时，当前镜像日志显示会继续尝试官方 `safetensors`。是否最终加载成功以健康检查和实际编码为准，不能看到一次 ORT 错误就判定整个服务失败。不同后端的耗时属于部署方案差异。

Nomic 固定为官方 `e5cf08aadaa33385f5990def41f7a23405aec398`：后续 `e9b6763` 配置增加别名字段，实测 TEI 1.9.3 会以重复 `max_position_embeddings` 拒绝加载。原失败日志保留在验证记录引用的报告目录。

完整设计及扩展评测要求见 [专项设计](../../docs/mvp/designs/2026-09-13-embedding-truth-test-design.md)，进度见 [状态表](../../docs/mvp/status.md)。
