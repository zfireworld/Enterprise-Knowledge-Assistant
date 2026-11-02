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
uv run python -m uvicorn app.knowledge.web_api:app --host 127.0.0.1 --port 8090
```

打开 `http://127.0.0.1:8090/`。工作台上传 PDF、Markdown 或 UTF-8 文本后生成 BGE 稠密与稀疏向量并写入 `CHUNKS_COLLECTION`，聊天通过同一 Milvus 集合执行普通与 HyDE 两路召回；页面不会使用本地关键词资料搜索。PDF 解析需要本地 MinerU；查询和导入需要 Milvus、BGE 及模型服务配置。导入任务状态保存在单进程内，重启后任务状态不保留；文件和向量存储分别位于 `output/web_imports/` 和 Milvus。资料列表最多统计前 1000 个可引用片段。

默认使用本地合成资料和确定性 Mock，适合离线检查流程。Mock 不是模型决策效果证明。资料可直接修改 `data/knowledge.json`，下一次请求即生效。

真实模型模式复用现有 `app/lm/lm_utils.py`：在根目录 `.env` 中设置 `OPENAI_BASE_URL`、`OPENAI_API_KEY`、`LLM_DEFAULT_MODEL`、`LLM_DEFAULT_TEMPERATURE`，然后运行：

```powershell
uv run python -m app.knowledge.cli "报销期限多久？" --model real
```

可通过 `--max-calls` 设置工具调用上限。真实模型需要兼容 JSON 输出的 API；工具错误、无效引用或达到上限会返回 `incomplete`。

## 使用双路 Milvus 检索

双路模式复用 BGE 稠密与稀疏混合检索、HyDE 和 RRF。配置现有 `.env` 中的 `MILVUS_URL`、BGE 模型及设备设置，选定一个**新集合名**作为 `CHUNKS_COLLECTION`，先执行：

```powershell
uv run python -m app.knowledge.index_cli <新集合名>
uv run python -m app.knowledge.cli "报销期限多久？" --model real --repository milvus
```

导入命令拒绝覆盖已有集合。修改资料后需新建集合并重新导入。已有商品集合中的片段通常没有 `doc_id` 和 `version_date`，需要补齐这些字段；不能将 `chunk_id` 当作文档 ID。Milvus 路径需要运行服务和模型文件，目前尚未端到端验证。

## 评审入口

代码：`app/knowledge/`（领域接口、仓库适配、工具、模型、服务、CLI）；测试：`test/test_knowledge.py`；样例：`examples/*.json`；需求与限制：`docs/`。`real_normal.json` 和 `real_conflict.json` 是真实模型对本地资料的运行记录；其余离线样例使用 Mock。Trace 记录工具参数、结果及简短决策依据，不记录模型内部思维过程。

引用校验验证引用属于已读取原文，无法机械保证自然语言回答被原文完整蕴含。冲突识别依赖模型及检索召回，不能保证发现所有冲突；应结合评估数据人工复核。现有 `pyproject.toml` 和 `uv.lock` 为依赖清单。
