"""
@Date: 2026-04-29
@Author: xisy
@Discription: 测评接口测试
"""

import pytest

from app.core.exceptions import BusinessErrorCode
from app.core.security import hash_password
from app.modules.assessment.schemas import AssessmentGenerationResult
from app.modules.auth.models import SysUser
from app.shared.llm import OpenAICompatibleLlmService
from test_pipeline_curriculum_api import (
    build_auth_headers,
    create_knowledge_version,
    create_learner_profile_version,
    create_project,
    generation_test_stubs,
)

TEST_PASSWORD = "Teacher@123"


def build_other_auth_headers(client, seeded_session_factory) -> dict[str, str]:
    """创建其他教师并构造认证请求头。"""
    session = seeded_session_factory()
    try:
        session.add(
            SysUser(
                username="teacher_other",
                display_name="其他教师",
                password_hash=hash_password(TEST_PASSWORD),
                role_code="teacher",
                status="active",
            )
        )
        session.commit()
    finally:
        session.close()

    login_response = client.post(
        "/api/v1/auth/login",
        json={"username": "teacher_other", "password": TEST_PASSWORD},
    )
    access_token = login_response.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {access_token}"}


def create_generation_batch(client, headers, project_id: int, knowledge_version_id: int, learner_profile_version_id: int) -> dict:
    """创建完整生成批次。"""
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
    return response.json()["data"]


def create_generation_baseline(client, headers) -> tuple[int, int, int]:
    """创建生成所需的项目、知识版本和学情版本。"""
    project_id = create_project(client, headers)
    knowledge_version_id = create_knowledge_version(client, headers, project_id)
    learner_profile_version_id = create_learner_profile_version(client, headers, project_id)
    return project_id, knowledge_version_id, learner_profile_version_id


def test_assessment_apis_should_query_results_and_protect_owner(
    client,
    seeded_session_factory,
    generation_test_stubs,
) -> None:
    """测评接口应支持查询结果并隔离其他教师访问。"""
    _ = generation_test_stubs
    headers = build_auth_headers(client)
    project_id, knowledge_version_id, learner_profile_version_id = create_generation_baseline(client, headers)
    batch_payload = create_generation_batch(client, headers, project_id, knowledge_version_id, learner_profile_version_id)

    blueprint_list_response = client.get(
        f"/api/v1/assessment-blueprints?curriculum_plan_id={batch_payload['curriculum_plan_id']}&scenario_type=unit_test",
        headers=headers,
    )
    assert blueprint_list_response.status_code == 200
    blueprint_list_payload = blueprint_list_response.json()["data"]
    assert blueprint_list_payload["pagination"]["total_count"] == 1
    blueprint_id = blueprint_list_payload["items"][0]["id"]
    assert blueprint_id == batch_payload["assessment_blueprint_id"]

    blueprint_detail_response = client.get(f"/api/v1/assessment-blueprints/{blueprint_id}", headers=headers)
    assert blueprint_detail_response.status_code == 200
    assert blueprint_detail_response.json()["data"]["content_json"]["knowledge_weights"][0]["suggested_question_count"] == 10

    paper_list_response = client.get(
        f"/api/v1/paper-results?generation_batch_id={batch_payload['id']}&scene_type=unit_test",
        headers=headers,
    )
    assert paper_list_response.status_code == 200
    paper_list_payload = paper_list_response.json()["data"]
    assert paper_list_payload["pagination"]["total_count"] == 1
    paper_id = paper_list_payload["items"][0]["id"]

    paper_detail_response = client.get(f"/api/v1/paper-results/{paper_id}", headers=headers)
    assert paper_detail_response.status_code == 200
    paper_detail_payload = paper_detail_response.json()["data"]
    assert paper_detail_payload["scene_type"] == "unit_test"
    assert len(paper_detail_payload["questions"]) == 10
    assert paper_detail_payload["questions"][0]["question_no"] == 1

    other_headers = build_other_auth_headers(client, seeded_session_factory)
    forbidden_blueprint_response = client.get(f"/api/v1/assessment-blueprints/{blueprint_id}", headers=other_headers)
    assert forbidden_blueprint_response.status_code == 404
    assert forbidden_blueprint_response.json()["errors"][0]["code"] == "ASSESSMENT_BLUEPRINT_NOT_FOUND"

    forbidden_paper_response = client.get(f"/api/v1/paper-results/{paper_id}", headers=other_headers)
    assert forbidden_paper_response.status_code == 404
    assert forbidden_paper_response.json()["errors"][0]["code"] == "PAPER_RESULT_NOT_FOUND"


def test_generation_batch_should_mark_failure_when_assessment_has_invalid_knowledge_ref(
    client,
    generation_test_stubs,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """测评引用不存在的知识点时应写入失败批次与失败任务。"""
    _ = generation_test_stubs
    headers = build_auth_headers(client)
    project_id, knowledge_version_id, learner_profile_version_id = create_generation_baseline(client, headers)
    original_generate = OpenAICompatibleLlmService.generate_structured_output

    def mixed_generate(self, *, messages, response_model, temperature=0.2):  # noqa: ANN001
        if response_model is AssessmentGenerationResult:
            return AssessmentGenerationResult(
                blueprint_name="非法测评蓝图",
                paper_title="非法单元测试",
                strategy_summary={"scene_type": "unit_test", "question_count": 10},
                knowledge_weights=[
                    {
                        "knowledge_point_id": 999999,
                        "weight_percent": 100,
                        "suggested_question_count": 10,
                        "question_types": ["single_choice", "fill_blank", "short_answer"],
                        "difficulty_range": [1, 5],
                    }
                ],
                question_type_distribution={"single_choice": 4, "fill_blank": 3, "short_answer": 3},
                difficulty_distribution={"3": 10},
                questions=[
                    {
                        "question_no": question_no,
                        "knowledge_point_id": 999999,
                        "question_type": "single_choice" if question_no <= 4 else "fill_blank" if question_no <= 7 else "short_answer",
                        "difficulty_level": 3,
                        "score_value": 10,
                        "stem_text": f"第{question_no}题：非法知识点引用。",
                        "options_json": {"A": "1", "B": "2"} if question_no <= 4 else None,
                        "answer_text": "参考答案",
                        "analysis_text": "用于验证非法知识点引用。",
                        "source_trace_json": {"knowledge_point_ids": [999999]},
                    }
                    for question_no in range(1, 11)
                ],
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
    assert failed_batch["curriculum_plan_id"] is not None
    assert failed_batch["lesson_plan_id"] is not None
    assert failed_batch["assessment_blueprint_id"] is None

    detail_response = client.get(f"/api/v1/generation-batches/{failed_batch['id']}", headers=headers)
    tasks = detail_response.json()["data"]["tasks"]
    assert [task["task_type"] for task in tasks] == [
        "curriculum_generate",
        "lesson_plan_generate",
        "assessment_generate",
    ]
    assert tasks[0]["task_status"] == "success"
    assert tasks[1]["task_status"] == "success"
    assert tasks[2]["task_status"] == "failure"
    assert tasks[2]["last_error_code"] == BusinessErrorCode.LLM_RESULT_INVALID.value
