"""
@Date: 2026-04-14
@Author: xisy
@Discription: 文件访问接口测试
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


def test_file_download_url_should_return_signed_url(client) -> None:
    """文件下载接口应返回签名 URL。"""
    headers = build_auth_headers(client)
    project_response = client.post(
        "/api/v1/projects",
        headers=headers,
        json={"name": "文件项目", "subject_code": "math", "grade_code": "grade_3"},
    )
    project_id = project_response.json()["data"]["id"]
    upload_response = client.post(
        f"/api/v1/projects/{project_id}/textbooks",
        headers=headers,
        files={"file": ("textbook.pdf", build_pdf_bytes(), "application/pdf")},
    )
    file_object_id = upload_response.json()["data"]["source_file"]["id"]

    response = client.get(f"/api/v1/files/{file_object_id}/download-url", headers=headers)

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["file_object_id"] == file_object_id
    assert payload["signed_url"].startswith("https://obs.test.example.com/")


def test_file_download_url_should_fail_when_signing_failed(client, monkeypatch: pytest.MonkeyPatch) -> None:
    """签名失败时应返回受控错误。"""
    headers = build_auth_headers(client)
    project_response = client.post(
        "/api/v1/projects",
        headers=headers,
        json={"name": "文件项目", "subject_code": "math", "grade_code": "grade_3"},
    )
    project_id = project_response.json()["data"]["id"]
    upload_response = client.post(
        f"/api/v1/projects/{project_id}/textbooks",
        headers=headers,
        files={"file": ("textbook.pdf", build_pdf_bytes(), "application/pdf")},
    )
    file_object_id = upload_response.json()["data"]["source_file"]["id"]

    def raise_sign_error(self, object_key: str, expires_in_seconds=None):  # noqa: ANN001
        _ = (self, object_key, expires_in_seconds)
        raise RuntimeError("sign failed")

    monkeypatch.setattr(ObsStorageClient, "create_download_signed_url", raise_sign_error)
    response = client.get(f"/api/v1/files/{file_object_id}/download-url", headers=headers)

    assert response.status_code == 503
    assert response.json()["errors"][0]["code"] == "EXTERNAL_SERVICE_ERROR"
