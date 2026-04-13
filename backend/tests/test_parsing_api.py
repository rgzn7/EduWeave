"""
@Date: 2026-04-13
@Author: xisy
@Discription: 解析模块接口测试
"""

from io import BytesIO

from pypdf import PdfWriter

from app.core.constants import PARSING_MODULE_CODE, PARSING_QUEUE_NAME, TASK_STATUS_PENDING, TEXTBOOK_PARSE_TASK_TYPE
from app.modules.p0_models import Project, TaskRecord


def build_auth_headers(client) -> dict[str, str]:
    """构造认证请求头。"""
    login_response = client.post(
        "/api/v1/auth/login",
        json={"username": "teacher_demo", "password": "Teacher@123"},
    )
    access_token = login_response.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {access_token}"}


def build_pdf_bytes() -> bytes:
    """生成空白 PDF 内容。"""
    writer = PdfWriter()
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
        json={"parse_mode": "full", "strategy_code": "p0_placeholder"},
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

    parse_version_id = version_payload["id"]
    pages_response = client.get(f"/api/v1/parse-versions/{parse_version_id}/pages", headers=headers)
    issues_response = client.get(f"/api/v1/parse-versions/{parse_version_id}/issues", headers=headers)

    assert pages_response.status_code == 200
    assert len(pages_response.json()["data"]["items"]) == 1
    assert pages_response.json()["data"]["items"][0]["blocks"][0]["block_type"] == "empty_page"
    assert issues_response.status_code == 200
    assert issues_response.json()["data"]["items"][0]["issue_type"] == "empty_page"


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
        json={"parse_mode": "full", "strategy_code": "p0_placeholder"},
    )

    assert response.status_code == 409
    assert response.json()["errors"][0]["code"] == "TASK_CONFLICT"
