"""
@Date: 2026-04-11
@Author: xisy
@Discription: 认证接口测试
"""

from datetime import timedelta

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

