"""
@Date: 2026-04-13
@Author: xisy
@Discription: 任务中心模块接口测试
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
        json={"name": "任务项目", "subject_code": "english", "grade_code": "grade_6"},
    )
    return response.json()["data"]["id"]


def test_task_center_should_list_and_detail_tasks(client) -> None:
    """任务中心应返回任务列表和详情。"""
    headers = build_auth_headers(client)
    project_id = create_project(client, headers)

    client.post(
        f"/api/v1/projects/{project_id}/learner-profiles",
        headers=headers,
        files={"file": ("student_profile.docx", b"fake-docx-content", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        data={"title": "学生学情", "subject_scope": "english"},
    )

    list_response = client.get(f"/api/v1/tasks?project_id={project_id}", headers=headers)
    assert list_response.status_code == 200
    payload = list_response.json()["data"]
    assert payload["pagination"]["total_count"] >= 1
    task_id = payload["items"][0]["id"]

    detail_response = client.get(f"/api/v1/tasks/{task_id}", headers=headers)
    assert detail_response.status_code == 200
    detail_payload = detail_response.json()["data"]
    assert detail_payload["task_type"] == "learner_profile_extract"
    assert [step["step_code"] for step in detail_payload["steps"]] == [
        "prepare_source",
        "extract_local",
        "build_profile_version",
    ]
