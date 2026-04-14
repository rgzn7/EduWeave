"""
@Date: 2026-04-13
@Author: xisy
@Discription: 解析模块接口测试
"""

from io import BytesIO

from pypdf import PdfWriter

from app.core.constants import MINERU_STRATEGY_VLM_DEFAULT, PARSING_MODULE_CODE, PARSING_QUEUE_NAME, TASK_STATUS_PENDING, TEXTBOOK_PARSE_TASK_TYPE
from app.modules.p0_models import Project, TaskRecord


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
        json={"name": "解析项目", "subject_code": "math", "grade_code": "grade_3"},
    )
    return response.json()["data"]["id"]


def upload_textbook(client, headers, project_id: int) -> int:
    """上传教材。"""
    response = client.post(
        f"/api/v1/projects/{project_id}/textbooks",
        headers=headers,
        files={"file": ("textbook.pdf", build_pdf_bytes(), "application/pdf")},
    )
    return response.json()["data"]["id"]


def test_parsing_task_should_create_parse_result_and_preview(client) -> None:
    """创建解析任务后应能查看预览数据。"""
    headers = build_auth_headers(client)
    project_id = create_project(client, headers)
    textbook_version_id = upload_textbook(client, headers, project_id)

    create_response = client.post(
        f"/api/v1/textbook-versions/{textbook_version_id}/parse-tasks",
        headers=headers,
        json={"strategy_code": MINERU_STRATEGY_VLM_DEFAULT},
    )
    assert create_response.status_code == 201
    assert create_response.json()["data"]["task_status"] == "success"

    version_list_response = client.get(
        f"/api/v1/textbook-versions/{textbook_version_id}/parse-versions",
        headers=headers,
    )
    assert version_list_response.status_code == 200
    version_payload = version_list_response.json()["data"]["items"][0]
    assert version_payload["parse_status"] == "success"
    assert version_payload["source_markdown_file_id"] is not None
    assert version_payload["source_json_file_id"] is not None
    assert version_payload["asset_manifest_json"]["raw_zip_file_id"] is not None

    parse_version_id = version_payload["id"]
    pages_response = client.get(f"/api/v1/parse-versions/{parse_version_id}/pages", headers=headers)
    issues_response = client.get(f"/api/v1/parse-versions/{parse_version_id}/issues", headers=headers)

    assert pages_response.status_code == 200
    assert len(pages_response.json()["data"]["items"]) == 1
    assert pages_response.json()["data"]["items"][0]["blocks"][0]["block_type"] == "heading"
    assert issues_response.status_code == 200
    assert issues_response.json()["data"]["pagination"]["total_count"] == 0


def test_parsing_task_should_reject_running_duplicate(client, seeded_session_factory) -> None:
    """存在运行中任务时应拒绝重复创建解析任务。"""
    headers = build_auth_headers(client)
    project_id = create_project(client, headers)
    textbook_version_id = upload_textbook(client, headers, project_id)

    session = seeded_session_factory()
    try:
        project = session.get(Project, project_id)
        session.add(
            TaskRecord(
                project_id=project_id,
                generation_batch_id=None,
                module_code=PARSING_MODULE_CODE,
                task_type=TEXTBOOK_PARSE_TASK_TYPE,
                biz_key=f"textbook_version:{textbook_version_id}:full",
                task_status=TASK_STATUS_PENDING,
                queue_name=PARSING_QUEUE_NAME,
                current_stage=None,
                progress_percent=0,
                retry_count=0,
                max_retry_count=3,
                request_id="test",
                worker_task_id=None,
                operator_user_id=project.owner_user_id,
                payload_json={"textbook_version_id": textbook_version_id},
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
        f"/api/v1/textbook-versions/{textbook_version_id}/parse-tasks",
        headers=headers,
        json={"strategy_code": MINERU_STRATEGY_VLM_DEFAULT},
    )

    assert response.status_code == 409
    assert response.json()["errors"][0]["code"] == "TASK_CONFLICT"


def test_reparse_task_should_create_child_parse_version(client) -> None:
    """页级重解析应创建新的子版本。"""
    headers = build_auth_headers(client)
    project_id = create_project(client, headers)
    upload_response = client.post(
        f"/api/v1/projects/{project_id}/textbooks",
        headers=headers,
        files={"file": ("textbook.pdf", build_pdf_bytes(page_count=2), "application/pdf")},
    )
    textbook_version_id = upload_response.json()["data"]["id"]

    create_response = client.post(
        f"/api/v1/textbook-versions/{textbook_version_id}/parse-tasks",
        headers=headers,
        json={"strategy_code": MINERU_STRATEGY_VLM_DEFAULT, "set_as_current_on_success": True},
    )
    first_parse_version_id = create_response.json()["data"]["result_json"]["parse_version_id"]

    reparse_response = client.post(
        f"/api/v1/parse-versions/{first_parse_version_id}/reparse-tasks",
        headers=headers,
        json={"page_range_text": "2", "strategy_code": MINERU_STRATEGY_VLM_DEFAULT, "set_as_current_on_success": True},
    )
    assert reparse_response.status_code == 201
    assert reparse_response.json()["data"]["task_status"] == "success"

    versions_response = client.get(
        f"/api/v1/textbook-versions/{textbook_version_id}/parse-versions",
        headers=headers,
    )
    versions = versions_response.json()["data"]["items"]
    assert len(versions) == 2
    assert versions[0]["parent_parse_version_id"] == first_parse_version_id
    assert versions[0]["page_range_text"] == "2"
    assert versions[0]["diff_json"]["revision_type"] == "reparse"
    assert versions[1]["version_status"] == "archived"


def test_manual_revision_should_create_new_parse_version(client) -> None:
    """人工修正应生成新解析版本。"""
    headers = build_auth_headers(client)
    project_id = create_project(client, headers)
    textbook_version_id = upload_textbook(client, headers, project_id)

    create_response = client.post(
        f"/api/v1/textbook-versions/{textbook_version_id}/parse-tasks",
        headers=headers,
        json={"strategy_code": MINERU_STRATEGY_VLM_DEFAULT, "set_as_current_on_success": True},
    )
    parent_parse_version_id = create_response.json()["data"]["result_json"]["parse_version_id"]
    pages_response = client.get(f"/api/v1/parse-versions/{parent_parse_version_id}/pages", headers=headers)
    parent_page = pages_response.json()["data"]["items"][0]

    manual_revision_response = client.post(
        f"/api/v1/parse-versions/{parent_parse_version_id}/manual-revisions",
        headers=headers,
        json={
            "pages": [
                {
                    "page_no": 1,
                    "page_status": "success",
                    "text_content": "人工修正后的页文本",
                    "markdown_content": "人工修正后的页文本",
                    "layout_json": parent_page["layout_json"],
                    "blocks": [
                        {
                            "block_no": 1,
                            "block_type": "paragraph",
                            "text_content": "人工修正后的块文本",
                            "markdown_content": "人工修正后的块文本",
                            "origin_ref_json": {"source": "manual"},
                            "is_deleted": 0,
                        }
                    ],
                }
            ],
            "set_as_current_on_success": True,
        },
    )
    assert manual_revision_response.status_code == 201
    payload = manual_revision_response.json()["data"]
    assert payload["parent_parse_version_id"] == parent_parse_version_id
    assert payload["review_status"] == "confirmed"
    assert payload["diff_json"]["revision_type"] == "manual"
    detail_pages_response = client.get(f"/api/v1/parse-versions/{payload['id']}/pages", headers=headers)
    assert detail_pages_response.json()["data"]["items"][0]["text_content"] == "人工修正后的页文本"
