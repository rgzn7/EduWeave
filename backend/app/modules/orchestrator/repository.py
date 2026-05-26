"""
@Date: 2026-05-26
@Author: xisy
@Discription: 一键生成编排模块数据访问层
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.p0_models import GenerationRun, Project


# 「活跃」运行的状态集合：仍在推进或在等待用户确认
ACTIVE_RUN_STATUSES: tuple[str, ...] = ("pending", "running", "waiting_user_confirm")


class OrchestratorRepository:
    """一键生成编排仓储。"""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_run(self, run_id: int) -> GenerationRun | None:
        """按主键查询运行。"""
        return self.session.get(GenerationRun, run_id)

    def get_active_run_for_project(self, project_id: int) -> GenerationRun | None:
        """查询项目当前活跃运行；无则返回 None。"""
        statement = (
            select(GenerationRun)
            .where(
                GenerationRun.project_id == project_id,
                GenerationRun.run_status.in_(ACTIVE_RUN_STATUSES),
            )
            .order_by(GenerationRun.created_at.desc(), GenerationRun.id.desc())
            .limit(1)
        )
        return self.session.scalar(statement)

    def get_latest_run_for_project(self, project_id: int) -> GenerationRun | None:
        """查询项目最近一次运行（不区分状态），用于 generation-process 兜底展示。"""
        statement = (
            select(GenerationRun)
            .where(GenerationRun.project_id == project_id)
            .order_by(GenerationRun.created_at.desc(), GenerationRun.id.desc())
            .limit(1)
        )
        return self.session.scalar(statement)

    def lock_project_for_run(self, project_id: int, owner_user_id: int) -> Project | None:
        """以 SELECT FOR UPDATE 锁住 project 行，作为单 project 单活跃 run 的应用层互斥锚点。

        SQLite 测试场景不支持 SELECT FOR UPDATE，此处使用 with_for_update(read=False)，
        在不支持的方言下会自动退化为普通 select。
        """
        statement = (
            select(Project)
            .where(Project.id == project_id, Project.owner_user_id == owner_user_id)
            .with_for_update()
        )
        return self.session.scalar(statement)

    def create_run(self, run: GenerationRun) -> GenerationRun:
        """创建运行记录。"""
        self.session.add(run)
        self.session.flush()
        return run

    def save(self, instance) -> None:
        """保存实体。"""
        self.session.add(instance)
        self.session.flush()
