<!-- @Date: 2026-04-26 @Author: xisy @Discription: EduWeave 后端开发说明 -->

# EduWeave Backend

EduWeave 后端当前已完成阶段一输入链、阶段二知识结构化链路和阶段三生成链路第一段：认证、项目、教材、学情、教材解析、解析确认、知识抽取、知识版本管理、知识人工修正、生成批次、课程大纲生成、任务中心和通用文件下载地址；教材解析与学情抽取已替换为真实 MinerU 接入，知识抽取与课程大纲生成通过 OpenAI 兼容接口接入结构化 LLM，知识阶段同时接入独立 Embedding 服务和 Milvus 向量写入。

## 当前基线

- 已稳定接口：
  - `/health`、`/ready`
  - `/api/v1/auth/login`、`/api/v1/auth/me`
  - `/api/v1/projects/**`
  - `/api/v1/projects/{project_id}/textbooks`
  - `/api/v1/projects/{project_id}/learner-profiles`
  - `/api/v1/learner-profile-versions/{profile_version_id}`
  - `/api/v1/textbook-versions/{textbook_version_id}/parse-tasks`
  - `/api/v1/parse-versions/{parse_version_id}/confirm`
  - `/api/v1/parse-versions/{parse_version_id}/reparse-tasks`
  - `/api/v1/parse-versions/{parse_version_id}/manual-revisions`
  - `/api/v1/parse-versions/{parse_version_id}/knowledge-tasks`
  - `/api/v1/parse-versions/{parse_version_id}/knowledge-versions`
  - `/api/v1/knowledge-versions/{knowledge_version_id}`
  - `/api/v1/knowledge-versions/{knowledge_version_id}/chapters`
  - `/api/v1/knowledge-versions/{knowledge_version_id}/points`
  - `/api/v1/knowledge-points/{knowledge_point_id}`
  - `/api/v1/knowledge-versions/{knowledge_version_id}/manual-revisions`
  - `/api/v1/generation-batches`
  - `/api/v1/generation-batches/{generation_batch_id}`
  - `/api/v1/curriculum-plans`
  - `/api/v1/curriculum-plans/{curriculum_plan_id}`
  - `/api/v1/tasks/**`
  - `/api/v1/files/{file_object_id}/download-url`
- 正式数据库初始化入口：`alembic upgrade head`
- 已存在本地库对齐入口：`python scripts/reconcile_alembic.py`
- 本地演示账号与 Milvus 必需集合初始化入口：`python scripts/bootstrap_local.py`
- Milvus P0 只初始化 `textbook_chunk_vector`、`knowledge_point_vector` 两类集合
- 当前自动化测试基线：`58 passed`

## 本地启动方式

后端开发统一使用 `backend/.venv` 独立虚拟环境启动，不再建议直接使用本机 `base` 环境手工执行 `uvicorn`。这样可以避免 `numpy`、`pymilvus`、`pandas` 等二进制依赖在全局环境中互相污染。

### 1. 准备环境变量

- 复制 `.env.example` 为 `.env`
- 测试或 CI 场景如需避免本地 `.env` 干扰，可设置 `APP_LOAD_DOTENV=0`
- `MILVUS_COLLECTION_PREFIX` 现在是可选项；如果 Milvus 已按独立库或独立集群隔离，可以留空直接使用逻辑集合名
- 阶段一新增 MinerU 配置：`MINERU_API_BASE_URL`、`MINERU_API_TOKEN`、`MINERU_MODEL_VERSION`、`MINERU_POLL_INTERVAL_SECONDS`、`MINERU_POLL_TIMEOUT_SECONDS`
- 阶段一新增 OBS 签名下载地址配置：`OBS_SIGNED_URL_EXPIRE_SECONDS`
- 阶段二与阶段三共用 OpenAI 兼容结构化 LLM 配置：`LLM_API_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL`、`LLM_TIMEOUT_SECONDS`
- 可选开启 LLM 推理强度：配置 `LLM_REASONING_EFFORT` 后会在聊天补全请求中传入 `reasoning_effort`，不配置或留空则不启用
- 阶段二新增独立向量化配置：`EMBEDDING_API_BASE_URL`、`EMBEDDING_API_KEY`、`EMBEDDING_MODEL`、`EMBEDDING_TIMEOUT_SECONDS`

### 2. 创建并安装虚拟环境

首次进入项目时，在 `backend/` 目录执行：

```bash
python -m venv .venv
./.venv/bin/python -m pip install "setuptools>=69.0" wheel
./.venv/bin/python -m pip install --no-build-isolation -e ".[dev]"
```

说明：

- 如果网络正常，也可以先尝试直接执行 `./.venv/bin/python -m pip install -e ".[dev]"`
- 当前项目已在依赖中固定 `numpy<2`，用于避免 Milvus 相关依赖在 NumPy 2.x 下出现 ABI 兼容问题

### 3. 初始化数据库

- 新库：在 `backend/` 目录执行 `./.venv/bin/python -m alembic upgrade head`
- 已由 SQL 脚本初始化的旧库：执行 `./.venv/bin/python scripts/reconcile_alembic.py`

### 4. 执行本地 bootstrap

在 `backend/` 目录执行：

```bash
./.venv/bin/python scripts/bootstrap_local.py
```

脚本会幂等确保本地演示教师账号存在，并尝试初始化 Milvus 必需集合；如果本地 Milvus 未启动或依赖环境异常，脚本会明确输出失败原因。

### 5. 启动开发服务

统一启动方式：

```bash
./.venv/bin/python scripts/start_dev.py
```

如果你更习惯先激活虚拟环境，也可以执行：

```bash
source .venv/bin/activate
python scripts/start_dev.py
```

`scripts/start_dev.py` 会校验当前解释器是否来自 `backend/.venv`。如果误用了本机 `base` 环境，脚本会直接阻止启动并提示正确命令。

### 6. 运行测试

在 `backend/` 目录执行：

```bash
./.venv/bin/python -m pytest
```

## 说明

- `sql/20260413_eduweave_mysql_27_tables.sql` 仍作为本阶段 schema 真源与历史初始化参考
- 日常开发不再推荐直接手工执行 27 表 SQL 初始化新环境，统一走 Alembic
- 若未安装 `PyMuPDF`，教材页图预览会降级为空；建议按 `pyproject.toml` 安装完整依赖
- 知识抽取前必须先显式调用 `/api/v1/parse-versions/{parse_version_id}/confirm` 确认解析版本
- 知识人工修正采用补丁式版本提交，当前支持 `update_summary / update_chapter / add_point / update_point / delete_point / merge_points`
- 生成批次当前只自动编排课程大纲生成，`lesson_plan / assessment / courseware / coverage / audit` 后续继续接入同一个 `generation_batch`
- 课程大纲生成要求显式传入 `knowledge_version_id` 和 `learner_profile_version_id`，后端会冻结本次基线并在成功后回写 `generation_batch.curriculum_plan_id`
