# 效果评估

## 复现方式

在仓库根目录执行：

```powershell
uv run python -m examples.generate_examples
uv run python -m examples.run_tests
```

第一条命令实际运行七组离线案例，每个 JSON 包含问题、对话历史、资料路径、状态、回答、引用和完整工具轨迹。第二条命令执行回归测试并写入 `examples/test-results.txt`。本次结果是 **44 项通过、退出码 0**；退出时 `multiprocess` 依赖还输出了一条资源清理异常，原样保留在日志中。

## 验收点与实际结果

| 验收点 | 输入及预期 | 实际结果与记录 |
| --- | --- | --- |
| 明确答案 | 忘记登录密码怎么办；应引用 D03 | `completed`，回答通过内部账号平台重置，见 [normal.json](../examples/normal.json) |
| 改写后的相似问题 | 账号密码如何重置；应与上题引用一致 | `completed`，引用同一 D03 原文，见 [rewrite.json](../examples/rewrite.json) |
| 文档冲突 | 报销期限多久；应列出两项规定并请求确认 | `needs_clarification`，分别读取并引用 D01 的 30 天及 D02 的 15 天，见 [conflict.json](../examples/conflict.json) |
| 资料外问题 | 公司停车位收费吗；不应编造答案 | `insufficient`，检索无结果，见 [missing.json](../examples/missing.json) |
| 上下文追问 | 上文询问年假，继续问“有几天”；应结合历史 | `completed`，检索参数包含年假上下文，引用 D04 的 5 天规定，见 [history.json](../examples/history.json) |
| 工具失败 | 检索时读取不存在的文件；应报告未完成 | `incomplete`，轨迹保留检索参数及文件不存在错误，见 [tool_failure.json](../examples/tool_failure.json) |
| 替换资料 | 将 D03 改为联系服务台后重复原问题 | 回答、原文引用及版本日期发生变化，见 [changed_document.json](../examples/changed_document.json)，与 [normal.json](../examples/normal.json) 对照；动作仍是检索再读取 |

替换案例使用 [knowledge_updated.json](../data/knowledge_updated.json)，原资料为 [knowledge.json](../data/knowledge.json)。测试还覆盖调用上限、拒绝未读取引用、版本切换、更新失败及异步并发；逐项结果见 [test-results.txt](../examples/test-results.txt)。

单独使用本地 BGE Reranker 对三条合成资料评分时，30 天和 15 天的报销规定均被动态 Top-K 保留，充电资料被截断；该单次结果不能证明其他冲突问题不会被截断，也不是完整的 Milvus 与真实模型端到端评估。

## 真实模型记录及限制

上述七组使用**确定性 Mock 决策模型和本地合成资料仓库**，用于验证流程和输出，不能证明真实模型会根据结果正确决策，也不代表网页的 Milvus 检索效果。缺失文件是模拟工具故障，并非真实 Milvus 故障。

此前已保存两条使用真实模型、但仍以本地合成资料作为检索来源的历史记录：[real_normal.json](../examples/real_normal.json) 读取 D03 后回答；[real_conflict.json](../examples/real_conflict.json) 读取 D01 和 D02 后说明冲突、请求确认，体现不同工具观察后的不同动作。这两条是历史运行记录，未在本次修改后重新执行，也不是 Milvus 双路检索记录。本次检查时配置的模型服务无法建立 TCP 连接，因此没有生成新的真实模型记录。

首次冲突运行 [real_conflict_before.json](../examples/real_conflict_before.json) 曾暗示较新文档可能优先，缺少依据；后续调整提示词后保存的冲突案例没有擅自选择。单次结果不能证明冲突识别可靠。仍需以实际模型和 Milvus 对六项验收点重新运行并保存轨迹，尤其验证资料不足、改写、追问、工具失败，以及导入新版本后答案和动作的变化。引用子串校验也不能保证回答的每项推论均被原文支持。
