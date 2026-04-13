"""
@Date: 2026-04-13
@Author: xisy
@Discription: 学情模块接口测试
"""


def build_auth_headers(client) -> dict[str, str]:
    """构造认证请求头。"""
    login_response = client.post(
        "/api/v1/auth/login",
        json={"username": "teacher_demo", "password": "Teacher@123"},
    )
    access_token = login_response.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {access_token}"}


def create_project(client, headers) -> int:
    """创建测试项目。"""
    response = client.post(
        "/api/v1/projects",
        headers=headers,
        json={"name": "学情项目", "subject_code": "english", "grade_code": "grade_6"},
    )
    return response.json()["data"]["id"]


def test_learner_profile_upload_should_extract_placeholder_result(client) -> None:
    """上传学情文件应自动产生占位抽取结果。"""
    headers = build_auth_headers(client)
    project_id = create_project(client, headers)

    response = client.post(
        f"/api/v1/projects/{project_id}/learner-profiles",
        headers=headers,
        files={"file": ("student_profile.docx", b"fake-docx-content", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        data={"title": "学生学情", "subject_scope": "english"},
    )

    assert response.status_code == 201
    payload = response.json()["data"]
    assert payload["title"] == "学生学情"
    assert payload["latest_version"]["extract_status"] == "success"
    assert payload["latest_version"]["records"][0]["subject_code"] == "english"

    version_id = payload["latest_version"]["id"]
    version_response = client.get(f"/api/v1/learner-profile-versions/{version_id}", headers=headers)
    assert version_response.status_code == 200
    assert version_response.json()["data"]["records"][0]["student_key"].endswith("_1")


def test_learner_profile_upload_should_reject_invalid_textbook_hint(client) -> None:
    """传入无效教材提示版本应返回 422。"""
    headers = build_auth_headers(client)
    project_id = create_project(client, headers)

    response = client.post(
        f"/api/v1/projects/{project_id}/learner-profiles",
        headers=headers,
        files={"file": ("student_profile.docx", b"fake-docx-content", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        data={"textbook_version_hint_id": 999},
    )

    assert response.status_code == 422
    assert response.json()["errors"][0]["code"] == "PROJECT_REFERENCE_INVALID"
