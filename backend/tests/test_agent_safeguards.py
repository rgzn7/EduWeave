"""
@Date: 2026-05-29
@Author: xisy
@Discription: 智能助手工具守护单元测试：同参重复熔断、配额终结态、read-before-write 硬约束、结构化拒绝
"""

from __future__ import annotations

from typing import Any

from app.core.config import get_settings
from app.modules.agent.executor import AgentRunExecutor
from app.modules.agent.tools import AgentToolService


class _StubToolService:
    """仅提供 check_write_precondition 的工具服务桩，默认放行。"""

    def __init__(self, block: dict[str, Any] | None = None) -> None:
        self._block = block

    def check_write_precondition(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
        return self._block


def _make_executor(
    *,
    max_tool_calls: int = 40,
    repeated_limit: int = 3,
    tool_service: _StubToolService | None = None,
) -> AgentRunExecutor:
    """绕过 __init__ 构造执行器，仅注入守护逻辑所需的最小状态。"""
    executor = object.__new__(AgentRunExecutor)
    settings = get_settings().model_copy(
        update={
            "agent_max_tool_calls": max_tool_calls,
            "agent_repeated_tool_call_limit": repeated_limit,
        }
    )
    executor.settings = settings
    executor.tool_call_count = 0
    executor.tool_signature_counts = {}
    executor.tool_quota_exhausted_reason = None
    executor._quota_notice_emitted = False
    executor.tool_service = tool_service or _StubToolService()
    return executor


def test_repeated_tool_call_blocked_after_limit() -> None:
    """同参连续调用超过上限后熔断，但不进入终结态（should_finalize=False）。"""
    executor = _make_executor(repeated_limit=3)
    args = {"query": "名词复数"}

    # 前 3 次放行
    for _ in range(3):
        assert executor._record_tool_call("search_textbook", args) is None
    assert executor.tool_call_count == 3

    # 第 4 次同参被熔断
    blocked = executor._record_tool_call("search_textbook", args)
    assert blocked is not None
    assert blocked["error_code"] == "repeated_tool_call_blocked"
    assert blocked["should_finalize"] is False
    assert blocked["ok"] is False
    # 熔断不消耗配额、不进入终结态
    assert executor.tool_call_count == 3
    assert executor.tool_quota_exhausted_reason is None

    # 换参数后继续放行
    assert executor._record_tool_call("search_textbook", {"query": "时态"}) is None
    assert executor.tool_call_count == 4


def test_max_tool_calls_triggers_finalize() -> None:
    """累计调用达到上限后触发终结态，后续一律拒绝并要求收尾。"""
    executor = _make_executor(max_tool_calls=2, repeated_limit=99)

    assert executor._record_tool_call("list_lessons", {"curriculum_plan_id": 1}) is None
    assert executor._record_tool_call("list_lessons", {"curriculum_plan_id": 2}) is None
    assert executor.tool_call_count == 2

    blocked = executor._record_tool_call("list_lessons", {"curriculum_plan_id": 3})
    assert blocked["error_code"] == "max_tool_calls_reached"
    assert blocked["should_finalize"] is True
    assert executor.tool_quota_exhausted_reason is not None

    # 终结态下任何工具都被拒为 tool_quota_exhausted
    again = executor._record_tool_call("search_textbook", {"query": "x"})
    assert again["error_code"] == "tool_quota_exhausted"
    assert again["should_finalize"] is True


def test_quota_notice_emitted_once() -> None:
    """终结态首轮注入一次性收尾通知，后续轮次不再重复。"""
    executor = _make_executor()
    # 未进入终结态：不注入
    assert executor._build_quota_notice_messages(forced_final=False) == []

    executor._trigger_final_round("已达到本次运行最大工具调用次数")
    first = executor._build_quota_notice_messages(forced_final=True)
    assert len(first) == 1
    assert first[0]["role"] == "system"
    assert "收尾" in first[0]["content"]
    # 再次调用不重复注入
    assert executor._build_quota_notice_messages(forced_final=True) == []


def test_read_before_write_block_does_not_consume_quota() -> None:
    """写前未读同目标时，预检拒绝且不消耗配额计数。"""
    block = {
        "ok": False,
        "error_code": "read_before_write_required",
        "should_finalize": False,
        "message": "写入前必须先 read",
    }
    executor = _make_executor(tool_service=_StubToolService(block=block))

    result = executor._record_tool_call("write_lesson_plan", {"content_json": {}})
    assert result is block
    # 不消耗配额、不计入签名、不终结
    assert executor.tool_call_count == 0
    assert executor.tool_signature_counts == {}
    assert executor.tool_quota_exhausted_reason is None


class _StubLessonWriter:
    """仅提供 get_lesson_plan_by_session 的教案写服务桩，模拟课次是否已有存量教案。"""

    def __init__(self, existing: Any) -> None:
        self._existing = existing

    def get_lesson_plan_by_session(self, **_kwargs: Any) -> Any:
        return self._existing


class _StubUser:
    """最小用户桩，仅提供 id。"""

    id = 1


# 表示「该课次已有存量 ready 教案」的非 None 哨兵，便于默认走「需先读」分支
_EXISTING_LESSON = object()


def _make_tool_service(
    *,
    curriculum_plan_id: int,
    session_no: int,
    existing_lesson: Any = _EXISTING_LESSON,
) -> AgentToolService:
    """绕过 __init__ 构造工具服务，仅注入 read-before-write 校验所需状态。

    existing_lesson 默认非 None（已有存量教案），传 None 模拟首次新建场景。
    """
    service = object.__new__(AgentToolService)
    service.curriculum_plan_id = curriculum_plan_id
    service.default_session_no = session_no
    service.read_lesson_targets = set()
    service.read_outline_targets = set()
    service.lesson_writer = _StubLessonWriter(existing_lesson)
    service.current_user = _StubUser()
    return service


def test_check_write_precondition_lesson_plan() -> None:
    """write_lesson_plan 前置依赖：存量教案未读则拒、已读则放行。"""
    service = _make_tool_service(curriculum_plan_id=10, session_no=2)

    # 未读：拒绝并附自然语言指令
    blocked = service.check_write_precondition("write_lesson_plan", {"content_json": {}})
    assert blocked is not None
    assert blocked["error_code"] == "read_before_write_required"
    assert blocked["should_finalize"] is False
    assert "llm_instruction" in blocked

    # 标记已读同目标后放行
    service.read_lesson_targets.add((10, 2))
    assert service.check_write_precondition("write_lesson_plan", {"content_json": {}}) is None


def test_check_write_precondition_lesson_plan_first_create_passthrough() -> None:
    """首次新建（该课次尚无存量教案）时无基线可读，应直接放行，避免与 read 的 NOT_FOUND 死锁。"""
    service = _make_tool_service(curriculum_plan_id=10, session_no=2, existing_lesson=None)
    assert service.check_write_precondition("write_lesson_plan", {"content_json": {}}) is None


def test_check_write_precondition_outline() -> None:
    """write_outline 前置依赖：未读则拒、已读则放行。"""
    service = _make_tool_service(curriculum_plan_id=10, session_no=2)

    blocked = service.check_write_precondition("write_outline", {"content_json": {}})
    assert blocked is not None
    assert blocked["error_code"] == "read_before_write_required"

    service.read_outline_targets.add(10)
    assert service.check_write_precondition("write_outline", {"content_json": {}}) is None


def test_check_write_precondition_passthrough_for_non_write_tools() -> None:
    """非写工具不触发前置依赖校验。"""
    service = _make_tool_service(curriculum_plan_id=10, session_no=2)
    assert service.check_write_precondition("search_textbook", {"query": "x"}) is None
    assert service.check_write_precondition("read_lesson_plan", {}) is None
