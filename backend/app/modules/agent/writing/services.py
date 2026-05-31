"""
@Date: 2026-05-31
@Author: xisy
@Discription: 智能助手资源写入服务：教案/大纲按「新建版本」落库
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import AppException, BusinessErrorCode
from app.modules.curriculum.repository import CurriculumRepository
from app.modules.curriculum.schemas import CurriculumGenerationResult
from app.modules.lesson_plan.repository import LessonPlanRepository
from app.modules.lesson_plan.schemas import LessonPlanGenerationResult
from app.modules.p0_models import CurriculumPlan, LessonPlan


class LessonPlanWriteService:
    """教案写入服务：按课次新建教案版本，归档同课次旧 ready 版本。"""

    def __init__(self, session: Session, repository: LessonPlanRepository | None = None) -> None:
        self.session = session
        self.repository = repository or LessonPlanRepository(session)

    def get_lesson_plan_by_session(
        self,
        *,
        curriculum_plan_id: int,
        class_session_no: int,
        owner_user_id: int,
    ) -> LessonPlan | None:
        """读取指定课次最新的 ready 教案（按版本号倒序）。"""
        if self.repository.get_curriculum_plan_for_owner(curriculum_plan_id, owner_user_id) is None:
            raise AppException(BusinessErrorCode.CURRICULUM_PLAN_NOT_FOUND, "课程大纲不存在或无权访问")
        statement = (
            select(LessonPlan)
            .where(
                LessonPlan.curriculum_plan_id == curriculum_plan_id,
                LessonPlan.class_session_no == class_session_no,
                LessonPlan.version_status == "ready",
            )
            .order_by(LessonPlan.version_no.desc(), LessonPlan.id.desc())
            .limit(1)
        )
        return self.session.scalar(statement)

    def write_lesson_plan_version(
        self,
        *,
        curriculum_plan_id: int,
        class_session_no: int,
        content_json: dict[str, Any],
        owner_user_id: int,
    ) -> LessonPlan:
        """以新版本写入教案；content_json 需满足教案结构化 schema。"""
        curriculum_plan = self.repository.get_curriculum_plan_for_owner(curriculum_plan_id, owner_user_id)
        if curriculum_plan is None:
            raise AppException(BusinessErrorCode.CURRICULUM_PLAN_NOT_FOUND, "课程大纲不存在或无权访问")

        try:
            validated = LessonPlanGenerationResult.model_validate(content_json)
        except ValidationError as exc:
            raise AppException(
                BusinessErrorCode.LLM_RESULT_INVALID,
                "教案内容结构不符合规范，请按 schema 修正后重试",
                {"errors": exc.errors()},
            ) from exc

        normalized_content = validated.model_dump()
        previous = self.get_lesson_plan_by_session(
            curriculum_plan_id=curriculum_plan_id,
            class_session_no=class_session_no,
            owner_user_id=owner_user_id,
        )
        style_code = previous.style_code if previous is not None else "standard"
        # Agent 改写只更新文本版本，继承原批次槽位让下游作业/课件继续定位最新教案。
        inherited_batch_id = previous.generation_batch_id if previous is not None else None

        stale_versions = self.session.scalars(
            select(LessonPlan).where(
                LessonPlan.curriculum_plan_id == curriculum_plan_id,
                LessonPlan.class_session_no == class_session_no,
                LessonPlan.version_status == "ready",
            )
        ).all()
        for stale in stale_versions:
            stale.version_status = "archived"
            stale.generation_batch_id = None
            self.session.add(stale)
        self.session.flush()

        lesson_plan = LessonPlan(
            curriculum_plan_id=curriculum_plan_id,
            generation_batch_id=inherited_batch_id,
            class_session_no=class_session_no,
            version_no=self.repository.get_next_lesson_plan_version_no(curriculum_plan_id),
            lesson_title=normalized_content.get("lesson_title") or (previous.lesson_title if previous else "教案"),
            style_code=style_code,
            version_status="ready",
            summary_text=normalized_content.get("summary_text"),
            content_json=normalized_content,
            created_by=owner_user_id,
        )
        self.repository.create_lesson_plan(lesson_plan)
        return lesson_plan


class CurriculumWriteService:
    """大纲写入服务：按项目新建大纲版本（parent_plan_id 指向当前版本）。"""

    def __init__(self, session: Session, repository: CurriculumRepository | None = None) -> None:
        self.session = session
        self.repository = repository or CurriculumRepository(session)

    def write_curriculum_version(
        self,
        *,
        curriculum_plan_id: int,
        content_json: dict[str, Any],
        owner_user_id: int,
    ) -> CurriculumPlan:
        """以新版本写入大纲；content_json 需满足大纲结构化 schema。"""
        current = self.repository.get_curriculum_plan_for_owner(curriculum_plan_id, owner_user_id)
        if current is None:
            raise AppException(BusinessErrorCode.CURRICULUM_PLAN_NOT_FOUND, "课程大纲不存在或无权访问")

        try:
            validated = CurriculumGenerationResult.model_validate(content_json)
        except ValidationError as exc:
            raise AppException(
                BusinessErrorCode.LLM_RESULT_INVALID,
                "大纲内容结构不符合规范，请按 schema 修正后重试",
                {"errors": exc.errors()},
            ) from exc

        normalized_content = validated.model_dump()
        new_plan = CurriculumPlan(
            project_id=current.project_id,
            knowledge_version_id=current.knowledge_version_id,
            learner_profile_version_id=current.learner_profile_version_id,
            parent_plan_id=current.id,
            version_no=self.repository.get_next_curriculum_version_no(current.project_id),
            plan_title=normalized_content.get("plan_title") or current.plan_title,
            target_subject_code=current.target_subject_code,
            target_grade_code=current.target_grade_code,
            chapter_range_json=current.chapter_range_json,
            course_count=len(normalized_content.get("lesson_sessions") or []) or current.course_count,
            session_duration_minutes=current.session_duration_minutes,
            generation_mode="agent",
            version_status="ready",
            summary_text=normalized_content.get("summary_text"),
            content_json=normalized_content,
            created_by=owner_user_id,
        )
        self.repository.create_curriculum_plan(new_plan)
        return new_plan
