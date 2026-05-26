"""
@Date: 2026-05-04
@Author: xisy
@Discription: 测评接口测试
"""

import json

import pytest

from app.core.constants import (
    ASSESSMENT_GENERATE_TASK_TYPE,
    ASSESSMENT_MODULE_CODE,
    GENERATION_QUEUE_NAME,
    TASK_STATUS_PENDING,
)
from app.core.exceptions import AppException, BusinessErrorCode
from app.core.security import hash_password
from app.modules.assessment.schemas import AssessmentGenerationResult
from app.modules.assessment.tasks import run_generate_assessment_task
from app.modules.auth.models import SysUser
from app.modules.p0_models import GenerationBatch, KnowledgePoint, LessonPlan
from app.modules.task_center.repository import TaskCenterRepository
from app.shared.llm import OpenAICompatibleLlmService
from test_pipeline_curriculum_api import (
    add_extra_chapter_with_point,
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


def create_generation_batch(
    client,
    headers,
    project_id: int,
    knowledge_version_id: int,
    learner_profile_version_id: int,
    *,
    chapter_range_json: dict | None = None,
) -> dict:
    """创建完整生成批次。"""
    request_json = {
        "project_id": project_id,
        "knowledge_version_id": knowledge_version_id,
        "learner_profile_version_id": learner_profile_version_id,
        "course_count": 2,
        "session_duration_minutes": 90,
    }
    if chapter_range_json is not None:
        request_json["chapter_range_json"] = chapter_range_json
    response = client.post(
        "/api/v1/generation-batches",
        headers=headers,
        json=request_json,
    )
    assert response.status_code == 201
    return response.json()["data"]


def create_assessment_task(client, headers, curriculum_plan_id: int) -> dict:
    """创建按需测评任务。"""
    response = client.post(f"/api/v1/curriculum-plans/{curriculum_plan_id}/assessment-tasks", headers=headers, json={})
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
    assessment_task_payload = create_assessment_task(client, headers, batch_payload["curriculum_plan_id"])
    assessment_blueprint_id = assessment_task_payload["result_json"]["assessment_blueprint_id"]

    blueprint_list_response = client.get(
        f"/api/v1/assessment-blueprints?curriculum_plan_id={batch_payload['curriculum_plan_id']}&scenario_type=unit_test",
        headers=headers,
    )
    assert blueprint_list_response.status_code == 200
    blueprint_list_payload = blueprint_list_response.json()["data"]
    assert blueprint_list_payload["pagination"]["total_count"] == 1
    blueprint_id = blueprint_list_payload["items"][0]["id"]
    assert blueprint_id == assessment_blueprint_id

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

    # 验证题目考查依据字段
    first_question = paper_detail_payload["questions"][0]
    assert first_question["knowledge_point_name"] == "乘法口诀"
    basis = first_question["question_basis_json"]
    assert basis is not None
    assert basis["knowledge_point_id"] == first_question["knowledge_point_id"]
    assert basis["knowledge_point_name"] == "乘法口诀"
    assert basis["assessment_position"] in {"基础掌握题", "典型应用题", "综合提升题"}
    assert "乘法口诀" in basis["basis_summary"]
    assert basis["source"]["blueprint_type"] == "assessment"
    assert basis["source"]["blueprint_id"] == assessment_blueprint_id
    assert basis["source"]["weight_percent"] == 100
    assert basis["source"]["suggested_question_count"] == 10

    other_headers = build_other_auth_headers(client, seeded_session_factory)
    forbidden_blueprint_response = client.get(f"/api/v1/assessment-blueprints/{blueprint_id}", headers=other_headers)
    assert forbidden_blueprint_response.status_code == 404
    assert forbidden_blueprint_response.json()["errors"][0]["code"] == "ASSESSMENT_BLUEPRINT_NOT_FOUND"

    forbidden_paper_response = client.get(f"/api/v1/paper-results/{paper_id}", headers=other_headers)
    assert forbidden_paper_response.status_code == 404
    assert forbidden_paper_response.json()["errors"][0]["code"] == "PAPER_RESULT_NOT_FOUND"


def test_question_item_list_should_filter_and_protect_owner(
    client,
    seeded_session_factory,
    generation_test_stubs,
) -> None:
    """题库题目列表接口应支持多维筛选并隔离其他教师访问。"""
    _ = generation_test_stubs
    headers = build_auth_headers(client)
    project_id, knowledge_version_id, learner_profile_version_id = create_generation_baseline(client, headers)
    batch_payload = create_generation_batch(client, headers, project_id, knowledge_version_id, learner_profile_version_id)
    create_assessment_task(client, headers, batch_payload["curriculum_plan_id"])

    paper_list_response = client.get(
        f"/api/v1/paper-results?generation_batch_id={batch_payload['id']}&scene_type=unit_test",
        headers=headers,
    )
    assert paper_list_response.status_code == 200
    paper_id = paper_list_response.json()["data"]["items"][0]["id"]

    base_response = client.get("/api/v1/question-items", headers=headers)
    assert base_response.status_code == 200
    base_payload = base_response.json()["data"]
    assert base_payload["pagination"]["total_count"] == 10
    assert len(base_payload["items"]) == 10
    first_item = base_payload["items"][0]
    assert first_item["paper_title"]
    assert first_item["scene_type"] == "unit_test"
    assert first_item["paper_result_id"] == paper_id
    assert first_item["generation_batch_id"] == batch_payload["id"]
    knowledge_point_id = first_item["knowledge_point_id"]
    # 列表项也应携带考查依据
    assert first_item["knowledge_point_name"] == "乘法口诀"
    assert first_item["question_basis_json"]["source"]["blueprint_type"] == "assessment"

    batch_response = client.get(
        f"/api/v1/question-items?generation_batch_id={batch_payload['id']}",
        headers=headers,
    )
    assert batch_response.status_code == 200
    assert batch_response.json()["data"]["pagination"]["total_count"] == 10

    typed_response = client.get(
        f"/api/v1/question-items?paper_result_id={paper_id}&question_type=single_choice&scene_type=unit_test",
        headers=headers,
    )
    assert typed_response.status_code == 200
    typed_payload = typed_response.json()["data"]
    assert typed_payload["pagination"]["total_count"] >= 1
    for item in typed_payload["items"]:
        assert item["question_type"] == "single_choice"
        assert item["scene_type"] == "unit_test"
        assert item["paper_result_id"] == paper_id

    paged_response = client.get(
        "/api/v1/question-items?page=1&page_size=3",
        headers=headers,
    )
    assert paged_response.status_code == 200
    paged_payload = paged_response.json()["data"]
    assert paged_payload["pagination"]["page_size"] == 3
    assert paged_payload["pagination"]["total_count"] == 10
    assert paged_payload["pagination"]["total_pages"] == 4
    assert len(paged_payload["items"]) == 3

    knowledge_response = client.get(
        f"/api/v1/question-items?knowledge_point_id={knowledge_point_id}",
        headers=headers,
    )
    assert knowledge_response.status_code == 200
    for item in knowledge_response.json()["data"]["items"]:
        assert item["knowledge_point_id"] == knowledge_point_id

    invalid_batch_response = client.get(
        "/api/v1/question-items?generation_batch_id=999999",
        headers=headers,
    )
    assert invalid_batch_response.status_code == 404
    assert invalid_batch_response.json()["errors"][0]["code"] == "GENERATION_BATCH_NOT_FOUND"

    invalid_paper_response = client.get(
        "/api/v1/question-items?paper_result_id=999999",
        headers=headers,
    )
    assert invalid_paper_response.status_code == 404
    assert invalid_paper_response.json()["errors"][0]["code"] == "PAPER_RESULT_NOT_FOUND"

    other_headers = build_other_auth_headers(client, seeded_session_factory)
    isolated_response = client.get("/api/v1/question-items", headers=other_headers)
    assert isolated_response.status_code == 200
    assert isolated_response.json()["data"]["pagination"]["total_count"] == 0

    forbidden_paper_response = client.get(
        f"/api/v1/question-items?paper_result_id={paper_id}",
        headers=other_headers,
    )
    assert forbidden_paper_response.status_code == 404
    assert forbidden_paper_response.json()["errors"][0]["code"] == "PAPER_RESULT_NOT_FOUND"


def test_question_item_list_should_reject_invalid_query_params(client) -> None:
    """题库题目列表接口应对非法查询参数返回 422。"""
    headers = build_auth_headers(client)

    invalid_question_type_response = client.get(
        "/api/v1/question-items?question_type=multi_choice",
        headers=headers,
    )
    assert invalid_question_type_response.status_code == 422

    invalid_scene_type_response = client.get(
        "/api/v1/question-items?scene_type=mock_exam",
        headers=headers,
    )
    assert invalid_scene_type_response.status_code == 422

    for param in ("generation_batch_id", "paper_result_id", "knowledge_point_id"):
        zero_response = client.get(f"/api/v1/question-items?{param}=0", headers=headers)
        assert zero_response.status_code == 422, f"{param}=0 应返回 422"
        negative_response = client.get(f"/api/v1/question-items?{param}=-1", headers=headers)
        assert negative_response.status_code == 422, f"{param}=-1 应返回 422"

    low_difficulty_response = client.get(
        "/api/v1/question-items?difficulty_level=0",
        headers=headers,
    )
    assert low_difficulty_response.status_code == 422

    high_difficulty_response = client.get(
        "/api/v1/question-items?difficulty_level=6",
        headers=headers,
    )
    assert high_difficulty_response.status_code == 422

    invalid_page_response = client.get("/api/v1/question-items?page=0", headers=headers)
    assert invalid_page_response.status_code == 422

    oversized_page_size_response = client.get(
        "/api/v1/question-items?page_size=101",
        headers=headers,
    )
    assert oversized_page_size_response.status_code == 422


def test_assessment_prompt_should_apply_scene_preset(
    client,
    generation_test_stubs,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """仅传 scene_type 时测评提示词与策略应自动套用场景预设（unit_test 走批次级）。"""
    _ = generation_test_stubs
    captured_system_prompts: list[str] = []
    captured_user_payloads: list[dict] = []
    original_generate = OpenAICompatibleLlmService.generate_structured_output

    def capture_generate(self, *, messages, response_model, temperature=0.2, **_extra_kwargs):  # noqa: ANN001
        if response_model is AssessmentGenerationResult:
            captured_system_prompts.append(messages[0].content)
            captured_user_payloads.append(json.loads(messages[1].content))
        return original_generate(self, messages=messages, response_model=response_model, temperature=temperature, **_extra_kwargs)

    monkeypatch.setattr(OpenAICompatibleLlmService, "generate_structured_output", capture_generate)
    headers = build_auth_headers(client)
    project_id, knowledge_version_id, learner_profile_version_id = create_generation_baseline(client, headers)
    batch_payload = create_generation_batch(client, headers, project_id, knowledge_version_id, learner_profile_version_id)

    response = client.post(
        f"/api/v1/curriculum-plans/{batch_payload['curriculum_plan_id']}/assessment-tasks",
        headers=headers,
        json={"scene_type": "unit_test"},
    )

    assert response.status_code == 201
    assert "scene_type=unit_test" in captured_system_prompts[0]
    assert "本次为单元测试" in captured_system_prompts[0]
    strategy_payload = captured_user_payloads[0]["assessment_strategy"]
    assert strategy_payload["scene_type"] == "unit_test"
    assert strategy_payload["question_count"] == 10
    assert strategy_payload["difficulty_range"] == [2, 4]
    paper_id = response.json()["data"]["result_json"]["paper_result_id"]
    paper_detail_response = client.get(f"/api/v1/paper-results/{paper_id}", headers=headers)
    paper_detail_payload = paper_detail_response.json()["data"]
    assert paper_detail_payload["scene_type"] == "unit_test"
    assert paper_detail_payload["question_count"] == 10
    assert paper_detail_payload["paper_json"]["scene_label"] == "单元测试"


def test_assessment_should_reject_homework_scene(
    client,
    generation_test_stubs,
) -> None:
    """批次级测评入口应拒绝 scene_type=homework，引导到课次级作业接口。"""
    _ = generation_test_stubs
    headers = build_auth_headers(client)
    project_id, knowledge_version_id, learner_profile_version_id = create_generation_baseline(client, headers)
    batch_payload = create_generation_batch(client, headers, project_id, knowledge_version_id, learner_profile_version_id)

    response = client.post(
        f"/api/v1/curriculum-plans/{batch_payload['curriculum_plan_id']}/assessment-tasks",
        headers=headers,
        json={"scene_type": "homework"},
    )
    assert response.status_code == 422
    error_codes = {error["code"] for error in response.json()["errors"]}
    assert error_codes == {BusinessErrorCode.ASSESSMENT_SCENE_INVALID.value}


def test_assessment_should_recalculate_inconsistent_distribution(
    client,
    generation_test_stubs,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """测评题目明细可信但分布统计漂移时应以后端重算结果落库。"""
    _ = generation_test_stubs
    headers = build_auth_headers(client)
    project_id, knowledge_version_id, learner_profile_version_id = create_generation_baseline(client, headers)
    batch_payload = create_generation_batch(client, headers, project_id, knowledge_version_id, learner_profile_version_id)
    original_generate = OpenAICompatibleLlmService.generate_structured_output

    def mixed_generate(self, *, messages, response_model, temperature=0.2, **_extra_kwargs):  # noqa: ANN001
        _ = _extra_kwargs
        if response_model is AssessmentGenerationResult:
            user_payload = json.loads(messages[1].content)
            point_id = int(user_payload["knowledge_points"][0]["id"])
            question_types = ["single_choice", "fill_blank", "short_answer"]
            questions = []
            for question_no in range(1, 11):
                question_type = question_types[(question_no - 1) % len(question_types)]
                difficulty_level = 3
                questions.append(
                    {
                        "question_no": question_no,
                        "knowledge_point_id": point_id,
                        "question_type": question_type,
                        "difficulty_level": difficulty_level,
                        "score_value": 10,
                        "stem_text": f"第{question_no}题：围绕乘法口诀完成练习。",
                        "options_json": {"A": "2", "B": "4"} if question_type == "single_choice" else None,
                        "answer_text": "参考答案",
                        "analysis_text": "考查乘法口诀。",
                        "source_trace_json": {"knowledge_point_ids": [point_id]},
                    }
                )
            return AssessmentGenerationResult(
                blueprint_name="统计漂移测评蓝图",
                paper_title="统计漂移测评",
                strategy_summary={"scene_type": "unit_test", "question_count": 10},
                knowledge_weights=[
                    {
                        "knowledge_point_id": point_id,
                        "weight_percent": 100,
                        "suggested_question_count": 10,
                        "question_types": question_types,
                        "difficulty_range": [1, 5],
                    }
                ],
                question_type_distribution={"single_choice": 10},
                difficulty_distribution={"1": 10},
                questions=questions,
            )
        return original_generate(self, messages=messages, response_model=response_model, temperature=temperature)

    monkeypatch.setattr(OpenAICompatibleLlmService, "generate_structured_output", mixed_generate)
    response = client.post(
        f"/api/v1/curriculum-plans/{batch_payload['curriculum_plan_id']}/assessment-tasks",
        headers=headers,
        json={},
    )

    assert response.status_code == 201
    task_payload = response.json()["data"]
    result_json = task_payload["result_json"]
    expected_question_type_distribution = {"single_choice": 4, "fill_blank": 3, "short_answer": 3}
    expected_difficulty_distribution = {"3": 10}

    blueprint_response = client.get(
        f"/api/v1/assessment-blueprints/{result_json['assessment_blueprint_id']}",
        headers=headers,
    )
    assert blueprint_response.status_code == 200
    blueprint_content = blueprint_response.json()["data"]["content_json"]
    assert blueprint_content["question_type_distribution"] == expected_question_type_distribution
    assert blueprint_content["difficulty_distribution"] == expected_difficulty_distribution

    paper_response = client.get(f"/api/v1/paper-results/{result_json['paper_result_id']}", headers=headers)
    assert paper_response.status_code == 200
    paper_json = paper_response.json()["data"]["paper_json"]
    assert paper_json["question_type_distribution"] == expected_question_type_distribution
    assert paper_json["difficulty_distribution"] == expected_difficulty_distribution


def test_assessment_should_truncate_excess_questions_to_strategy(
    client,
    generation_test_stubs,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LLM 多返回题目时应按题号截断到策略题量并成功落库。"""
    _ = generation_test_stubs
    headers = build_auth_headers(client)
    project_id, knowledge_version_id, learner_profile_version_id = create_generation_baseline(client, headers)
    batch_payload = create_generation_batch(client, headers, project_id, knowledge_version_id, learner_profile_version_id)
    original_generate = OpenAICompatibleLlmService.generate_structured_output

    def overflow_generate(self, *, messages, response_model, temperature=0.2):  # noqa: ANN001
        if response_model is AssessmentGenerationResult:
            user_payload = json.loads(messages[1].content)
            point_id = int(user_payload["knowledge_points"][0]["id"])
            question_types = ["single_choice", "fill_blank", "short_answer"]
            questions = []
            for question_no in range(1, 14):
                question_type = question_types[(question_no - 1) % len(question_types)]
                questions.append(
                    {
                        "question_no": question_no,
                        "knowledge_point_id": point_id,
                        "question_type": question_type,
                        "difficulty_level": 3,
                        "score_value": 10,
                        "stem_text": f"第{question_no}题：围绕乘法口诀完成练习。",
                        "options_json": {"A": "2", "B": "4"} if question_type == "single_choice" else None,
                        "answer_text": "参考答案",
                        "analysis_text": "考查乘法口诀。",
                        "source_trace_json": {"knowledge_point_ids": [point_id]},
                    }
                )
            return AssessmentGenerationResult(
                blueprint_name="多返回测评蓝图",
                paper_title="多返回测评",
                strategy_summary={"scene_type": "unit_test", "question_count": 10},
                knowledge_weights=[
                    {
                        "knowledge_point_id": point_id,
                        "weight_percent": 100,
                        "suggested_question_count": 13,
                        "question_types": question_types,
                        "difficulty_range": [1, 5],
                    }
                ],
                question_type_distribution={"single_choice": 5, "fill_blank": 4, "short_answer": 4},
                difficulty_distribution={"3": 13},
                questions=questions,
            )
        return original_generate(self, messages=messages, response_model=response_model, temperature=temperature)

    monkeypatch.setattr(OpenAICompatibleLlmService, "generate_structured_output", overflow_generate)
    response = client.post(
        f"/api/v1/curriculum-plans/{batch_payload['curriculum_plan_id']}/assessment-tasks",
        headers=headers,
        json={},
    )

    assert response.status_code == 201
    result_json = response.json()["data"]["result_json"]
    assert result_json["question_count"] == 10

    paper_response = client.get(f"/api/v1/paper-results/{result_json['paper_result_id']}", headers=headers)
    assert paper_response.status_code == 200
    paper_data = paper_response.json()["data"]
    assert paper_data["question_count"] == 10
    assert len(paper_data["questions"]) == 10
    assert [item["question_no"] for item in paper_data["questions"]] == list(range(1, 11))
    assert paper_data["paper_json"]["question_type_distribution"] == {
        "single_choice": 4,
        "fill_blank": 3,
        "short_answer": 3,
    }


def test_generation_batch_should_mark_failure_when_assessment_has_invalid_knowledge_ref(
    client,
    seeded_session_factory,
    generation_test_stubs,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """按需测评引用章节范围外知识点时不应把基础批次改成失败。"""
    _ = generation_test_stubs
    headers = build_auth_headers(client)
    project_id, knowledge_version_id, learner_profile_version_id = create_generation_baseline(client, headers)
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
    batch_payload = create_generation_batch(
        client,
        headers,
        project_id,
        knowledge_version_id,
        learner_profile_version_id,
        chapter_range_json={"chapter_node_ids": [scoped_chapter_id]},
    )
    original_generate = OpenAICompatibleLlmService.generate_structured_output

    def mixed_generate(self, *, messages, response_model, temperature=0.2, **_extra_kwargs):  # noqa: ANN001
        _ = _extra_kwargs
        if response_model is AssessmentGenerationResult:
            return AssessmentGenerationResult(
                blueprint_name="非法测评蓝图",
                paper_title="非法单元测试",
                strategy_summary={"scene_type": "unit_test", "question_count": 10},
                knowledge_weights=[
                    {
                        "knowledge_point_id": outside_point_id,
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
                        "knowledge_point_id": outside_point_id,
                        "question_type": "single_choice" if question_no <= 4 else "fill_blank" if question_no <= 7 else "short_answer",
                        "difficulty_level": 3,
                        "score_value": 10,
                        "stem_text": f"第{question_no}题：非法知识点引用。",
                        "options_json": {"A": "1", "B": "2"} if question_no <= 4 else None,
                        "answer_text": "参考答案",
                        "analysis_text": "用于验证非法知识点引用。",
                        "source_trace_json": {"knowledge_point_ids": [outside_point_id]},
                    }
                    for question_no in range(1, 11)
                ],
            )
        return original_generate(self, messages=messages, response_model=response_model, temperature=temperature)

    monkeypatch.setattr(OpenAICompatibleLlmService, "generate_structured_output", mixed_generate)
    response = client.post(
        f"/api/v1/curriculum-plans/{batch_payload['curriculum_plan_id']}/assessment-tasks",
        headers=headers,
        json={},
    )

    assert response.status_code == 503
    assert response.json()["errors"][0]["code"] == BusinessErrorCode.LLM_RESULT_INVALID.value

    list_response = client.get(f"/api/v1/generation-batches?project_id={project_id}", headers=headers)
    assert list_response.status_code == 200
    succeeded_batch = list_response.json()["data"]["items"][0]
    assert succeeded_batch["batch_status"] == "success"
    assert succeeded_batch["curriculum_plan_id"] is not None
    assert succeeded_batch["lesson_plan_id"] is not None

    detail_response = client.get(f"/api/v1/generation-batches/{succeeded_batch['id']}", headers=headers)
    tasks = detail_response.json()["data"]["tasks"]
    assert [task["task_type"] for task in tasks] == [
        "curriculum_generate",
        "lesson_plan_generate",
        "coverage_analyze",
        "assessment_generate",
    ]
    assert tasks[0]["task_status"] == "success"
    assert tasks[1]["task_status"] == "success"
    assert tasks[2]["task_status"] == "success"
    assert tasks[3]["task_status"] == "failure"
    assert tasks[3]["last_error_code"] == BusinessErrorCode.LLM_RESULT_INVALID.value


def test_assessment_should_require_existing_lesson_plan(
    client,
    seeded_session_factory,
    generation_test_stubs,
) -> None:
    """按需测评在服务层和任务层都应要求批次已有教案。"""
    _ = generation_test_stubs
    headers = build_auth_headers(client)
    project_id, knowledge_version_id, learner_profile_version_id = create_generation_baseline(client, headers)
    batch_payload = create_generation_batch(client, headers, project_id, knowledge_version_id, learner_profile_version_id)

    session = seeded_session_factory()
    try:
        batch = session.query(GenerationBatch).filter(GenerationBatch.id == batch_payload["id"]).one()
        batch.lesson_plan_id = None
        for lesson_plan in session.query(LessonPlan).filter(LessonPlan.generation_batch_id == batch.id).all():
            session.delete(lesson_plan)
        session.commit()
    finally:
        session.close()

    response = client.post(
        f"/api/v1/curriculum-plans/{batch_payload['curriculum_plan_id']}/assessment-tasks",
        headers=headers,
        json={},
    )
    assert response.status_code == 422
    assert response.json()["errors"][0]["code"] == BusinessErrorCode.GENERATION_BASELINE_INVALID.value

    session = seeded_session_factory()
    try:
        task_repository = TaskCenterRepository(session)
        task = task_repository.create_task(
            project_id=project_id,
            generation_batch_id=batch_payload["id"],
            module_code=ASSESSMENT_MODULE_CODE,
            task_type=ASSESSMENT_GENERATE_TASK_TYPE,
            task_status=TASK_STATUS_PENDING,
            queue_name=GENERATION_QUEUE_NAME,
            biz_key=f"generation_batch:{batch_payload['id']}:assessment:unit_test",
            operator_user_id=None,
            payload_json={
                "generation_batch_id": batch_payload["id"],
                "curriculum_plan_id": batch_payload["curriculum_plan_id"],
                "scene_type": "unit_test",
            },
            request_id=None,
        )
        for step_order, (step_code, step_name) in enumerate(
            [
                ("prepare_assessment_baseline", "准备测评生成基线"),
                ("invoke_llm_assessment", "调用 LLM 生成测评"),
                ("persist_assessment_result", "落库测评蓝图与试卷"),
                ("finalize_assessment_task", "完成测评任务"),
            ],
            start=1,
        ):
            task_repository.create_task_step(
                task_record_id=task.id,
                step_code=step_code,
                step_name=step_name,
                step_order=step_order,
                step_status=TASK_STATUS_PENDING,
            )
        database_url = session.get_bind().url.render_as_string(hide_password=False)
        session.commit()
        task_id = task.id
    finally:
        session.close()

    with pytest.raises(AppException) as exc_info:
        run_generate_assessment_task(
            {
                "task_record_id": task_id,
                "generation_batch_id": batch_payload["id"],
                "curriculum_plan_id": batch_payload["curriculum_plan_id"],
                "scene_type": "unit_test",
                "operator_user_id": None,
                "database_url": database_url,
            }
        )
    assert exc_info.value.code == BusinessErrorCode.GENERATION_BASELINE_INVALID

    session = seeded_session_factory()
    try:
        failed_task = TaskCenterRepository(session).get_task_by_id(task_id)
        assert failed_task.task_status == "failure"
        assert failed_task.last_error_code == BusinessErrorCode.GENERATION_BASELINE_INVALID.value
    finally:
        session.close()


def test_assessment_final_exam_scene_should_generate_twenty_questions(
    client,
    generation_test_stubs,
) -> None:
    """final_exam 场景应自动套用 20 题预设。"""
    _ = generation_test_stubs
    headers = build_auth_headers(client)
    project_id, knowledge_version_id, learner_profile_version_id = create_generation_baseline(client, headers)
    batch_payload = create_generation_batch(client, headers, project_id, knowledge_version_id, learner_profile_version_id)

    response = client.post(
        f"/api/v1/curriculum-plans/{batch_payload['curriculum_plan_id']}/assessment-tasks",
        headers=headers,
        json={"scene_type": "final_exam"},
    )
    assert response.status_code == 201
    result_json = response.json()["data"]["result_json"]
    assert result_json["question_count"] == 20

    paper_response = client.get(f"/api/v1/paper-results/{result_json['paper_result_id']}", headers=headers)
    assert paper_response.status_code == 200
    paper_payload = paper_response.json()["data"]
    assert paper_payload["scene_type"] == "final_exam"
    assert paper_payload["question_count"] == 20
    assert len(paper_payload["questions"]) == 20
    difficulty_levels = {question["difficulty_level"] for question in paper_payload["questions"]}
    assert difficulty_levels <= {2, 3, 4, 5}


def test_assessment_should_support_multiple_scenes_in_one_batch(
    client,
    generation_test_stubs,
) -> None:
    """同一批次下 unit_test 与 final_exam 应能并存生成，同一场景不可重复生成（homework 已迁至课次级）。"""
    _ = generation_test_stubs
    headers = build_auth_headers(client)
    project_id, knowledge_version_id, learner_profile_version_id = create_generation_baseline(client, headers)
    batch_payload = create_generation_batch(client, headers, project_id, knowledge_version_id, learner_profile_version_id)
    curriculum_plan_id = batch_payload["curriculum_plan_id"]
    generation_batch_id = batch_payload["id"]

    expected_counts = {"unit_test": 10, "final_exam": 20}
    for scene_type, expected_count in expected_counts.items():
        scene_response = client.post(
            f"/api/v1/curriculum-plans/{curriculum_plan_id}/assessment-tasks",
            headers=headers,
            json={"scene_type": scene_type},
        )
        assert scene_response.status_code == 201
        assert scene_response.json()["data"]["result_json"]["question_count"] == expected_count

    all_papers_response = client.get(
        f"/api/v1/paper-results?generation_batch_id={generation_batch_id}",
        headers=headers,
    )
    assert all_papers_response.status_code == 200
    assert all_papers_response.json()["data"]["pagination"]["total_count"] == 2

    for scene_type, expected_count in expected_counts.items():
        scene_papers_response = client.get(
            f"/api/v1/paper-results?generation_batch_id={generation_batch_id}&scene_type={scene_type}",
            headers=headers,
        )
        assert scene_papers_response.status_code == 200
        scene_papers_payload = scene_papers_response.json()["data"]
        assert scene_papers_payload["pagination"]["total_count"] == 1
        assert scene_papers_payload["items"][0]["scene_type"] == scene_type
        assert scene_papers_payload["items"][0]["question_count"] == expected_count

    duplicate_response = client.post(
        f"/api/v1/curriculum-plans/{curriculum_plan_id}/assessment-tasks",
        headers=headers,
        json={"scene_type": "unit_test"},
    )
    assert duplicate_response.status_code == 409
    assert duplicate_response.json()["errors"][0]["code"] == "TASK_CONFLICT"


def test_assessment_should_reject_invalid_scene_type(
    client,
    generation_test_stubs,
) -> None:
    """非法 scene_type 应被请求校验拒绝。"""
    _ = generation_test_stubs
    headers = build_auth_headers(client)
    project_id, knowledge_version_id, learner_profile_version_id = create_generation_baseline(client, headers)
    batch_payload = create_generation_batch(client, headers, project_id, knowledge_version_id, learner_profile_version_id)

    response = client.post(
        f"/api/v1/curriculum-plans/{batch_payload['curriculum_plan_id']}/assessment-tasks",
        headers=headers,
        json={"scene_type": "midterm"},
    )
    assert response.status_code == 422
