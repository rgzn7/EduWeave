# @Date: 2026-05-30
# @Author: xisy
# @Discription: EduWeave 后端镜像（FastAPI + Python 3.12）。仅安装依赖、以源码方式运行，
#               不构建本项目包，规避 setuptools 显式 packages 列表与 pip 构建拷贝导致的坑。
#               同一镜像可同时承载 API 与 Celery worker（worker 在 Zeabur 覆盖启动命令）。

FROM python:3.12-slim

# 运行环境基础设置：日志直出、关闭 pip 缓存、源码目录加入模块搜索路径、默认生产模式
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app \
    APP_ENV=production \
    SERVICE_ROLE=api \
    CELERY_QUEUES=celery,profile_queue,parsing_queue,knowledge_queue,generation_queue \
    CELERY_LOGLEVEL=info

WORKDIR /app

# 先装运行期依赖（依赖清单单独成层，未变更时命中缓存）
COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

# 复制源码与数据库迁移脚本；应用以源码方式运行，import app.* 由 PYTHONPATH=/app 解析
COPY app ./app
COPY migrations ./migrations
COPY alembic.ini ./

# Zeabur 以 Dockerfile 部署时取 EXPOSE 端口（默认 8080），并据此注入同值的 $PORT
EXPOSE 8080

# 启动：默认先执行数据库迁移，再拉起 API；worker 服务通过 SERVICE_ROLE=worker 切换为 Celery。
CMD ["sh", "-c", "if [ \"${SERVICE_ROLE:-api}\" = \"worker\" ]; then celery -A app.worker worker -B -Q ${CELERY_QUEUES:-celery,profile_queue,parsing_queue,knowledge_queue,generation_queue} --loglevel=${CELERY_LOGLEVEL:-info}; else alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}; fi"]
