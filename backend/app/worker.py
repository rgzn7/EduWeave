"""
@Date: 2026-04-11
@Author: xisy
@Discription: Celery Worker 启动入口
"""

from app.shared.queue.app import celery_app

__all__ = ["celery_app"]

