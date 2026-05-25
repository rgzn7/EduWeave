"""
@Date: 2026-05-25
@Author: xisy
@Discription: 课后作业接口测试
"""

import pytest

from app.core.exceptions import BusinessErrorCode
from app.modules.p0_models import HomeworkResult
from test_assessment_api import build_other_auth_headers, create_generation_baseline, create_generation_batch
from test_pipeline_curriculum_api import build_auth_headers, generation_test_stubs


def _list_lesson_plans(client, headers, curriculum_plan_id: int) -> list[dict]:
    """列出当前教师可见的教案。"""
    response = client.get(
        f"/api/v1/lesson-plans?curriculum_plan_id={curriculum_plan_id}&page_size=100",
        headers=headers,
    )
    assert response.status_code == 200
    return response.json()["data"]["items"]


def test_homework_task_create_should_produce_per_lesson_result(
    client,
    generation_test_stubs,
) -> None:
    """按教案创建课后作业任务应产出一份蓝图、一份作业和 6 道题，再次创建返回 409。"""
    _ = generation_test_stubs
    headers = build_auth_headers(client)
    project_id, knowledge_version_id, learner_profile_version_id = create_generation_baseline(client, headers)
    batch_payload = create_generation_batch(client, headers, project_id, knowledge_version_id, learner_profile_version_id)

    lesson_plans = _list_lesson_plans(client, headers, batch_payload["curriculum_plan_id"])
    assert len(lesson_plans) >= 1
    lesson_plan = lesson_plans[0]

    create_response = client.post(
        f"/api/v1/lesson-plans/{lesson_plan['id']}/homework-tasks",
        headers=headers,
    )
    assert create_response.status_code == 201
    result_json = create_response.json()["data"]["result_json"]
    assert result_json["question_count"] == 6
    assert result_json["lesson_plan_id"] == lesson_plan["id"]

    detail_response = client.get(
        f"/api/v1/lesson-plans/{lesson_plan['id']}/homework-result",
        headers=headers,
    )
    assert detail_response.status_code == 200
    detail_payload = detail_response.json()["data"]
    assert detail_payload["lesson_plan_id"] == lesson_plan["id"]
    assert detail_payload["question_count"] == 6
    assert len(detail_payload["questions"]) == 6
    assert detail_payload["content_json"]["scene_type"] == "homework"
    assert detail_payload["content_json"]["scene_label"] == "课后作业"
    assert detail_payload["class_session_no"] == lesson_plan["class_session_no"]

    duplicate_response = client.post(
        f"/api/v1/lesson-plans/{lesson_plan['id']}/homework-tasks",
        headers=headers,
    )
    assert duplicate_response.status_code == 409
    assert duplicate_response.json()["errors"][0]["code"] == BusinessErrorCode.TASK_CONFLICT.value


def test_homework_results_list_should_filter_by_curriculum_and_batch(
    client,
    generation_test_stubs,
) -> None:
    """作业列表接口应支持按课程大纲或生成批次筛选。"""
    _ = generation_test_stubs
    headers = build_auth_headers(client)
    project_id, knowledge_version_id, learner_profile_version_id = create_generation_baseline(client, headers)
    batch_payload = create_generation_batch(client, headers, project_id, knowledge_version_id, learner_profile_version_id)
    lesson_plans = _list_lesson_plans(client, headers, batch_payload["curriculum_plan_id"])

    for lesson_plan in lesson_plans:
        response = client.post(
            f"/api/v1/lesson-plans/{lesson_plan['id']}/homework-tasks",
            headers=headers,
        )
        assert response.status_code == 201

    curriculum_response = client.get(
        f"/api/v1/homework-results?curriculum_plan_id={batch_payload['curriculum_plan_id']}",
        headers=headers,
    )
    assert curriculum_response.status_code == 200
    curriculum_payload = curriculum_response.json()["data"]
    assert curriculum_payload["pagination"]["total_count"] == len(lesson_plans)
    session_nos = [item["class_session_no"] for item in curriculum_payload["items"]]
    assert session_nos == sorted(session_nos)

    batch_response = client.get(
        f"/api/v1/homework-results?generation_batch_id={batch_payload['id']}",
        headers=headers,
    )
    assert batch_response.status_code == 200
    assert batch_response.json()["data"]["pagination"]["total_count"] == len(lesson_plans)


