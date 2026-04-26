"""
@Date: 2026-04-14
@Author: xisy
@Discription: 认证接口测试
"""

from datetime import timedelta
import json

import jwt

from app.core.config import get_settings
from app.shared.utils.datetime_util import DateTimeUtil


def test_teacher_login_success(client) -> None:
    """教师账号应可成功登录。"""
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "teacher_demo", "password": "Teacher@123"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"]["user"]["username"] == "teacher_demo"
    assert payload["data"]["token_type"] == "Bearer"
    assert payload["data"]["access_token"]


def test_teacher_login_with_wrong_password_should_fail(client) -> None:
    """错误密码应返回鉴权失败。"""
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "teacher_demo", "password": "wrong-password"},
    )

    assert response.status_code == 401
    payload = response.json()
    assert payload["success"] is False
    assert payload["errors"][0]["code"] == "INVALID_CREDENTIALS"


def test_disabled_teacher_login_should_fail(client) -> None:
    """禁用教师账号应禁止登录。"""
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "teacher_disabled", "password": "Teacher@123"},
    )

    assert response.status_code == 403
    payload = response.json()
    assert payload["errors"][0]["code"] == "ACCOUNT_DISABLED"


def test_get_current_user_success(client) -> None:
    """有效令牌应能获取当前教师信息。"""
    login_response = client.post(
        "/api/v1/auth/login",
        json={"username": "teacher_demo", "password": "Teacher@123"},
    )
    access_token = login_response.json()["data"]["access_token"]

    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {access_token}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["username"] == "teacher_demo"
    assert payload["data"]["role_code"] == "teacher"


def test_get_current_user_with_invalid_token_should_fail(client) -> None:
    """无效令牌应返回 401。"""
    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer invalid-token"},
    )

    assert response.status_code == 401
    payload = response.json()
    assert payload["errors"][0]["code"] == "INVALID_TOKEN"


def test_get_current_user_with_expired_token_should_fail(client) -> None:
    """过期令牌应返回 401。"""
    settings = get_settings()
    expired_token = jwt.encode(
        {
            "sub": "1",
            "username": "teacher_demo",
            "role_code": "teacher",
            "exp": DateTimeUtil.now_utc() - timedelta(minutes=5),
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )

    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {expired_token}"},
    )

    assert response.status_code == 401
    payload = response.json()
    assert payload["errors"][0]["code"] == "TOKEN_EXPIRED"


def test_get_current_user_with_invalid_sub_should_fail(client) -> None:
    """sub 非法的令牌应返回 401。"""
    settings = get_settings()
    invalid_sub_token = jwt.encode(
        {
            "sub": "not-an-int",
            "username": "teacher_demo",
            "role_code": "teacher",
            "exp": DateTimeUtil.now_utc() + timedelta(minutes=5),
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )

    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {invalid_sub_token}"},
    )

    assert response.status_code == 401
    payload = response.json()
    assert payload["errors"][0]["code"] == "INVALID_TOKEN"


def test_access_log_should_include_request_id_and_user_id_for_authenticated_request(client, capfd) -> None:
    """鉴权接口访问日志应包含 request_id 与 user_id。"""
    login_response = client.post(
        "/api/v1/auth/login",
        json={"username": "teacher_demo", "password": "Teacher@123"},
    )
    login_payload = login_response.json()
    access_token = login_payload["data"]["access_token"]
    user_id = str(login_payload["data"]["user"]["id"])

    capfd.readouterr()
    request_id = "test-request-id-auth-me"
    response = client.get(
        "/api/v1/auth/me",
        headers={
            "Authorization": f"Bearer {access_token}",
            "X-Request-Id": request_id,
        },
    )

    assert response.status_code == 200
    assert response.headers["X-Request-Id"] == request_id

    captured = capfd.readouterr().out.splitlines()
    access_logs = []
    for line in captured:
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("event") == "请求处理完成" and record.get("path") == "/api/v1/auth/me":
            access_logs.append(record)

    assert access_logs
    assert access_logs[-1]["request_id"] == request_id
    assert access_logs[-1]["user_id"] == user_id
