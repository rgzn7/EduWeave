"""
@Date: 2026-05-23
@Author: xisy
@Discription: 数值类型安全解析工具
"""

from math import isfinite
from typing import Any


def safe_int(value: Any, default: int) -> int:
    """安全地将任意输入解析为整数，失败时回退到默认值。

    适用场景：解析来自 JSON 字段、人工编辑数据或第三方接口返回值等
    无法保证类型的"应当是整数"的字段，避免单条异常数据导致整个流程中断。

    解析规则：
    - ``bool`` 视为非法输入（避免 ``True`` 被误转为 ``1``）。
    - ``int`` 原值返回。
    - ``float`` 仅在有限值时取整返回，``nan`` / ``inf`` 回退。
    - ``str`` 去除首尾空白后尝试整数解析，失败、空串均回退。
    - 其他类型一律回退。
    """
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not isfinite(value):
            return default
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return default
        try:
            return int(text)
        except ValueError:
            return default
    return default
