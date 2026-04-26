"""
@Date: 2026-04-14
@Author: xisy
@Discription: FastAPI 应用启动入口
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.core.middleware import AccessLogMiddleware, RequestIdMiddleware
from app.modules.auth.router import router as auth_router
from app.modules.curriculum.router import router as curriculum_router
from app.modules.file_asset.router import router as file_asset_router
from app.modules.knowledge.router import router as knowledge_router
from app.modules.learner_profile.router import router as learner_profile_router
from app.modules.parsing.router import router as parsing_router
from app.modules.pipeline.router import router as pipeline_router
from app.modules.project.router import router as project_router
from app.modules.system.router import router as system_router
from app.modules.task_center.router import router as task_center_router
from app.modules.textbook.router import router as textbook_router

settings = get_settings()
configure_logging(settings.log_level)
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    """统一管理应用生命周期。"""
    logger.info("应用启动完成", app_name=settings.app_name, app_env=settings.app_env)
    yield
    logger.info("应用关闭完成", app_name=settings.app_name, app_env=settings.app_env)


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-Id"],
)
app.add_middleware(AccessLogMiddleware)
# RequestIdMiddleware 需要位于日志中间件外层，确保访问日志写出时仍能拿到 request_id 与 user_id。
app.add_middleware(RequestIdMiddleware)

register_exception_handlers(app)

app.include_router(system_router)
app.include_router(auth_router, prefix=settings.api_v1_prefix)
app.include_router(file_asset_router, prefix=settings.api_v1_prefix)
app.include_router(project_router, prefix=settings.api_v1_prefix)
app.include_router(textbook_router, prefix=settings.api_v1_prefix)
app.include_router(learner_profile_router, prefix=settings.api_v1_prefix)
app.include_router(parsing_router, prefix=settings.api_v1_prefix)
app.include_router(knowledge_router, prefix=settings.api_v1_prefix)
app.include_router(pipeline_router, prefix=settings.api_v1_prefix)
app.include_router(curriculum_router, prefix=settings.api_v1_prefix)
app.include_router(task_center_router, prefix=settings.api_v1_prefix)
