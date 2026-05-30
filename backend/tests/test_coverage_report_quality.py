"""
@Date: 2026-05-30
@Author: xisy
@Discription: 覆盖报告质量评审字段测试
"""

from app.modules.auth.models import SysUser
from app.modules.quality_report.service import CoverageService
from app.modules.p0_models import (
    AssessmentBlueprint,
    ChapterNode,
    CoursewareResult,
    CurriculumPlan,
    FileObject,
    GenerationBatch,
    HomeworkBlueprint,
    HomeworkQuestion,
    HomeworkResult,
    KnowledgeEvidence,
    KnowledgePoint,
    KnowledgeVersion,
    LearnerProfileFile,
    LearnerProfileRecord,
    LearnerProfileVersion,
    LessonPlan,
    PaperResult,
    ParseVersion,
    Project,
    QuestionItem,
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


def _create_point(
    session,
    *,
    knowledge_version_id: int,
    chapter_id: int,
    name: str,
    importance: int,
    difficulty: int,
    sort_order: int,
) -> KnowledgePoint:
    """创建测试知识点。"""
    point = KnowledgePoint(
        knowledge_version_id=knowledge_version_id,
        chapter_node_id=chapter_id,
        point_code=f"kp_quality_{sort_order}",
        point_name=name,
        point_type="knowledge",
        importance_level=importance,
        difficulty_level=difficulty,
        mastery_level_hint="理解",
        tags_json={"items": [name]},
        summary_text=f"{name}的教学摘要",
        sort_order=sort_order,
    )
    session.add(point)
    session.flush()
    return point


def _create_quality_fixture(session, *, with_profile_record: bool = True) -> dict:
    """构造覆盖报告质量评审测试数据。"""
    user = session.query(SysUser).filter(SysUser.username == "teacher_demo").one()
    project = Project(
        owner_user_id=user.id,
        name="覆盖报告质量项目",
        subject_code="math",
        grade_code="grade_3",
    )
    session.add(project)
    session.flush()

    textbook_file = _create_file_object(
        session,
        project_id=project.id,
        user_id=user.id,
        biz_type="textbook",
        filename="quality-textbook.pdf",
    )
    profile_source_file = _create_file_object(
        session,
        project_id=project.id,
        user_id=user.id,
        biz_type="learner_profile",
        filename="quality-profile.docx",
    )
    textbook_version = TextbookVersion(
        project_id=project.id,
        source_file_id=textbook_file.id,
        version_no=1,
        textbook_name="三年级数学",
        subject_code="math",
        grade_code="grade_3",
        file_hash="quality-textbook-hash",
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
        page_count=20,
    )
    session.add(parse_version)
    session.flush()
    knowledge_version = KnowledgeVersion(
        project_id=project.id,
        parse_version_id=parse_version.id,
        version_no=1,
        version_status="ready",
        summary_json={"knowledge_point_count": 7},
    )
    session.add(knowledge_version)
    session.flush()

    learner_profile_file = LearnerProfileFile(
        project_id=project.id,
        source_file_id=profile_source_file.id,
        title="学生学情",
        file_status="uploaded",
        uploaded_by=user.id,
    )
    session.add(learner_profile_file)
    session.flush()
    learner_profile_version = LearnerProfileVersion(
        project_id=project.id,
        profile_file_id=learner_profile_file.id,
        version_no=1,
        grade_code="grade_3",
        subject_scope="math",
        extract_status="success",
        review_status="confirmed",
        version_status="ready",
        summary_text="学生数学基础中等偏上，综合应用需要提升。",
        created_by=user.id,
    )
    session.add(learner_profile_version)
    session.flush()
    if with_profile_record:
        session.add(
            LearnerProfileRecord(
                project_id=project.id,
                profile_version_id=learner_profile_version.id,
                student_key="quality_student_math",
                student_name="王同学",
                is_anonymous=0,
                grade_code="grade_3",
                subject_code="math",
                score_value=82,
                weakness_tags_json={"items": ["综合应用待提升"]},
                ability_tags_json={"items": ["计算能力", "逻辑能力"]},
                time_plan_json={"items": ["计划每周安排2次数学课，重点训练应用题分析能力"]},
                summary_text="当前学生数学基础中等偏上，应用题分析需要加强。",
                sort_order=0,
            )
        )

    chapter = ChapterNode(
        knowledge_version_id=knowledge_version.id,
        parent_id=None,
        node_path="1",
        node_no=1,
        node_level=1,
        node_type="chapter",
        title="一 年、月、日",
        page_start=7,
        page_end=13,
        sort_order=1,
    )
    session.add(chapter)
    session.flush()

    points = {
        "complete": _create_point(
            session,
            knowledge_version_id=knowledge_version.id,
            chapter_id=chapter.id,
            name="完整闭环知识点",
            importance=5,
            difficulty=2,
            sort_order=1,
        ),
        "planning": _create_point(
            session,
            knowledge_version_id=knowledge_version.id,
            chapter_id=chapter.id,
            name="仅规划知识点",
            importance=3,
            difficulty=3,
            sort_order=2,
        ),
        "teaching": _create_point(
            session,
            knowledge_version_id=knowledge_version.id,
            chapter_id=chapter.id,
            name="教学未测知识点",
            importance=3,
            difficulty=4,
            sort_order=3,
        ),
        "assessment": _create_point(
            session,
            knowledge_version_id=knowledge_version.id,
            chapter_id=chapter.id,
            name="测评无教学知识点",
            importance=3,
            difficulty=5,
            sort_order=4,
        ),
        "none": _create_point(
            session,
            knowledge_version_id=knowledge_version.id,
            chapter_id=chapter.id,
            name="完全未覆盖知识点",
            importance=5,
            difficulty=3,
            sort_order=5,
        ),
        "extra_a": _create_point(
            session,
            knowledge_version_id=knowledge_version.id,
            chapter_id=chapter.id,
            name="额外未覆盖知识点A",
            importance=2,
            difficulty=1,
            sort_order=6,
        ),
        "extra_b": _create_point(
            session,
            knowledge_version_id=knowledge_version.id,
            chapter_id=chapter.id,
            name="额外未覆盖知识点B",
            importance=2,
            difficulty=1,
            sort_order=7,
        ),
    }
    for index, point in enumerate(points.values(), start=1):
        session.add(
            KnowledgeEvidence(
                knowledge_point_id=point.id,
                parse_version_id=parse_version.id,
                evidence_type="text",
                page_no=6 + index,
                excerpt_text=f"{point.point_name}的教材证据片段",
                score_value=0.8 + index / 100,
            )
        )

    generation_batch = GenerationBatch(
        project_id=project.id,
        batch_no=1,
        batch_name="质量报告批次",
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
        plan_title="质量报告课程方案",
        target_subject_code="math",
        target_grade_code="grade_3",
        course_count=1,
        session_duration_minutes=90,
        version_status="ready",
        summary_text="覆盖报告课程方案摘要",
        content_json={
            "coverage_knowledge_points": [points["complete"].id, points["planning"].id],
            "lesson_sessions": [
                {
                    "session_no": 1,
                    "knowledge_point_refs": [points["complete"].id, points["planning"].id],
                }
            ],
        },
        created_by=user.id,
    )
    session.add(curriculum_plan)
    session.flush()

    lesson_plan = LessonPlan(
        curriculum_plan_id=curriculum_plan.id,
        generation_batch_id=generation_batch.id,
        class_session_no=1,
        version_no=1,
        lesson_title="质量报告教案",
        version_status="ready",
        summary_text="覆盖报告教案摘要",
        content_json={
            "knowledge_point_refs": [points["complete"].id, points["teaching"].id],
            "session_plans": [
                {
                    "session_no": 1,
                    "knowledge_point_refs": [points["complete"].id, points["teaching"].id],
                }
            ],
        },
        created_by=user.id,
    )
    session.add(lesson_plan)
    session.flush()
    generation_batch.curriculum_plan_id = curriculum_plan.id
    generation_batch.lesson_plan_id = lesson_plan.id

    courseware_result = CoursewareResult(
        generation_batch_id=generation_batch.id,
        lesson_plan_id=lesson_plan.id,
        result_status="success",
        page_count=2,
        structure_json={
            "deck": {
                "slides": [
                    {
                        "slide_no": 1,
                        "slide_type": "knowledge",
                        "title": "完整闭环知识点",
                        "knowledge_point_refs": [points["complete"].id],
                    },
                    {
                        "slide_no": 2,
                        "slide_type": "practice",
                        "title": "教学未测知识点",
                        "knowledge_point_refs": [points["teaching"].id],
                    },
                ]
            }
        },
    )
    session.add(courseware_result)

    assessment_blueprint = AssessmentBlueprint(
        curriculum_plan_id=curriculum_plan.id,
        version_no=1,
        scenario_type="unit_test",
        blueprint_name="质量报告单元测试蓝图",
        version_status="ready",
        content_json={"knowledge_weights": []},
        created_by=user.id,
    )
    session.add(assessment_blueprint)
    session.flush()
    paper_result = PaperResult(
        generation_batch_id=generation_batch.id,
        assessment_blueprint_id=assessment_blueprint.id,
        scene_type="unit_test",
        title="质量报告单元测试",
        result_status="success",
        question_count=2,
        paper_json={"questions": []},
    )
    session.add(paper_result)
    session.flush()
    complete_question = QuestionItem(
        generation_batch_id=generation_batch.id,
        paper_result_id=paper_result.id,
        knowledge_point_id=points["complete"].id,
        question_no=1,
        question_type="single_choice",
        difficulty_level=2,
        score_value=10,
        stem_text="基础题：围绕完整闭环知识点完成练习。",
        answer_text="参考答案",
        analysis_text="解析",
    )
    out_of_range_question = QuestionItem(
        generation_batch_id=generation_batch.id,
        paper_result_id=paper_result.id,
        knowledge_point_id=points["assessment"].id,
        question_no=2,
        question_type="short_answer",
        difficulty_level=5,
        score_value=10,
        stem_text="综合思维挑战：围绕测评无教学知识点完成跨情境应用分析。",
        answer_text="参考答案",
        analysis_text="解析",
    )
    session.add_all([complete_question, out_of_range_question])

    homework_blueprint = HomeworkBlueprint(
        lesson_plan_id=lesson_plan.id,
        generation_batch_id=generation_batch.id,
        version_no=1,
        blueprint_name="质量报告课后作业蓝图",
        version_status="ready",
        content_json={"knowledge_weights": []},
        created_by=user.id,
    )
    session.add(homework_blueprint)
    session.flush()
    homework_result = HomeworkResult(
        generation_batch_id=generation_batch.id,
        lesson_plan_id=lesson_plan.id,
        homework_blueprint_id=homework_blueprint.id,
        title="质量报告课后作业",
        result_status="success",
        question_count=1,
        content_json={"questions": []},
    )
    session.add(homework_result)
    session.flush()
    complete_homework_question = HomeworkQuestion(
        generation_batch_id=generation_batch.id,
        homework_result_id=homework_result.id,
        lesson_plan_id=lesson_plan.id,
        knowledge_point_id=points["complete"].id,
        question_no=1,
        question_type="fill_blank",
        difficulty_level=1,
        score_value=10,
        stem_text="课后巩固：围绕完整闭环知识点完成填空。",
        answer_text="参考答案",
        analysis_text="解析",
    )
    session.add(complete_homework_question)
    session.commit()

    return {
        "generation_batch_id": generation_batch.id,
        "points": {key: point.id for key, point in points.items()},
        "out_of_range_question_id": out_of_range_question.id,
    }


def test_coverage_report_quality_fields_should_be_readable(seeded_session_factory) -> None:
    """覆盖报告应返回比赛展示需要的质量评审字段。"""
    session = seeded_session_factory()
    try:
        data = _create_quality_fixture(session)
        report_json = CoverageService(session).build_coverage_payload(data["generation_batch_id"])["report_json"]

        complete_id = data["points"]["complete"]
        complete_summary = report_json["knowledge_point_summaries"][str(complete_id)]
        assert complete_summary["chapter_title"] == "一 年、月、日"
        assert complete_summary["chapter_page_range"] == "7-13"
        assert complete_summary["difficulty_band"] == "基础掌握题"
        assert complete_summary["evidence"]["excerpt_text"] == "完整闭环知识点的教材证据片段"

        assert len(report_json["uncovered_knowledge_points"]) == len(report_json["uncovered_knowledge_point_ids"])
        assert report_json["uncovered_knowledge_points"][0]["point_name"] == "完全未覆盖知识点"

        matrix = {
            row["knowledge_point_id"]: row
            for row in report_json["knowledge_point_coverage_matrix"]
        }
        assert matrix[data["points"]["complete"]]["closure_status"] == "complete_loop"
        assert matrix[data["points"]["planning"]]["closure_status"] == "planning_only"
        assert matrix[data["points"]["teaching"]]["closure_status"] == "teaching_no_assessment"
        assert matrix[data["points"]["assessment"]]["closure_status"] == "assessment_no_teaching"
        assert matrix[data["points"]["none"]]["closure_status"] == "no_coverage"

        courseware_gap = report_json["artifact_gap_analysis"]["courseware_slide"]
        assert courseware_gap["valid_reference_status"] == "valid"
        assert courseware_gap["coverage_status"] == "weak"
        assert courseware_gap["covered_count"] == 2

        assessment_quality_v2 = report_json["assessment_quality_v2"]
        assert assessment_quality_v2["question_count"] == 3
        assert assessment_quality_v2["difficulty_band_distribution"]["基础掌握题"]["count"] == 2
        assert assessment_quality_v2["difficulty_band_distribution"]["综合提升题"]["count"] == 1
        unit_test_scene = next(
            item for item in assessment_quality_v2["by_scene"] if item["scene_type"] == "unit_test"
        )
        assert unit_test_scene["passed"] is False
        assert unit_test_scene["out_of_range_questions"][0]["difficulty_band"] == "综合提升题"

        difficulty_warning = next(
            warning for warning in report_json["warnings"] if warning["code"] == "QUESTION_DIFFICULTY_OUT_OF_RANGE"
        )
        assert difficulty_warning["question_item_ids"] == [data["out_of_range_question_id"]]
        assert difficulty_warning["question_items"][0]["question_no"] == 2
        assert difficulty_warning["question_items"][0]["stem_excerpt"].startswith("综合思维挑战")
        assert difficulty_warning["scene_label"] == "单元测试"

        uncovered_warning = next(
            warning for warning in report_json["warnings"] if warning["code"] == "UNCOVERED_KNOWLEDGE_POINTS"
        )
        assert uncovered_warning["knowledge_points"][0]["point_name"] == "完全未覆盖知识点"

        learner_alignment = report_json["learner_profile_alignment"]
        assert learner_alignment["status"] == "available"
        assert learner_alignment["weakness_tags"] == ["综合应用待提升"]
        assert "典型应用题" in learner_alignment["assessment_fit_summary"]

        suggestion_by_point = {
            item["knowledge_point_id"]: item
            for item in report_json["action_suggestions"]
        }
        assert suggestion_by_point[data["points"]["none"]]["priority"] == "high"
        assert suggestion_by_point[data["points"]["teaching"]]["target_artifact_type"] == "question_item"
    finally:
        session.close()


def test_coverage_report_should_allow_missing_profile_records(seeded_session_factory) -> None:
    """学情记录缺失时覆盖报告仍应生成。"""
    session = seeded_session_factory()
    try:
        data = _create_quality_fixture(session, with_profile_record=False)
        report_json = CoverageService(session).build_coverage_payload(data["generation_batch_id"])["report_json"]

        assert report_json["learner_profile_alignment"] == {"status": "not_available"}
        assert report_json["knowledge_point_summaries"]
        assert report_json["action_suggestions"]
    finally:
        session.close()
