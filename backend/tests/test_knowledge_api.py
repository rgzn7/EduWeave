"""
@Date: 2026-04-14
@Author: xisy
@Discription: 知识结构化模块接口测试
"""

from io import BytesIO

import pytest
from pypdf import PdfWriter

from app.core.config import get_settings
from app.core.constants import KNOWLEDGE_EXTRACT_TASK_TYPE, KNOWLEDGE_MODULE_CODE, KNOWLEDGE_QUEUE_NAME, TASK_STATUS_PENDING
from app.core.exceptions import AppException, BusinessErrorCode
from app.modules.knowledge.schemas import (
    KnowledgeChapterBoundaryItem,
    KnowledgeChapterBoundaryResult,
    KnowledgeChapterPointExtractionResult,
    KnowledgeExtractionEvidenceDraft,
    KnowledgeExtractionPointDraft,
)
from app.modules.p0_models import ChapterNode, KnowledgeEvidence, Project, SemanticChunk, TaskRecord
from app.modules.task_center.repository import TaskCenterRepository
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


def create_project(client, headers) -> int:
    """创建测试项目。"""
    response = client.post(
        "/api/v1/projects",
        headers=headers,
        json={"name": "知识项目", "subject_code": "math", "grade_code": "grade_3"},
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


@pytest.fixture()
def knowledge_test_stubs(monkeypatch: pytest.MonkeyPatch):
    """替换知识阶段依赖的 LLM、Embedding 与向量写入。"""
    vector_store: dict[str, list] = {}

    def fake_generate_structured_output(self, *, messages, response_model, temperature=0.2):  # noqa: ANN001
        _ = (self, messages, response_model, temperature)
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
        return KnowledgeChapterPointExtractionResult(
            summary_json={
                "teaching_objectives": ["掌握乘法口诀", "理解乘法含义"],
                "key_points": ["乘法口诀"],
                "difficult_points": ["乘法应用题"],
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


def test_knowledge_task_should_require_confirmed_parse_version(client, knowledge_test_stubs) -> None:
    """未确认解析版本时应拒绝创建知识任务。"""
    _ = knowledge_test_stubs
    headers = build_auth_headers(client)
    project_id = create_project(client, headers)
    parse_version_id = upload_and_parse_textbook(client, headers, project_id)

    response = client.post(
        f"/api/v1/parse-versions/{parse_version_id}/knowledge-tasks",
        headers=headers,
        json={"force_regenerate": False},
    )

    assert response.status_code == 422
    assert response.json()["errors"][0]["code"] == "PARSE_VERSION_NOT_CONFIRMED"


def test_knowledge_task_should_create_version_and_query_details(client, seeded_session_factory, knowledge_test_stubs) -> None:
    """确认解析版本后应可抽取知识结构并查询详情。"""
    headers = build_auth_headers(client)
    project_id = create_project(client, headers)
    parse_version_id = upload_and_parse_textbook(client, headers, project_id)

    confirm_response = client.post(f"/api/v1/parse-versions/{parse_version_id}/confirm", headers=headers)
    assert confirm_response.status_code == 200
    assert confirm_response.json()["data"]["review_status"] == "confirmed"

    create_response = client.post(
        f"/api/v1/parse-versions/{parse_version_id}/knowledge-tasks",
        headers=headers,
        json={"force_regenerate": False},
    )
    assert create_response.status_code == 201
    task_payload = create_response.json()["data"]
    assert task_payload["task_type"] == "knowledge_extract"
    assert task_payload["task_status"] == "success"

    task_detail_response = client.get(f"/api/v1/tasks/{task_payload['id']}", headers=headers)
    assert task_detail_response.status_code == 200
    steps = task_detail_response.json()["data"]["steps"]
    assert [step["step_code"] for step in steps] == [
        "prepare_parse_source",
        "invoke_llm_extract",
        "persist_knowledge_result",
        "upsert_vectors",
    ]

    version_list_response = client.get(
        f"/api/v1/parse-versions/{parse_version_id}/knowledge-versions",
        headers=headers,
    )
    assert version_list_response.status_code == 200
    version_payload = version_list_response.json()["data"]["items"][0]
    assert version_payload["version_status"] == "ready"
    assert version_payload["chapter_count"] == 1
    assert version_payload["point_count"] == 1

    knowledge_version_id = version_payload["id"]
    detail_response = client.get(f"/api/v1/knowledge-versions/{knowledge_version_id}", headers=headers)
    assert detail_response.status_code == 200
    assert detail_response.json()["data"]["summary_json"]["knowledge_point_count"] == 1
    assert detail_response.json()["data"]["summary_json"]["chapter_summaries"][0]["chapter_title"] == "第2页标题"

    chapters_response = client.get(f"/api/v1/knowledge-versions/{knowledge_version_id}/chapters", headers=headers)
    assert chapters_response.status_code == 200
    chapters = chapters_response.json()["data"]
    assert len(chapters) == 1
    assert chapters[0]["node_path"] == "1"
    assert chapters[0]["node_type"] == "chapter"
    assert chapters[0]["line_start"] == 6
    assert chapters[0]["line_end"] == 8
    assert chapters[0]["page_start"] == 2
    assert chapters[0]["page_end"] == 2

    points_response = client.get(f"/api/v1/knowledge-versions/{knowledge_version_id}/points", headers=headers)
    assert points_response.status_code == 200
    points = points_response.json()["data"]["items"]
    assert len(points) == 1
    assert points[0]["point_name"] == "乘法口诀"
    assert points[0]["chapter_title"] == "第2页标题"

    point_detail_response = client.get(f"/api/v1/knowledge-points/{points[0]['id']}", headers=headers)
    assert point_detail_response.status_code == 200
    assert point_detail_response.json()["data"]["evidences"][0]["page_no"] == 2
    assert point_detail_response.json()["data"]["evidences"][0]["semantic_chunk_id"] is not None

    session = seeded_session_factory()
    try:
        chapter = session.query(ChapterNode).filter(ChapterNode.knowledge_version_id == knowledge_version_id).one()
        semantic_chunk = session.query(SemanticChunk).filter(SemanticChunk.knowledge_version_id == knowledge_version_id).one()
        evidence = session.query(KnowledgeEvidence).filter(KnowledgeEvidence.knowledge_point_id == points[0]["id"]).one()
        assert chapter.line_start == 6
        assert chapter.line_end == 8
        assert semantic_chunk.line_start == 6
        assert semantic_chunk.line_end == 8
        assert semantic_chunk.page_start == 2
        assert semantic_chunk.page_end == 2
        assert "# 第1页标题" not in semantic_chunk.chunk_text
        assert "textbook.pdf 第1页解析内容" not in semantic_chunk.chunk_text
        assert "# 第2页标题" in semantic_chunk.chunk_text
        assert evidence.semantic_chunk_id == semantic_chunk.id
    finally:
        session.close()

    assert "semantic_chunk_vector" in knowledge_test_stubs
    assert "knowledge_point_vector" in knowledge_test_stubs
    chunk_record = knowledge_test_stubs["semantic_chunk_vector"][0]
    assert chunk_record.id.startswith("semantic_chunk:")
    assert chunk_record.semantic_chunk_id > 0
    assert chunk_record.project_id > 0
    assert chunk_record.textbook_version_id > 0
    assert chunk_record.parse_version_id == parse_version_id
    assert chunk_record.knowledge_version_id == knowledge_version_id
    assert chunk_record.page_start == 2
    assert chunk_record.page_end == 2
    assert chunk_record.chunk_type == "semantic"
    assert chunk_record.metadata["semantic_chunk_id"] > 0
    assert chunk_record.metadata["line_start"] == 6
    assert chunk_record.metadata["line_end"] == 8
    assert "parse_block_id" not in chunk_record.metadata
    point_record = knowledge_test_stubs["knowledge_point_vector"][0]
    assert point_record.knowledge_version_id == knowledge_version_id
    assert point_record.importance_level == 5


def test_knowledge_task_should_reject_running_duplicate(client, seeded_session_factory, knowledge_test_stubs) -> None:
    """存在运行中知识任务时应拒绝重复创建。"""
    _ = knowledge_test_stubs
    headers = build_auth_headers(client)
    project_id = create_project(client, headers)
    parse_version_id = upload_and_parse_textbook(client, headers, project_id)
    confirm_response = client.post(f"/api/v1/parse-versions/{parse_version_id}/confirm", headers=headers)
    assert confirm_response.status_code == 200

    session = seeded_session_factory()
    try:
        project = session.get(Project, project_id)
        session.add(
            TaskRecord(
                project_id=project_id,
                generation_batch_id=None,
                module_code=KNOWLEDGE_MODULE_CODE,
                task_type=KNOWLEDGE_EXTRACT_TASK_TYPE,
                biz_key=f"parse_version:{parse_version_id}:knowledge",
                task_status=TASK_STATUS_PENDING,
                queue_name=KNOWLEDGE_QUEUE_NAME,
                current_stage=None,
                progress_percent=0,
                retry_count=0,
                max_retry_count=3,
                request_id="test",
                worker_task_id=None,
                operator_user_id=project.owner_user_id,
                payload_json={"parse_version_id": parse_version_id},
                result_json=None,
                last_error_code=None,
                last_error_message=None,
                started_at=None,
                finished_at=None,
            )
        )
        session.commit()
    finally:
        session.close()

    response = client.post(
        f"/api/v1/parse-versions/{parse_version_id}/knowledge-tasks",
        headers=headers,
        json={"force_regenerate": False},
    )
    assert response.status_code == 409
    assert response.json()["errors"][0]["code"] == "TASK_CONFLICT"


def test_knowledge_manual_revision_should_create_new_version(client, knowledge_test_stubs) -> None:
    """知识人工修正应生成新的知识版本并归档旧版本。"""
    _ = knowledge_test_stubs
    headers = build_auth_headers(client)
    project_id = create_project(client, headers)
    parse_version_id = upload_and_parse_textbook(client, headers, project_id)
    client.post(f"/api/v1/parse-versions/{parse_version_id}/confirm", headers=headers)
    create_response = client.post(
        f"/api/v1/parse-versions/{parse_version_id}/knowledge-tasks",
        headers=headers,
        json={"force_regenerate": False},
    )
    knowledge_version_id = create_response.json()["data"]["result_json"]["knowledge_version_id"]

    points_response = client.get(f"/api/v1/knowledge-versions/{knowledge_version_id}/points", headers=headers)
    point = points_response.json()["data"]["items"][0]

    revision_response = client.post(
        f"/api/v1/knowledge-versions/{knowledge_version_id}/manual-revisions",
        headers=headers,
        json={
            "operations": [
                {
                    "op_type": "update_summary",
                    "summary_json": {"teaching_objectives": ["强化乘法口诀应用"]},
                },
                {
                    "op_type": "update_point",
                    "knowledge_point_id": point["id"],
                    "point_name": "乘法口诀与应用",
                    "importance_level": 4,
                    "evidences": [
                        {
                            "page_no": 2,
                            "block_no": 2,
                            "evidence_type": "manual",
                            "excerpt_text": "textbook.pdf 第2页解析内容",
                            "score_value": 0.9,
                        }
                    ],
                },
            ]
        },
    )
    assert revision_response.status_code == 201
    revision_payload = revision_response.json()["data"]
    assert revision_payload["parent_knowledge_version_id"] == knowledge_version_id
    assert revision_payload["version_status"] == "ready"
    assert revision_payload["summary_json"]["teaching_objectives"] == ["强化乘法口诀应用"]

    new_points_response = client.get(f"/api/v1/knowledge-versions/{revision_payload['id']}/points", headers=headers)
    new_point = new_points_response.json()["data"]["items"][0]
    assert new_point["point_name"] == "乘法口诀与应用"

    old_version_response = client.get(f"/api/v1/knowledge-versions/{knowledge_version_id}", headers=headers)
    assert old_version_response.json()["data"]["version_status"] == "archived"


def test_run_extract_task_should_mark_failure_when_llm_invalid(client, seeded_session_factory, monkeypatch: pytest.MonkeyPatch) -> None:
    """LLM 返回非法结果时应写入失败状态。"""
    from app.modules.knowledge.tasks import run_extract_task

    headers = build_auth_headers(client)
    project_id = create_project(client, headers)
    parse_version_id = upload_and_parse_textbook(client, headers, project_id)
    client.post(f"/api/v1/parse-versions/{parse_version_id}/confirm", headers=headers)

    def raise_invalid_result(self, *, messages, response_model, temperature=0.2):  # noqa: ANN001
        _ = (self, messages, response_model, temperature)
        raise AppException(BusinessErrorCode.LLM_RESULT_INVALID, "LLM 返回结果非法")

    monkeypatch.setattr(OpenAICompatibleLlmService, "generate_structured_output", raise_invalid_result)

    session = seeded_session_factory()
    try:
        project = session.get(Project, project_id)
        task_repository = TaskCenterRepository(session)
        task = task_repository.create_task(
            project_id=project_id,
            module_code=KNOWLEDGE_MODULE_CODE,
            task_type=KNOWLEDGE_EXTRACT_TASK_TYPE,
            task_status=TASK_STATUS_PENDING,
            queue_name=KNOWLEDGE_QUEUE_NAME,
            biz_key=f"parse_version:{parse_version_id}:knowledge:manual",
            operator_user_id=project.owner_user_id,
            payload_json={"parse_version_id": parse_version_id},
            request_id="test",
        )
        for step_order, (step_code, step_name) in enumerate(
            [
                ("prepare_parse_source", "准备解析基线"),
                ("invoke_llm_extract", "调用 LLM 抽取知识结构"),
                ("persist_knowledge_result", "落库知识结构"),
                ("upsert_vectors", "写入向量索引"),
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
        session.commit()
        payload = {
            "task_record_id": task.id,
            "parse_version_id": parse_version_id,
            "operator_user_id": project.owner_user_id,
            "force_regenerate": False,
            "database_url": session.get_bind().url.render_as_string(hide_password=False),
        }

        with pytest.raises(AppException) as exc_info:
            run_extract_task(payload)
        assert exc_info.value.code == BusinessErrorCode.LLM_RESULT_INVALID

        session.expire_all()
        failed_task = task_repository.get_task_by_id(task.id)
        assert failed_task.task_status == "failure"
        assert failed_task.last_error_code == "LLM_RESULT_INVALID"
        assert failed_task.last_error_message == "LLM 返回结果非法"
    finally:
        session.close()
