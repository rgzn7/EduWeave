"""
@Date: 2026-05-09
@Author: xisy
@Discription: DOCX 同步导出接口测试
"""

from io import BytesIO
from zipfile import ZipFile

from test_assessment_api import build_other_auth_headers, create_assessment_task, create_generation_batch
from test_pipeline_curriculum_api import (
    build_auth_headers,
    create_knowledge_version,
    create_learner_profile_version,
    create_project,
    generation_test_stubs,
)


def read_docx_document_xml(content: bytes) -> str:
    """读取 DOCX 主文档 XML。"""
    with ZipFile(BytesIO(content)) as archive:
        return archive.read("word/document.xml").decode("utf-8")


def create_export_baseline(client, headers) -> dict:
    """创建导出测试所需的课程、教案和试卷结果。"""
    project_id = create_project(client, headers)
    knowledge_version_id = create_knowledge_version(client, headers, project_id)
    learner_profile_version_id = create_learner_profile_version(client, headers, project_id)
    batch_payload = create_generation_batch(
        client,
        headers,
        project_id,
        knowledge_version_id,
        learner_profile_version_id,
    )
    assessment_task_payload = create_assessment_task(client, headers, batch_payload["curriculum_plan_id"])
    return {
        "project_id": project_id,
        "curriculum_plan_id": batch_payload["curriculum_plan_id"],
        "lesson_plan_id": batch_payload["lesson_plan_id"],
        "paper_result_id": assessment_task_payload["result_json"]["paper_result_id"],
    }


def test_docx_export_should_create_files_and_backfill_export_ids(
    client,
    mock_obs_storage,
    generation_test_stubs,
) -> None:
    """DOCX 导出应生成文件、回填导出文件并支持下载地址。"""
    _ = generation_test_stubs
    headers = build_auth_headers(client)
    baseline = create_export_baseline(client, headers)

    curriculum_response = client.post(
        f"/api/v1/curriculum-plans/{baseline['curriculum_plan_id']}/export-docx",
        headers=headers,
    )
    assert curriculum_response.status_code == 200
    curriculum_payload = curriculum_response.json()["data"]
    assert curriculum_payload["signed_url"].startswith("https://obs.test.example.com/")
    # object_key 应嵌入模板版本号段，便于模板升级时旧文件自然失效
    assert "/tv" in curriculum_payload["object_key"]
    # 文件名应面向教师友好，包含课题与资产类型
    assert curriculum_payload["object_key"].endswith("三年级数学乘法提升课程-课程大纲.docx")
    curriculum_xml = read_docx_document_xml(mock_obs_storage[curriculum_payload["object_key"]])
    assert "三年级数学乘法提升课程" in curriculum_xml
    assert "第1讲 乘法口诀训练" in curriculum_xml

    curriculum_detail_response = client.get(
        f"/api/v1/curriculum-plans/{baseline['curriculum_plan_id']}",
        headers=headers,
    )
    assert curriculum_detail_response.json()["data"]["export_file_id"] == curriculum_payload["file_object_id"]

    repeated_curriculum_response = client.post(
        f"/api/v1/curriculum-plans/{baseline['curriculum_plan_id']}/export-docx",
        headers=headers,
    )
    assert repeated_curriculum_response.status_code == 200
    assert repeated_curriculum_response.json()["data"]["file_object_id"] == curriculum_payload["file_object_id"]

    lesson_response = client.post(
        f"/api/v1/lesson-plans/{baseline['lesson_plan_id']}/export-docx",
        headers=headers,
    )
    assert lesson_response.status_code == 200
    lesson_payload = lesson_response.json()["data"]
    assert "/tv" in lesson_payload["object_key"]
    assert lesson_payload["object_key"].endswith("乘法口诀训练教案-第1讲-教案.docx")
    lesson_xml = read_docx_document_xml(mock_obs_storage[lesson_payload["object_key"]])
    # 教案标题应去掉「第N讲」前缀，并且不再出现英文字段名
    assert "乘法口诀训练教案" in lesson_xml
    assert "第1讲 乘法口诀训练教案" not in lesson_xml
    assert "导入" in lesson_xml
    assert "single_choice" not in lesson_xml
    assert "knowledge_point_refs" not in lesson_xml

    lesson_detail_response = client.get(f"/api/v1/lesson-plans/{baseline['lesson_plan_id']}", headers=headers)
    assert lesson_detail_response.json()["data"]["export_file_id"] == lesson_payload["file_object_id"]

    paper_response = client.post(
        f"/api/v1/paper-results/{baseline['paper_result_id']}/export-docx",
        headers=headers,
    )
    assert paper_response.status_code == 200
    paper_payload = paper_response.json()["data"]
    assert "/tv" in paper_payload["object_key"]
    assert paper_payload["object_key"].endswith("三年级数学乘法单元测试-单元测试.docx")
    paper_xml = read_docx_document_xml(mock_obs_storage[paper_payload["object_key"]])
    assert "三年级数学乘法单元测试" in paper_xml
    assert "第1题：围绕乘法口诀完成练习。" in paper_xml
    assert "参考答案" in paper_xml
    # 题型与场景应该走中文标签，且不暴露原始英文枚举
    assert "单选题" in paper_xml
    assert "single_choice" not in paper_xml
    # 选项应渲染为 A. xxx 形式
    assert "A. 2" in paper_xml
    # 不再展示数据库内部追溯字段
    assert "来源摘要" not in paper_xml
    assert "source_trace" not in paper_xml

    paper_detail_response = client.get(f"/api/v1/paper-results/{baseline['paper_result_id']}", headers=headers)
    assert paper_detail_response.json()["data"]["export_file_id"] == paper_payload["file_object_id"]

    download_response = client.get(f"/api/v1/files/{paper_payload['file_object_id']}/download-url", headers=headers)
    assert download_response.status_code == 200
    assert download_response.json()["data"]["signed_url"].startswith("https://obs.test.example.com/")


def test_docx_export_should_protect_owner(client, seeded_session_factory, generation_test_stubs) -> None:
    """DOCX 导出接口应隔离其他教师资源。"""
    _ = generation_test_stubs
    headers = build_auth_headers(client)
    baseline = create_export_baseline(client, headers)
    other_headers = build_other_auth_headers(client, seeded_session_factory)

    curriculum_response = client.post(
        f"/api/v1/curriculum-plans/{baseline['curriculum_plan_id']}/export-docx",
        headers=other_headers,
    )
    assert curriculum_response.status_code == 404
    assert curriculum_response.json()["errors"][0]["code"] == "CURRICULUM_PLAN_NOT_FOUND"

    lesson_response = client.post(
        f"/api/v1/lesson-plans/{baseline['lesson_plan_id']}/export-docx",
        headers=other_headers,
    )
    assert lesson_response.status_code == 404
    assert lesson_response.json()["errors"][0]["code"] == "LESSON_PLAN_NOT_FOUND"

    paper_response = client.post(
        f"/api/v1/paper-results/{baseline['paper_result_id']}/export-docx",
        headers=other_headers,
    )
    assert paper_response.status_code == 404
    assert paper_response.json()["errors"][0]["code"] == "PAPER_RESULT_NOT_FOUND"
