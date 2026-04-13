"""
@Date: 2026-04-11
@Author: xisy
@Discription: 时间处理工具
"""

from datetime import datetime, timezone


class DateTimeUtil:
    """统一时间工具。"""

    @staticmethod
    def now_utc() -> datetime:
        """获取当前 UTC 时间。"""
        return datetime.now(timezone.utc)

    @staticmethod
    def to_isoformat(value: datetime) -> str:
        """输出带 Z 后缀的 ISO8601 字符串。"""
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

