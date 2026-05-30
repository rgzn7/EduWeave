# EduWeave Zeabur 部署说明书

@Date: 2026-05-30 @Author: xisy @Discription: EduWeave 在 Zeabur 上的多服务 Docker 部署指南

## 一、整体架构

EduWeave 不是单容器应用，需要在同一个 Zeabur Project 内编排多个服务协同运行。前端通过容器内 nginx 同源反代 `/api` 到后端内网，避免跨域；后端 API 与 Celery worker 共用同一镜像，仅启动命令不同；MySQL、Redis 使用 Zeabur 市场一键服务；向量库使用托管的 Zilliz Cloud；OBS、LLM、MinerU、Embedding、Raccoon 均为外部云服务，只需在后端配置环境变量。

| 服务名 | 部署来源 | 监听端口 | 说明 |
|--------|----------|----------|------|
| `backend` | `backend/` 目录 + Dockerfile | 8080 | FastAPI / uvicorn，启动时自动执行数据库迁移 |
| `worker` | 同 `backend` 镜像 | 无需对外 | Celery worker 内嵌 beat，处理异步任务与周期任务 |
| `frontend` | `frontend/` 目录 + Dockerfile | 8080 | nginx 托管 Vite 产物并反代 `/api` |
| `mysql` | Zeabur 市场 Prebuilt | 3306 | 业务数据库 |
| `redis` | Zeabur 市场 Prebuilt | 6379 | Celery broker / backend |
| Zilliz Cloud | 外部托管 | — | Milvus 向量库，后端仅配 URI 与 Token |

服务间通过 Zeabur 私有网络互访，地址格式为 `<服务名>.zeabur.internal:<端口>`，例如后端为 `backend.zeabur.internal:8080`、数据库为 `mysql.zeabur.internal:3306`。

## 二、本地准备（已随仓库提供）

以下文件已在仓库中生成，拖拽上传即可被 Zeabur 识别为 Docker 构建：

- `backend/Dockerfile` 与 `backend/.dockerignore`：后端 / worker 共用镜像
- `frontend/Dockerfile`、`frontend/nginx.conf` 与 `frontend/.dockerignore`：前端 nginx 镜像
- 前端 `src/lib/api.ts` 已调整为未配置 `VITE_API_BASE_URL` 时回退到同源地址，配合 nginx 反代无需写死后端域名

注意 `.dockerignore` 已排除本地 `.env`，生产配置一律改由 Zeabur 控制台注入，切勿把本地 `.env` 打进镜像。

## 三、部署步骤

### 1. 创建 Project 与基础设施

在 Zeabur 新建一个 Project，先从市场（Prebuilt / Marketplace）添加 MySQL 与 Redis 两个服务。MySQL 创建后记下其注入的连接变量；MySQL 默认数据库名可能不是 `eduweave`，需在后端环境变量中显式指定 `MYSQL_DATABASE=eduweave`，或在数据库中手动建库。

### 2. 准备 Zilliz Cloud（Milvus 托管）

在 Zilliz Cloud 注册并创建一个免费 Cluster，拿到 Public Endpoint 与 API Token，分别对应后端的 `MILVUS_URI` 与 `MILVUS_TOKEN`。向量维度 `MILVUS_EMBEDDING_DIM` 必须与所用 Embedding 模型输出维度一致（默认 1024）。

### 3. 部署后端 backend

将本地 `backend/` 目录拖拽到 Zeabur 新建服务。Zeabur 检测到 `Dockerfile` 后走 Docker 构建，服务名建议命名为 `backend`（nginx 反代依赖此名）。在该服务的 Variables 中配置第四节的后端环境变量，并在 Networking 中确认对外端口为 8080、健康检查路径设为 `/health`。

### 4. 部署 worker（同镜像，改启动命令）

再次将 `backend/` 目录拖拽创建一个新服务，命名为 `worker`。在其 Settings 中覆盖启动命令（Start Command）为：

```
celery -A app.worker worker -B -Q celery,profile_queue,parsing_queue,knowledge_queue,generation_queue --loglevel=info
```

worker 的环境变量与 backend 完全一致（可直接复制），但 worker 不对外暴露端口，也不需要健康检查。`-B` 表示内嵌 beat 调度，单 worker 实例足够；若未来扩成多 worker，必须把 beat 拆成独立服务（命令去掉 `-B` 另起一个 `celery -A app.worker beat`），否则会重复调度。

### 5. 部署前端 frontend

将本地 `frontend/` 目录拖拽创建服务，命名为 `frontend`，Docker 构建。前端默认走同源反代，无需配置 `VITE_API_BASE_URL`。对外端口 8080。部署完成后通过该服务的 Zeabur 域名访问即可，所有 `/api` 请求会被 nginx 转发到 `backend`。

### 6. 绑定域名

