"""
@Date: 2026-04-13
@Author: xisy
@Discription: 本地 bootstrap 能力测试
"""

from sqlalchemy import delete, func, select

from app.core.bootstrap import DEMO_TEACHER_PASSWORD, DEMO_TEACHER_USERNAME, ensure_demo_teacher
from app.core.security import verify_password
from app.modules.auth.models import SysUser


def test_ensure_demo_teacher_should_be_idempotent(mysql_session_factory) -> None:
    """演示教师账号初始化应保持幂等。"""
    session = mysql_session_factory()
    try:
        session.execute(delete(SysUser))
        session.commit()

        first_result = ensure_demo_teacher(session)
        second_result = ensure_demo_teacher(session)

        assert first_result.action == "created"
        assert second_result.action == "unchanged"

        total_count = session.scalar(select(func.count()).select_from(SysUser))
        assert total_count == 1

        user = session.scalar(select(SysUser).where(SysUser.username == DEMO_TEACHER_USERNAME))
        assert user is not None
        assert user.display_name == "示例教师"
        assert user.role_code == "teacher"
        assert user.status == "active"
        assert verify_password(DEMO_TEACHER_PASSWORD, user.password_hash) is True
    finally:
        session.close()
