# Repository Guidelines

## Project Structure & Module Organization

This Python 3.11+ project has two FastAPI services. `app/import_process/` handles document ingestion; `app/query_process/` handles search and chat. Each service keeps API routes, LangGraph state and nodes, and its HTML page nearby. Shared configuration, external-service clients, model helpers, and utilities live in `app/conf/`, `app/clients/`, `app/lm/`, and `app/utils/`. Prompt templates are in `prompts/`; sample manuals are in `doc/`. `output/` and `logs/` contain generated artifacts. The `test/` directory currently contains standalone diagnostic and integration scripts.

## Build, Test, and Development Commands

Run commands from the repository root:

- `uv sync` installs dependencies from `pyproject.toml` and `uv.lock`.
- `uv run python -m app.import_process.api.file_import_service` starts the import API on `127.0.0.1:8000`.
- `uv run python -m app.query_process.api.query_service` starts the query API on `127.0.0.1:8001`.
- `uv run python test/05-test-main-graph.py` exercises the import graph using `doc/hak180产品安全手册.pdf`. It requires configured external services and writes to `output/`.

There is no separate build step or configured project-wide test command.

## Coding Style & Naming Conventions

Use four spaces for Python indentation. Follow existing `snake_case` names for modules, functions, and variables, and `PascalCase` for classes and typed state objects. Keep graph nodes in the relevant `agent/nodes/` directory with the existing `node_*.py` pattern. Put reusable settings in `app/conf/` and prompt text in `.prompt` files. No formatter or linter is configured in `pyproject.toml`; keep edits consistent with nearby code.

## Testing Guidelines

The current `test/` files are executable scripts, not an automated pytest suite; no coverage threshold is configured. Run the script relevant to your change and check its logs and outputs. For new isolated logic, add focused automated tests with `test_*.py` names, and avoid requiring live model, database, or object-storage services where possible.

## Configuration & Security

Configuration modules load the root `.env`. Set required credentials and endpoints there or in the environment, including model API, Milvus, MinIO, and MongoDB settings. Never commit `.env`, credentials, generated `logs/` or `output/` data, or private manuals from `doc/`.

## Commits & Pull Requests

This checkout has no Git history, so no existing commit convention can be verified. Use short imperative commit subjects that identify the affected area, such as `Fix import graph state handling`. In pull requests, describe behavior changes, configuration needs, and validation performed; link related issues and include screenshots for HTML page changes.
