"""
@Date: 2026-04-26
@Author: xisy
@Discription: 生成编排与课程大纲接口测试
"""

import json
from io import BytesIO

import pytest
from pypdf import PdfWriter

from app.core.config import get_settings
from app.core.exceptions import AppException, BusinessErrorCode
from app.modules.curriculum.schemas import CurriculumGenerationResult
from app.modules.knowledge.schemas import (
    KnowledgeExtractionChapterDraft,
    KnowledgeExtractionEvidenceDraft,
    KnowledgeExtractionPointDraft,
    KnowledgeExtractionResult,
)
from app.shared.llm import OpenAICompatibleEmbeddingService, OpenAICompatibleLlmService
from app.shared.vector import MilvusVectorService


def build_auth_headers(client) -> dict[str, str]:
    """构造认证请求头。"""
    login_response = client.post(
        "/api/v1/auth/login",
        json={"username": "teacher_demo", "password": "Teacher@123"},
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


@pytest.fixture()
def generation_test_stubs(monkeypatch: pytest.MonkeyPatch):
    """替换知识抽取、课程生成和向量写入依赖。"""
    vector_store: dict[str, list] = {}

    def fake_generate_structured_output(self, *, messages, response_model, temperature=0.2):  # noqa: ANN001
        _ = (self, temperature)
        if response_model is KnowledgeExtractionResult:
            return KnowledgeExtractionResult(
                summary_json={
                    "teaching_objectives": ["掌握乘法口诀", "理解乘法应用"],
                    "key_points": ["乘法口诀"],
                    "difficult_points": ["应用题分析"],
                },
                chapters=[
                    KnowledgeExtractionChapterDraft(
                        node_path="1",
                        node_no=1,
                        node_level=1,
                        node_type="unit",
                        title="第一单元 表内乘法",
                        summary_text="乘法基础知识",
                        page_start=1,
                        page_end=2,
                        sort_order=0,
                    ),
                    KnowledgeExtractionChapterDraft(
                        node_path="1.1",
                        node_no=1,
                        node_level=2,
                        node_type="section",
                        title="乘法口诀",
                        summary_text="重点掌握口诀记忆与应用",
                        page_start=1,
                        page_end=2,
                        sort_order=1,
                    ),
                ],
                knowledge_points=[
                    KnowledgeExtractionPointDraft(
                        chapter_path="1.1",
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
                                page_no=1,
                                block_no=2,
                                evidence_type="parse_block",
                                excerpt_text="textbook.pdf 第1页解析内容",
                                score_value=0.95,
                            )
                        ],
                    )
                ],
            )

        user_payload = json.loads(messages[1].content)
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

    def fake_embed_texts(self, texts: list[str]):  # noqa: ANN001
        dimension = get_settings().milvus_embedding_dim
        return [[float(index + 1)] * dimension for index, _ in enumerate(texts)]

    def fake_upsert_vectors(self, collection_name: str, records):  # noqa: ANN001
        vector_store[collection_name] = list(records)
        return {"upsert_count": len(records)}

    monkeypatch.setattr(OpenAICompatibleLlmService, "generate_structured_output", fake_generate_structured_output)
    monkeypatch.setattr(OpenAICompatibleEmbeddingService, "embed_texts", fake_embed_texts)
    monkeypatch.setattr(MilvusVectorService, "upsert_vectors", fake_upsert_vectors)
    yield vector_store


def test_generation_batch_should_create_curriculum_plan(client, generation_test_stubs) -> None:
    """创建生成批次后应自动生成课程大纲。"""
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
    assert batch_payload["tasks"][0]["task_type"] == "curriculum_generate"
    assert batch_payload["tasks"][0]["task_status"] == "success"
    assert batch_payload["tasks"][0]["result_json"]["curriculum_plan_id"] == batch_payload["curriculum_plan_id"]

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
    assert response.json()["errors"][0]["code"] == "LLM_RESULT_INVALID"

    list_response = client.get(f"/api/v1/generation-batches?project_id={project_id}", headers=headers)
    assert list_response.status_code == 200
    failed_batch = list_response.json()["data"]["items"][0]
    assert failed_batch["batch_status"] == "failure"

    detail_response = client.get(f"/api/v1/generation-batches/{failed_batch['id']}", headers=headers)
    task_payload = detail_response.json()["data"]["tasks"][0]
    assert task_payload["task_status"] == "failure"
    assert task_payload["last_error_code"] == "LLM_RESULT_INVALID"
