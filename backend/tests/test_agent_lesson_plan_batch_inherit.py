"""
@Date: 2026-05-31
@Author: xisy
@Discription: 智能助手写教案新版本时继承并转交 generation_batch 槽位的回归测试

覆盖核心修复：agent 改写教案不再把 batch 置空脱离批次，而是把 (batch, session)
唯一槽位从旧版本转交给最新 ready 版本，保证下游作业/课件可按批次定位最新内容，
且 uk_lesson_plan_batch_session 唯一约束不被破坏。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.modules.agent.writers import LessonPlanWriteService
from app.modules.auth.models import SysUser
from app.modules.p0_models import (
    ChapterNode,
    CurriculumPlan,
    FileObject,
    GenerationBatch,
    KnowledgePoint,
    KnowledgeVersion,
    LearnerProfileFile,
    LearnerProfileVersion,
    LessonPlan,
    ParseVersion,
    Project,
    TextbookVersion,
)


def _create_file_object(session, *, project_id: int, user_id: int, biz_type: str, filename: str) -> FileObject:
    """创建测试文件对象。"""
    file_object = FileObject(
        project_id=project_id,
        biz_type=biz_type,
        bucket_name="test-bucket",
        object_key=f"tests/{biz_type}/{filename}",
        original_filename=filename,
        file_ext=filename.rsplit(".", 1)[-1],
        mime_type="application/octet-stream",
        file_size=10,
        content_hash=f"{biz_type}-{filename}",
        uploaded_by=user_id,
    )
    session.add(file_object)
    session.flush()
    return file_object


def _seed_baseline(session) -> dict[str, Any]:
    """播种一个挂在批次上的原始 ready 教案及其完整依赖链。"""
    user = session.query(SysUser).filter(SysUser.username == "teacher_demo").one()
    project = Project(
        owner_user_id=user.id,
        name="批次继承项目",
        subject_code="math",
        grade_code="grade_3",
    )
    session.add(project)
    session.flush()

    textbook_file = _create_file_object(
        session, project_id=project.id, user_id=user.id, biz_type="textbook", filename="t.pdf"
    )
    profile_file_obj = _create_file_object(
        session, project_id=project.id, user_id=user.id, biz_type="learner_profile", filename="p.docx"
    )
    textbook_version = TextbookVersion(
        project_id=project.id,
        source_file_id=textbook_file.id,
        version_no=1,
        textbook_name="三年级数学",
        subject_code="math",
        grade_code="grade_3",
        file_hash="t-hash",
        parse_status="success",
    )
    session.add(textbook_version)
    session.flush()
    parse_version = ParseVersion(
        project_id=project.id,
        textbook_version_id=textbook_version.id,
        version_no=1,
        strategy_code="test",
        parse_status="success",
        review_status="confirmed",
        page_count=10,
    )
    session.add(parse_version)
    session.flush()
    knowledge_version = KnowledgeVersion(
        project_id=project.id,
        parse_version_id=parse_version.id,
        version_no=1,
        version_status="ready",
        summary_json={"knowledge_point_count": 1},
    )
    session.add(knowledge_version)
    session.flush()

    profile_file = LearnerProfileFile(
        project_id=project.id,
        source_file_id=profile_file_obj.id,
        title="学情",
        file_status="uploaded",
        uploaded_by=user.id,
    )
    session.add(profile_file)
    session.flush()
    learner_profile_version = LearnerProfileVersion(
        project_id=project.id,
        profile_file_id=profile_file.id,
        version_no=1,
        grade_code="grade_3",
        subject_scope="math",
        extract_status="success",
        review_status="confirmed",
        version_status="ready",
        summary_text="学情摘要",
        created_by=user.id,
    )
    session.add(learner_profile_version)
    session.flush()

    chapter = ChapterNode(
        knowledge_version_id=knowledge_version.id,
        parent_id=None,
        node_path="1",
        node_no=1,
        node_level=1,
        node_type="chapter",
        title="第一章",
        sort_order=1,
    )
    session.add(chapter)
    session.flush()
    point = KnowledgePoint(
        knowledge_version_id=knowledge_version.id,
        chapter_node_id=chapter.id,
        point_code="kp_1",
        point_name="乘法口诀",
        point_type="knowledge",
        importance_level=5,
        difficulty_level=2,
        mastery_level_hint="理解",
        tags_json={"items": ["乘法口诀"]},
        summary_text="乘法口诀摘要",
        sort_order=1,
    )
    session.add(point)
    session.flush()

    generation_batch = GenerationBatch(
        project_id=project.id,
        batch_no=1,
        batch_name="批次1",
        batch_status="success",
        knowledge_version_id=knowledge_version.id,
        learner_profile_version_id=learner_profile_version.id,
        course_count=1,
        session_duration_minutes=90,
    )
    session.add(generation_batch)
    session.flush()
    curriculum_plan = CurriculumPlan(
        project_id=project.id,
        knowledge_version_id=knowledge_version.id,
        learner_profile_version_id=learner_profile_version.id,
        version_no=1,
        plan_title="课程方案",
        target_subject_code="math",
        target_grade_code="grade_3",
        course_count=1,
        session_duration_minutes=90,
        version_status="ready",
        summary_text="方案摘要",
        content_json={"lesson_sessions": [{"session_no": 1, "knowledge_point_refs": [point.id]}]},
        created_by=user.id,
    )
    session.add(curriculum_plan)
    session.flush()
    lesson_plan = LessonPlan(
        curriculum_plan_id=curriculum_plan.id,
        generation_batch_id=generation_batch.id,
        class_session_no=1,
        version_no=1,
        lesson_title="原始教案",
        style_code="standard",
        version_status="ready",
        summary_text="原始摘要",
        content_json={"knowledge_point_refs": [point.id]},
        created_by=user.id,
    )
    session.add(lesson_plan)
    session.flush()
    generation_batch.curriculum_plan_id = curriculum_plan.id
    generation_batch.lesson_plan_id = lesson_plan.id
    session.commit()

    return {
        "user": user,
        "curriculum_plan": curriculum_plan,
        "generation_batch": generation_batch,
        "lesson_plan": lesson_plan,
        "point": point,
    }


def _valid_lesson_content(point_id: int, *, title: str, summary: str) -> dict[str, Any]:
    """构造一份满足 LessonPlanGenerationResult schema 的教案内容。"""
    step = {
        "step_no": 1,
        "stage_name": "导入",
        "duration_minutes": 10,
        "teacher_actions": ["复习旧知"],
        "student_activities": ["回答提问"],
        "knowledge_point_refs": [point_id],
    }
    return {
        "lesson_title": title,
        "summary_text": summary,
        "course_overview": {"audience": "三年级", "duration": "1课时", "focus": "乘法口诀"},
        "material_list": ["口诀表"],
        "core_knowledge": ["乘法口诀"],
        "teaching_flow": [step],
        "session_plans": [
            {
                "session_no": 1,
                "title": "第1讲 乘法口诀",
                "objectives": ["熟记口诀"],
                "teaching_focus": ["口诀记忆"],
                "teaching_steps": [step],
                "homework": ["背诵口诀"],
                "knowledge_point_refs": [point_id],
            }
        ],
        "after_class_plan": {"review": "复习口诀", "homework": "练习题", "parent_communication": "家长监督背诵"},
        "learner_adjustments": ["分层练习"],
        "knowledge_point_refs": [point_id],
    }


def test_agent_write_inherits_and_transfers_batch_slot(seeded_session_factory) -> None:
    """agent 写新版本应继承原批次，并把旧版本的 batch 槽位让出（置空）。"""
    session = seeded_session_factory()
    try:
        seed = _seed_baseline(session)
        curriculum_plan_id = seed["curriculum_plan"].id
        batch_id = seed["generation_batch"].id
        original_id = seed["lesson_plan"].id
        user_id = seed["user"].id
        point_id = seed["point"].id

        service = LessonPlanWriteService(session)
        new_version = service.write_lesson_plan_version(
            curriculum_plan_id=curriculum_plan_id,
            class_session_no=1,
            content_json=_valid_lesson_content(point_id, title="改后教案v2", summary="改后摘要v2"),
            owner_user_id=user_id,
        )
        session.commit()

        # 新版本继承原批次，下游作业/课件才能按批次定位
        assert new_version.generation_batch_id == batch_id
        assert new_version.version_status == "ready"

        # 旧版本被归档且让出 batch 槽位（置空），保证 (batch, session) 唯一
        original = session.get(LessonPlan, original_id)
        session.refresh(original)
        assert original.version_status == "archived"
        assert original.generation_batch_id is None

        # 任一时刻 (batch, session) 仅一条持有者
        holders = session.scalars(
            select(LessonPlan).where(
                LessonPlan.generation_batch_id == batch_id,
                LessonPlan.class_session_no == 1,
            )
        ).all()
        assert [holder.id for holder in holders] == [new_version.id]
    finally:
        session.close()


def test_agent_repeated_edit_keeps_batch_on_latest(seeded_session_factory) -> None:
    """连续两次改写：批次始终随最新 ready 版本流转，唯一约束不冲突。"""
    session = seeded_session_factory()
    try:
        seed = _seed_baseline(session)
        curriculum_plan_id = seed["curriculum_plan"].id
        batch_id = seed["generation_batch"].id
        user_id = seed["user"].id
        point_id = seed["point"].id

        service = LessonPlanWriteService(session)
        v2 = service.write_lesson_plan_version(
            curriculum_plan_id=curriculum_plan_id,
            class_session_no=1,
            content_json=_valid_lesson_content(point_id, title="v2", summary="s2"),
            owner_user_id=user_id,
        )
        session.commit()
        v2_id = v2.id

        # 第二次改写：未触发唯一键冲突即说明「先让位再继承」次序正确
        v3 = service.write_lesson_plan_version(
            curriculum_plan_id=curriculum_plan_id,
            class_session_no=1,
            content_json=_valid_lesson_content(point_id, title="v3", summary="s3"),
            owner_user_id=user_id,
        )
        session.commit()

        assert v3.generation_batch_id == batch_id
        v2_reloaded = session.get(LessonPlan, v2_id)
        session.refresh(v2_reloaded)
        assert v2_reloaded.version_status == "archived"
        assert v2_reloaded.generation_batch_id is None

        holders = session.scalars(
            select(LessonPlan).where(
                LessonPlan.generation_batch_id == batch_id,
                LessonPlan.class_session_no == 1,
            )
        ).all()
        assert [holder.id for holder in holders] == [v3.id]
    finally:
        session.close()
