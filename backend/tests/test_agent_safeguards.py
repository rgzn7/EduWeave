"""
@Date: 2026-05-31
@Author: xisy
@Discription: 智能助手工具守护单元测试：同参重复熔断、配额终结态、read-before-write 硬约束、结构化拒绝
"""

from __future__ import annotations

from typing import Any

from app.core.config import get_settings
from app.modules.agent.runtime.guard import AgentToolCallGuard
from app.modules.agent.tools.context import AgentToolContext
from app.modules.agent.tools.lesson import LessonAgentTool
from app.modules.agent.tools.registry import AgentToolRegistry


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
) -> AgentToolCallGuard:
    """构造工具调用守护器，仅注入守护逻辑所需的最小状态。"""
    settings = get_settings().model_copy(
        update={
            "agent_max_tool_calls": max_tool_calls,
            "agent_repeated_tool_call_limit": repeated_limit,
        }
    )
    return AgentToolCallGuard(settings, tool_service or _StubToolService())


def test_repeated_tool_call_blocked_after_limit() -> None:
    """同参连续调用超过上限后熔断，但不进入终结态（should_finalize=False）。"""
    guard = _make_executor(repeated_limit=3)
    args = {"query": "名词复数"}

    # 前 3 次放行
    for _ in range(3):
        assert guard.record_tool_call("search_textbook", args) is None
    assert guard.tool_call_count == 3

    # 第 4 次同参被熔断
    blocked = guard.record_tool_call("search_textbook", args)
    assert blocked is not None
    assert blocked["error_code"] == "repeated_tool_call_blocked"
    assert blocked["should_finalize"] is False
    assert blocked["ok"] is False
    # 熔断不消耗配额、不进入终结态
    assert guard.tool_call_count == 3
    assert guard.tool_quota_exhausted_reason is None

    # 换参数后继续放行
    assert guard.record_tool_call("search_textbook", {"query": "时态"}) is None
    assert guard.tool_call_count == 4


def test_max_tool_calls_triggers_finalize() -> None:
    """累计调用达到上限后触发终结态，后续一律拒绝并要求收尾。"""
    guard = _make_executor(max_tool_calls=2, repeated_limit=99)

    assert guard.record_tool_call("list_lessons", {"curriculum_plan_id": 1}) is None
    assert guard.record_tool_call("list_lessons", {"curriculum_plan_id": 2}) is None
    assert guard.tool_call_count == 2

    blocked = guard.record_tool_call("list_lessons", {"curriculum_plan_id": 3})
    assert blocked["error_code"] == "max_tool_calls_reached"
    assert blocked["should_finalize"] is True
    assert guard.tool_quota_exhausted_reason is not None

    # 终结态下任何工具都被拒为 tool_quota_exhausted
    again = guard.record_tool_call("search_textbook", {"query": "x"})
    assert again["error_code"] == "tool_quota_exhausted"
    assert again["should_finalize"] is True


def test_quota_notice_emitted_once() -> None:
    """终结态首轮注入一次性收尾通知，后续轮次不再重复。"""
    guard = _make_executor()
    # 未进入终结态：不注入
    assert guard.build_quota_notice_messages(forced_final=False) == []

    guard.trigger_final_round("已达到本次运行最大工具调用次数")
    first = guard.build_quota_notice_messages(forced_final=True)
    assert len(first) == 1
    assert first[0]["role"] == "system"
    assert "收尾" in first[0]["content"]
    # 再次调用不重复注入
    assert guard.build_quota_notice_messages(forced_final=True) == []


def test_read_before_write_block_does_not_consume_quota() -> None:
    """写前未读同目标时，预检拒绝且不消耗配额计数。"""
    block = {
        "ok": False,
        "error_code": "read_before_write_required",
        "should_finalize": False,
        "message": "写入前必须先 read",
    }
    guard = _make_executor(tool_service=_StubToolService(block=block))

    result = guard.record_tool_call("write_lesson_plan", {"content_json": {}})
    assert result is block
    # 不消耗配额、不计入签名、不终结
    assert guard.tool_call_count == 0
    assert guard.tool_signature_counts == {}
    assert guard.tool_quota_exhausted_reason is None


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
) -> AgentToolRegistry:
    """绕过 __init__ 构造工具服务，仅注入 read-before-write 校验所需状态。

    existing_lesson 默认非 None（已有存量教案），传 None 模拟首次新建场景。
    """
    context = object.__new__(AgentToolContext)
    context.curriculum_plan_id = curriculum_plan_id
    context.default_session_no = session_no
    context.read_lesson_targets = set()
    context.read_outline_targets = set()
    context.lesson_writer = _StubLessonWriter(existing_lesson)
    context.current_user = _StubUser()
    return AgentToolRegistry(tool_context=context)


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
    service.context.read_lesson_targets.add((10, 2))
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

    service.context.read_outline_targets.add(10)
    assert service.check_write_precondition("write_outline", {"content_json": {}}) is None


def test_check_write_precondition_passthrough_for_non_write_tools() -> None:
    """非写工具不触发前置依赖校验。"""
    service = _make_tool_service(curriculum_plan_id=10, session_no=2)
    assert service.check_write_precondition("search_textbook", {"query": "x"}) is None
    assert service.check_write_precondition("read_lesson_plan", {}) is None


class _StubLessonPlan:
    """最小教案记录桩：summary_text/lesson_title 存于独立列，content_json 不含它们。"""

    def __init__(self) -> None:
        self.id = 99
        self.class_session_no = 2
        self.version_no = 5
        self.lesson_title = "见面问候教案"
        self.summary_text = "本课围绕问候与自我介绍展开，兼顾分层表达。"
        # 模拟生成期落库形态：content_json 顶层无 summary_text，概述带额外键
        self.content_json = {
            "course_overview": {"audience": "A", "duration": "D", "focus": "F", "teaching_style": "情境"},
            "material_list": ["卡片"],
        }


class _ReadStubLessonWriter:
    """读工具用教案写服务桩，按课次返回固定记录。"""

    def __init__(self, lesson_plan: Any) -> None:
        self._lesson_plan = lesson_plan

    def get_lesson_plan_by_session(self, **_kwargs: Any) -> Any:
        return self._lesson_plan


def test_read_lesson_plan_backfills_summary_text() -> None:
    """读工具须把独立列 summary_text/lesson_title 回填进 content，
    使读出内容与写入 schema 同构，避免 Agent 整体回写丢失教案概述。"""
    import json

    context = object.__new__(AgentToolContext)
    context.curriculum_plan_id = 10
    context.default_session_no = 2
    context.read_lesson_targets = set()
    context.current_user = _StubUser()
    context.lesson_writer = _ReadStubLessonWriter(_StubLessonPlan())
    service = LessonAgentTool(context)

    result = service.read_lesson_plan({"curriculum_plan_id": 10, "class_session_no": 2})
    content = json.loads(result["content"])

    # 关键回归点：summary_text 必须出现在回灌给模型的 content 中
    assert content["summary_text"] == "本课围绕问候与自我介绍展开，兼顾分层表达。"
    assert content["lesson_title"] == "见面问候教案"
    # 概述额外键随原 content_json 一并保留
    assert content["course_overview"]["teaching_style"] == "情境"
    # 已读目标被记录，供后续 write 前置校验放行
    assert (10, 2) in context.read_lesson_targets
