"""
@Date: 2026-05-19
@Author: xisy
@Discription: 生成编排与课程大纲、教案、测评、课件接口测试
"""

import json
from io import BytesIO

import pytest
from pydantic import ValidationError
from pypdf import PdfWriter

from app.core.config import get_settings
from app.core.exceptions import AppException, BusinessErrorCode
from app.core.security import hash_password
from app.modules.assessment.schemas import AssessmentGenerationResult
from app.modules.auth.models import SysUser
from app.modules.courseware.schemas import SlideDeckGenerationResult, SlideDraft
from app.modules.courseware.service import CoursewareService
from app.modules.curriculum.schemas import CurriculumGenerationResult
from app.modules.knowledge.schemas import (
    KnowledgeChapterBoundaryItem,
    KnowledgeChapterBoundaryResult,
    KnowledgeChapterPointExtractionResult,
    KnowledgeExtractionEvidenceDraft,
    KnowledgeExtractionPointDraft,
)
from app.modules.lesson_plan.schemas import LessonPlanGenerationResult
from app.modules.p0_models import ChapterNode, CoursewareResult, KnowledgePoint, LessonPlan, QuestionItem
from app.shared.llm import OpenAICompatibleEmbeddingService, OpenAICompatibleLlmService
from app.shared.ppt import RaccoonPptJobState, RaccoonPptService
from app.shared.vector import MilvusVectorService


def build_auth_headers(client) -> dict[str, str]:
    """构造认证请求头。"""
    login_response = client.post(
        "/api/v1/auth/login",
        json={"username": "teacher_demo", "password": "Teacher@123"},
    )
    access_token = login_response.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {access_token}"}


def build_other_auth_headers(client, seeded_session_factory) -> dict[str, str]:
    """构造另一个教师的认证请求头。"""
    session = seeded_session_factory()
    try:
        session.add(
            SysUser(
                username="teacher_other",
                display_name="其他教师",
                password_hash=hash_password("Teacher@123"),
                role_code="teacher",
                status="active",
            )
        )
        session.commit()
    finally:
        session.close()

    login_response = client.post(
        "/api/v1/auth/login",
        json={"username": "teacher_other", "password": "Teacher@123"},
    )
    access_token = login_response.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {access_token}"}


def build_pdf_bytes(page_count: int = 1) -> bytes:
    """生成空白 PDF 内容。"""
    writer = PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=200, height=200)
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def create_project(client, headers, *, name: str = "生成项目") -> int:
    """创建测试项目。"""
    response = client.post(
        "/api/v1/projects",
        headers=headers,
        json={"name": name, "subject_code": "math", "grade_code": "grade_3"},
    )
    return response.json()["data"]["id"]


def upload_and_parse_textbook(client, headers, project_id: int) -> int:
    """上传教材并创建解析版本。"""
    upload_response = client.post(
        f"/api/v1/projects/{project_id}/textbooks",
        headers=headers,
        files={"file": ("textbook.pdf", build_pdf_bytes(page_count=2), "application/pdf")},
    )
    textbook_version_id = upload_response.json()["data"]["id"]
    parse_response = client.post(
        f"/api/v1/textbook-versions/{textbook_version_id}/parse-tasks",
        headers=headers,
        json={"strategy_code": "mineru_vlm_default"},
    )
    return parse_response.json()["data"]["result_json"]["parse_version_id"]


def create_knowledge_version(client, headers, project_id: int) -> int:
    """创建可用知识版本。"""
    parse_version_id = upload_and_parse_textbook(client, headers, project_id)
    client.post(f"/api/v1/parse-versions/{parse_version_id}/confirm", headers=headers)
    response = client.post(
        f"/api/v1/parse-versions/{parse_version_id}/knowledge-tasks",
        headers=headers,
        json={"force_regenerate": False},
    )
    return response.json()["data"]["result_json"]["knowledge_version_id"]


