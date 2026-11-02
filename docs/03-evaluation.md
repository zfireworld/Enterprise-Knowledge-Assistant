# 评估

执行 `python -m unittest test.test_knowledge -v`：6 项测试通过，覆盖单一答案、冲突、相似问法、历史追问、无资料、工具故障、调用上限、原文替换及拒绝未读取引用。

实际离线运行记录：`examples/normal.json`、`examples/conflict.json`、`examples/missing.json` 和 `examples/tool_failure.json`。这些是 Mock 轨迹，不证明真实模型的决策能力。

真实模型在本地资料上运行：`examples/real_normal.json` 中模型搜索并读取 D03 后给出答案；`examples/real_conflict.json` 中模型读取 D01 和 D02，列出冲突并要求确认。两例使用已配置的 OpenAI 兼容模型服务，并非 Milvus 结果。

首次冲突运行 `examples/real_conflict_before.json` 暗示较新文档可能优先，缺少依据。收紧提示词后复测的 `real_conflict.json` 没有选定优先制度；单次通过不能保证其他问题均正确。Milvus 双路、更多真实模型问法和语义支持度仍需评估。
