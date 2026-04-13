"""
@Date: 2026-04-13
@Author: xisy
@Discription: 学情模块占位任务
"""

import re
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.constants import (
    REVIEW_STATUS_PENDING,
    TASK_STATUS_FAILURE,
    TASK_STATUS_PROCESSING,
    TASK_STATUS_SUCCESS,
    VERSION_STATUS_READY,
)
from app.core.database import SessionLocal
from app.modules.learner_profile.repository import LearnerProfileRepository
from app.modules.p0_models import LearnerProfileRecord, LearnerProfileVersion
from app.modules.task_center.repository import TaskCenterRepository
from app.shared.utils.datetime_util import DateTimeUtil


def run_placeholder_extract_task(payload: dict) -> dict[str, int]:
    """执行学情占位抽取任务。"""
    session = _create_session(payload)
    repository = LearnerProfileRepository(session)
    task_repository = TaskCenterRepository(session)
    task = task_repository.get_task_by_id(payload["task_record_id"])
    step = task_repository.get_task_step(payload["task_record_id"], "extract_profile")
    now = DateTimeUtil.now_utc()

    try:
        if task is None or step is None:
            raise RuntimeError("学情抽取任务不存在")
        task.task_status = TASK_STATUS_PROCESSING
        task.current_stage = "extract_profile"
        task.progress_percent = 10
        task.started_at = task.started_at or now
        step.step_status = TASK_STATUS_PROCESSING
        step.progress_percent = 10
        step.started_at = step.started_at or now
        task_repository.save(task)
        task_repository.save(step)
        session.commit()

        profile_file = repository.get_profile_file_by_id(payload["profile_file_id"])
        project = repository.get_project(payload["project_id"])
        if profile_file is None or project is None:
            raise RuntimeError("学情文件或项目不存在")

        source_file = repository.get_file_object(profile_file.source_file_id)
        if source_file is None:
            raise RuntimeError("学情源文件不存在")

        version_no = repository.get_next_version_no(profile_file.id)
        subject_code = _pick_subject_code(payload.get("subject_scope"), project.subject_code)
        summary_text = payload.get("title") or source_file.original_filename
        profile_version = LearnerProfileVersion(
            project_id=project.id,
            profile_file_id=profile_file.id,
            parent_version_id=None,
            version_no=version_no,
            textbook_version_hint_id=payload.get("textbook_version_hint_id"),
            grade_code=payload.get("grade_code") or project.grade_code,
            subject_scope=payload.get("subject_scope") or project.subject_code,
            extract_status="success",
            review_status=REVIEW_STATUS_PENDING,
            version_status=VERSION_STATUS_READY,
            summary_text=summary_text,
            raw_result_json={
                "mode": "placeholder",
                "summary_text": summary_text,
                "subject_code": subject_code,
            },
            source_snapshot_json={
                "title": payload.get("title"),
                "subject_scope": payload.get("subject_scope"),
                "grade_code": payload.get("grade_code"),
                "filename": source_file.original_filename,
            },
            created_by=payload.get("operator_user_id"),
        )
        repository.create_profile_version(profile_version)
        student_key = _build_student_key(source_file.original_filename)
        profile_record = LearnerProfileRecord(
            project_id=project.id,
            profile_version_id=profile_version.id,
            student_key=student_key,
            student_name=Path(source_file.original_filename).stem,
            is_anonymous=0,
            region_name=None,
            grade_code=payload.get("grade_code") or project.grade_code,
            subject_code=subject_code,
            textbook_version_hint_id=payload.get("textbook_version_hint_id"),
            score_value=None,
            advantage_tags_json={"items": []},
            weakness_tags_json={"items": []},
            ability_tags_json={"items": []},
            habit_tags_json={"items": []},
            behavior_traits_json={"items": []},
            time_plan_json={"items": []},
            summary_text=summary_text,
            evidence_json={"filename": source_file.original_filename},
            sort_order=0,
        )
        repository.create_profile_record(profile_record)

        profile_file.file_status = "success"
        if project.current_learner_profile_version_id is None or payload.get("set_as_current"):
            project.current_learner_profile_version_id = profile_version.id
        project.last_activity_at = DateTimeUtil.now_utc()
        repository.save(profile_file)
        repository.save(project)

        finished_at = DateTimeUtil.now_utc()
        task.task_status = TASK_STATUS_SUCCESS
        task.current_stage = "extract_profile"
        task.progress_percent = 100
        task.result_json = {"profile_version_id": profile_version.id, "record_count": 1}
        task.finished_at = finished_at
        step.step_status = TASK_STATUS_SUCCESS
        step.progress_percent = 100
        step.detail_json = {"profile_version_id": profile_version.id}
        step.finished_at = finished_at
        task_repository.save(task)
        task_repository.save(step)
        session.commit()
        return {"profile_version_id": profile_version.id, "record_count": 1}
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        task = task_repository.get_task_by_id(payload["task_record_id"])
        step = task_repository.get_task_step(payload["task_record_id"], "extract_profile")
        if task is not None:
            task.task_status = TASK_STATUS_FAILURE
            task.last_error_code = "PLACEHOLDER_PROFILE_EXTRACT_FAILED"
            task.last_error_message = str(exc)
            task.finished_at = DateTimeUtil.now_utc()
            task_repository.save(task)
        if step is not None:
            step.step_status = TASK_STATUS_FAILURE
            step.detail_json = {"error": str(exc)}
            step.finished_at = DateTimeUtil.now_utc()
            task_repository.save(step)
        session.commit()
        raise
    finally:
        session.close()


def _pick_subject_code(subject_scope: str | None, default_subject_code: str) -> str:
    """从学科范围中挑选单个学科编码。"""
    if not subject_scope:
        return default_subject_code
    normalized = subject_scope.replace("，", ",").split(",")[0].strip()
    return normalized or default_subject_code


def _build_student_key(filename: str) -> str:
    """根据文件名生成稳定学生标识。"""
    stem = Path(filename).stem
    normalized = re.sub(r"\W+", "_", stem, flags=re.UNICODE).strip("_")
    return f"{normalized or 'student'}_1"


def _create_session(payload: dict) -> Session:
    """为任务创建数据库会话。"""
    database_url = payload.get("database_url")
    if not database_url:
        return SessionLocal()
    engine = create_engine(database_url, pool_pre_ping=True, future=True)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, class_=Session)
    return factory()