def create_learner_profile_version(client, headers, project_id: int) -> int:
    """创建可用学情版本。"""
    response = client.post(
        f"/api/v1/projects/{project_id}/learner-profiles",
        headers=headers,
        files={
            "file": (
                "student_profile.docx",
                b"fake-docx-content",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
        data={"title": "学生学情", "subject_scope": "math"},
    )
    return response.json()["data"]["latest_version"]["id"]


def add_extra_chapter_with_point(seeded_session_factory, knowledge_version_id: int) -> tuple[int, int]:
    """向知识版本追加一个用于范围测试的章节和知识点。"""
    session = seeded_session_factory()
    try:
        chapter = ChapterNode(
            knowledge_version_id=knowledge_version_id,
            parent_id=None,
            node_path="99",
            node_no=99,
            node_level=1,
            node_type="chapter",
            title="范围章节",
            summary_text="用于验证章节范围收敛。",
            page_start=99,
            page_end=100,
            sort_order=99,
        )
        session.add(chapter)
        session.flush()
        point = KnowledgePoint(
            knowledge_version_id=knowledge_version_id,
            chapter_node_id=chapter.id,
            point_code="kp_scope_only",
            point_name="范围内知识点",
            point_type="knowledge",
            importance_level=4,
            difficulty_level=2,
            mastery_level_hint="understand",
            tags_json={"tags": ["范围"]},
            summary_text="只应在选中范围内进入生成提示词。",
            sort_order=99,
        )
        session.add(point)
        session.commit()
        return chapter.id, point.id
    finally:
        session.close()


def add_many_extra_knowledge_points(seeded_session_factory, knowledge_version_id: int, *, count: int = 35) -> list[int]:
    """向既有章节追加多个知识点，用于验证课件不再按前 30 个截断。"""
    session = seeded_session_factory()
    try:
        chapter = (
            session.query(ChapterNode)
            .filter(ChapterNode.knowledge_version_id == knowledge_version_id)
            .order_by(ChapterNode.id.asc())
            .first()
        )
        point_ids: list[int] = []
        for index in range(1, count + 1):
            point = KnowledgePoint(
                knowledge_version_id=knowledge_version_id,
                chapter_node_id=chapter.id,
                point_code=f"kp_extra_{index}",
                point_name=f"后置知识点{index}",
                point_type="knowledge",
                importance_level=3,
                difficulty_level=2,
                mastery_level_hint="understand",
                tags_json={"tags": ["后置"]},
                summary_text=f"用于验证课件知识点选择的第 {index} 个后置知识点。",
                sort_order=100 + index,
            )
            session.add(point)
            session.flush()
            point_ids.append(point.id)
        session.commit()
        return point_ids
    finally:
        session.close()


@pytest.fixture()
def generation_test_stubs(monkeypatch: pytest.MonkeyPatch):
    """替换知识抽取、课程生成和向量写入依赖。"""
    vector_store: dict[str, list] = {}

    def fake_generate_structured_output(self, *, messages, response_model, temperature=0.2):  # noqa: ANN001
        _ = (self, temperature)
        if response_model is KnowledgeChapterBoundaryResult:
            return KnowledgeChapterBoundaryResult(
                items=[
                    KnowledgeChapterBoundaryItem(
                        title="第2页标题",
                        start_line=6,
                        line_text="# 第2页标题",
                        confidence=0.96,
                    )
                ]
            )

        if response_model is KnowledgeChapterPointExtractionResult:
            return KnowledgeChapterPointExtractionResult(
                summary_json={
                    "teaching_objectives": ["掌握乘法口诀", "理解乘法应用"],
                    "key_points": ["乘法口诀"],
                    "difficult_points": ["应用题分析"],
                },
                knowledge_points=[
                    KnowledgeExtractionPointDraft(
                        point_code="kp_multiplication_table",
                        point_name="乘法口诀",
                        point_type="knowledge",
                        importance_level=5,
                        difficulty_level=3,
                        mastery_level_hint="understand",
                        tags_json={"tags": ["重点", "基础"]},
                        summary_text="要求熟练背诵并灵活应用乘法口诀。",
                        sort_order=0,
                        evidences=[
                            KnowledgeExtractionEvidenceDraft(
                                page_no=2,
                                block_no=2,
                                evidence_type="parse_block",
                                excerpt_text="textbook.pdf 第2页解析内容",
                                score_value=0.95,
                            )
                        ],
                    )
                ],
            )

        user_payload = json.loads(messages[1].content)
        if response_model is CurriculumGenerationResult:
            course_count = int(user_payload["generation_batch"]["course_count"])
            point_id = int(user_payload["knowledge_version"]["knowledge_points"][0]["id"])
            return CurriculumGenerationResult(
                plan_title="三年级数学乘法提升课程",
                summary_text="围绕乘法口诀和应用题进行阶段提升。",
                course_overview={"target": "提升乘法理解与应用能力"},
                stage_goals=["熟练背诵口诀", "能够解决基础应用题"],
                lesson_sessions=[
                    {
                        "session_no": session_no,
                        "title": f"第{session_no}讲 乘法口诀训练",
                        "duration_minutes": 90,
                        "objectives": ["掌握乘法口诀"],
                        "key_points": ["乘法口诀"],
                        "activities": ["口算热身", "例题讲解"],
                        "homework": ["完成口诀练习"],
                        "knowledge_point_refs": [point_id],
                    }
                    for session_no in range(1, course_count + 1)
                ],
                key_points=["乘法口诀"],
                difficult_points=["应用题分析"],
                learner_adjustments=["增加口算练习频次"],
                coverage_knowledge_points=[point_id],
            )

        if response_model is AssessmentGenerationResult:
            point_id = int(user_payload["knowledge_points"][0]["id"])
            strategy = user_payload["assessment_strategy"]
            question_count = int(strategy["question_count"])
            question_types = list(strategy["question_types"])
            difficulty_min, difficulty_max = strategy["difficulty_range"]
            difficulty_span = difficulty_max - difficulty_min + 1
            questions = []
            question_type_distribution: dict[str, int] = {}
            difficulty_distribution: dict[str, int] = {}
            for question_no in range(1, question_count + 1):
                question_type = question_types[(question_no - 1) % len(question_types)]
                difficulty_level = difficulty_min + ((question_no - 1) % difficulty_span)
                question_type_distribution[question_type] = question_type_distribution.get(question_type, 0) + 1
                difficulty_key = str(difficulty_level)
                difficulty_distribution[difficulty_key] = difficulty_distribution.get(difficulty_key, 0) + 1
                questions.append(
                    {
                        "question_no": question_no,
                        "knowledge_point_id": point_id,
                        "question_type": question_type,
                        "difficulty_level": difficulty_level,
                        "score_value": 10,
                        "stem_text": f"第{question_no}题：围绕乘法口诀完成练习。",
                        "options_json": {"A": "2", "B": "4", "C": "6", "D": "8"} if question_type == "single_choice" else None,
                        "answer_text": "参考答案",
                        "analysis_text": "考查乘法口诀的理解与应用。",
                        "source_trace_json": {"knowledge_point_ids": [point_id]},
                    }
                )
            return AssessmentGenerationResult(
                blueprint_name="三年级数学乘法单元测试蓝图",
                paper_title="三年级数学乘法单元测试",
                strategy_summary={"scene_type": strategy["scene_type"], "question_count": question_count},
                knowledge_weights=[
                    {
                        "knowledge_point_id": point_id,
                        "weight_percent": 100,
                        "suggested_question_count": question_count,
                        "question_types": question_types,
                        "difficulty_range": strategy["difficulty_range"],
                    }
                ],
                question_type_distribution=question_type_distribution,
                difficulty_distribution=difficulty_distribution,
                questions=questions,
            )

        if response_model is SlideDeckGenerationResult:
            point_id = int(user_payload["知识点"][0]["id"])
            return SlideDeckGenerationResult(
                deck_title="三年级数学乘法提升课件",
                slides=[
                    SlideDraft(slide_no=1, slide_type="cover", title="乘法口诀提升", bullet_points=[]),
                    SlideDraft(
                        slide_no=2,
                        slide_type="knowledge",
                        title="乘法口诀",
                        bullet_points=["熟记乘法口诀", "理解口诀规律"],
                        knowledge_point_refs=[point_id],
                    ),
                    SlideDraft(slide_no=3, slide_type="summary", title="本课小结", bullet_points=["回顾乘法口诀"]),
                ],
            )

        target_session = user_payload.get("target_lesson_session") or {"session_no": 1, "title": "第1讲 乘法口诀训练"}
        target_refs = target_session.get("knowledge_point_refs") if isinstance(target_session, dict) else None
        point_id = int(target_refs[0]) if target_refs else int(user_payload["knowledge_points"][0]["id"])
        session_no = int(target_session["session_no"])
        session_title = target_session.get("title") or f"第{session_no}讲 乘法口诀训练"
        return LessonPlanGenerationResult(
            lesson_title=f"{session_title}教案",
            summary_text=f"围绕{session_title}组织导入、讲解、练习与课后巩固。",
            course_overview={"lesson_type": "提升课", "duration_minutes": 90},
            material_list=["教材解析片段", "口算练习纸"],
            core_knowledge=["乘法口诀", "应用题分析"],
            teaching_flow=[
                {
                    "step_no": 1,
                    "stage_name": "导入",
                    "duration_minutes": 10,
                    "teacher_actions": ["用口算热身引入乘法口诀"],
                    "student_activities": ["完成快速口算"],
                    "knowledge_point_refs": [point_id],
                },
                {
                    "step_no": 2,
                    "stage_name": "讲解与练习",
                    "duration_minutes": 60,
                    "teacher_actions": ["讲解口诀规律并组织例题练习"],
                    "student_activities": ["完成例题并复述解题过程"],
                    "knowledge_point_refs": [point_id],
                },
            ],
            session_plans=[
                {
                    "session_no": session_no,
                    "title": session_title,
                    "objectives": ["掌握乘法口诀"],
                    "teaching_focus": ["口诀记忆", "基础应用"],
                    "teaching_steps": [
                        {
                            "step_no": 1,
                            "stage_name": "讲解",
                            "duration_minutes": 30,
                            "teacher_actions": ["拆解口诀规律"],
                            "student_activities": ["跟读并完成练习"],
                            "knowledge_point_refs": [point_id],
                        }
                    ],
                    "homework": ["完成口诀练习"],
                    "knowledge_point_refs": [point_id],
                }
            ],
            after_class_plan={"homework": ["口诀复习"], "review_focus": "应用题审题"},
            learner_adjustments=["增加口算练习频次"],
            knowledge_point_refs=[point_id],
        )

    def fake_embed_texts(self, texts: list[str]):  # noqa: ANN001
        dimension = get_settings().milvus_embedding_dim
        return [[float(index + 1)] * dimension for index, _ in enumerate(texts)]

    def fake_upsert_vectors(self, collection_name: str, records):  # noqa: ANN001
        vector_store[collection_name] = list(records)
        return {"upsert_count": len(records)}

    def fake_create_job_and_short_poll(self, *, prompt: str, role: str, scene: str, audience: str):  # noqa: ANN001
        _ = (self, prompt, role, scene, audience)
        return RaccoonPptJobState(
            job_id="ppt-job-1",
            status="succeeded",
            download_url="https://raccoon.test.example.com/courseware.pptx",
            raw_payload={"data": {"job_id": "ppt-job-1", "status": "succeeded"}},
        )

    def fake_download_pptx(self, download_url: str):  # noqa: ANN001
        _ = (self, download_url)
        return b"fake-pptx-content"

    monkeypatch.setattr(OpenAICompatibleLlmService, "generate_structured_output", fake_generate_structured_output)
    monkeypatch.setattr(OpenAICompatibleEmbeddingService, "embed_texts", fake_embed_texts)
    monkeypatch.setattr(MilvusVectorService, "upsert_vectors", fake_upsert_vectors)
    monkeypatch.setattr(RaccoonPptService, "create_job_and_short_poll", fake_create_job_and_short_poll)
    monkeypatch.setattr(RaccoonPptService, "download_pptx", fake_download_pptx)
    yield vector_store


def test_generation_batch_should_create_curriculum_lesson_plans_and_coverage(client, generation_test_stubs) -> None:
    """创建生成批次后应自动生成课程大纲、多课次教案和覆盖率报告。"""
    _ = generation_test_stubs
    headers = build_auth_headers(client)
    project_id = create_project(client, headers)
    knowledge_version_id = create_knowledge_version(client, headers, project_id)
    learner_profile_version_id = create_learner_profile_version(client, headers, project_id)

    response = client.post(
        "/api/v1/generation-batches",
        headers=headers,
        json={
            "project_id": project_id,
            "knowledge_version_id": knowledge_version_id,
            "learner_profile_version_id": learner_profile_version_id,
            "batch_name": "第一轮生成",
            "chapter_range_json": {"chapter_node_ids": []},
            "course_count": 2,
            "session_duration_minutes": 90,
        },
    )

    assert response.status_code == 201
    batch_payload = response.json()["data"]
    assert batch_payload["batch_status"] == "success"
    assert batch_payload["curriculum_plan_id"] is not None
    assert batch_payload["lesson_plan_id"] is not None
    assert batch_payload["lesson_plan_ids"][0] == batch_payload["lesson_plan_id"]
    assert len(batch_payload["lesson_plan_ids"]) == 2
    assert batch_payload["pipeline_options_json"]["enabled_steps"] == ["curriculum", "lesson_plan", "coverage"]
    assert batch_payload["assessment_strategy_json"]["scene_type"] == "unit_test"
    assert batch_payload["tasks"][0]["task_type"] == "curriculum_generate"
    assert batch_payload["tasks"][0]["task_status"] == "success"
    assert batch_payload["tasks"][0]["result_json"]["curriculum_plan_id"] == batch_payload["curriculum_plan_id"]
    assert batch_payload["tasks"][1]["task_type"] == "lesson_plan_generate"
    assert batch_payload["tasks"][1]["task_status"] == "success"
    assert batch_payload["tasks"][1]["result_json"]["lesson_plan_ids"] == batch_payload["lesson_plan_ids"]
    assert batch_payload["tasks"][1]["result_json"]["lesson_plan_count"] == 2
    assert batch_payload["tasks"][1]["result_json"]["coverage_task_id"] == batch_payload["tasks"][2]["id"]
    assert batch_payload["tasks"][2]["task_type"] == "coverage_analyze"
    assert batch_payload["tasks"][2]["task_status"] == "success"
    assert batch_payload["tasks"][2]["result_json"]["coverage_report_id"] is not None
    assert batch_payload["tasks"][2]["result_json"]["coverage_rate"] == 100.0

    task_detail_response = client.get(f"/api/v1/tasks/{batch_payload['tasks'][0]['id']}", headers=headers)
    assert task_detail_response.status_code == 200
    assert [step["step_code"] for step in task_detail_response.json()["data"]["steps"]] == [
        "prepare_generation_baseline",
        "invoke_llm_curriculum",
        "persist_curriculum_plan",
        "finalize_generation_batch",
    ]

    project_detail_response = client.get(f"/api/v1/projects/{project_id}", headers=headers)
    assert project_detail_response.json()["data"]["latest_generation_batch_id"] == batch_payload["id"]

    plan_detail_response = client.get(f"/api/v1/curriculum-plans/{batch_payload['curriculum_plan_id']}", headers=headers)
    assert plan_detail_response.status_code == 200
    plan_payload = plan_detail_response.json()["data"]
    assert plan_payload["plan_title"] == "三年级数学乘法提升课程"
    assert len(plan_payload["content_json"]["lesson_sessions"]) == 2

    list_response = client.get(
        f"/api/v1/curriculum-plans?project_id={project_id}&knowledge_version_id={knowledge_version_id}",
        headers=headers,
    )
    assert list_response.status_code == 200
    assert list_response.json()["data"]["pagination"]["total_count"] == 1

    batch_detail_response = client.get(f"/api/v1/generation-batches/{batch_payload['id']}", headers=headers)
    assert batch_detail_response.status_code == 200
    assert batch_detail_response.json()["data"]["curriculum_plan_id"] == batch_payload["curriculum_plan_id"]
    assert batch_detail_response.json()["data"]["lesson_plan_id"] == batch_payload["lesson_plan_id"]
    assert batch_detail_response.json()["data"]["lesson_plan_ids"] == batch_payload["lesson_plan_ids"]
    assert [task["task_type"] for task in batch_detail_response.json()["data"]["tasks"]] == [
        "curriculum_generate",
        "lesson_plan_generate",
        "coverage_analyze",
    ]

    lesson_detail_response = client.get(f"/api/v1/lesson-plans/{batch_payload['lesson_plan_id']}", headers=headers)
    assert lesson_detail_response.status_code == 200
    lesson_payload = lesson_detail_response.json()["data"]
    assert lesson_payload["generation_batch_id"] == batch_payload["id"]
    assert lesson_payload["class_session_no"] == 1
    assert lesson_payload["lesson_title"] == "第1讲 乘法口诀训练教案"
    assert lesson_payload["content_json"]["teaching_flow"][0]["stage_name"] == "导入"
    assert lesson_payload["content_json"]["session_plans"][0]["title"] == "第1讲 乘法口诀训练"

    lesson_list_response = client.get(
        f"/api/v1/lesson-plans?curriculum_plan_id={batch_payload['curriculum_plan_id']}",
        headers=headers,
    )
    assert lesson_list_response.status_code == 200
    lesson_items = lesson_list_response.json()["data"]["items"]
    assert lesson_list_response.json()["data"]["pagination"]["total_count"] == 2
    assert [item["class_session_no"] for item in lesson_items] == [1, 2]

    missing_lesson_response = client.get("/api/v1/lesson-plans/999999", headers=headers)
    assert missing_lesson_response.status_code == 404
    assert missing_lesson_response.json()["errors"][0]["code"] == "LESSON_PLAN_NOT_FOUND"

    blueprint_list_response = client.get(
        f"/api/v1/assessment-blueprints?curriculum_plan_id={batch_payload['curriculum_plan_id']}",
        headers=headers,
    )
    assert blueprint_list_response.json()["data"]["pagination"]["total_count"] == 0

    paper_list_response = client.get(
        f"/api/v1/paper-results?generation_batch_id={batch_payload['id']}&scene_type=unit_test",
        headers=headers,
    )
    assert paper_list_response.status_code == 200
    assert paper_list_response.json()["data"]["pagination"]["total_count"] == 0

    courseware_list_response = client.get(
        f"/api/v1/courseware-results?generation_batch_id={batch_payload['id']}",
        headers=headers,
    )
    assert courseware_list_response.status_code == 200
    assert courseware_list_response.json()["data"]["pagination"]["total_count"] == 0

    coverage_list_response = client.get(
        f"/api/v1/coverage-reports?generation_batch_id={batch_payload['id']}",
        headers=headers,
    )
    assert coverage_list_response.status_code == 200
    coverage_payload = coverage_list_response.json()["data"]["items"][0]
    assert coverage_payload["coverage_rate"] == 100.0
    assert coverage_payload["warning_count"] == 0
    assert coverage_payload["report_json"]["total_knowledge_point_count"] == 1
    assert coverage_payload["report_json"]["covered_knowledge_point_ids"]
    artifact_coverage = coverage_payload["report_json"]["artifact_coverage"]
    assert set(artifact_coverage) == {"curriculum_plan", "lesson_plan", "question_item", "courseware_slide"}
    assert artifact_coverage["curriculum_plan"]["covered_knowledge_point_ids"]
    assert artifact_coverage["lesson_plan"]["item_count"] == 2
    assert artifact_coverage["question_item"]["item_count"] == 0
    assert artifact_coverage["courseware_slide"]["item_count"] == 0
    assert coverage_payload["report_json"]["assessment_quality"]["question_count"] == 0

    coverage_detail_response = client.get(f"/api/v1/coverage-reports/{coverage_payload['id']}", headers=headers)
    assert coverage_detail_response.status_code == 200
    assert coverage_detail_response.json()["data"]["report_json"]["important_knowledge_point_coverage"]["coverage_rate"] == 100.0

    assessment_task_response = client.post(
        f"/api/v1/curriculum-plans/{batch_payload['curriculum_plan_id']}/assessment-tasks",
        headers=headers,
        json={},
    )
    assert assessment_task_response.status_code == 201
    assessment_task_payload = assessment_task_response.json()["data"]
    assert assessment_task_payload["task_type"] == "assessment_generate"
    assert assessment_task_payload["task_status"] == "success"
    assert assessment_task_payload["result_json"]["question_count"] == 10

    duplicate_assessment_response = client.post(
        f"/api/v1/curriculum-plans/{batch_payload['curriculum_plan_id']}/assessment-tasks",
        headers=headers,
        json={},
    )
    assert duplicate_assessment_response.status_code == 409
    assert duplicate_assessment_response.json()["errors"][0]["code"] == "TASK_CONFLICT"

    refreshed_batch_response = client.get(f"/api/v1/generation-batches/{batch_payload['id']}", headers=headers)
    refreshed_batch_payload = refreshed_batch_response.json()["data"]
    assert refreshed_batch_payload["batch_status"] == "success"

    blueprint_detail_response = client.get(
        f"/api/v1/assessment-blueprints/{assessment_task_payload['result_json']['assessment_blueprint_id']}",
        headers=headers,
    )
    assert blueprint_detail_response.status_code == 200
    assert blueprint_detail_response.json()["data"]["scenario_type"] == "unit_test"

    paper_id = assessment_task_payload["result_json"]["paper_result_id"]
    paper_detail_response = client.get(f"/api/v1/paper-results/{paper_id}", headers=headers)
    assert paper_detail_response.status_code == 200
    assert len(paper_detail_response.json()["data"]["questions"]) == 10

    coverage_after_assessment_response = client.get(
        f"/api/v1/coverage-reports?generation_batch_id={batch_payload['id']}",
        headers=headers,
    )
    coverage_after_assessment = coverage_after_assessment_response.json()["data"]["items"][0]
    assessment_quality = coverage_after_assessment["report_json"]["assessment_quality"]
    assert assessment_quality["question_count"] == 10
    assert assessment_quality["question_type_distribution"] == {
        "single_choice": 4,
        "fill_blank": 3,
        "short_answer": 3,
    }
    assert assessment_quality["difficulty_distribution"] == {"1": 0, "2": 4, "3": 3, "4": 3, "5": 0}
    assert assessment_quality["strategy_checks"][0]["passed"] is True
    assert coverage_after_assessment["report_json"]["artifact_coverage"]["question_item"]["item_count"] == 10

    courseware_task_response = client.post(
        f"/api/v1/lesson-plans/{batch_payload['lesson_plan_ids'][0]}/courseware-tasks",
        headers=headers,
    )
    assert courseware_task_response.status_code == 201
    courseware_task_payload = courseware_task_response.json()["data"]
    assert courseware_task_payload["task_type"] == "courseware_generate"
    assert courseware_task_payload["task_status"] == "success"
    courseware_result_id = courseware_task_payload["result_json"]["courseware_result_id"]

    courseware_detail_response = client.get(f"/api/v1/courseware-results/{courseware_result_id}", headers=headers)
    assert courseware_detail_response.status_code == 200
    courseware_payload = courseware_detail_response.json()["data"]
    assert courseware_payload["result_status"] == "success"
    assert courseware_payload["lesson_plan_id"] == batch_payload["lesson_plan_ids"][0]
    assert courseware_payload["preview_json"]["raccoon_status"] == "succeeded"

    duplicate_courseware_response = client.post(
        f"/api/v1/lesson-plans/{batch_payload['lesson_plan_ids'][0]}/courseware-tasks",
        headers=headers,
    )
    assert duplicate_courseware_response.status_code == 409
    assert duplicate_courseware_response.json()["errors"][0]["code"] == "TASK_CONFLICT"

    file_url_response = client.get(f"/api/v1/files/{courseware_payload['export_file_id']}/download-url", headers=headers)
    assert file_url_response.status_code == 200
    assert file_url_response.json()["data"]["signed_url"].startswith("https://obs.test.example.com/")

    structure = courseware_payload["structure_json"]
    assert structure["generator"] == "llm_slides+raccoon_layout"
    assert structure["pptx_stale"] is False
    assert structure["edit_log"] == []
    assert len(structure["deck"]["slides"]) == 3
    assert structure["deck"]["slides"][0]["slide_type"] == "cover"
    assert courseware_payload["page_count"] == 3

    coverage_after_courseware_response = client.get(
        f"/api/v1/coverage-reports?generation_batch_id={batch_payload['id']}",
        headers=headers,
    )
    courseware_coverage = coverage_after_courseware_response.json()["data"]["items"][0]["report_json"]["artifact_coverage"][
        "courseware_slide"
    ]
    assert courseware_coverage["item_count"] == 3
    assert courseware_coverage["covered_knowledge_point_ids"]
    assert courseware_coverage["items"][1]["slide_no"] == 2
    assert courseware_coverage["items"][1]["valid_knowledge_point_ids"]

    slides_update_response = client.put(
        f"/api/v1/courseware-results/{courseware_result_id}/slides",
        headers=headers,
        json={
            "deck_title": "教师修订版课件",
            "slides": [
                {"slide_no": 1, "slide_type": "cover", "title": "乘法口诀提升（修订）", "bullet_points": []},
                {
                    "slide_no": 2,
                    "slide_type": "knowledge",
                    "title": "乘法口诀精讲",
                    "bullet_points": ["熟记口诀", "掌握进位"],
                },
            ],
        },
    )
    assert slides_update_response.status_code == 200
    updated_payload = slides_update_response.json()["data"]
    assert updated_payload["structure_json"]["deck"]["deck_title"] == "教师修订版课件"
    assert len(updated_payload["structure_json"]["deck"]["slides"]) == 2
    assert updated_payload["structure_json"]["pptx_stale"] is True
    assert len(updated_payload["structure_json"]["edit_log"]) == 1
    assert updated_payload["structure_json"]["edit_log"][0]["action"] == "edit"
    assert updated_payload["page_count"] == 2

    regenerate_response = client.post(
        f"/api/v1/courseware-results/{courseware_result_id}/regenerate",
        headers=headers,
    )
    assert regenerate_response.status_code == 200
    regenerated_payload = regenerate_response.json()["data"]
    assert regenerated_payload["result_status"] == "success"
    assert regenerated_payload["export_file_id"] is not None
    assert regenerated_payload["structure_json"]["pptx_stale"] is False
    assert len(regenerated_payload["structure_json"]["deck"]["slides"]) == 2


def test_coverage_report_should_only_count_success_courseware(
    client,
    seeded_session_factory,
    generation_test_stubs,
) -> None:
    """覆盖率报告的课件矩阵只应统计 result_status=success 的课件，非成功课件不计入。"""
    _ = generation_test_stubs
    headers = build_auth_headers(client)
    project_id = create_project(client, headers)
    knowledge_version_id = create_knowledge_version(client, headers, project_id)
    learner_profile_version_id = create_learner_profile_version(client, headers, project_id)

    batch_response = client.post(
        "/api/v1/generation-batches",
        headers=headers,
        json={
            "project_id": project_id,
            "knowledge_version_id": knowledge_version_id,
            "learner_profile_version_id": learner_profile_version_id,
            "chapter_range_json": {"chapter_node_ids": []},
            "course_count": 2,
            "session_duration_minutes": 90,
        },
    )
    assert batch_response.status_code == 201
    batch_payload = batch_response.json()["data"]
    generation_batch_id = batch_payload["id"]
    lesson_plan_ids = batch_payload["lesson_plan_ids"]
    assert len(lesson_plan_ids) == 2

    courseware_response = client.post(
        f"/api/v1/lesson-plans/{lesson_plan_ids[0]}/courseware-tasks",
        headers=headers,
    )
    assert courseware_response.status_code == 201
    assert courseware_response.json()["data"]["task_status"] == "success"

    coverage_before_response = client.get(
        f"/api/v1/coverage-reports?generation_batch_id={generation_batch_id}",
        headers=headers,
    )
    assert coverage_before_response.status_code == 200
    coverage_before = coverage_before_response.json()["data"]["items"][0]
    courseware_before = coverage_before["report_json"]["artifact_coverage"]["courseware_slide"]
    success_item_count = courseware_before["item_count"]
    success_covered_ids = list(courseware_before["covered_knowledge_point_ids"])
    assert success_item_count == 3
    assert success_covered_ids, "成功课件应至少覆盖一个知识点用于对照"

    fake_kp_id = max(success_covered_ids) + 10000
    leak_slides = [
        {
            "slide_no": 1,
            "slide_type": "cover",
            "title": "未完成课件",
            "bullet_points": [],
            "knowledge_point_refs": [fake_kp_id],
        },
        {
            "slide_no": 2,
            "slide_type": "knowledge",
            "title": "未完成讲解",
            "bullet_points": ["占位"],
            "knowledge_point_refs": success_covered_ids,
        },
    ]

    session = seeded_session_factory()
    try:
        leaked_courseware = CoursewareResult(
            generation_batch_id=generation_batch_id,
            lesson_plan_id=lesson_plan_ids[1],
            template_code="raccoon_default",
            template_version="openapi_v2",
            result_status="processing",
            page_count=len(leak_slides),
            page_type_stats_json={"cover": 1, "knowledge": 1},
            structure_json={"deck": {"deck_title": "未完成课件", "slides": leak_slides}},
        )
        session.add(leaked_courseware)
        session.commit()
        leaked_courseware_id = leaked_courseware.id
    finally:
        session.close()

    refresh_processing_response = client.post(
        f"/api/v1/generation-batches/{generation_batch_id}/coverage-reports/refresh",
        headers=headers,
    )
    assert refresh_processing_response.status_code == 200
    courseware_after_processing = refresh_processing_response.json()["data"]["report_json"]["artifact_coverage"][
        "courseware_slide"
    ]
    assert courseware_after_processing["item_count"] == success_item_count
    assert fake_kp_id not in courseware_after_processing["covered_knowledge_point_ids"]
    assert courseware_after_processing["covered_knowledge_point_ids"] == success_covered_ids
    assert all(
        item["courseware_result_id"] != leaked_courseware_id for item in courseware_after_processing["items"]
    )

    session = seeded_session_factory()
    try:
        leaked_courseware = session.get(CoursewareResult, leaked_courseware_id)
        leaked_courseware.result_status = "failure"
        session.add(leaked_courseware)
        session.commit()
    finally:
        session.close()

    refresh_failure_response = client.post(
        f"/api/v1/generation-batches/{generation_batch_id}/coverage-reports/refresh",
        headers=headers,
    )
    assert refresh_failure_response.status_code == 200
    courseware_after_failure = refresh_failure_response.json()["data"]["report_json"]["artifact_coverage"][
        "courseware_slide"
    ]
    assert courseware_after_failure["item_count"] == success_item_count
    assert fake_kp_id not in courseware_after_failure["covered_knowledge_point_ids"]
    assert all(
        item["courseware_result_id"] != leaked_courseware_id for item in courseware_after_failure["items"]
    )


def test_curriculum_prompt_should_use_chapter_range_scope(
    client,
    seeded_session_factory,
    generation_test_stubs,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """课程大纲提示词应只包含章节范围内的章节和知识点。"""
    _ = generation_test_stubs
    captured_curriculum_payloads: list[dict] = []
    captured_lesson_payloads: list[dict] = []
    captured_assessment_payloads: list[dict] = []
    original_generate = OpenAICompatibleLlmService.generate_structured_output

    def capture_generate(self, *, messages, response_model, temperature=0.2):  # noqa: ANN001
        if response_model is CurriculumGenerationResult:
            captured_curriculum_payloads.append(json.loads(messages[1].content))
        if response_model is LessonPlanGenerationResult:
            captured_lesson_payloads.append(json.loads(messages[1].content))
        if response_model is AssessmentGenerationResult:
            captured_assessment_payloads.append(json.loads(messages[1].content))
        return original_generate(self, messages=messages, response_model=response_model, temperature=temperature)

    monkeypatch.setattr(OpenAICompatibleLlmService, "generate_structured_output", capture_generate)
    headers = build_auth_headers(client)
    project_id = create_project(client, headers)
    knowledge_version_id = create_knowledge_version(client, headers, project_id)
    learner_profile_version_id = create_learner_profile_version(client, headers, project_id)
    scoped_chapter_id, scoped_point_id = add_extra_chapter_with_point(seeded_session_factory, knowledge_version_id)

    response = client.post(
        "/api/v1/generation-batches",
        headers=headers,
        json={
            "project_id": project_id,
            "knowledge_version_id": knowledge_version_id,
            "learner_profile_version_id": learner_profile_version_id,
            "chapter_range_json": {"chapter_node_ids": [scoped_chapter_id]},
            "course_count": 1,
            "session_duration_minutes": 90,
        },
    )

    assert response.status_code == 201
    curriculum_payload = captured_curriculum_payloads[0]
    assert [item["id"] for item in curriculum_payload["knowledge_version"]["chapters"]] == [scoped_chapter_id]
    assert [item["id"] for item in curriculum_payload["knowledge_version"]["knowledge_points"]] == [scoped_point_id]
    assert curriculum_payload["knowledge_version"]["chapter_range_scope"]["is_scoped"] is True
    assert curriculum_payload["knowledge_version"]["chapter_range_scope"]["requested_chapter_ids"] == [scoped_chapter_id]
    assert [item["id"] for item in captured_lesson_payloads[0]["knowledge_points"]] == [scoped_point_id]

    batch_payload = response.json()["data"]
    coverage_response = client.get(
        f"/api/v1/coverage-reports?generation_batch_id={batch_payload['id']}",
        headers=headers,
    )
    assert coverage_response.status_code == 200
    coverage_payload = coverage_response.json()["data"]["items"][0]
    knowledge_scope = coverage_payload["coverage_summary_json"]["knowledge_scope"]
    assert coverage_payload["report_json"]["total_knowledge_point_count"] == 1
    assert coverage_payload["report_json"]["uncovered_knowledge_point_ids"] == []
    assert knowledge_scope["chapter_range_scoped"] is True
    assert knowledge_scope["requested_chapter_ids"] == [scoped_chapter_id]
    assert knowledge_scope["effective_chapter_ids"] == [scoped_chapter_id]
    assert knowledge_scope["total_knowledge_version_point_count"] == 2
    assert knowledge_scope["scoped_knowledge_point_count"] == 1

    assessment_task_response = client.post(
        f"/api/v1/curriculum-plans/{batch_payload['curriculum_plan_id']}/assessment-tasks",
        headers=headers,
        json={},
    )
    assert assessment_task_response.status_code == 201
    assert [item["id"] for item in captured_assessment_payloads[0]["knowledge_points"]] == [scoped_point_id]


def test_lesson_plan_generation_result_should_reject_empty_skeleton() -> None:
    """教案生成 Schema 应拒绝空骨架内容。"""
    valid_payload = {
        "lesson_title": "第1讲 教案",
        "summary_text": "围绕核心知识开展教学。",
        "course_overview": {"lesson_type": "提升课"},
        "material_list": ["教材片段"],
        "core_knowledge": ["核心知识"],
        "teaching_flow": [
            {
                "step_no": 1,
                "stage_name": "导入",
                "duration_minutes": 10,
                "teacher_actions": ["提出情境问题"],
                "student_activities": ["回答问题"],
                "knowledge_point_refs": [1],
            }
        ],
        "session_plans": [
            {
                "session_no": 1,
                "title": "第1讲",
                "objectives": ["掌握核心知识"],
                "teaching_focus": ["核心知识"],
                "teaching_steps": [
                    {
                        "step_no": 1,
                        "stage_name": "讲解",
                        "duration_minutes": 30,
                        "teacher_actions": ["讲解概念"],
                        "student_activities": ["完成练习"],
                        "knowledge_point_refs": [1],
                    }
                ],
                "homework": ["完成练习"],
                "knowledge_point_refs": [1],
            }
        ],
        "after_class_plan": {"homework": ["完成练习"]},
        "learner_adjustments": ["增加示例"],
        "knowledge_point_refs": [1],
    }
    LessonPlanGenerationResult(**valid_payload)

    for field_name, empty_value in [
        ("course_overview", {}),
        ("teaching_flow", []),
        ("session_plans", []),
    ]:
        invalid_payload = {**valid_payload, field_name: empty_value}
        with pytest.raises(ValidationError):
            LessonPlanGenerationResult(**invalid_payload)

    invalid_step_payload = {
        **valid_payload,
        "teaching_flow": [
            {
                "step_no": 1,
                "stage_name": "导入",
                "duration_minutes": 10,
                "teacher_actions": [],
                "student_activities": ["回答问题"],
                "knowledge_point_refs": [1],
            }
        ],
    }
    with pytest.raises(ValidationError):
        LessonPlanGenerationResult(**invalid_step_payload)


def test_courseware_prompt_should_prefer_current_lesson_knowledge_refs(
    client,
    seeded_session_factory,
    generation_test_stubs,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """课件提示词应优先使用当前教案引用的知识点，而不是前 30 个知识点。"""
    _ = generation_test_stubs
    captured_payloads: list[dict] = []
    original_build_messages = CoursewareService.build_slide_deck_messages

    def capture_build_messages(self, context):  # noqa: ANN001
        messages = original_build_messages(self, context)
        captured_payloads.append(json.loads(messages[1].content))
        return messages

    def stub_create_job(self, *, prompt: str, role: str, scene: str, audience: str):  # noqa: ANN001
        _ = (self, prompt, role, scene, audience)
        return RaccoonPptJobState(
            job_id="ppt-job-selected-kp",
            status="succeeded",
            download_url="https://raccoon.test.example.com/courseware.pptx",
            raw_payload={"data": {"job_id": "ppt-job-selected-kp", "status": "succeeded"}},
        )

    monkeypatch.setattr(CoursewareService, "build_slide_deck_messages", capture_build_messages)
    monkeypatch.setattr(RaccoonPptService, "create_job_and_short_poll", stub_create_job)
    headers = build_auth_headers(client)
    project_id = create_project(client, headers)
    knowledge_version_id = create_knowledge_version(client, headers, project_id)
    learner_profile_version_id = create_learner_profile_version(client, headers, project_id)
    target_point_ids = add_many_extra_knowledge_points(seeded_session_factory, knowledge_version_id, count=35)

    response = client.post(
        "/api/v1/generation-batches",
        headers=headers,
        json={
            "project_id": project_id,
            "knowledge_version_id": knowledge_version_id,
            "learner_profile_version_id": learner_profile_version_id,
            "course_count": 1,
            "session_duration_minutes": 90,
        },
    )
    assert response.status_code == 201
    batch_payload = response.json()["data"]
    lesson_plan_id = batch_payload["lesson_plan_id"]

    session = seeded_session_factory()
    try:
        lesson_plan = session.query(LessonPlan).filter(LessonPlan.id == lesson_plan_id).one()
        lesson_plan.content_json = {
            **lesson_plan.content_json,
            "target_lesson_session": {
                "session_no": 1,
                "title": "后置知识点课次",
                "knowledge_point_refs": target_point_ids,
            },
            "knowledge_point_refs": target_point_ids,
            "teaching_flow": [
                {
                    "step_no": 1,
                    "stage_name": "讲解",
                    "teacher_actions": ["讲解后置知识点"],
                    "student_activities": ["完成后置练习"],
                    "knowledge_point_refs": target_point_ids,
                }
            ],
            "session_plans": [
                {
                    "session_no": 1,
                    "title": "后置知识点课次",
                    "objectives": ["掌握后置知识点"],
                    "teaching_focus": ["后置知识点"],
                    "teaching_steps": [
                        {
                            "step_no": 1,
                            "stage_name": "讲解",
                            "teacher_actions": ["讲解后置知识点"],
                            "student_activities": ["完成后置练习"],
                            "knowledge_point_refs": target_point_ids,
                        }
                    ],
                    "homework": ["完成后置练习"],
                    "knowledge_point_refs": target_point_ids,
                }
            ],
        }
        session.commit()
    finally:
        session.close()

    courseware_task_response = client.post(f"/api/v1/lesson-plans/{lesson_plan_id}/courseware-tasks", headers=headers)

    assert courseware_task_response.status_code == 201
    prompt_payload = captured_payloads[0]
    assert prompt_payload["知识点选择"]["source"] == "lesson_plan"
    assert prompt_payload["知识点选择"]["limit"] == 30
    assert prompt_payload["知识点选择"]["original_count"] == 35
    assert prompt_payload["知识点选择"]["selected_count"] == 30
    assert prompt_payload["知识点选择"]["truncated_count"] == 5
    assert prompt_payload["知识点选择"]["is_truncated"] is True
    assert [item["id"] for item in prompt_payload["知识点"]] == target_point_ids[:30]


def test_courseware_task_should_fail_on_slide_deck_stage_when_llm_invalid(
    client,
    generation_test_stubs,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """课件结构生成失败时应停留在结构化课件阶段，不应提前进入 Raccoon 创建阶段。"""
    _ = generation_test_stubs
    headers = build_auth_headers(client)
    project_id = create_project(client, headers)
    knowledge_version_id = create_knowledge_version(client, headers, project_id)
    learner_profile_version_id = create_learner_profile_version(client, headers, project_id)

    response = client.post(
        "/api/v1/generation-batches",
        headers=headers,
        json={
            "project_id": project_id,
            "knowledge_version_id": knowledge_version_id,
            "learner_profile_version_id": learner_profile_version_id,
            "course_count": 1,
            "session_duration_minutes": 90,
        },
    )
    assert response.status_code == 201
    batch_payload = response.json()["data"]

    original_generate = OpenAICompatibleLlmService.generate_structured_output

    def fail_slide_deck_generate(self, *, messages, response_model, temperature=0.2):  # noqa: ANN001
        if response_model is SlideDeckGenerationResult:
            raise AppException(BusinessErrorCode.LLM_RESULT_INVALID, "LLM 返回课件结构非法")
        return original_generate(self, messages=messages, response_model=response_model, temperature=temperature)

    monkeypatch.setattr(OpenAICompatibleLlmService, "generate_structured_output", fail_slide_deck_generate)

    courseware_task_response = client.post(
        f"/api/v1/lesson-plans/{batch_payload['lesson_plan_id']}/courseware-tasks",
        headers=headers,
    )
    assert courseware_task_response.status_code == 503
    assert courseware_task_response.json()["errors"][0]["code"] == BusinessErrorCode.LLM_RESULT_INVALID.value

    batch_detail_response = client.get(f"/api/v1/generation-batches/{batch_payload['id']}", headers=headers)
    courseware_task_payload = [
        task for task in batch_detail_response.json()["data"]["tasks"] if task["task_type"] == "courseware_generate"
    ][0]
    assert courseware_task_payload["task_status"] == "failure"
    assert courseware_task_payload["current_stage"] == "generate_slide_deck"
    assert courseware_task_payload["last_error_code"] == BusinessErrorCode.LLM_RESULT_INVALID.value

    task_detail_response = client.get(f"/api/v1/tasks/{courseware_task_payload['id']}", headers=headers)
    task_steps = {step["step_code"]: step for step in task_detail_response.json()["data"]["steps"]}
    assert task_steps["prepare_courseware_baseline"]["step_status"] == "success"
    assert task_steps["generate_slide_deck"]["step_status"] == "failure"
    assert task_steps["create_raccoon_ppt_job"]["step_status"] == "pending"

    courseware_list_response = client.get(
        f"/api/v1/courseware-results?generation_batch_id={batch_payload['id']}",
        headers=headers,
    )
    assert courseware_list_response.json()["data"]["pagination"]["total_count"] == 0


def test_generation_batch_should_reject_foreign_baseline(client, generation_test_stubs) -> None:
    """生成批次应拒绝跨项目知识或学情版本。"""
    _ = generation_test_stubs
    headers = build_auth_headers(client)
    first_project_id = create_project(client, headers, name="项目一")
    second_project_id = create_project(client, headers, name="项目二")
    knowledge_version_id = create_knowledge_version(client, headers, first_project_id)
    foreign_profile_version_id = create_learner_profile_version(client, headers, second_project_id)

    response = client.post(
        "/api/v1/generation-batches",
        headers=headers,
        json={
            "project_id": first_project_id,
            "knowledge_version_id": knowledge_version_id,
            "learner_profile_version_id": foreign_profile_version_id,
            "course_count": 2,
            "session_duration_minutes": 90,
        },
    )

    assert response.status_code == 422
    assert response.json()["errors"][0]["code"] == "GENERATION_BASELINE_INVALID"


def test_coverage_report_should_protect_owner(client, generation_test_stubs, seeded_session_factory) -> None:
    """覆盖率报告接口应隔离不同教师的数据。"""
    _ = generation_test_stubs
    headers = build_auth_headers(client)
    other_headers = build_other_auth_headers(client, seeded_session_factory)
    project_id = create_project(client, headers)
    knowledge_version_id = create_knowledge_version(client, headers, project_id)
    learner_profile_version_id = create_learner_profile_version(client, headers, project_id)

    response = client.post(
        "/api/v1/generation-batches",
        headers=headers,
        json={
            "project_id": project_id,
            "knowledge_version_id": knowledge_version_id,
            "learner_profile_version_id": learner_profile_version_id,
            "course_count": 2,
            "session_duration_minutes": 90,
        },
    )
    batch_payload = response.json()["data"]
    coverage_report_id = batch_payload["tasks"][2]["result_json"]["coverage_report_id"]

    forbidden_list_response = client.get(
        f"/api/v1/coverage-reports?generation_batch_id={batch_payload['id']}",
        headers=other_headers,
    )
    assert forbidden_list_response.status_code == 404
    assert forbidden_list_response.json()["errors"][0]["code"] == "GENERATION_BATCH_NOT_FOUND"

    forbidden_detail_response = client.get(f"/api/v1/coverage-reports/{coverage_report_id}", headers=other_headers)
    assert forbidden_detail_response.status_code == 404
    assert forbidden_detail_response.json()["errors"][0]["code"] == "COVERAGE_REPORT_NOT_FOUND"


def test_coverage_report_should_include_on_demand_courseware_refs_after_refresh(
    client,
    generation_test_stubs,
) -> None:
    """覆盖率应纳入按需课件页面引用，并支持手动刷新识别非法引用。"""
    _ = generation_test_stubs
    headers = build_auth_headers(client)
    project_id = create_project(client, headers)
    knowledge_version_id = create_knowledge_version(client, headers, project_id)
    learner_profile_version_id = create_learner_profile_version(client, headers, project_id)

    response = client.post(
        "/api/v1/generation-batches",
        headers=headers,
        json={
            "project_id": project_id,
            "knowledge_version_id": knowledge_version_id,
            "learner_profile_version_id": learner_profile_version_id,
            "course_count": 2,
            "session_duration_minutes": 90,
        },
    )
    assert response.status_code == 201
    batch_payload = response.json()["data"]
    assert batch_payload["batch_status"] == "success"

    coverage_response = client.get(
        f"/api/v1/coverage-reports?generation_batch_id={batch_payload['id']}",
        headers=headers,
    )
    coverage_payload = coverage_response.json()["data"]["items"][0]
    assert coverage_payload["coverage_rate"] == 100.0
    assert coverage_payload["warning_count"] == 0
    assert coverage_payload["report_json"]["artifact_coverage"]["courseware_slide"]["item_count"] == 0

    courseware_task_response = client.post(
        f"/api/v1/lesson-plans/{batch_payload['lesson_plan_ids'][0]}/courseware-tasks",
        headers=headers,
    )
    assert courseware_task_response.status_code == 201
    courseware_result_id = courseware_task_response.json()["data"]["result_json"]["courseware_result_id"]

    refreshed_coverage_response = client.get(
        f"/api/v1/coverage-reports?generation_batch_id={batch_payload['id']}",
        headers=headers,
    )
    refreshed_coverage_payload = refreshed_coverage_response.json()["data"]["items"][0]
    assert refreshed_coverage_payload["warning_count"] == 0
    assert refreshed_coverage_payload["report_json"]["artifact_coverage"]["courseware_slide"]["item_count"] == 3

    slides_update_response = client.put(
        f"/api/v1/courseware-results/{courseware_result_id}/slides",
        headers=headers,
        json={
            "deck_title": "含非法引用的课件",
            "slides": [
                {"slide_no": 1, "slide_type": "cover", "title": "封面", "bullet_points": []},
                {
                    "slide_no": 2,
                    "slide_type": "knowledge",
                    "title": "非法引用页",
                    "bullet_points": ["用于刷新校验"],
                    "knowledge_point_refs": [999999],
                },
            ],
        },
    )
    assert slides_update_response.status_code == 200

    manual_refresh_response = client.post(
        f"/api/v1/generation-batches/{batch_payload['id']}/coverage-reports/refresh",
        headers=headers,
    )
    assert manual_refresh_response.status_code == 200
    refreshed_report = manual_refresh_response.json()["data"]["report_json"]
    assert refreshed_report["artifact_coverage"]["courseware_slide"]["invalid_knowledge_point_ids"] == [999999]
    assert refreshed_report["warnings"][0]["code"] == "INVALID_KNOWLEDGE_POINT_REF"


def test_coverage_refresh_should_warn_when_question_difficulty_out_of_strategy(
    client,
    seeded_session_factory,
    generation_test_stubs,
) -> None:
    """覆盖率刷新应校验题目难度是否落在测评场景预设范围内。"""
    _ = generation_test_stubs
    headers = build_auth_headers(client)
    project_id = create_project(client, headers)
    knowledge_version_id = create_knowledge_version(client, headers, project_id)
    learner_profile_version_id = create_learner_profile_version(client, headers, project_id)

    response = client.post(
        "/api/v1/generation-batches",
        headers=headers,
        json={
            "project_id": project_id,
            "knowledge_version_id": knowledge_version_id,
            "learner_profile_version_id": learner_profile_version_id,
            "course_count": 1,
            "session_duration_minutes": 90,
        },
    )
    assert response.status_code == 201
    batch_payload = response.json()["data"]

    assessment_task_response = client.post(
        f"/api/v1/curriculum-plans/{batch_payload['curriculum_plan_id']}/assessment-tasks",
        headers=headers,
        json={},
    )
    assert assessment_task_response.status_code == 201

    session = seeded_session_factory()
    try:
        question = (
            session.query(QuestionItem)
            .filter(QuestionItem.generation_batch_id == batch_payload["id"])
            .order_by(QuestionItem.question_no.asc())
            .first()
        )
        question.difficulty_level = 5
        session.commit()
        out_of_range_question_id = question.id
    finally:
        session.close()

    manual_refresh_response = client.post(
        f"/api/v1/generation-batches/{batch_payload['id']}/coverage-reports/refresh",
        headers=headers,
    )
    assert manual_refresh_response.status_code == 200
    report_json = manual_refresh_response.json()["data"]["report_json"]
    warning_codes = [warning["code"] for warning in report_json["warnings"]]
    assert "QUESTION_DIFFICULTY_OUT_OF_RANGE" in warning_codes
    assert report_json["assessment_quality"]["difficulty_distribution"]["5"] == 1
    assert report_json["assessment_quality"]["strategy_checks"][0]["passed"] is False
    assert report_json["assessment_quality"]["strategy_checks"][0]["out_of_range_question_item_ids"] == [
        out_of_range_question_id
    ]


def test_courseware_refresh_should_finalize_pending_raccoon_job(
    client,
    generation_test_stubs,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """课件短轮询未完成时应保持处理中，并可通过刷新收口批次。"""
    _ = generation_test_stubs

    def running_create_job(self, *, prompt: str, role: str, scene: str, audience: str):  # noqa: ANN001
        _ = (self, prompt, role, scene, audience)
        return RaccoonPptJobState(
            job_id="ppt-job-pending",
            status="running",
            raw_payload={"data": {"job_id": "ppt-job-pending", "status": "running"}},
        )

    monkeypatch.setattr(RaccoonPptService, "create_job_and_short_poll", running_create_job)

    headers = build_auth_headers(client)
    project_id = create_project(client, headers)
    knowledge_version_id = create_knowledge_version(client, headers, project_id)
    learner_profile_version_id = create_learner_profile_version(client, headers, project_id)

    response = client.post(
        "/api/v1/generation-batches",
        headers=headers,
        json={
            "project_id": project_id,
            "knowledge_version_id": knowledge_version_id,
            "learner_profile_version_id": learner_profile_version_id,
            "course_count": 2,
            "session_duration_minutes": 90,
        },
    )

    assert response.status_code == 201
    batch_payload = response.json()["data"]
    assert batch_payload["batch_status"] == "success"
    assert len(batch_payload["tasks"]) == 3

    courseware_task_response = client.post(
        f"/api/v1/lesson-plans/{batch_payload['lesson_plan_ids'][0]}/courseware-tasks",
        headers=headers,
    )
    assert courseware_task_response.status_code == 201
    courseware_task_payload = courseware_task_response.json()["data"]
    assert courseware_task_payload["task_type"] == "courseware_generate"
    assert courseware_task_payload["task_status"] == "processing"

    courseware_list_response = client.get(
        f"/api/v1/courseware-results?generation_batch_id={batch_payload['id']}",
        headers=headers,
    )
    courseware_payload = courseware_list_response.json()["data"]["items"][0]
    assert courseware_payload["result_status"] == "processing"
    assert courseware_payload["export_file_id"] is None
    coverage_list_response = client.get(
        f"/api/v1/coverage-reports?generation_batch_id={batch_payload['id']}",
        headers=headers,
    )
    assert coverage_list_response.status_code == 200
    assert coverage_list_response.json()["data"]["pagination"]["total_count"] == 1

    def succeeded_short_poll(self, job_id: str, initial_state=None):  # noqa: ANN001
        _ = (self, initial_state)
        return RaccoonPptJobState(
            job_id=job_id,
            status="succeeded",
            download_url="https://raccoon.test.example.com/courseware.pptx",
            raw_payload={"data": {"job_id": job_id, "status": "succeeded"}},
        )

    monkeypatch.setattr(RaccoonPptService, "short_poll_job", succeeded_short_poll)

    refresh_response = client.post(f"/api/v1/courseware-results/{courseware_payload['id']}/refresh", headers=headers)
    assert refresh_response.status_code == 200
    refreshed_payload = refresh_response.json()["data"]
    assert refreshed_payload["result_status"] == "success"
    assert refreshed_payload["export_file_id"] is not None

    batch_detail_response = client.get(f"/api/v1/generation-batches/{batch_payload['id']}", headers=headers)
    batch_detail_payload = batch_detail_response.json()["data"]
    assert batch_detail_payload["batch_status"] == "success"
    assert [task["task_type"] for task in batch_detail_payload["tasks"]] == [
        "curriculum_generate",
        "lesson_plan_generate",
        "coverage_analyze",
        "courseware_generate",
    ]
    assert batch_detail_payload["tasks"][3]["task_status"] == "success"
    task_detail_response = client.get(f"/api/v1/tasks/{courseware_task_payload['id']}", headers=headers)
    task_steps = {step["step_code"]: step for step in task_detail_response.json()["data"]["steps"]}
    assert task_steps["poll_raccoon_ppt_job"]["step_status"] == "success"
    assert task_steps["archive_courseware_result"]["step_status"] == "success"
    assert task_steps["finalize_generation_batch"]["step_status"] == "success"
    coverage_response = client.get(
        f"/api/v1/coverage-reports?generation_batch_id={batch_payload['id']}",
        headers=headers,
    )
    assert coverage_response.json()["data"]["pagination"]["total_count"] == 1


def test_courseware_reply_should_continue_after_required_user_input(
    client,
    generation_test_stubs,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Raccoon 要求补充输入时应保存问题，并可通过 reply 继续生成。"""
    _ = generation_test_stubs

    def waiting_create_job(self, *, prompt: str, role: str, scene: str, audience: str):  # noqa: ANN001
        _ = (self, prompt, role, scene, audience)
        return RaccoonPptJobState(
            job_id="ppt-job-waiting",
            status="waiting_user_input",
            required_user_input="请补充课件页数偏好。",
            raw_payload={"data": {"job_id": "ppt-job-waiting", "status": "waiting_user_input"}},
        )

    monkeypatch.setattr(RaccoonPptService, "create_job_and_short_poll", waiting_create_job)

    headers = build_auth_headers(client)
    project_id = create_project(client, headers)
    knowledge_version_id = create_knowledge_version(client, headers, project_id)
    learner_profile_version_id = create_learner_profile_version(client, headers, project_id)

    response = client.post(
        "/api/v1/generation-batches",
        headers=headers,
        json={
            "project_id": project_id,
            "knowledge_version_id": knowledge_version_id,
            "learner_profile_version_id": learner_profile_version_id,
            "course_count": 2,
            "session_duration_minutes": 90,
        },
    )

    assert response.status_code == 201
    batch_payload = response.json()["data"]
    assert batch_payload["batch_status"] == "success"
    assert len(batch_payload["tasks"]) == 3

    courseware_task_response = client.post(
        f"/api/v1/lesson-plans/{batch_payload['lesson_plan_ids'][0]}/courseware-tasks",
        headers=headers,
    )
    assert courseware_task_response.status_code == 201
    courseware_task_payload = courseware_task_response.json()["data"]
    assert courseware_task_payload["task_status"] == "processing"

    courseware_list_response = client.get(
        f"/api/v1/courseware-results?generation_batch_id={batch_payload['id']}",
        headers=headers,
    )
    courseware_payload = courseware_list_response.json()["data"]["items"][0]
    assert courseware_payload["result_status"] == "processing"
    assert courseware_payload["preview_json"]["required_user_input"] == "请补充课件页数偏好。"

    def succeeded_reply_and_short_poll(self, *, job_id: str, answer: str):  # noqa: ANN001
        _ = (self, answer)
        return RaccoonPptJobState(
            job_id=job_id,
            status="succeeded",
            download_url="https://raccoon.test.example.com/courseware.pptx",
            raw_payload={"data": {"job_id": job_id, "status": "succeeded"}},
        )

    monkeypatch.setattr(RaccoonPptService, "reply_and_short_poll", succeeded_reply_and_short_poll)

    reply_response = client.post(
        f"/api/v1/courseware-results/{courseware_payload['id']}/reply",
        headers=headers,
        json={"answer": "请生成 18 页左右，互动练习页不少于 3 页。"},
    )
    assert reply_response.status_code == 200
    replied_payload = reply_response.json()["data"]
    assert replied_payload["result_status"] == "success"
    assert replied_payload["export_file_id"] is not None

    batch_detail_response = client.get(f"/api/v1/generation-batches/{batch_payload['id']}", headers=headers)
    batch_detail_payload = batch_detail_response.json()["data"]
    assert batch_detail_payload["batch_status"] == "success"
    assert [task["task_type"] for task in batch_detail_payload["tasks"]] == [
        "curriculum_generate",
        "lesson_plan_generate",
        "coverage_analyze",
        "courseware_generate",
    ]
    assert batch_detail_payload["tasks"][3]["task_status"] == "success"
    task_detail_response = client.get(f"/api/v1/tasks/{courseware_task_payload['id']}", headers=headers)
    task_steps = {step["step_code"]: step for step in task_detail_response.json()["data"]["steps"]}
    assert task_steps["poll_raccoon_ppt_job"]["step_status"] == "success"
    assert task_steps["archive_courseware_result"]["step_status"] == "success"
    assert task_steps["finalize_generation_batch"]["step_status"] == "success"
    coverage_response = client.get(
        f"/api/v1/coverage-reports?generation_batch_id={batch_payload['id']}",
        headers=headers,
    )
    assert coverage_response.json()["data"]["pagination"]["total_count"] == 1


def test_generation_batch_should_mark_failure_when_llm_invalid(
    client,
    generation_test_stubs,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LLM 返回非法结构时应写入失败批次与失败任务。"""
    _ = generation_test_stubs
    headers = build_auth_headers(client)
    project_id = create_project(client, headers)
    knowledge_version_id = create_knowledge_version(client, headers, project_id)
    learner_profile_version_id = create_learner_profile_version(client, headers, project_id)

    original_generate = OpenAICompatibleLlmService.generate_structured_output

    def mixed_generate(self, *, messages, response_model, temperature=0.2):  # noqa: ANN001
        if response_model is CurriculumGenerationResult:
            raise AppException(BusinessErrorCode.LLM_RESULT_INVALID, "LLM 返回课程大纲非法")
        return original_generate(self, messages=messages, response_model=response_model, temperature=temperature)

    monkeypatch.setattr(OpenAICompatibleLlmService, "generate_structured_output", mixed_generate)
    response = client.post(
        "/api/v1/generation-batches",
        headers=headers,
        json={
            "project_id": project_id,
            "knowledge_version_id": knowledge_version_id,
            "learner_profile_version_id": learner_profile_version_id,
            "course_count": 2,
            "session_duration_minutes": 90,
        },
    )

    assert response.status_code == 503
    assert response.json()["errors"][0]["code"] == BusinessErrorCode.LLM_RESULT_INVALID.value

    list_response = client.get(f"/api/v1/generation-batches?project_id={project_id}", headers=headers)
    assert list_response.status_code == 200
    failed_batch = list_response.json()["data"]["items"][0]
    assert failed_batch["batch_status"] == "failure"

    detail_response = client.get(f"/api/v1/generation-batches/{failed_batch['id']}", headers=headers)
    task_payload = detail_response.json()["data"]["tasks"][0]
    assert task_payload["task_status"] == "failure"
    assert task_payload["last_error_code"] == BusinessErrorCode.LLM_RESULT_INVALID.value


def test_generation_batch_should_mark_failure_when_lesson_plan_has_invalid_knowledge_ref(
    client,
    seeded_session_factory,
    generation_test_stubs,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """教案引用章节范围外知识点时应写入失败批次与失败任务。"""
    _ = generation_test_stubs
    headers = build_auth_headers(client)
    project_id = create_project(client, headers)
    knowledge_version_id = create_knowledge_version(client, headers, project_id)
    learner_profile_version_id = create_learner_profile_version(client, headers, project_id)
    scoped_chapter_id, scoped_point_id = add_extra_chapter_with_point(seeded_session_factory, knowledge_version_id)
    session = seeded_session_factory()
    try:
        outside_point_id = (
            session.query(KnowledgePoint)
            .filter(KnowledgePoint.knowledge_version_id == knowledge_version_id, KnowledgePoint.id != scoped_point_id)
            .order_by(KnowledgePoint.id.asc())
            .first()
            .id
        )
    finally:
        session.close()

    original_generate = OpenAICompatibleLlmService.generate_structured_output

    def mixed_generate(self, *, messages, response_model, temperature=0.2):  # noqa: ANN001
        if response_model is LessonPlanGenerationResult:
            return LessonPlanGenerationResult(
                lesson_title="非法知识点教案",
                summary_text="包含不存在的知识点引用。",
                course_overview={"lesson_type": "提升课"},
                material_list=["教材解析片段"],
                core_knowledge=["乘法口诀"],
                teaching_flow=[
                    {
                        "step_no": 1,
                        "stage_name": "导入",
                        "duration_minutes": 10,
                        "teacher_actions": ["导入"],
                        "student_activities": ["练习"],
                        "knowledge_point_refs": [outside_point_id],
                    }
                ],
                session_plans=[
                    {
                        "session_no": 1,
                        "title": "非法知识点教案",
                        "objectives": ["验证非法引用"],
                        "teaching_focus": ["非法引用"],
                        "teaching_steps": [
                            {
                                "step_no": 1,
                                "stage_name": "讲解",
                                "duration_minutes": 30,
                                "teacher_actions": ["讲解"],
                                "student_activities": ["练习"],
                                "knowledge_point_refs": [outside_point_id],
                            }
                        ],
                        "homework": ["完成练习"],
                        "knowledge_point_refs": [outside_point_id],
                    }
                ],
                after_class_plan={"homework": ["完成练习"]},
                learner_adjustments=["增加讲解"],
                knowledge_point_refs=[outside_point_id],
            )
        return original_generate(self, messages=messages, response_model=response_model, temperature=temperature)

    monkeypatch.setattr(OpenAICompatibleLlmService, "generate_structured_output", mixed_generate)
    response = client.post(
        "/api/v1/generation-batches",
        headers=headers,
        json={
            "project_id": project_id,
            "knowledge_version_id": knowledge_version_id,
            "learner_profile_version_id": learner_profile_version_id,
            "chapter_range_json": {"chapter_node_ids": [scoped_chapter_id]},
            "course_count": 1,
            "session_duration_minutes": 90,
        },
    )

    assert response.status_code == 503
    assert response.json()["errors"][0]["code"] == BusinessErrorCode.LLM_RESULT_INVALID.value

    list_response = client.get(f"/api/v1/generation-batches?project_id={project_id}", headers=headers)
    assert list_response.status_code == 200
    failed_batch = list_response.json()["data"]["items"][0]
    assert failed_batch["batch_status"] == "failure"
    assert failed_batch["curriculum_plan_id"] is not None
    assert failed_batch["lesson_plan_id"] is None

    detail_response = client.get(f"/api/v1/generation-batches/{failed_batch['id']}", headers=headers)
    tasks = detail_response.json()["data"]["tasks"]
    assert [task["task_type"] for task in tasks] == ["curriculum_generate", "lesson_plan_generate"]
    assert tasks[0]["task_status"] == "success"
    assert tasks[1]["task_status"] == "failure"
    assert tasks[1]["last_error_code"] == BusinessErrorCode.LLM_RESULT_INVALID.value


def test_pending_courseware_should_finalize_via_background_poll(
    client,
    generation_test_stubs,
    seeded_session_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """停泊等待 Raccoon 的课件任务应能被后台复查自动推进完成，无需前端刷新。"""
    _ = generation_test_stubs
    from app.modules.courseware.tasks import poll_pending_remote_courseware_results_once

    def running_create_job(self, *, prompt: str, role: str, scene: str, audience: str):  # noqa: ANN001
        _ = (self, prompt, role, scene, audience)
        return RaccoonPptJobState(
            job_id="ppt-job-bgpoll",
            status="running",
            raw_payload={"data": {"job_id": "ppt-job-bgpoll", "status": "running"}},
        )

    monkeypatch.setattr(RaccoonPptService, "create_job_and_short_poll", running_create_job)

    headers = build_auth_headers(client)
    project_id = create_project(client, headers)
    knowledge_version_id = create_knowledge_version(client, headers, project_id)
    learner_profile_version_id = create_learner_profile_version(client, headers, project_id)

    batch_response = client.post(
        "/api/v1/generation-batches",
        headers=headers,
        json={
            "project_id": project_id,
            "knowledge_version_id": knowledge_version_id,
            "learner_profile_version_id": learner_profile_version_id,
            "course_count": 1,
            "session_duration_minutes": 90,
        },
    )
    assert batch_response.status_code == 201
    batch_payload = batch_response.json()["data"]

    courseware_task_response = client.post(
        f"/api/v1/lesson-plans/{batch_payload['lesson_plan_ids'][0]}/courseware-tasks",
        headers=headers,
    )
    assert courseware_task_response.status_code == 201
    courseware_task_payload = courseware_task_response.json()["data"]
    assert courseware_task_payload["task_status"] == "processing"

    # 阶段一：Raccoon 仍在生成，后台单发复查应保持任务停泊
    def running_get_job(self, job_id: str):  # noqa: ANN001
        _ = self
        return RaccoonPptJobState(
            job_id=job_id,
            status="running",
            raw_payload={"data": {"job_id": job_id, "status": "running"}},
        )

    monkeypatch.setattr(RaccoonPptService, "get_job_state", running_get_job)
    session = seeded_session_factory()
    try:
        pending_summary = poll_pending_remote_courseware_results_once(session)
    finally:
        session.close()
    assert pending_summary == {"scanned": 1, "succeeded": 0, "failed": 0, "pending": 1, "errored": 0}
    parked_detail = client.get(f"/api/v1/tasks/{courseware_task_payload['id']}", headers=headers).json()["data"]
    assert parked_detail["task_status"] == "processing"

    # 阶段二：Raccoon 完成，后台复查无需前端刷新即收口
    def succeeded_get_job(self, job_id: str):  # noqa: ANN001
        _ = self
        return RaccoonPptJobState(
            job_id=job_id,
            status="succeeded",
            download_url="https://raccoon.test.example.com/courseware.pptx",
            raw_payload={"data": {"job_id": job_id, "status": "succeeded"}},
        )

    monkeypatch.setattr(RaccoonPptService, "get_job_state", succeeded_get_job)
    session = seeded_session_factory()
    try:
        done_summary = poll_pending_remote_courseware_results_once(session)
    finally:
        session.close()
    assert done_summary["scanned"] == 1
    assert done_summary["succeeded"] == 1

    task_detail = client.get(f"/api/v1/tasks/{courseware_task_payload['id']}", headers=headers).json()["data"]
    assert task_detail["task_status"] == "success"
    courseware_items = client.get(
        f"/api/v1/courseware-results?generation_batch_id={batch_payload['id']}",
        headers=headers,
    ).json()["data"]["items"]
    assert courseware_items[0]["result_status"] == "success"
    assert courseware_items[0]["export_file_id"] is not None
