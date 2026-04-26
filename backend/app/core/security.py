"""
@Date: 2026-04-14
@Author: xisy
@Discription: 认证、安全与当前用户依赖
"""

from datetime import timedelta
from typing import Any, Annotated

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import ExpiredSignatureError, InvalidTokenError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db_session
from app.core.exceptions import AppException, BusinessErrorCode
from app.core.middleware import set_user_id
from app.modules.auth.models import SysUser
from app.modules.auth.repository import AuthRepository
from app.shared.utils.datetime_util import DateTimeUtil

settings = get_settings()
security_scheme = HTTPBearer(auto_error=False)

try:
    from pwdlib import PasswordHash

    password_hasher = PasswordHash.recommended()
except ImportError:
    from argon2 import PasswordHasher
    from argon2.exceptions import VerifyMismatchError

    class PasswordHashCompat:
        """在 pwdlib 不可用时提供兼容哈希能力。"""

        def __init__(self) -> None:
            self._hasher = PasswordHasher()

        def hash(self, password: str) -> str:
            return self._hasher.hash(password)

        def verify(self, password: str, password_hash: str) -> bool:
            try:
                return self._hasher.verify(password_hash, password)
            except VerifyMismatchError:
                return False

    password_hasher = PasswordHashCompat()


def hash_password(password: str) -> str:
    """生成密码哈希。"""
    return password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """校验密码是否匹配。"""
    return password_hasher.verify(password, password_hash)


def create_access_token(user: SysUser) -> tuple[str, int]:
    """为教师账号创建访问令牌。"""
    expires_delta = timedelta(minutes=settings.jwt_access_token_expire_minutes)
    expires_at = DateTimeUtil.now_utc() + expires_delta
    payload: dict[str, Any] = {
        "sub": str(user.id),
        "username": user.username,
        "role_code": user.role_code,
        "exp": expires_at,
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, settings.jwt_access_token_expire_minutes * 60


def decode_access_token(token: str) -> dict[str, Any]:
    """解析访问令牌。"""
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except ExpiredSignatureError as exc:
        raise AppException(BusinessErrorCode.TOKEN_EXPIRED, "访问令牌已过期") from exc
    except InvalidTokenError as exc:
        raise AppException(BusinessErrorCode.INVALID_TOKEN, "无效的访问令牌") from exc


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security_scheme)],
    session: Annotated[Session, Depends(get_db_session)],
    request: Request,
) -> SysUser:
    """获取当前登录教师账号。"""
    if credentials is None:
        raise AppException(BusinessErrorCode.UNAUTHORIZED, "未提供访问令牌")

    payload = decode_access_token(credentials.credentials)
    try:
        user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError) as exc:
        raise AppException(BusinessErrorCode.INVALID_TOKEN, "无效的访问令牌") from exc
    repository = AuthRepository(session)
    user = repository.get_by_id(user_id)
    if user is None:
        raise AppException(BusinessErrorCode.UNAUTHORIZED, "当前用户不存在")
    if user.status != "active":
        raise AppException(BusinessErrorCode.ACCOUNT_DISABLED, "当前账号已被禁用")

    request.state.user_id = str(user.id)
    set_user_id(user.id)
    return user
