"""
@Date: 2026-04-11
@Author: xisy
@Discription: Celery 应用与基础任务
"""

from dataclasses import dataclass
from importlib import import_module
from typing import Any

from celery import Celery

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
    settings: Settings | None = None,
    run_inline: bool | None = None,
) -> TaskDispatchResult:
    """统一派发任务，测试环境允许同步执行。"""
    current_settings = settings or get_settings()
    should_run_inline = current_settings.task_eager_mode if run_inline is None else run_inline
    if should_run_inline:
        result = execute_callable_task(callable_path, payload)
        return TaskDispatchResult(worker_task_id=None, executed_inline=True, result=result)

    async_result = execute_callable_task.delay(callable_path, payload)
    return TaskDispatchResult(worker_task_id=str(async_result.id), executed_inline=False)


@celery_app.task(name="system.smoke_ping")
def smoke_ping() -> dict[str, str]:
    """基础烟雾测试任务。"""
    return {"status": "ok", "message": "队列连通正常"}
