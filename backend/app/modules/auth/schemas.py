"""
@Date: 2026-04-11
@Author: xisy
@Discription: 认证模块请求与响应模型
"""

from pydantic import Field

from app.schemas.base import BaseSchema


class LoginRequest(BaseSchema):
    """登录请求模型。"""

    username: str = Field(description="登录账号", min_length=3, max_length=64, examples=["teacher_demo"])
    password: str = Field(description="登录密码", min_length=6, max_length=128, examples=["Teacher@123"])


class TeacherUserResponse(BaseSchema):
    """教师账号响应模型。"""

    id: int = Field(description="教师账号主键", examples=[1])
    username: str = Field(description="教师登录账号", examples=["teacher_demo"])
    display_name: str = Field(description="教师显示名称", examples=["示例教师"])
    role_code: str = Field(description="角色编码，当前阶段固定为 teacher", examples=["teacher"])
    status: str = Field(description="账号状态", examples=["active"])


class LoginResponse(BaseSchema):
    """登录结果模型。"""

    access_token: str = Field(description="访问令牌", examples=["eyJhbGciOiJIUzI1NiJ9.xxx.yyy"])
    token_type: str = Field(default="Bearer", description="令牌类型", examples=["Bearer"])
    expires_in: int = Field(description="过期秒数", examples=[7200])
    user: TeacherUserResponse = Field(description="当前教师信息")
