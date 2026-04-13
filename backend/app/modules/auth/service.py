"""
@Date: 2026-04-11
@Author: xisy
@Discription: 认证模块业务服务
"""

from app.core.exceptions import AppException, BusinessErrorCode
from app.core.security import create_access_token, verify_password
from app.modules.auth.repository import AuthRepository
from app.modules.auth.schemas import LoginResponse, TeacherUserResponse


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

    @staticmethod
    def build_user_response(user) -> TeacherUserResponse:
        """构造当前用户响应。"""
        return TeacherUserResponse.model_validate(user, from_attributes=True)

