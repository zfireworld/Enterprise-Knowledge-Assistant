# 企业知识问答 Agent 手工测试指南

本指南覆盖正常回答、文档冲突、资料外问题、相似问题、上下文追问、工具失败和资料更新。每组列出的“已有实际结果”来自 `examples/` 中已运行的**离线确定性 Mock + 本地合成资料**；网页使用 Milvus 双路检索，选择“智能回答”时还使用真实模型，实际结果可能不同，应如实记录，不要把以下历史结果当成新的运行结果。

## 一、准备测试环境

1. 在项目根目录执行 `uv sync`，配置 `.env` 中的 Milvus、MongoDB、BGE 和模型服务参数，分别启动数据库及模型服务。
2. 建议使用独立测试集合，避免既有资料影响结果。在启动网页服务的 PowerShell 窗口中执行：

   ```powershell
   $env:CHUNKS_COLLECTION = 'kb_manual_20261104'
   .\start.bat
   ```

   如果该集合已用于其他资料，请换一个未使用的集合名。该环境变量只作用于此窗口及其子进程，不会修改 `.env`；关闭窗口后重新启动服务需要再次设置。导入会在 Milvus 创建集合并写入测试数据，在 MongoDB 写入版本记录。
3. 打开 `http://127.0.0.1:8090/`，进入“知识资料”→“导入资料”，逐一选择以下文件，导入方式选“新建文档（V1）”，填写对应日期，等待每次导入成功：

   | 文件 | 版本日期 | 核心内容 |
   | --- | --- | --- |
   | [01-费用报销制度.md](../examples/manual_data/01-费用报销制度.md) | 2025-01-01 | 30 天内报销 |
   | [02-费用报销说明.md](../examples/manual_data/02-费用报销说明.md) | 2025-02-01 | 15 天内报销 |
   | [03-账号登录FAQ.md](../examples/manual_data/03-账号登录FAQ.md) | 2025-03-01 | 在内部账号平台重置密码 |
   | [04-年假制度.md](../examples/manual_data/04-年假制度.md) | 2025-01-01 | 符合条件的员工每年 5 天年假 |

   网页会自动生成文档 ID；下文历史记录中的 D01～D04 是离线数据的 ID，网页实测应核对页面上的实际 ID。不要把更新版文件作为第五份新文档导入，留待第七组测试。
4. 切换到“知识问答”，回答模式选“智能回答”。首次加载本地 BGE 可能需要等待。除上下文追问外，每组开始前点击“新对话”。“规则演示”使用 Mock 决策，仍会访问网页的 Milvus 检索及 HyDE 模型，不能代替真实模型决策验证。

## 二、查看和保存 Trace

网页回答下可展开“查看执行过程”，检查工具参数、简要结果和错误。网页问答使用 `api/chat/stream`；在浏览器开发者工具（F12）→“网络/Network”选择该请求，查看最终 `final` 事件的数据。下方示例也可使用保留的 `api/chat` JSON 接口获取完整响应：

- `status`、`answer`、`citations`、`missing_information`：检查状态、答案、文档 ID、版本日期、引用原文及资料缺口。
- `trace`：按顺序查看 `action`、`arguments`、`result` 或 `error`，以及 `reason`；`decision_reason` 是结束依据。
- 对回答中的每段引用，核对对应 `read_passage` 结果中的完整原文；`search_documents` 返回完整候选片段，但不会自动登记引用证据。

可在网络面板复制完整响应并保存为 `examples/manual_real_*.json`。也可以在**另一个 PowerShell 窗口**运行下面的示例，将真实模型请求结果保存到文件：

```powershell
$body = @{ question = '忘记登录密码怎么办？'; history = @(); model = 'real' } | ConvertTo-Json -Depth 20
$result = Invoke-RestMethod -Uri 'http://127.0.0.1:8090/api/chat' -Method Post -ContentType 'application/json; charset=utf-8' -Body ([System.Text.Encoding]::UTF8.GetBytes($body))
$result | ConvertTo-Json -Depth 30 | Set-Content -Encoding utf8 examples/manual_real_normal.json
$result | ConvertTo-Json -Depth 30
```

手动保存时同时记录输入问题、历史、运行日期、使用的模型和测试资料；响应中不自动包含输入。不要提交密钥或私人资料。若 API 直接返回 HTTP 错误，记录状态码和错误内容，不要将其伪装为工具 Trace。

## 三、逐组测试

### 1. 正常回答

- **输入**：`忘记登录密码怎么办？`
- **检查**：回答通过内部账号平台重置，引用账号 FAQ 的文档 ID、日期与原文；Trace 先检索候选，再读取支持回答的片段。
- **已有离线实际结果**：`completed`；回答“员工忘记登录密码时，应通过内部账号平台重置密码。”Trace 为 `search_documents(忘记登录密码怎么办？)` → `read_passage(D03, D03-1)` → 结束。完整记录：[normal.json](../examples/normal.json)。

### 2. 改写后的相似问题

