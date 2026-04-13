"""
@Date: 2026-04-11
@Author: xisy
@Discription: 队列能力导出
"""

from app.shared.queue.app import TaskDispatchResult, celery_app, dispatch_task

__all__ = ["celery_app", "dispatch_task", "TaskDispatchResult"]

from app.shared.queue.app import CeleryAppFactory, celery_app

__all__ = ["CeleryAppFactory", "celery_app"]
