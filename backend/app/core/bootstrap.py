"""
@Date: 2026-04-13
@Author: xisy
@Discription: 本地开发 bootstrap 公共能力
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import hash_password, verify_password
from app.modules.auth.models import SysUser

DEMO_TEACHER_USERNAME = "teacher_demo"
DEMO_TEACHER_DISPLAY_NAME = "示例教师"
DEMO_TEACHER_PASSWORD = "Teacher@123"


@dataclass(slots=True)
class DemoTeacherSeedResult:
    """演示教师账号初始化结果。"""

    action: str
    user_id: int
    username: str


def ensure_demo_teacher(session: Session) -> DemoTeacherSeedResult:
    """幂等初始化本地演示教师账号。"""
    statement = select(SysUser).where(SysUser.username == DEMO_TEACHER_USERNAME)
    user = session.scalar(statement)

    if user is None:
        user = SysUser(
            username=DEMO_TEACHER_USERNAME,
            display_name=DEMO_TEACHER_DISPLAY_NAME,
            password_hash=hash_password(DEMO_TEACHER_PASSWORD),
            role_code="teacher",
            status="active",
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        return DemoTeacherSeedResult(action="created", user_id=user.id, username=user.username)

    updated = False
    if user.display_name != DEMO_TEACHER_DISPLAY_NAME:
        user.display_name = DEMO_TEACHER_DISPLAY_NAME
        updated = True
    if user.role_code != "teacher":
        user.role_code = "teacher"
        updated = True
    if user.status != "active":
        user.status = "active"
        updated = True
    if not verify_password(DEMO_TEACHER_PASSWORD, user.password_hash):
        user.password_hash = hash_password(DEMO_TEACHER_PASSWORD)
        updated = True

    if updated:
        session.add(user)
        session.commit()
        session.refresh(user)
        return DemoTeacherSeedResult(action="updated", user_id=user.id, username=user.username)

    return DemoTeacherSeedResult(action="unchanged", user_id=user.id, username=user.username)
