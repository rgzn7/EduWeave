"""
@Date: 2026-05-30
@Author: xisy
@Discription: 业务模块包初始化
"""

import sys

from app.modules import quality_report

# 兼容历史任务记录中的旧 callable_path，Zeabur 上传会过滤 coverage 目录名，因此实际模块改为 quality_report。
sys.modules.setdefault("app.modules.coverage", quality_report)
