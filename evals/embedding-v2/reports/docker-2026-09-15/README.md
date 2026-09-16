# 初轮报告：包含已确认的 Qwen 批次异常

此目录保留四输入批次实验及原始结果，**Qwen 的质量分数不用于模型优劣结论**。后续探针确认等长批次推理会改变向量，不能把这组异常分数当成模型权重本身的表现。

- [原始汇总](summary.json)
- [原始批次探针](qwen-batch-probe.json)
- [单输入串行规避探针](qwen-batch-probe-fixed.json)
- [参数被预热覆盖的日志](qwen-max-batch-requests-ignored.log)
- [原因、范围及复现说明](../../QWEN-BATCH-ISSUE.md)

最终比较使用独立的 `docker-2026-09-15-serial` 目录，四模型统一单输入、单并发，避免混用不同运行口径。
