# EduWeave Backend

EduWeave 后端当前已完成基础收口，现有骨架提供认证、健康检查、统一响应/异常、27 表 schema 基线、Alembic 迁移入口、本地 bootstrap 和 Milvus/OBS/队列基础适配。

## 当前基线

- 已稳定接口：`/health`、`/ready`、`/api/v1/auth/login`、`/api/v1/auth/me`
- 正式数据库初始化入口：`alembic upgrade head`
- 已存在本地库对齐入口：`python scripts/reconcile_alembic.py`
- 本地演示账号与 Milvus 必需集合初始化入口：`python scripts/bootstrap_local.py`
- Milvus P0 只初始化 `textbook_chunk_vector`、`knowledge_point_vector` 两类集合

## 本地启动方式

后端开发统一使用 `backend/.venv` 独立虚拟环境启动，不再建议直接使用本机 `base` 环境手工执行 `uvicorn`。这样可以避免 `numpy`、`pymilvus`、`pandas` 等二进制依赖在全局环境中互相污染。

### 1. 准备环境变量

- 复制 `.env.example` 为 `.env`
- 测试或 CI 场景如需避免本地 `.env` 干扰，可设置 `APP_LOAD_DOTENV=0`
- `MILVUS_COLLECTION_PREFIX` 现在是可选项；如果 Milvus 已按独立库或独立集群隔离，可以留空直接使用逻辑集合名

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
