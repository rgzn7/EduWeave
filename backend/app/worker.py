"""
@Date: 2026-04-11
@Author: xisy
@Discription: Celery Worker 启动入口
"""

from app.shared.queue.app import celery_app

# 导入以触发 @celery_app.task 注册周期任务，供 Celery Beat 调度
from app.modules.task_center import recovery as _recovery  # noqa: F401
from app.modules.courseware import tasks as _courseware_tasks  # noqa: F401

__all__ = ["celery_app"]

