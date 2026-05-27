<!-- @Date: 2026-05-22 @Author: xisy @Discription: EduWeave 后端开发说明 -->

# EduWeave Backend

EduWeave 后端当前已完成阶段一输入链、阶段二知识结构化链路和阶段三生成链路：认证、项目、教材、学情、教材解析、解析确认、知识抽取、知识版本管理、知识人工修正、生成批次、课程大纲生成、教案生成、测评蓝图与单元测试试卷生成、Raccoon PPT 课件生成、覆盖率分析、轻量生成追溯、任务中心和通用文件下载地址；教材解析与学情抽取已替换为真实 MinerU 接入，知识抽取、课程大纲生成、教案生成与测评生成支持 OpenAI Responses `json_schema` 与 Chat Completions `json_object` 两种结构化 LLM 接入方式，课件生成通过 Raccoon PPT OpenAPI 接入，覆盖率分析采用规则统计，知识阶段同时接入独立 Embedding 服务和 Milvus 向量写入。

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
  - `/api/v1/lesson-plans`
  - `/api/v1/lesson-plans/{lesson_plan_id}`
  - `/api/v1/assessment-blueprints`
  - `/api/v1/assessment-blueprints/{assessment_blueprint_id}`
  - `/api/v1/paper-results`
  - `/api/v1/paper-results/{paper_result_id}`
  - `/api/v1/courseware-results`
  - `/api/v1/courseware-results/{courseware_result_id}`
  - `/api/v1/courseware-results/{courseware_result_id}/refresh`
  - `/api/v1/courseware-results/{courseware_result_id}/reply`
  - `/api/v1/coverage-reports`
  - `/api/v1/coverage-reports/{coverage_report_id}`
  - `/api/v1/tasks/**`
  - `/api/v1/files/{file_object_id}/download-url`
- 正式数据库初始化入口：`alembic upgrade head`
- 已存在本地库对齐入口：`python scripts/reconcile_alembic.py`
- 本地演示账号与 Milvus 必需集合初始化入口：`python scripts/bootstrap_local.py`
- Milvus P0 只初始化 `semantic_chunk_vector`、`knowledge_point_vector` 两类集合
- MySQL 当前为 28 表 schema，新增 `semantic_chunk` 作为教材语义块；Zilliz 云端集合已切换为 `semantic_chunk_vector` 与 `knowledge_point_vector`
- 当前自动化测试基线：`139 passed`

## 本地启动方式

后端开发统一使用 `backend/.venv` 独立虚拟环境启动，不再建议直接使用本机 `base` 环境手工执行 `uvicorn`。这样可以避免 `numpy`、`pymilvus`、`pandas` 等二进制依赖在全局环境中互相污染。

### 1. 准备环境变量

- 复制 `.env.example` 为 `.env`
- 测试或 CI 场景如需避免本地 `.env` 干扰，可设置 `APP_LOAD_DOTENV=0`
- `MILVUS_COLLECTION_PREFIX` 现在是可选项；如果 Milvus 已按独立库或独立集群隔离，可以留空直接使用逻辑集合名
- 阶段一新增 MinerU 配置：`MINERU_API_BASE_URL`、`MINERU_API_TOKEN`、`MINERU_MODEL_VERSION`、`MINERU_POLL_INTERVAL_SECONDS`、`MINERU_POLL_TIMEOUT_SECONDS`
- 阶段一新增 OBS 签名下载地址配置：`OBS_SIGNED_URL_EXPIRE_SECONDS`
- 阶段二与阶段三共用 OpenAI 兼容结构化 LLM 配置：`LLM_API_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL`、`LLM_API_FORMAT`、`LLM_TIMEOUT_SECONDS`
- `LLM_API_FORMAT=response` 时调用 `/responses`，使用 `text.format.type=json_schema` 且 `strict=false`；`LLM_API_FORMAT=chat` 时调用 `/chat/completions`，使用 `response_format.type=json_object`，适配 DeepSeek 等不支持 Responses API 的网关
- 两种格式都会继续复用现有“只输出 JSON”提示词与 Pydantic 响应模型做最终校验
- 可选开启 LLM 推理强度：配置 `LLM_REASONING_EFFORT` 后，`response` 格式传入 `reasoning.effort`，`chat` 格式传入 `reasoning_effort`；不配置或留空则改用 `temperature`
- 知识抽取阶段可通过 `KNOWLEDGE_EXTRACT_MAX_CONCURRENCY` 控制语义块级 LLM 并发数，默认 10，范围 1-10；设置为 1 时等价于串行抽取
- 教案生成阶段可通过 `LESSON_PLAN_MAX_CONCURRENCY` 控制并发数，默认 10，范围 1-10；系统会先串行生成第 1 课为 Packy 建立 prompt cache，再最多 10 并发生成剩余课次
- 阶段二新增独立向量化配置：`EMBEDDING_API_BASE_URL`、`EMBEDDING_API_KEY`、`EMBEDDING_MODEL`、`EMBEDDING_TIMEOUT_SECONDS`
- 阶段三新增 Raccoon PPT 配置：`RACCOON_API_HOST`、`RACCOON_API_TOKEN`、`RACCOON_REQUEST_TIMEOUT_SECONDS`、`RACCOON_POLL_INTERVAL_SECONDS`、`RACCOON_SHORT_POLL_TIMEOUT_SECONDS`

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

