"""
@Date: 2026-04-11
@Author: xisy
@Discription: 认证模块路由
"""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.database import get_db_session
from app.core.security import get_current_user
from app.modules.auth.models import SysUser
from app.modules.auth.repository import AuthRepository
from app.modules.auth.schemas import LoginRequest, LoginResponse, TeacherUserResponse
from app.modules.auth.service import AuthService
from app.schemas.response import ApiResponse, ResponseFactory

router = APIRouter(prefix="/auth", tags=["认证"])


def get_auth_service(session: Annotated[Session, Depends(get_db_session)]) -> AuthService:
    """构造认证服务依赖。"""
    repository = AuthRepository(session)
    return AuthService(repository)


@router.post(
    "/login",
    summary="教师账号登录",
    description="教师使用账号密码登录系统，返回访问令牌和当前教师基础信息。",
    operation_id="auth_login",
    response_model=ApiResponse[LoginResponse],
    status_code=status.HTTP_200_OK,
)
def login(
    request: LoginRequest,
    service: Annotated[AuthService, Depends(get_auth_service)],
):
    """执行教师账号登录。"""
    result = service.login(request.username, request.password)
    return ResponseFactory.success(result.model_dump(), "登录成功")


@router.get(
    "/me",
    summary="获取当前教师信息",
    description="根据当前访问令牌获取已登录教师的基础账号信息。",
    operation_id="auth_me",
    response_model=ApiResponse[TeacherUserResponse],
    status_code=status.HTTP_200_OK,
)
def get_me(
    current_user: Annotated[SysUser, Depends(get_current_user)],
):
    """获取当前登录教师信息。"""
    return ResponseFactory.success(
        AuthService.build_user_response(current_user).model_dump(),
        "获取当前用户信息成功",
    )
