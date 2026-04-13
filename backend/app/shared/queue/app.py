"""
@Date: 2026-04-11
@Author: xisy
@Discription: Celery 应用与基础任务
"""

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


@celery_app.task(name="system.smoke_ping")
def smoke_ping() -> dict[str, str]:
    """基础烟雾测试任务。"""
    return {"status": "ok", "message": "队列连通正常"}