后端完整运行需要三类应用进程，均依赖 Redis、MySQL、Milvus 已就绪：

- API 服务：处理 HTTP 请求
- Celery worker：执行教材解析、知识抽取、课程大纲/教案/测评/课件生成、覆盖率分析等异步任务
- Celery beat：定时调度后台周期任务（僵尸任务回收、课件远程状态复查）

#### 5.1 API 服务

```bash
./.venv/bin/python scripts/start_dev.py
```

`scripts/start_dev.py` 会校验当前解释器是否来自 `backend/.venv`，如果误用本机 `base` 环境会直接阻止启动并提示正确命令。也可以先激活虚拟环境再启动：

```bash
source .venv/bin/activate
python scripts/start_dev.py
```

#### 5.2 Celery worker 与 beat

开发单机推荐用一条命令：worker 通过 `-B` 内嵌 beat，一个进程同时执行任务与定时调度：

```bash
./.venv/bin/celery -A app.worker worker -B -Q celery,profile_queue,parsing_queue,knowledge_queue,generation_queue --loglevel=info
```

生产或多 worker 部署时，beat 必须独立成单一进程（多个 beat 实例会重复调度），与 worker 分开启动：

```bash
./.venv/bin/celery -A app.worker worker -Q celery,profile_queue,parsing_queue,knowledge_queue,generation_queue --loglevel=info
./.venv/bin/celery -A app.worker beat --loglevel=info
```

要点：

- `-A app.worker` 指向 `app/worker.py` 暴露的 Celery 应用
- worker 的 `-Q` 必须同时包含默认队列 `celery` 与四个业务队列：异步业务任务按业务投递到 `profile_queue / parsing_queue / knowledge_queue / generation_queue`，而 beat 调度的周期任务（`system.reap_stale_tasks`、`courseware.poll_pending_remote_results`）投递到默认 `celery` 队列，缺少任一队列会导致对应任务无人消费
- 不启动 beat 时 API 与普通任务仍可用，但崩溃后的僵尸任务不会自动回收、停泊等待 Raccoon 的课件任务不会自动完成
- 周期行为可由环境变量调整：`TASK_REAPER_INTERVAL_SECONDS`（reaper 扫描间隔，默认 300）、`TASK_STALE_THRESHOLD_SECONDS`（任务判定为僵尸的超时秒数，默认 1800）、`TASK_RETRY_BACKOFF_BASE_SECONDS`（失败重试退避基数，默认 30）、`COURSEWARE_REMOTE_POLL_INTERVAL_SECONDS`（课件远程状态复查间隔，默认 60）

### 6. 运行测试

在 `backend/` 目录执行：

```bash
./.venv/bin/python -m pytest
```

## 说明

- `sql/20260430_eduweave_mysql_28_tables.sql` 仍作为最终初始化脚本与历史参考；早期迁移会读取该 SQL，后续调整需同步评估迁移回放影响
- 日常开发不再推荐直接手工执行 28 表 SQL 初始化新环境，统一走 Alembic
- 若未安装 `PyMuPDF`，教材页图预览会降级为空；建议按 `pyproject.toml` 安装完整依赖
- 知识抽取前必须先显式调用 `/api/v1/parse-versions/{parse_version_id}/confirm` 确认解析版本
- 知识人工修正采用补丁式版本提交，当前支持 `update_summary / update_chapter / add_point / update_point / delete_point / merge_points`
- 生成批次当前自动顺序编排课程大纲、多课次教案与初始覆盖率分析；测评蓝图、单元测试试卷和 Raccoon PPT 课件由用户按需触发，并继续复用同一个 `generation_batch` 保留血缘，轻量 `generation_trace` 已随覆盖率报告写入，完整 `audit` 模块后续继续接入同一个批次根
- 创建生成批次时要求显式传入 `knowledge_version_id` 和 `learner_profile_version_id`，后端会冻结本次基线、章节范围、课次与测评策略；课程大纲和教案成功后分别回写 `generation_batch.curriculum_plan_id` 与 `generation_batch.lesson_plan_id`，测评结果通过 `assessment_blueprint`、`paper_result` 和 `question_item` 按批次查询
- 测评生成当前默认使用 `unit_test` 场景，落库 `assessment_blueprint`、`paper_result` 和 `question_item`，并支持试卷 DOCX 导出；PDF 导出暂未实现
- 课件生成当前使用 Raccoon PPT OpenAPI，若短轮询未完成则课件结果和批次保持 `processing`；除可通过 `/api/v1/courseware-results/{courseware_result_id}/refresh` 手动刷新外，Celery beat 会周期复查停泊在 `waiting_raccoon_result` 阶段的课件任务并自动归档 PPTX 到 OBS，因此关闭页面后也能完成（`waiting_user_input` 阶段需用户调用 `/api/v1/courseware-results/{courseware_result_id}/reply` 回复后才能继续）；课件成功后会刷新覆盖率报告，覆盖率刷新成功后批次才进入 `success`
- 异步任务具备崩溃恢复与失败重试能力：Celery beat 的 `system.reap_stale_tasks` 周期回收卡在 `processing` 的僵尸任务，可重试错误（LLM、MinerU、Raccoon 等外部依赖瞬时类）按 `task_record.retry_count`/`max_retry_count` 指数退避自动重排，业务校验类错误直接判失败；等待外部异步结果的停泊任务不会被误判回收
