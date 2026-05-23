"""
@Date: 2026-05-23
@Author: xisy
@Discription: Celery Worker 启动入口测试
"""

import subprocess
import sys
from pathlib import Path


def test_worker_should_register_sys_user_metadata_before_business_tasks() -> None:
    """Worker 入口应预加载认证模型，避免动态任务解析 task_record 外键失败。"""
    backend_dir = Path(__file__).resolve().parents[1]
    command = [
        sys.executable,
        "-c",
        (
            "import app.worker; "
            "from app.core.database import Base; "
            "assert 'sys_user' in Base.metadata.tables; "
            "assert 'task_record' in Base.metadata.tables; "
            "Base.metadata.sorted_tables"
        ),
    ]

    result = subprocess.run(command, cwd=backend_dir, capture_output=True, text=True, check=False)

    assert result.returncode == 0, result.stderr
