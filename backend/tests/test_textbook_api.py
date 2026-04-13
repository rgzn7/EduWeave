"""
@Date: 2026-04-13
@Author: xisy
@Discription: 教材模块接口测试
"""

from io import BytesIO

import pytest
from pypdf import PdfWriter

from app.shared.storage import ObsStorageClient


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
        json={"name": "教材项目", "subject_code": "math", "grade_code": "grade_3"},
    )
    return response.json()["data"]["id"]


def test_textbook_upload_should_create_version_and_current_ref(client) -> None:
    """上传教材应创建版本并设为当前引用。"""
    headers = build_auth_headers(client)
    project_id = create_project(client, headers)

    response = client.post(
        f"/api/v1/projects/{project_id}/textbooks",
        headers=headers,
        files={"file": ("textbook.pdf", build_pdf_bytes(), "application/pdf")},
    )

    assert response.status_code == 201
    payload = response.json()["data"]
    assert payload["version_no"] == 1
    assert payload["is_current"] is True
    assert payload["source_file"]["original_filename"] == "textbook.pdf"


def test_textbook_upload_should_reject_invalid_file_type(client) -> None:
    """非 PDF 文件应返回 422。"""
    headers = build_auth_headers(client)
    project_id = create_project(client, headers)

    response = client.post(
        f"/api/v1/projects/{project_id}/textbooks",
        headers=headers,
        files={"file": ("textbook.txt", b"not-pdf", "text/plain")},
    )

    assert response.status_code == 422
    assert response.json()["errors"][0]["code"] == "INVALID_FILE_TYPE"


def test_textbook_upload_should_rollback_when_obs_failed(client, monkeypatch: pytest.MonkeyPatch) -> None:
    """OBS 上传失败时不应留下脏数据。"""
    headers = build_auth_headers(client)
    project_id = create_project(client, headers)

    def raise_upload_error(self, object_key: str, content: bytes, content_type=None, metadata=None):  # noqa: ANN001
        _ = (self, object_key, content, content_type, metadata)
        raise RuntimeError("OBS unavailable")

    monkeypatch.setattr(ObsStorageClient, "upload_bytes", raise_upload_error)
    response = client.post(
        f"/api/v1/projects/{project_id}/textbooks",
        headers=headers,
        files={"file": ("textbook.pdf", build_pdf_bytes(), "application/pdf")},
    )

    assert response.status_code == 503
    assert response.json()["errors"][0]["code"] == "FILE_UPLOAD_FAILED"

    list_response = client.get(f"/api/v1/projects/{project_id}/textbooks", headers=headers)
    assert list_response.json()["data"]["pagination"]["total_count"] == 0


def test_textbook_upload_should_increment_version_no(client) -> None:
    """第二次上传应递增版本号。"""
    headers = build_auth_headers(client)
    project_id = create_project(client, headers)

    client.post(
        f"/api/v1/projects/{project_id}/textbooks",
        headers=headers,
        files={"file": ("textbook1.pdf", build_pdf_bytes(), "application/pdf")},
    )
    response = client.post(
        f"/api/v1/projects/{project_id}/textbooks",
        headers=headers,
        files={"file": ("textbook2.pdf", build_pdf_bytes(), "application/pdf")},
    )

    assert response.status_code == 201
    assert response.json()["data"]["version_no"] == 2