def test_homework_questions_list_should_filter_by_lesson_plan(
    client,
    generation_test_stubs,
) -> None:
    """作业题目列表接口应支持按教案筛选与分页。"""
    _ = generation_test_stubs
    headers = build_auth_headers(client)
    project_id, knowledge_version_id, learner_profile_version_id = create_generation_baseline(client, headers)
    batch_payload = create_generation_batch(client, headers, project_id, knowledge_version_id, learner_profile_version_id)
    lesson_plans = _list_lesson_plans(client, headers, batch_payload["curriculum_plan_id"])
    lesson_plan = lesson_plans[0]

    create_response = client.post(
        f"/api/v1/lesson-plans/{lesson_plan['id']}/homework-tasks",
        headers=headers,
    )
    assert create_response.status_code == 201
    homework_result_id = create_response.json()["data"]["result_json"]["homework_result_id"]

    by_lesson_response = client.get(
        f"/api/v1/homework-questions?lesson_plan_id={lesson_plan['id']}",
        headers=headers,
    )
    assert by_lesson_response.status_code == 200
    by_lesson_payload = by_lesson_response.json()["data"]
    assert by_lesson_payload["pagination"]["total_count"] == 6
    first_item = by_lesson_payload["items"][0]
    assert first_item["lesson_plan_id"] == lesson_plan["id"]
    assert first_item["homework_result_id"] == homework_result_id
    assert first_item["homework_title"]

    by_result_response = client.get(
        f"/api/v1/homework-questions?homework_result_id={homework_result_id}",
        headers=headers,
    )
    assert by_result_response.status_code == 200
    assert by_result_response.json()["data"]["pagination"]["total_count"] == 6


def test_homework_result_should_protect_other_owner(
    client,
    seeded_session_factory,
    generation_test_stubs,
) -> None:
    """其他教师不应能查询、导出或重复生成本人之外的课后作业。"""
    _ = generation_test_stubs
    headers = build_auth_headers(client)
    project_id, knowledge_version_id, learner_profile_version_id = create_generation_baseline(client, headers)
    batch_payload = create_generation_batch(client, headers, project_id, knowledge_version_id, learner_profile_version_id)
    lesson_plans = _list_lesson_plans(client, headers, batch_payload["curriculum_plan_id"])
    lesson_plan = lesson_plans[0]

    create_response = client.post(
        f"/api/v1/lesson-plans/{lesson_plan['id']}/homework-tasks",
        headers=headers,
    )
    assert create_response.status_code == 201
    result_json = create_response.json()["data"]["result_json"]
    homework_result_id = result_json["homework_result_id"]
    homework_blueprint_id = result_json["homework_blueprint_id"]

    other_headers = build_other_auth_headers(client, seeded_session_factory)
    forbidden_result_response = client.get(
        f"/api/v1/homework-results/{homework_result_id}",
        headers=other_headers,
    )
    assert forbidden_result_response.status_code == 404
    assert forbidden_result_response.json()["errors"][0]["code"] == BusinessErrorCode.HOMEWORK_RESULT_NOT_FOUND.value

    forbidden_blueprint_response = client.get(
        f"/api/v1/homework-blueprints/{homework_blueprint_id}",
        headers=other_headers,
    )
    assert forbidden_blueprint_response.status_code == 404
    assert forbidden_blueprint_response.json()["errors"][0]["code"] == BusinessErrorCode.HOMEWORK_BLUEPRINT_NOT_FOUND.value

    forbidden_lesson_response = client.post(
        f"/api/v1/lesson-plans/{lesson_plan['id']}/homework-tasks",
        headers=other_headers,
    )
    assert forbidden_lesson_response.status_code == 404
    assert forbidden_lesson_response.json()["errors"][0]["code"] == BusinessErrorCode.LESSON_PLAN_NOT_FOUND.value


