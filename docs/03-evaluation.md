# 效果评估

## 复现方式

在仓库根目录执行：

```powershell
uv run python -m examples.generate_examples
uv run python -m examples.run_tests
```

第一条命令实际运行七组离线案例，每个 JSON 包含问题、对话历史、资料路径、状态、回答、引用和完整工具轨迹。第二条命令执行回归测试并写入 `examples/test-results.txt`。本次结果是 **51 项通过、退出码 0**；退出时 `multiprocess` 依赖还输出了一条资源清理异常，原样保留在日志中。

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

来源定位测试使用模拟 MinerU 输出验证按页切分、版本文件访问和引用链接，并只读检查现有两种手册的 MinerU 内容列表可按页切分；另外已运行下述合成 PDF 真实解析测试。旧 Milvus 片段只读兼容，不自动生成页码和原文件链接。浏览器自动化验证因工具超时未完成。

## 真实模型记录及限制

上述七组使用**确定性 Mock 决策模型和本地合成资料仓库**，用于验证流程和输出，不能证明真实模型会根据结果正确决策，也不代表网页的 Milvus 检索效果。缺失文件是模拟工具故障，并非真实 Milvus 故障。

此前已保存两条使用真实模型、但仍以本地合成资料作为检索来源的历史记录：[real_normal.json](../examples/real_normal.json) 读取 D03 后回答；[real_conflict.json](../examples/real_conflict.json) 读取 D01 和 D02 后说明冲突、请求确认，体现不同工具观察后的不同动作。这两条是历史运行记录，不是 Milvus 双路检索记录。

首次冲突运行 [real_conflict_before.json](../examples/real_conflict_before.json) 曾暗示较新文档可能优先，缺少依据；后续调整提示词后保存的冲突案例没有擅自选择。单次结果不能证明冲突识别可靠。引用子串校验也不能保证回答的每项推论均被原文支持。

## 真实模型与 Milvus 验收（2026-11-04）

使用 Qwen `qwen3.8-max-0902`、本地 BGE 向量和重排模型、真实 MongoDB 与 Milvus，在独立集合 `kb_eval_6053807dd6` 导入四份合成 Markdown 资料。请求通过 FastAPI 测试客户端调用应用接口；并非浏览器或 HTTP 网络部署测试。完整参数、回答、引用和 Trace 保存在以下文件；初步自动核对结果见 [checks.json](../examples/live_runs/6053807dd6/checks.json)。

| 场景 | 实际结果 | 运行记录 |
| --- | --- | --- |
| 正常回答 | `completed`；引用账号 FAQ 的平台重置原文 | [normal.json](../examples/live_runs/6053807dd6/normal.json) |
| 相似问法 | `completed`；引用同一文档的原文 | [rewrite.json](../examples/live_runs/6053807dd6/rewrite.json) |
| 冲突 | `needs_clarification`；读取并引用 30 天、15 天两份制度，没有选择优先制度 | [conflict.json](../examples/live_runs/6053807dd6/conflict.json) |
| 资料外 | `insufficient`；两次搜索后说明未找到停车收费规定 | [missing.json](../examples/live_runs/6053807dd6/missing.json) |
| 上下文追问 | `completed`；将“有几天？”改写为“年假有几天？”，引用 5 天规定 | [history_followup.json](../examples/live_runs/6053807dd6/history_followup.json) |
| 更新版本 | `completed`；引用新版本“联系服务台”，原文件接口返回更新后的合成文件 | [updated.json](../examples/live_runs/6053807dd6/updated.json)、[updated_import.json](../examples/live_runs/6053807dd6/updated_import.json) |
| 工具故障 | `incomplete`；Trace 记录人为注入的 Milvus 检索异常 | [tool_failure_injected.json](../examples/live_runs/6053807dd6/tool_failure_injected.json) |

年假[第一轮](../examples/live_runs/6053807dd6/history_initial.json)引用了正确的 5 天原文，但模型将状态设为 `incomplete`，因为缺少适用条件等细节；第二轮追问才返回 `completed`。这是本次发现的状态判定差异，应结合产品预期继续评估。冲突场景读取了两方原文，而资料外场景选择补充搜索后结束，展示了不同观察结果下的两条模型决策路径。

上述原文件链接验证使用 Markdown。工具失败由代码注入，并非实际关闭或破坏 Milvus。上述每项仅为一次运行，不能证明稳定性；样例中的链接依赖该独立集合及本机 `output/web_imports/` 的文件。

重新运行可执行 `uv run python -m examples.run_real_milvus_cases`。脚本每次创建独立 Milvus 集合和新记录目录，使用真实模型，产生模型调用和本地资源开销，并在数据库和 `output/` 保留合成测试数据；需提前配置并启动所需服务。

## 真实 PDF 来源定位验收（2026-11-04）

使用程序生成的两页英文合成 PDF，在独立集合 `kb_pdf_eval_19089be3ff` 经过本地 MinerU 解析、BGE 向量、Milvus、BGE 重排和真实模型问答。真实运行记录：[导入](../examples/live_runs/19089be3ff/pdf_import.json)、[按页切分结果](../examples/live_runs/19089be3ff/pdf_chunks.json)、[问题和 Trace](../examples/live_runs/19089be3ff/pdf_question.json)、[核验结果](../examples/live_runs/19089be3ff/pdf_checks.json)。

实际两页均成功入库；模型读取并引用第 2 页“每 17 天检查设备”的原文，引用链接包含 `#page=2`，文件接口返回的字节与上传 PDF 一致。随后启动临时隔离服务，通过真实 HTTP 验证首页 `200`、PDF 字节范围请求 `206`、问答 SSE 的进度和最终结果，见 [pdf_http_sse.json](../examples/live_runs/19089be3ff/pdf_http_sse.json)。浏览器自动化工具超时，因此 PDF 阅读器是否实际跳页仍需手动确认。每次运行 `uv run python -m examples.run_real_pdf_case` 都会生成新的合成 PDF、独立集合和运行记录，需要本地 MinerU、模型文件、数据库和真实模型服务。
