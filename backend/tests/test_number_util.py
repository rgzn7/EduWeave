"""
@Date: 2026-05-23
@Author: xisy
@Discription: safe_int 数值解析工具单元测试
"""

from math import inf, nan

import pytest

from app.shared.utils import safe_int


class TestSafeIntValid:
    """命中合法输入路径。"""

    def test_int_returns_original(self) -> None:
        assert safe_int(1, default=99) == 1

    def test_zero_keeps_value(self) -> None:
        # 0 是合法整数，不应当被回退（之前 `or slide_index` 写法会把 0 当成 False 而回退）。
        assert safe_int(0, default=99) == 0

    def test_negative_int_returns_original(self) -> None:
        assert safe_int(-3, default=99) == -3

    def test_numeric_string_parses(self) -> None:
        assert safe_int("3", default=99) == 3

    def test_numeric_string_with_whitespace_parses(self) -> None:
        assert safe_int("  4 ", default=99) == 4

    def test_negative_numeric_string_parses(self) -> None:
        assert safe_int("-7", default=99) == -7

    def test_finite_float_truncates(self) -> None:
        assert safe_int(3.7, default=99) == 3


class TestSafeIntFallback:
    """命中非法输入回退路径。"""

    @pytest.mark.parametrize("value", ["第3页", "abc", "3.5", "3a"])
    def test_non_numeric_string_falls_back(self, value: str) -> None:
        assert safe_int(value, default=99) == 99

    def test_empty_string_falls_back(self) -> None:
        assert safe_int("", default=99) == 99

    def test_whitespace_only_string_falls_back(self) -> None:
        assert safe_int("   ", default=99) == 99

    def test_none_falls_back(self) -> None:
        assert safe_int(None, default=99) == 99

    @pytest.mark.parametrize("value", [True, False])
    def test_bool_falls_back(self, value: bool) -> None:
        # 避免 True 被错误识别为 1。
        assert safe_int(value, default=99) == 99

    @pytest.mark.parametrize("value", [nan, inf, -inf])
    def test_non_finite_float_falls_back(self, value: float) -> None:
        assert safe_int(value, default=99) == 99

    @pytest.mark.parametrize("value", [[1], {"a": 1}, (1,), object()])
    def test_other_types_fall_back(self, value: object) -> None:
        assert safe_int(value, default=99) == 99
