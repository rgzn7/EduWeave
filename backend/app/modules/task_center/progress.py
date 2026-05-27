"""
@Date: 2026-05-27
@Author: xisy
@Discription: 任务进度单调推进工具
"""

from __future__ import annotations

from typing import Any


def clamp_progress(progress_percent: int | float | str | None) -> int:
    """把进度归一到 0-100 的整数区间。"""
    try:
        progress = int(progress_percent or 0)
    except (TypeError, ValueError):
        progress = 0
    return max(0, min(100, progress))


def monotonic_progress(current_percent: int | None, next_percent: int | float | str | None) -> int:
    """计算单调进度，避免运行中进度被较小值覆盖。"""
    return max(clamp_progress(current_percent), clamp_progress(next_percent))


def assign_monotonic_progress(record: Any, progress_percent: int | float | str | None) -> None:
    """为带 progress_percent 字段的 ORM 对象写入单调进度。"""
    record.progress_percent = monotonic_progress(getattr(record, "progress_percent", 0), progress_percent)
