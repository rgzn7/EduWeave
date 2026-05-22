"""
@Date: 2026-04-11
@Author: xisy
@Discription: Celery 应用与基础任务
"""

from dataclasses import dataclass
from importlib import import_module
from typing import Any

from celery import Celery
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings


class CeleryAppFactory:
    """Celery 应用工厂。"""

    @staticmethod
    def create(settings: Settings) -> Celery:
        app = Celery(
            "eduweave",
            broker=settings.redis_url,
            backend=settings.redis_url,
        )
        app.conf.update(
            task_serializer="json",
            result_serializer="json",
            accept_content=["json"],
            timezone="UTC",
            enable_utc=True,
            task_track_started=True,
            # 单 worker 每次只预取 1 个任务，避免长任务在单 worker 上囤积
            worker_prefetch_multiplier=1,
            # broker 启动期重连，避免 worker/beat 早于 Redis 就绪时启动失败
            broker_connection_retry_on_startup=True,
            # 任务结果 24h 过期，防止 Redis 结果区无限膨胀
            result_expires=86400,
            # 周期回收僵尸任务：扫描卡在 processing 的 task_record 并重排或判失败
            beat_schedule={
                "reap-stale-tasks": {
                    "task": "system.reap_stale_tasks",
                    "schedule": float(settings.task_reaper_interval_seconds),
                },
                # 周期复查停泊在 Raccoon 远程生成阶段的课件任务，使关闭页面也能完成
                "poll-pending-courseware": {
                    "task": "courseware.poll_pending_remote_results",
                    "schedule": float(settings.courseware_remote_poll_interval_seconds),
                },
            },
        )
        return app


celery_app = CeleryAppFactory.create(get_settings())


@dataclass(slots=True)
class TaskDispatchResult:
    """统一任务投递结果。"""

    worker_task_id: str | None
    executed_inline: bool
    result: dict[str, Any] | None = None


def import_callable(callable_path: str):
    """按路径导入处理函数。"""
    module_path, function_name = callable_path.rsplit(".", 1)
    module = import_module(module_path)
    return getattr(module, function_name)


@celery_app.task(name="system.execute_callable_task")
def execute_callable_task(callable_path: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    """执行指定处理函数。"""
    handler = import_callable(callable_path)
    return handler(payload)


def dispatch_task(
    callable_path: str,
    payload: dict[str, Any],
    *,
    queue: str | None = None,
    settings: Settings | None = None,
    run_inline: bool | None = None,
    countdown: int | None = None,
    session: Session | None = None,
) -> TaskDispatchResult:
    """统一派发任务，测试环境允许同步执行。

    queue 用于将任务投递到与任务记录 queue_name 一致的队列，
    避免 worker 仅监听业务队列时任务滞留在默认 celery 队列。
    countdown 为失败重试的退避延迟（秒）。
    session 仅在同步内联执行时使用：注入当前数据库连接串，使内联任务连到
    与调用方一致的数据库（如测试用例的独立库）；异步派发绝不会序列化数据库
    连接串，避免明文密码经 Redis broker 传输。
    """
    current_settings = settings or get_settings()
    should_run_inline = current_settings.task_eager_mode if run_inline is None else run_inline
    if should_run_inline:
        inline_payload = dict(payload)
        if session is not None and "database_url" not in inline_payload:
            inline_payload["database_url"] = session.get_bind().url.render_as_string(hide_password=False)
        result = execute_callable_task(callable_path, inline_payload)
        return TaskDispatchResult(worker_task_id=None, executed_inline=True, result=result)

    async_result = execute_callable_task.apply_async(
        args=[callable_path, payload],
        queue=queue,
        countdown=countdown,
    )
    return TaskDispatchResult(worker_task_id=str(async_result.id), executed_inline=False)


@celery_app.task(name="system.smoke_ping")
def smoke_ping() -> dict[str, str]:
    """基础烟雾测试任务。"""
    return {"status": "ok", "message": "队列连通正常"}
