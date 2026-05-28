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


DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def test_learner_profile_upload_should_extract_placeholder_result(client, stub_class_profile_llm) -> None:
    """上传单份学情文件应自动产生真实结构化结果并完成班级聚合。"""
    headers = build_auth_headers(client)
    project_id = create_project(client, headers)

    response = client.post(
        f"/api/v1/projects/{project_id}/learner-profiles",
        headers=headers,
        files=[("files", ("student_profile.docx", b"fake-docx-content", DOCX_MIME))],
        data={"title": "三年级一班", "subject_scope": "english"},
    )

    assert response.status_code == 201
    payload = response.json()["data"]
    assert payload["title"] == "三年级一班"
    assert payload["latest_version"]["extract_status"] == "success"
    subject_codes = {item["subject_code"] for item in payload["latest_version"]["records"]}
    assert subject_codes == {"chinese", "math"}
    assert len(payload["latest_version"]["records"]) == 2
    # 班级聚合结果应被 surface
    assert payload["latest_version"]["class_profile"] is not None

    version_id = payload["latest_version"]["id"]
    version_response = client.get(f"/api/v1/learner-profile-versions/{version_id}", headers=headers)
    assert version_response.status_code == 200
    first_student_key = version_response.json()["data"]["records"][0]["student_key"]
    assert first_student_key.startswith("s1_")
    assert "王xx" in first_student_key


def test_learner_profile_upload_multiple_students_should_build_class_version(client, stub_class_profile_llm) -> None:
    """上传多份学生 docx 应聚合到同一个班级版本且学生标识不冲突。"""
    headers = build_auth_headers(client)
    project_id = create_project(client, headers)

    response = client.post(
        f"/api/v1/projects/{project_id}/learner-profiles",
        headers=headers,
        files=[
            ("files", ("student_1.docx", b"fake-docx-1", DOCX_MIME)),
            ("files", ("student_2.docx", b"fake-docx-2", DOCX_MIME)),
        ],
        data={"title": "三年级一班"},
    )

    assert response.status_code == 201
    payload = response.json()["data"]
    version = payload["latest_version"]
    assert version["extract_status"] == "success"
    # 2 名学生 × 2 学科 = 4 条记录，且 student_key 通过序号前缀去重
    records = version["records"]
    assert len(records) == 4
    student_keys = {item["student_key"] for item in records}
    assert len(student_keys) == 4
    assert any(key.startswith("s1_") for key in student_keys)
    assert any(key.startswith("s2_") for key in student_keys)
    assert version["class_profile"] is not None
    assert version["summary_text"]


def test_learner_profile_upload_should_reject_invalid_textbook_hint(client) -> None:
    """传入无效教材提示版本应返回 422。"""
    headers = build_auth_headers(client)
    project_id = create_project(client, headers)

    response = client.post(
        f"/api/v1/projects/{project_id}/learner-profiles",
        headers=headers,
        files=[("files", ("student_profile.docx", b"fake-docx-content", DOCX_MIME))],
        data={"textbook_version_hint_id": 999},
    )

    assert response.status_code == 422
    assert response.json()["errors"][0]["code"] == "PROJECT_REFERENCE_INVALID"


def test_learner_profile_versions_and_manual_revision_should_succeed(client, stub_class_profile_llm) -> None:
    """学情版本列表和人工修正接口应返回新版本。"""
    headers = build_auth_headers(client)
    project_id = create_project(client, headers)

    upload_response = client.post(
        f"/api/v1/projects/{project_id}/learner-profiles",
        headers=headers,
        files=[("files", ("student_profile.docx", b"fake-docx-content", DOCX_MIME))],
        data={"title": "三年级一班", "subject_scope": "english,math"},
    )
    profile_file_id = upload_response.json()["data"]["id"]
    profile_version_id = upload_response.json()["data"]["latest_version"]["id"]

    versions_response = client.get(
        f"/api/v1/projects/{project_id}/learner-profiles/{profile_file_id}/versions",
        headers=headers,
    )
    assert versions_response.status_code == 200
    assert versions_response.json()["data"]["pagination"]["total_count"] == 1

    manual_revision_response = client.post(
        f"/api/v1/learner-profile-versions/{profile_version_id}/manual-revisions",
        headers=headers,
        json={
            "summary_text": "人工修正后的学情摘要",
            "records": [
                {
                    "student_key": "wangxx_english",
                    "student_name": "王xx",
                    "is_anonymous": True,
                    "region_name": "上海",
                    "grade_code": "grade_3",
                    "subject_code": "english",
                    "score_value": 88,
                    "advantage_tags_json": {"items": ["表达能力较强"]},
                    "weakness_tags_json": {"items": ["口语表达待提升"]},
                    "ability_tags_json": {"items": ["表达能力"]},
                    "habit_tags_json": {"items": ["作业完成及时"]},
                    "behavior_traits_json": {"items": ["性格开朗"]},
                    "time_plan_json": {"items": [{"subject_name": "英语"}]},
                    "summary_text": "英语人工修正摘要",
                    "evidence_json": {"source": "manual"},
                    "sort_order": 0,
                }
            ],
            "set_as_current": True,
        },
    )
    assert manual_revision_response.status_code == 201
    payload = manual_revision_response.json()["data"]
    assert payload["parent_version_id"] == profile_version_id
    assert payload["review_status"] == "confirmed"
    assert payload["summary_text"] == "人工修正后的学情摘要"
    assert payload["records"][0]["is_anonymous"] is True
