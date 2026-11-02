# 仓库贡献指南

## 项目结构与模块组织

本项目使用 Python 3.11 及以上版本，包含两个 FastAPI 服务：`app/import_process/` 负责文档导入，`app/query_process/` 负责检索和对话。各服务分别存放 API 路由、LangGraph 状态与节点，以及对应的 HTML 页面。共享配置、外部服务客户端、模型辅助代码和通用工具分别位于 `app/conf/`、`app/clients/`、`app/lm/` 和 `app/utils/`。提示词模板放在 `prompts/`，示例手册放在 `doc/`；`output/` 和 `logs/` 存放运行产物。`test/` 目前主要是可独立运行的诊断和集成脚本。

## 构建、测试与本地运行

在仓库根目录执行以下命令：

- `uv sync`：根据 `pyproject.toml` 和 `uv.lock` 安装依赖。
- `uv run python -m app.import_process.api.file_import_service`：在 `127.0.0.1:8000` 启动导入服务。
- `uv run python -m app.query_process.api.query_service`：在 `127.0.0.1:8001` 启动查询服务。
- `uv run python test/05-test-main-graph.py`：使用 `doc/hak180产品安全手册.pdf` 验证导入流程。该脚本依赖已配置的外部服务，并会写入 `output/`。

仓库目前没有单独的构建步骤或统一的测试命令。

## 代码风格与命名

Python 代码使用四个空格缩进。模块、函数和变量使用 `snake_case`，类和类型化状态对象使用 `PascalCase`。图节点放在对应服务的 `agent/nodes/` 下，并沿用 `node_*.py` 命名。可复用配置放在 `app/conf/`，提示词放在 `.prompt` 文件中。`pyproject.toml` 尚未配置格式化或静态检查工具；修改时保持与相邻代码一致。

## 测试要求

现有 `test/` 文件是可执行脚本，不是已配置的 pytest 测试套件；仓库也没有覆盖率门槛。修改后运行相关脚本，并检查日志和输出。新增可独立验证的逻辑时，优先编写 `test_*.py` 自动化测试，尽量避免测试依赖在线模型、数据库或对象存储。

## 配置与安全

配置模块会加载根目录的 `.env`。在该文件或环境变量中设置模型 API、Milvus、MinIO 和 MongoDB 等必要凭据与地址。不要提交 `.env`、密钥、`logs/` 或 `output/` 中的生成数据，也不要提交 `doc/` 中的私有手册。

## 提交与拉取请求

当前工作目录没有 Git 历史，无法核实既有提交格式。建议使用简短的祈使句作为提交标题，并指出修改范围，例如 `Fix import graph state handling`。拉取请求应说明行为变化、所需配置和验证结果；关联相关议题，修改 HTML 页面时附上截图。