为 `frontend` 绑定 Zeabur 自动域名或自定义域名作为用户入口；`backend` 可不暴露公网（仅供 nginx 内网访问），如需直接访问后端文档 `/docs` 再单独开公网域名。

## 四、后端环境变量清单

下列变量在 backend 与 worker 两个服务上都要配置。标注「必填」的若缺失，应用启动即报错。

### 基础与跨域

- `APP_ENV=production`
- `API_V1_PREFIX=/api/v1`
- `LOG_LEVEL=INFO`
- `CORS_ALLOWED_ORIGINS`：填前端正式域名（逗号分隔）。走同源反代时浏览器请求同源，理论上不触发跨域，但仍建议把前端域名填上以兼容直连场景。

### 数据库（必填）

后端读取 `MYSQL_USERNAME`，可直接使用 Zeabur MySQL 模板注入的用户名变量，也可以直接填实际用户名：

- `MYSQL_HOST=mysql.zeabur.internal`
- `MYSQL_PORT=3306`
- `MYSQL_USERNAME`：使用 Zeabur MySQL 模板注入值，或手动填实际用户名
- `MYSQL_PASSWORD=${MYSQL_PASSWORD}`
- `MYSQL_DATABASE=eduweave`

### Redis（必填）

- `REDIS_URI=redis://redis.zeabur.internal:6379/0`（若 Redis 设了密码则为 `redis://:密码@redis.zeabur.internal:6379/0`）
- `TASK_EAGER_MODE=false`

### 鉴权（必填）

- `JWT_SECRET`：生产务必改成高强度随机串，不能留 `please_change_me`
- `JWT_ACCESS_TOKEN_EXPIRE_MINUTES=120`
- `JWT_ALGORITHM=HS256`

### 向量库 Milvus / Zilliz（必填）

- `MILVUS_URI`：Zilliz Cluster Public Endpoint
- `MILVUS_TOKEN`：Zilliz API Token
- `MILVUS_DB_NAME=default`
- `MILVUS_EMBEDDING_DIM=1024`（必须与 Embedding 模型维度一致）
- `MILVUS_INDEX_TYPE=HNSW`、`MILVUS_METRIC_TYPE=COSINE`

### 对象存储 OBS（必填）

- `OBS_ENDPOINT`、`OBS_AK`、`OBS_SK`、`OBS_BUCKET`、`OBS_BASE_PREFIX=projects`、`OBS_SIGNED_URL_EXPIRE_SECONDS=3600`

### LLM / Embedding / MinerU / Raccoon（按需）

- `LLM_API_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL`
- `LLM_API_FORMAT=response`（务必保持 `response`：agent 工具调用强依赖 Responses 协议，改成 chat 会导致工具参数错位失败）
- `EMBEDDING_API_BASE_URL`、`EMBEDDING_API_KEY`、`EMBEDDING_MODEL`
- `MINERU_API_TOKEN`（文档解析需要）
- `RACCOON_API_TOKEN`（课件生成需要）

其余并发、重试、超时类变量保持默认即可，完整项参见 `backend/.env.example`。

## 五、端口与私有网络说明

Zeabur 以 Dockerfile 部署时，服务端口取 `EXPOSE` 的值（本项目前后端均为 8080），并注入同值的 `PORT` 环境变量供应用监听，因此后端 uvicorn 用 `--port ${PORT:-8080}`、前端 nginx `listen 8080`。服务间互访不要走公网，使用 `<服务名>.zeabur.internal:<端口>` 内网地址，既省流量又更安全。

## 六、上线后自检

- 访问 `https://<backend域名>/health`（若开放）或在 worker/backend 日志看到「应用启动完成」即为后端正常
- 打开前端域名能加载页面，登录接口 `/api/v1/auth/login` 返回正常，说明 nginx 反代链路通
- 在 worker 日志确认 Celery 已连接 Redis、beat 周期任务（`reap-stale-tasks`、`poll-pending-courseware`）按间隔触发
- 触发一次教材解析 / 知识抽取，确认 MinerU、LLM、Milvus、OBS 全链路可用

## 七、常见问题

- 后端启动即崩、报缺少配置：检查第四节「必填」变量是否漏配，尤其 `MYSQL_*`、`REDIS_URI`、`JWT_SECRET`、`MILVUS_URI`、`MILVUS_EMBEDDING_DIM`、`OBS_*`。
- 前端能打开但接口 404 / 502：确认后端服务名确为 `backend` 且端口 8080，与 `nginx.conf` 中 `backend.zeabur.internal:8080` 一致。
- 流式（agent 时间线、课件生成）卡住不增量输出：确认未在 nginx 之外再套一层开启缓冲的代理；本配置已 `proxy_buffering off`。
- 异步任务一直 pending：确认 worker 服务已起、启动命令包含全部队列、`REDIS_URI` 与 backend 指向同一 Redis。
- 数据库结构变更未生效：迁移在 backend 启动时执行；新增迁移后重新部署 backend 即可，worker 不跑迁移。
