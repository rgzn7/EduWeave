"""
@Date: 2026-05-30
@Author: xisy
@Discription: 认证模块业务服务
"""

import secrets

from app.core.exceptions import AppException, BusinessErrorCode
from app.core.security import create_access_token, hash_password, verify_password
from app.modules.auth.models import SysUser
from app.modules.auth.repository import AuthRepository
from app.modules.auth.schemas import LoginResponse, TeacherUserResponse

DEMO_TEACHER_USERNAME = "teacher_demo"
DEMO_TEACHER_DISPLAY_NAME = "示例教师"


class AuthService:
    """认证服务。"""

    def __init__(self, repository: AuthRepository) -> None:
        self.repository = repository

    def login(self, username: str, password: str) -> LoginResponse:
        """执行教师账号登录。"""
        user = self.repository.get_by_username(username)
        if user is None or not verify_password(password, user.password_hash):
            raise AppException(BusinessErrorCode.INVALID_CREDENTIALS, "用户名或密码错误")
        if user.status != "active":
            raise AppException(BusinessErrorCode.ACCOUNT_DISABLED, "当前账号已被禁用")
        if user.role_code != "teacher":
            raise AppException(BusinessErrorCode.UNAUTHORIZED, "当前账号不是教师账号")

        token, expires_in = create_access_token(user)
        self.repository.update_last_login(user)
        return LoginResponse(
            access_token=token,
            token_type="Bearer",
            expires_in=expires_in,
            user=TeacherUserResponse.model_validate(user, from_attributes=True),
        )

    def create_demo_session(self) -> LoginResponse:
        """创建免输入账号密码的演示教师会话。"""
        user = self.repository.get_by_username(DEMO_TEACHER_USERNAME)
        if user is None:
            user = SysUser(
                username=DEMO_TEACHER_USERNAME,
                display_name=DEMO_TEACHER_DISPLAY_NAME,
                password_hash=hash_password(secrets.token_urlsafe(32)),
                role_code="teacher",
                status="active",
            )
            user = self.repository.save_user(user)
        elif user.role_code != "teacher" or user.status != "active" or user.display_name != DEMO_TEACHER_DISPLAY_NAME:
            user.role_code = "teacher"
            user.status = "active"
            user.display_name = DEMO_TEACHER_DISPLAY_NAME
            user = self.repository.save_user(user)

        token, expires_in = create_access_token(user)
        self.repository.update_last_login(user)
        return LoginResponse(
            access_token=token,
            token_type="Bearer",
            expires_in=expires_in,
            user=TeacherUserResponse.model_validate(user, from_attributes=True),
        )

    @staticmethod
    def build_user_response(user) -> TeacherUserResponse:
        """构造当前用户响应。"""
        return TeacherUserResponse.model_validate(user, from_attributes=True)
