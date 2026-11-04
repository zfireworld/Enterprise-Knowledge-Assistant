# 企业知识问答 Agent

通过两个工具检索和读取合成制度，输出答案、文档 ID、版本日期、原文引用、资料缺口和执行轨迹。模型看到工具结果后可选择继续检索、读取、追问或结束。原有导入及产品问答功能保留。

## 运行

在项目根目录，Python 3.11+：

```powershell
uv sync
uv run python -m app.knowledge.cli "报销期限多久？"
uv run python -m app.knowledge.cli "有几天？" --history '[{"role":"user","content":"年假规定是什么？"}]'
uv run python -m unittest test.test_knowledge -v
uv run python -m examples.generate_examples
```

启动浏览器工作台：

```powershell
.\start.bat
```

首次运行前执行 `uv sync`，然后在 PowerShell 中运行上述命令，或双击项目根目录的 `start.bat`。脚本在当前窗口运行服务，按 `Ctrl+C` 停止。MongoDB、Milvus 和模型服务需自行启动；脚本不会启动 Docker 或模型。如果不使用 Windows，也可执行 `uv run python -m uvicorn app.knowledge.web_api:app --host 127.0.0.1 --port 8090`。

打开 `http://127.0.0.1:8090/`。工作台上传 PDF、Markdown 或 UTF-8 文本后生成 BGE 稠密与稀疏向量并写入 `CHUNKS_COLLECTION`，聊天通过同一 Milvus 集合执行普通与 HyDE 两路召回，RRF 融合后使用 BGE Reranker 重排序；页面不会使用本地关键词资料搜索。PDF 解析需要本地 MinerU；查询和导入需要 Milvus、MongoDB、BGE 及模型服务配置，MongoDB 地址和数据库名分别通过 `MONGO_URL`、`MONGO_DB_NAME` 设置。导入任务状态保存在单进程内，重启后任务状态不保留；文件和向量分别存储在 `output/web_imports/` 和 Milvus。

### 文档版本管理

在“知识资料”中选择“导入资料”新建文档，或点击已有文档的“更新版本”，上传完整的新版本并填写版本日期。文档 ID 保持不变，版本按 V1、V2 递增；“版本历史”展示处理状态及当前版本。系统先解析并写入新版本，成功后才切换当前版本；失败或并发更新未获胜时，原版本继续可查询。一次问答使用同一份版本快照，不同文档仍会一起检索，避免把不同制度之间的冲突当作版本更新。

版本记录保存在 MongoDB 的 `knowledge_document_versions` 集合，按 Milvus 集合隔离。已有无版本标识但包含文档 ID 和版本日期的片段会展示为 V1，首次更新时登记，不会立即改写原片段。旧数据的资料列表只扫描前 1000 个片段，可能显示不全；失败或被替换版本的向量保留但不参与新查询，尚未实现自动清理和历史版本回滚。导入中重启服务可能留下处理中的版本记录，需重新发起导入。

网页上传和问答支持异步请求：导入任务创建、同步数据库访问与本地模型计算在线程中执行；真实决策模型使用异步调用，普通召回可与 HyDE 文档生成并发。模型决策和后续工具执行仍按观察结果依次进行。BGE 模型在单进程内串行使用，避免并发争用；异步不保证单次解析或向量计算更快。后台任务仍运行在当前进程，并非持久化任务队列。

导入进度通过 SSE 推送：工作台连接 `/api/import/{task_id}/events`，旧版导入页面连接 `/status/{task_id}/events`；连接时先发送当前状态，完成或失败时结束。断线时前端查询一次原状态接口并尝试重连，最多等待 30 分钟；等待超时或断线不代表后台任务已停止。任务和订阅都只存在单进程内，不支持跨 worker 共享或服务重启后恢复。

工作台问答使用 `POST /api/chat/stream` 推送改写、决策及工具阶段，最终答案只在引用校验完成后返回，不是逐字输出；断开连接会取消问答协程，但已在线程中执行的同步调用可能继续完成。原 `POST /api/chat` JSON 接口保留供已有调用方使用。

真实模型收到追问时，会先结合最近六条对话消息将问题改写为可独立检索的形式。接口返回的 `query_rewrite` 包含原问题、改写结果和处理状态；改写失败时使用原问题及历史继续执行。离线 Mock 不执行模型改写。

网页导入时按最多 800 个字符切分，目标重叠 120 个字符，优先在段落、换行和句末切分；为了保留自然边界，实际重叠可能小于 120。该参数为初始配置，尚需通过检索评估集验证。既有 Milvus 数据不会自动重新切分；可通过更新版本重新导入。

默认使用本地合成资料和确定性 Mock，适合离线检查流程。Mock 不是模型决策效果证明。资料可直接修改 `data/knowledge.json`，下一次请求即生效。

真实模型模式复用现有 `app/lm/lm_utils.py`：在根目录 `.env` 中设置 `OPENAI_BASE_URL`、`OPENAI_API_KEY`、`LLM_DEFAULT_MODEL`、`LLM_DEFAULT_TEMPERATURE`，然后运行：

```powershell
uv run python -m app.knowledge.cli "报销期限多久？" --model real
```

可通过 `--max-calls` 设置工具调用上限。真实模型需要兼容 JSON 输出的 API；工具错误、无效引用或达到上限会返回 `incomplete`。

## 使用双路 Milvus 检索

双路模式复用 BGE 稠密与稀疏混合检索、HyDE、RRF 和已有的 BGE Reranker。通过 `BGE_RERANKER_LARGE`、`BGE_RERANKER_DEVICE` 和 `BGE_RERANKER_FP16` 配置本地重排模型；重排失败时记录日志并回退到 RRF 顺序。重排对完整片段评分，沿用旧版动态保留策略（1～10 条，绝对分差 0.5 或相对分差 0.25 截断）。模型收到候选完整片段，引用前仍须调用读取工具核对并登记证据。分差截断可能漏掉冲突文档，需结合实际数据评估。配置现有 `.env` 中的 `MILVUS_URL`、BGE 模型及设备设置，选定一个**新集合名**作为 `CHUNKS_COLLECTION`，先执行：

```powershell
uv run python -m app.knowledge.index_cli <新集合名>
uv run python -m app.knowledge.cli "报销期限多久？" --model real --repository milvus
```

该命令拒绝覆盖已有集合；网页导入的更新流程见上文。已有商品集合中的片段如缺少 `doc_id` 和 `version_date`，需要补齐这些字段；不能将 `chunk_id` 当作文档 ID。真实 MongoDB 和 Milvus 的版本切换使用合成向量做过隔离验证，完整本地模型与 PDF 导入链路仍需在实际环境中验证。

## 评审入口

代码：`app/knowledge/`（领域接口、仓库适配、工具、模型、服务、CLI）；测试：`test/test_knowledge*.py`；样例：`examples/*.json`；验收点与复现方法见 `docs/03-evaluation.md`。`real_normal.json` 和 `real_conflict.json` 是历史真实模型对本地资料的运行记录；其余离线样例使用 Mock，不能证明真实模型或 Milvus 的效果。Trace 记录工具参数、结果及简短决策依据，不记录模型内部思维过程。

网页导入测试资料、逐项手动操作及查看 Trace 的方法见 [手工测试指南](docs/06-manual-testing.md)。

引用校验验证引用属于已读取原文，无法机械保证自然语言回答被原文完整蕴含。冲突识别依赖模型及检索召回，不能保证发现所有冲突；应结合评估数据人工复核。现有 `pyproject.toml` 和 `uv.lock` 为依赖清单。
