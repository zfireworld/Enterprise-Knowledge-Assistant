# 企业知识问答 Agent

通过两个工具检索和读取合成制度，输出答案、文档 ID、版本日期、原文引用、资料缺口和执行轨迹。模型看到工具结果后可选择继续检索、读取、追问或结束。原有导入及产品问答功能保留。

## 环境准备

### 离线 Mock 快速体验

安装 [Python 3.11 或以上版本](https://www.python.org/downloads/)和 [uv](https://docs.astral.sh/uv/getting-started/installation/)，在仓库根目录执行：

```powershell
uv sync
uv run python -m app.knowledge.cli "报销期限多久？"
```

首次安装依赖需要联网，可能需要下载体积较大的 PyTorch 等依赖。安装完成后，此命令使用仓库中的合成资料和确定性 Mock，不需要数据库、模型 API、BGE 权重或 MinerU；它只验证流程，不证明真实模型的决策能力。`uv sync` 只安装 Python 项目依赖，不负责启动数据库、启动模型服务或准备全部模型权重。

### 完整网页和真实模型

1. 安装并启动 Docker Desktop（Windows 建议使用 WSL 2 后端），按 [Milvus 2.6 官方部署指南](https://blog.milvus.io/docs/v2.6.x/install_standalone-docker-compose.md)启动 Milvus Standalone。例如在独立于仓库的空目录下载官方 Compose 文件，运行 `docker compose up -d`，再通过 `docker compose ps` 检查状态；不要覆盖已有实例的数据或配置。该部署还会启动 Milvus 所需的 etcd 和 MinIO。另启动 MongoDB：测试环境确认端口和容器名未占用后，可执行 `docker run -d --name knowledge-mongo -p 27017:27017 mongo:7`。数据库不必与应用运行在同一台机器，示例 MongoDB 无认证，仅供本机测试。
2. 准备 BGE-M3 和 BGE Reranker 的模型文件，例如从 [BAAI/bge-m3](https://huggingface.co/BAAI/bge-m3) 与 [BAAI/bge-reranker-large](https://huggingface.co/BAAI/bge-reranker-large) 下载完整模型到本机目录。安装项目依赖后，可在仓库根目录运行下面的示例；自行将 `D:/models` 替换为可写目录：

   ```powershell
   uv run python -c "from huggingface_hub import snapshot_download; snapshot_download('BAAI/bge-m3', local_dir='D:/models/bge-m3')"
   uv run python -c "from huggingface_hub import snapshot_download; snapshot_download('BAAI/bge-reranker-large', local_dir='D:/models/bge-reranker-large')"
   ```

   首次下载需要联网和足够磁盘空间。未设置 `BGE_M3_PATH` 时程序会尝试加载 `BAAI/bge-m3`，可能触发下载；重排模型不可用时会回退到 RRF 排序。CPU 可运行，但导入和查询速度取决于硬件。
3. 准备支持 OpenAI 兼容接口及 JSON 输出的模型服务，可使用本地服务或远程服务；真实模型及 HyDE 召回需要可访问的服务。`uv sync` 不会启动该服务。
4. 将 `.env.example` 复制为项目根目录的 `.env`（已有 `.env` 时不要覆盖）：

   ```powershell
   Copy-Item .env.example .env
   ```

   编辑 `.env`，将以下环境变量修改为**自己的实际地址、模型路径和密钥**。示例地址仅适用于服务运行在本机且使用相应端口时；模型目录需替换成本机已下载的目录。

   ```dotenv
   OPENAI_BASE_URL=http://127.0.0.1:8000/v1
   OPENAI_API_KEY=填写服务所需的密钥
   LLM_DEFAULT_MODEL=填写服务提供的模型名
   LLM_DEFAULT_TEMPERATURE=0.1
   MILVUS_URL=http://127.0.0.1:19530
   CHUNKS_COLLECTION=knowledge_chunks
   MONGO_URL=mongodb://127.0.0.1:27017/
   MONGO_DB_NAME=knowledge_agent
   BGE_M3_PATH=D:/models/bge-m3
   BGE_DEVICE=cpu
   BGE_FP16=false
   BGE_RERANKER_LARGE=D:/models/bge-reranker-large
   BGE_RERANKER_DEVICE=cpu
   BGE_RERANKER_FP16=false
   ```

   模型服务是否需要密钥取决于服务提供方。`.env` 已被 Git 忽略，不要将真实密钥写进 `.env.example` 或提交到仓库。若系统中已设置同名环境变量，应同时检查其值，避免与 `.env` 配置不一致；修改后重启应用。
5. 仅在导入 PDF 时需要本地 MinerU。项目使用 `mineru -p <PDF> -o <输出目录> -b pipeline`，并强制 `MINERU_MODEL_SOURCE=local`，因此必须预先按所安装 MinerU 版本的文档准备 pipeline 模型文件；`MODELSCOPE_OFFLINE=1` 不会代替模型下载。将兼容该命令及输出目录结构的 `mineru` 加入 PATH，或在 `.env` 中设置 `MINERU_EXECUTABLE` 为可执行文件完整路径。可运行 `mineru --help` 检查参数，并用一份合成 PDF 验证；MinerU 版本变更可能导致命令或输出结构不兼容，参见 [MinerU 官方文档](https://opendatalab.github.io/MinerU/)和[版本迁移说明](https://opendatalab.github.io/MinerU/reference/migration_4/)。Markdown/TXT 导入不需要 MinerU。

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

新导入的 PDF 使用 MinerU `content_list.json` 按物理页切分，并为每个版本登记原文件；引用经过读取及校验后可点击“查看原文”跳至对应 PDF 页。页码是 PDF 页序号，可能与印刷页码不同；浏览器需要支持 PDF `#page` 跳转。解析内容列表缺失或页码不可靠时，系统保留原始 Markdown 流程且不猜测页码。旧片段不自动回填位置；可通过更新版本重新导入。原文件存储在 `output/web_imports/`，删除后链接将不可用；服务当前未实现用户认证，勿在不可信网络直接开放文件接口。

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

该命令拒绝覆盖已有集合；网页导入的更新流程见上文。已有商品集合中的片段如缺少 `doc_id` 和 `version_date`，需要补齐这些字段；不能将 `chunk_id` 当作文档 ID。已使用真实 MongoDB、Milvus、本地 MinerU 和模型在隔离集合中验证合成 PDF 导入与引用链接；浏览器 PDF 阅读器跳页仍需手动验证。

## 评审入口

代码：`app/knowledge/`（领域接口、仓库适配、工具、模型、服务、CLI）；测试：`test/test_knowledge*.py`；样例：`examples/*.json` 和 `examples/live_runs/`；验收点与复现方法见 `docs/03-evaluation.md`。`real_normal.json` 和 `real_conflict.json` 是历史真实模型对本地资料的运行记录；`examples/live_runs/6053807dd6/` 是真实模型及独立 Milvus 集合的验收记录，其中工具失败是故障注入；`examples/live_runs/19089be3ff/` 是合成 PDF 真实解析与引用来源记录。离线样例使用 Mock，不能证明真实模型或 Milvus 的效果。Trace 记录工具参数、结果及简短决策依据，不记录模型内部思维过程。

网页导入测试资料、逐项手动操作及查看 Trace 的方法见 [手工测试指南](docs/06-manual-testing.md)。

引用校验验证引用属于已读取原文，无法机械保证自然语言回答被原文完整蕴含。冲突识别依赖模型及检索召回，不能保证发现所有冲突；应结合评估数据人工复核。现有 `pyproject.toml` 和 `uv.lock` 为依赖清单。
