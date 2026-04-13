"""
@Date: 2026-04-13
@Author: xisy
@Discription: 项目模块接口测试
"""

from io import BytesIO

from pypdf import PdfWriter


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


def test_project_create_and_list_should_succeed(client) -> None:
    """应可创建项目并分页查询。"""
    headers = build_auth_headers(client)
    create_response = client.post(
        "/api/v1/projects",
        headers=headers,
        json={
            "name": "项目A",
            "subject_code": "math",
            "grade_code": "grade_3",
            "applicable_target": "三年级学生",
        },
    )

    assert create_response.status_code == 201
    payload = create_response.json()
    assert payload["data"]["name"] == "项目A"

    list_response = client.get("/api/v1/projects?page=1&page_size=10", headers=headers)
    assert list_response.status_code == 200
    list_payload = list_response.json()
    assert list_payload["data"]["pagination"]["total_count"] >= 1
    assert list_payload["data"]["items"][0]["name"] == "项目A"


def test_project_dashboard_should_return_aggregated_counts(client) -> None:
    """工作台应返回聚合统计。"""
    headers = build_auth_headers(client)
    create_response = client.post(
        "/api/v1/projects",
        headers=headers,
        json={"name": "项目工作台", "subject_code": "math", "grade_code": "grade_3"},
    )
    project_id = create_response.json()["data"]["id"]

    dashboard_response = client.get(f"/api/v1/projects/{project_id}/dashboard", headers=headers)
    assert dashboard_response.status_code == 200
    dashboard_payload = dashboard_response.json()["data"]
    assert dashboard_payload["stats"]["textbook_count"] == 0
    assert dashboard_payload["stats"]["learner_profile_file_count"] == 0
    assert dashboard_payload["stats"]["task_total_count"] == 0


def test_project_active_refs_should_reject_foreign_version(client) -> None:
    """切换外部项目版本应返回 422。"""
    headers = build_auth_headers(client)
    project_a = client.post(
        "/api/v1/projects",
        headers=headers,
        json={"name": "项目A", "subject_code": "math", "grade_code": "grade_3"},
    ).json()["data"]["id"]
    project_b = client.post(
        "/api/v1/projects",
        headers=headers,
        json={"name": "项目B", "subject_code": "math", "grade_code": "grade_3"},
    ).json()["data"]["id"]

    upload_response = client.post(
        f"/api/v1/projects/{project_b}/textbooks",
        headers=headers,
        files={"file": ("textbook.pdf", build_pdf_bytes(), "application/pdf")},
    )
    textbook_version_id = upload_response.json()["data"]["id"]

    patch_response = client.patch(
        f"/api/v1/projects/{project_a}/active-refs",
        headers=headers,
        json={"current_textbook_version_id": textbook_version_id},
    )

    assert patch_response.status_code == 422
    assert patch_response.json()["errors"][0]["code"] == "PROJECT_REFERENCE_INVALID"