- **输入**：新对话中输入 `账号密码如何重置？`
- **检查**：答案和引用应与第 1 组指向同一条账号 FAQ，不能因为换一种问法而改变事实。
- **已有离线实际结果**：`completed`；回答和 D03 引用与第 1 组一致。Trace 为 `search_documents(账号密码如何重置？)` → `read_passage(D03, D03-1)` → 结束。完整记录：[rewrite.json](../examples/rewrite.json)。

### 3. 文档冲突

- **输入**：新对话中输入 `报销期限多久？`
- **检查**：两份资料分别要求 30 天和 15 天；应读取并引用两方、指出适用范围或优先级缺失，要求确认。不能只因日期较新就认定 15 天有效。记录真实检索是否同时召回两份文档。
- **已有离线实际结果**：`needs_clarification`；列出 30 天和 15 天，请求确认适用制度。Trace 为 `search_documents(报销期限多久？)` → `read_passage(D01, D01-1)` → `read_passage(D02, D02-1)` → 结束。完整记录：[conflict.json](../examples/conflict.json)。
- **历史真实模型记录**：[real_conflict.json](../examples/real_conflict.json) 使用本地合成资料，不是网页 Milvus 的本次运行结果。

### 4. 资料外问题

- **输入**：新对话中输入 `公司停车位收费吗？`
- **检查**：测试资料没有停车收费规定，应说明资料不足，不能凭空作答。向量检索可能返回不相关候选，重点检查模型是否识别其不支持答案。
- **已有离线实际结果**：`insufficient`，回答“未找到相关资料。”Trace 为 `search_documents(公司停车位收费吗？)` → 空结果 → 结束。完整记录：[missing.json](../examples/missing.json)。

### 5. 上下文追问

- **操作**：点击“新对话”，先发送 `年假怎么规定？`；收到回复后，在**同一对话**继续发送 `有几天？`。
- **检查**：第二次回答应结合前文，引用年假制度并保留“符合条件”的限制；Trace 中的检索应能体现年假上下文。
- **已有离线实际结果**：历史为用户消息“年假怎么规定？”，问题为“有几天？”；`completed`，回答“符合条件的员工每年可享受5天年假。”Trace 为 `search_documents(年假怎么规定？ 有几天？)` → `read_passage(D04, D04-1)` → 结束。完整记录：[history.json](../examples/history.json)。网页历史还会包含第一轮助手回复，因此不要求检索词逐字一致。

### 6. 工具失败

安全复现**离线文件读取工具失败**，不会停止或更改正在使用的 Docker 数据库。在项目根目录的新 PowerShell 窗口执行：

```powershell
uv run python -m app.knowledge.cli '报销期限多久？' --model mock --repository local --data data/nonexistent.json
```

- **检查**：文件不存在时，`status` 为 `incomplete`；`trace` 中 `search_documents` 应包含问题参数和文件不存在的 `error`，不能返回确定答案。
- **已有离线实际结果**：回答“工具失败，无法确认回答完整”，无引用。Trace 为 `search_documents(报销期限多久？)` → 文件不存在错误 → 模型选择结束。完整记录：[tool_failure.json](../examples/tool_failure.json)。
- 这是模拟本地仓库故障，**不是**真实模型或 Milvus 工具失败的验证；真实故障应在独立测试环境自行注入，并保存实际响应。连接初始化失败也可能直接返回 HTTP 503，而没有工具 Trace。

### 7. 更新资料后重新回答

1. 先完成第 1 组，保留原回答和 Trace。
2. 进入“知识资料”，在账号 FAQ 对应的文档行点击“更新版本”；选择 [05-账号登录FAQ更新版.md](../examples/manual_data/05-账号登录FAQ更新版.md)，日期填 `2025-04-01`，等待导入完成。
3. 在“版本历史”确认 V2 为当前版本、V1 保留；点击“新对话”，再次问 `忘记登录密码怎么办？`。
4. 检查回答和引用已变为“联系服务台重置密码”，引用日期为 `2025-04-01`，文档 ID 与 V1 相同；Trace 应读取新版本内容，不应引用旧的账号平台原文。

**已有离线实际结果**：`completed`，答案为“员工忘记登录密码时，应联系服务台重置密码。”Trace 仍为搜索 → 读取 D03 → 结束，读取内容和日期已变化。对照 [normal.json](../examples/normal.json) 和 [changed_document.json](../examples/changed_document.json)。离线案例切换的是 JSON 文件，网页版本更新需要按上述步骤另行验证。

## 四、记录与复现

建议为每次真实运行记录：日期、输入及上下文、模型与资料、预期、实际状态和答案、引用核对结果、Trace 文件、通过或失败及原因。遇到错误时保留真实响应；不要修改既有历史样例冒充新结果。

重现已保存的离线样例和自动化测试：

```powershell
uv run python -m examples.generate_examples
uv run python -m examples.run_tests
```

前者会覆盖对应离线 JSON，后者会更新 [test-results.txt](../examples/test-results.txt)。详细评估及已知局限见 [03-evaluation.md](03-evaluation.md)。
