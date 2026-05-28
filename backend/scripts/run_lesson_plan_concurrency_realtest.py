"""
@Date: 2026-05-27
@Author: xisy
@Discription: 教案生成暖缓存后并发真实测试脚本
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

# 本脚本专测教案生成任务，使用同步任务模式方便一次性观察暖缓存与后续并发结果。
os.environ["TASK_EAGER_MODE"] = "1"

for index, item in enumerate(sys.argv):
    if item == "--concurrency" and index + 1 < len(sys.argv):
        os.environ["LESSON_PLAN_MAX_CONCURRENCY"] = sys.argv[index + 1]
    elif item.startswith("--concurrency="):
        os.environ["LESSON_PLAN_MAX_CONCURRENCY"] = item.split("=", 1)[1]

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.constants import TASK_STATUS_PENDING
from app.core.database import SessionLocal
from app.modules.assessment.presets import DEFAULT_ASSESSMENT_SCENE_TYPE, resolve_assessment_strategy
from app.modules.auth.models import SysUser  # noqa: F401  # 注册 sys_user 表，避免外键元数据缺失
from app.modules.curriculum.repository import CurriculumRepository
from app.modules.curriculum.tasks import _create_lesson_plan_task
from app.modules.lesson_plan import tasks as lesson_plan_tasks
from app.modules.p0_models import CurriculumPlan, GenerationBatch, KnowledgePoint, LessonPlan, TaskRecord, TaskStepRecord
from app.modules.pipeline.repository import PipelineRepository
from app.modules.task_center.repository import TaskCenterRepository

_LLM_EVENT_LOCK = threading.Lock()
_LLM_EVENTS: list[dict[str, Any]] = []


def main() -> None:
    """执行教案并发真实测试。"""
    args = _parse_args()
    if args.concurrency is not None:
        os.environ["LESSON_PLAN_MAX_CONCURRENCY"] = str(args.concurrency)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    session = SessionLocal()
    try:
        base_curriculum = session.get(CurriculumPlan, args.base_curriculum_id)
        if base_curriculum is None:
            raise RuntimeError(f"基础课程大纲不存在：{args.base_curriculum_id}")
        scoped_knowledge_point_ids = _list_scoped_knowledge_point_ids(
            session,
            knowledge_version_id=base_curriculum.knowledge_version_id,
            chapter_node_id=args.scope_chapter_id,
        )
        lesson_sessions = _build_lesson_sessions(
            base_curriculum.content_json,
            args.sessions,
            scoped_knowledge_point_ids=scoped_knowledge_point_ids,
        )
        cloned_curriculum = _create_cloned_curriculum(
            session,
            base_curriculum=base_curriculum,
            lesson_sessions=lesson_sessions,
            scope_chapter_id=args.scope_chapter_id,
            timestamp=timestamp,
        )
        batch, task = _create_batch_and_task(
            session,
            curriculum=cloned_curriculum,
            timestamp=timestamp,
        )
        print(
            json.dumps(
                {
                    "stage": "created",
                    "base_curriculum_id": base_curriculum.id,
                    "curriculum_plan_id": cloned_curriculum.id,
                    "generation_batch_id": batch.id,
                    "task_record_id": task.id,
                    "sessions": args.sessions,
                    "requested_concurrency": args.concurrency,
                    "scope_chapter_id": args.scope_chapter_id,
                    "scoped_knowledge_point_count": len(scoped_knowledge_point_ids or []),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        task_id = task.id
        batch_id = batch.id
        curriculum_id = cloned_curriculum.id
        operator_user_id = cloned_curriculum.created_by
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    _patch_lesson_plan_call_logging()
    result = lesson_plan_tasks.run_generate_lesson_plan_task(
        {
            "task_record_id": task_id,
            "generation_batch_id": batch_id,
            "curriculum_plan_id": curriculum_id,
            "operator_user_id": operator_user_id,
        }
    )
    summary = _collect_summary(
        task_id=task_id,
        batch_id=batch_id,
        curriculum_id=curriculum_id,
        result=result,
        llm_events=_LLM_EVENTS,
        timestamp=timestamp,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


def _parse_args() -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(description="教案生成暖缓存后并发真实测试")
    parser.add_argument("--base-curriculum-id", type=int, default=3, help="用于克隆课次结构的课程大纲 ID")
    parser.add_argument("--sessions", type=int, default=7, help="克隆后的总课次数，需大于 1")
    parser.add_argument("--concurrency", type=int, default=6, help="LESSON_PLAN_MAX_CONCURRENCY")
    parser.add_argument("--scope-chapter-id", type=int, default=None, help="可选章节节点 ID，用于缩小知识范围")
    args = parser.parse_args()
    if args.sessions < 2:
        raise ValueError("--sessions 必须大于 1，才能观察暖缓存后的并发阶段")
    if args.concurrency is not None and args.concurrency < 1:
        raise ValueError("--concurrency 必须大于 0")
    return args


def _patch_lesson_plan_call_logging() -> None:
    """给单课次 LLM 调用加测试日志，不改变任务生成逻辑。"""
    original = lesson_plan_tasks._generate_single_lesson_plan

    def wrapped_generate_single_lesson_plan(**kwargs):  # noqa: ANN001
        lesson_session = kwargs.get("lesson_session") or {}
        class_session_no = int(lesson_session.get("session_no") or 0)
        started_at = time.perf_counter()
        start_event = {
            "event": "llm_start",
            "class_session_no": class_session_no,
            "at": started_at,
            "thread": threading.current_thread().name,
        }
        with _LLM_EVENT_LOCK:
            _LLM_EVENTS.append(start_event)
        print(json.dumps(start_event, ensure_ascii=False), flush=True)
        try:
            return original(**kwargs)
        finally:
            finished_at = time.perf_counter()
            done_event = {
                "event": "llm_done",
                "class_session_no": class_session_no,
                "at": finished_at,
                "elapsed_seconds": round(finished_at - started_at, 3),
                "thread": threading.current_thread().name,
            }
            with _LLM_EVENT_LOCK:
                _LLM_EVENTS.append(done_event)
            print(json.dumps(done_event, ensure_ascii=False), flush=True)

    lesson_plan_tasks._generate_single_lesson_plan = wrapped_generate_single_lesson_plan


def _list_scoped_knowledge_point_ids(
    session,
    *,
    knowledge_version_id: int,
    chapter_node_id: int | None,
) -> list[int] | None:
    """查询指定章节下的知识点 ID。"""
    if chapter_node_id is None:
        return None
    rows = (
        session.query(KnowledgePoint.id)
        .filter(
            KnowledgePoint.knowledge_version_id == knowledge_version_id,
            KnowledgePoint.chapter_node_id == chapter_node_id,
        )
        .order_by(KnowledgePoint.sort_order.asc(), KnowledgePoint.id.asc())
        .all()
    )
    ids = [int(row[0]) for row in rows]
    if not ids:
        raise RuntimeError(f"章节 {chapter_node_id} 下没有知识点，无法进行 scoped 并发测试")
    return ids


def _build_lesson_sessions(
    content_json: dict[str, Any],
    session_count: int,
    *,
    scoped_knowledge_point_ids: list[int] | None,
) -> list[dict[str, Any]]:
    """基于已有课程大纲课次克隆出指定数量的测试课次。"""
    base_sessions = content_json.get("lesson_sessions") if isinstance(content_json, dict) else None
    if not isinstance(base_sessions, list) or not base_sessions:
        raise RuntimeError("基础课程大纲缺少 lesson_sessions")

    lesson_sessions: list[dict[str, Any]] = []
    for index in range(session_count):
        source = deepcopy(base_sessions[index % len(base_sessions)])
        source["session_no"] = index + 1
        source["title"] = f"并发测试第{index + 1}讲：{source.get('title') or '英语综合训练'}"
        source["duration_minutes"] = int(source.get("duration_minutes") or 90)
        source["objectives"] = _append_marker(source.get("objectives"), index + 1, "目标")
        source["activities"] = _append_marker(source.get("activities"), index + 1, "活动")
        source["homework"] = _append_marker(source.get("homework"), index + 1, "作业")
        if scoped_knowledge_point_ids is not None:
            source["knowledge_point_refs"] = scoped_knowledge_point_ids
        lesson_sessions.append(source)
    return lesson_sessions


def _append_marker(values: Any, session_no: int, label: str) -> list[str]:
    """给克隆课次追加测试标记，避免多课次内容完全相同。"""
    normalized = [str(item) for item in values] if isinstance(values, list) else []
    normalized.append(f"并发测试第{session_no}讲{label}：围绕本讲重点完成一次口头复述。")
    return normalized


def _create_cloned_curriculum(
    session,
    *,
    base_curriculum: CurriculumPlan,
    lesson_sessions: list[dict[str, Any]],
    scope_chapter_id: int | None,
    timestamp: str,
) -> CurriculumPlan:
    """创建只用于并发测试的课程大纲副本。"""
    repository = CurriculumRepository(session)
    content_json = deepcopy(base_curriculum.content_json or {})
    content_json["lesson_sessions"] = lesson_sessions
    cloned = CurriculumPlan(
        project_id=base_curriculum.project_id,
        knowledge_version_id=base_curriculum.knowledge_version_id,
        learner_profile_version_id=base_curriculum.learner_profile_version_id,
        parent_plan_id=base_curriculum.id,
        version_no=repository.get_next_curriculum_version_no(base_curriculum.project_id),
        plan_title=f"教案并发真实测试课程大纲 {timestamp}",
        target_subject_code=base_curriculum.target_subject_code,
        target_grade_code=base_curriculum.target_grade_code,
        chapter_range_json=(
            {"chapter_node_ids": [scope_chapter_id]}
            if scope_chapter_id is not None
            else base_curriculum.chapter_range_json
        ),
        course_count=len(lesson_sessions),
        session_duration_minutes=base_curriculum.session_duration_minutes,
        generation_mode="manual_test",
        version_status="ready",
        summary_text=f"基于课程大纲 {base_curriculum.id} 克隆，用于验证教案生成第 1 课暖缓存后并发生成。",
        content_json=content_json,
        export_file_id=None,
        created_by=base_curriculum.created_by,
    )
    session.add(cloned)
    session.flush()
    return cloned


def _create_batch_and_task(
    session,
    *,
    curriculum: CurriculumPlan,
    timestamp: str,
) -> tuple[GenerationBatch, TaskRecord]:
    """创建测试批次和教案生成任务。"""
    repository = PipelineRepository(session)
    task_repository = TaskCenterRepository(session)
    batch = GenerationBatch(
        project_id=curriculum.project_id,
        batch_no=repository.get_next_batch_no(curriculum.project_id),
        batch_name=f"教案并发真实测试 {timestamp}",
        trigger_mode="manual_test",
        batch_status=TASK_STATUS_PENDING,
        knowledge_version_id=curriculum.knowledge_version_id,
        learner_profile_version_id=curriculum.learner_profile_version_id,
        chapter_range_json=curriculum.chapter_range_json,
        course_count=curriculum.course_count,
        session_duration_minutes=curriculum.session_duration_minutes,
        assessment_strategy_json=resolve_assessment_strategy(DEFAULT_ASSESSMENT_SCENE_TYPE),
        pipeline_options_json={"enabled_steps": ["lesson_plan"], "realtest": "lesson_plan_concurrency"},
        curriculum_plan_id=curriculum.id,
        created_by=curriculum.created_by,
    )
    session.add(batch)
    session.flush()
    task = _create_lesson_plan_task(
        task_repository=task_repository,
        generation_batch=batch,
        curriculum_plan=curriculum,
        owner_user_id=curriculum.created_by,
        request_id=f"lesson-plan-concurrency-realtest-{timestamp}",
    )
    session.commit()
    return batch, task


def _collect_summary(
    *,
    task_id: int,
    batch_id: int,
    curriculum_id: int,
    result: dict[str, Any],
    llm_events: list[dict[str, Any]],
    timestamp: str,
) -> dict[str, Any]:
    """汇总任务步骤、生成教案和报告路径。"""
    session = SessionLocal()
    try:
        task = session.get(TaskRecord, task_id)
        steps = (
            session.query(TaskStepRecord)
            .filter(TaskStepRecord.task_record_id == task_id)
            .order_by(TaskStepRecord.step_order.asc())
            .all()
        )
        lessons = (
            session.query(LessonPlan)
            .filter(LessonPlan.generation_batch_id == batch_id)
            .order_by(LessonPlan.class_session_no.asc())
            .all()
        )
        step_payload = [
            {
                "step_code": step.step_code,
                "step_status": step.step_status,
                "progress_percent": step.progress_percent,
                "detail_json": step.detail_json,
            }
            for step in steps
        ]
        summary = {
            "stage": "finished",
            "task": None
            if task is None
            else {
                "id": task.id,
                "task_status": task.task_status,
                "current_stage": task.current_stage,
                "progress_percent": task.progress_percent,
                "result_json": task.result_json,
                "last_error_code": task.last_error_code,
                "last_error_message": task.last_error_message,
            },
            "result": result,
            "llm_events": list(llm_events),
            "steps": step_payload,
            "lesson_count": len(lessons),
            "lessons": [
                {
                    "id": lesson.id,
                    "class_session_no": lesson.class_session_no,
                    "lesson_title": lesson.lesson_title,
                    "summary_text": lesson.summary_text,
                }
                for lesson in lessons
            ],
        }
        report_path = _write_report(
            timestamp=timestamp,
            curriculum_id=curriculum_id,
            batch_id=batch_id,
            task_id=task_id,
            summary=summary,
        )
        summary["report_path"] = str(report_path)
        return summary
    finally:
        session.close()


def _write_report(
    *,
    timestamp: str,
    curriculum_id: int,
    batch_id: int,
    task_id: int,
    summary: dict[str, Any],
) -> Path:
    """写入 Markdown 测试报告。"""
    report_path = PROJECT_ROOT / "docs" / f"lesson_plan_concurrency_realtest_{timestamp}.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    invoke_step = next(
        (step for step in summary["steps"] if step["step_code"] == "invoke_llm_lesson_plan"),
        None,
    )
    detail_json = invoke_step.get("detail_json") if isinstance(invoke_step, dict) else {}
    llm_usage = detail_json.get("llm_usage") if isinstance(detail_json, dict) else None
    lines = [
        "<!-- @Date: 2026-05-27 @Author: xisy @Discription: 教案生成并发真实测试报告 -->",
        "",
        "# 教案生成并发真实测试报告",
        "",
        "本报告由 `backend/scripts/run_lesson_plan_concurrency_realtest.py` 自动生成，用于验证教案生成任务在第 1 课暖缓存后对后续课次进行并发生成。",
        "",
        "## 测试对象",
        "",
        f"- 课程大纲 ID：`{curriculum_id}`",
        f"- 生成批次 ID：`{batch_id}`",
        f"- 教案任务 ID：`{task_id}`",
        f"- 任务状态：`{summary['task']['task_status'] if summary.get('task') else 'unknown'}`",
        f"- 生成教案数：`{summary['lesson_count']}`",
        "",
        "## 并发观测",
        "",
        f"- total_sessions：`{detail_json.get('total_sessions') if isinstance(detail_json, dict) else None}`",
        f"- processed_sessions：`{detail_json.get('processed_sessions') if isinstance(detail_json, dict) else None}`",
        f"- parallel_limit：`{detail_json.get('parallel_limit') if isinstance(detail_json, dict) else None}`",
        f"- cache_warmup_completed：`{detail_json.get('cache_warmup_completed') if isinstance(detail_json, dict) else None}`",
        f"- llm_usage：`{json.dumps(llm_usage, ensure_ascii=False)}`",
        "",
        "## LLM 调用事件",
        "",
    ]
    for event in summary.get("llm_events") or []:
        lines.append(
            f"- {event.get('event')} 第 {event.get('class_session_no')} 讲，"
            f"thread=`{event.get('thread')}`，at=`{event.get('at')}`，"
            f"elapsed=`{event.get('elapsed_seconds')}`"
        )
    lines.extend(
        [
            "",
            "## 生成教案",
            "",
        ]
    )
    for lesson in summary["lessons"]:
        lines.extend(
            [
                f"- 第 {lesson['class_session_no']} 讲：{lesson['lesson_title']}",
                f"  摘要：{lesson['summary_text'] or ''}",
            ]
        )
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


if __name__ == "__main__":
    main()