def test_homework_result_should_404_when_not_generated(
    client,
    generation_test_stubs,
) -> None:
    """未生成作业时按教案查询应返回 404。"""
    _ = generation_test_stubs
    headers = build_auth_headers(client)
    project_id, knowledge_version_id, learner_profile_version_id = create_generation_baseline(client, headers)
    batch_payload = create_generation_batch(client, headers, project_id, knowledge_version_id, learner_profile_version_id)
    lesson_plans = _list_lesson_plans(client, headers, batch_payload["curriculum_plan_id"])
    lesson_plan = lesson_plans[0]

    response = client.get(
        f"/api/v1/lesson-plans/{lesson_plan['id']}/homework-result",
        headers=headers,
    )
    assert response.status_code == 404
    assert response.json()["errors"][0]["code"] == BusinessErrorCode.HOMEWORK_RESULT_NOT_FOUND.value


def test_homework_should_refresh_coverage_with_homework_bucket(
    client,
    generation_test_stubs,
) -> None:
    """生成课后作业后覆盖率报告应包含 homework_question 桶并统计题量。"""
    _ = generation_test_stubs
    headers = build_auth_headers(client)
    project_id, knowledge_version_id, learner_profile_version_id = create_generation_baseline(client, headers)
    batch_payload = create_generation_batch(client, headers, project_id, knowledge_version_id, learner_profile_version_id)
    lesson_plans = _list_lesson_plans(client, headers, batch_payload["curriculum_plan_id"])

    for lesson_plan in lesson_plans:
        response = client.post(
            f"/api/v1/lesson-plans/{lesson_plan['id']}/homework-tasks",
            headers=headers,
        )
        assert response.status_code == 201

    coverage_response = client.get(
        f"/api/v1/coverage-reports?generation_batch_id={batch_payload['id']}",
        headers=headers,
    )
    assert coverage_response.status_code == 200
    coverage_items = coverage_response.json()["data"]["items"]
    assert coverage_items, "should have coverage report after generation"
    coverage_id = coverage_items[0]["id"]

    detail_response = client.get(f"/api/v1/coverage-reports/{coverage_id}", headers=headers)
    assert detail_response.status_code == 200
    report_json = detail_response.json()["data"]["report_json"]
    artifact_coverage = report_json["artifact_coverage"]
    assert "homework_question" in artifact_coverage
    homework_bucket = artifact_coverage["homework_question"]
    assert homework_bucket["item_count"] == 6 * len(lesson_plans)
    assert homework_bucket["display_name"] == "作业题目"

    strategy_checks = report_json["assessment_quality"]["strategy_checks"]
    source_types = {check["source_type"] for check in strategy_checks}
    assert "homework_result" in source_types


def test_coverage_report_should_only_count_success_homework(
    client,
    seeded_session_factory,
    generation_test_stubs,
) -> None:
    """覆盖率报告只统计成功状态课后作业的题目。"""
    _ = generation_test_stubs
    headers = build_auth_headers(client)
    project_id, knowledge_version_id, learner_profile_version_id = create_generation_baseline(client, headers)
    batch_payload = create_generation_batch(client, headers, project_id, knowledge_version_id, learner_profile_version_id)
    lesson_plan = _list_lesson_plans(client, headers, batch_payload["curriculum_plan_id"])[0]

    create_response = client.post(
        f"/api/v1/lesson-plans/{lesson_plan['id']}/homework-tasks",
        headers=headers,
    )
    assert create_response.status_code == 201
    homework_result_id = create_response.json()["data"]["result_json"]["homework_result_id"]

    coverage_response = client.get(
        f"/api/v1/coverage-reports?generation_batch_id={batch_payload['id']}",
        headers=headers,
    )
    assert coverage_response.status_code == 200
    report_json = coverage_response.json()["data"]["items"][0]["report_json"]
    assert report_json["artifact_coverage"]["homework_question"]["item_count"] == 6

    session = seeded_session_factory()
    try:
        homework_result = session.query(HomeworkResult).filter(HomeworkResult.id == homework_result_id).one()
        homework_result.result_status = "failure"
        session.commit()
    finally:
        session.close()

    refresh_response = client.post(
        f"/api/v1/generation-batches/{batch_payload['id']}/coverage-reports/refresh",
        headers=headers,
    )
    assert refresh_response.status_code == 200
    refreshed_report = refresh_response.json()["data"]["report_json"]
    assert refreshed_report["artifact_coverage"]["homework_question"]["item_count"] == 0
    assert refreshed_report["assessment_quality"]["question_count"] == 0
