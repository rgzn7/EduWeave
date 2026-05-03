"""
@Date: 2026-04-26
@Author: xisy
@Discription: 生成编排模块数据访问层
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.p0_models import GenerationBatch, KnowledgeVersion, LearnerProfileVersion, LessonPlan, Project


class PipelineRepository:
    """生成编排模块仓储。"""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_project_for_owner(self, project_id: int, owner_user_id: int) -> Project | None:
        """查询当前教师拥有的项目。"""
        statement = select(Project).where(Project.id == project_id, Project.owner_user_id == owner_user_id)
        return self.session.scalar(statement)

    def get_knowledge_version_in_project(self, project_id: int, knowledge_version_id: int) -> KnowledgeVersion | None:
        """查询项目下知识版本。"""
        statement = select(KnowledgeVersion).where(
            KnowledgeVersion.id == knowledge_version_id,
            KnowledgeVersion.project_id == project_id,
        )
        return self.session.scalar(statement)

    def get_learner_profile_version_in_project(
        self,
        project_id: int,
        learner_profile_version_id: int,
    ) -> LearnerProfileVersion | None:
        """查询项目下学情版本。"""
        statement = select(LearnerProfileVersion).where(
            LearnerProfileVersion.id == learner_profile_version_id,
            LearnerProfileVersion.project_id == project_id,
        )
        return self.session.scalar(statement)

    def get_next_batch_no(self, project_id: int) -> int:
        """获取项目下一个生成批次号。"""
        statement = select(func.max(GenerationBatch.batch_no)).where(GenerationBatch.project_id == project_id)
        current_max = self.session.scalar(statement)
        return int(current_max or 0) + 1

    def create_generation_batch(self, generation_batch: GenerationBatch) -> GenerationBatch:
        """创建生成批次。"""
        self.session.add(generation_batch)
        self.session.flush()
        return generation_batch

    def get_generation_batch_for_owner(self, generation_batch_id: int, owner_user_id: int) -> GenerationBatch | None:
        """查询当前教师可见的生成批次。"""
        statement = (
            select(GenerationBatch)
            .join(Project, Project.id == GenerationBatch.project_id)
            .where(GenerationBatch.id == generation_batch_id, Project.owner_user_id == owner_user_id)
        )
        return self.session.scalar(statement)

    def list_generation_batches_for_owner(
        self,
        owner_user_id: int,
        *,
        project_id: int,
        offset: int,
        limit: int,
    ) -> list[GenerationBatch]:
        """分页查询当前教师可见的生成批次。"""
        statement = (
            select(GenerationBatch)
            .join(Project, Project.id == GenerationBatch.project_id)
            .where(Project.owner_user_id == owner_user_id, GenerationBatch.project_id == project_id)
            .order_by(GenerationBatch.batch_no.desc(), GenerationBatch.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.scalars(statement))

    def count_generation_batches_for_owner(self, owner_user_id: int, *, project_id: int) -> int:
        """统计当前教师可见的生成批次数量。"""
        statement = (
            select(func.count())
            .select_from(GenerationBatch)
            .join(Project, Project.id == GenerationBatch.project_id)
            .where(Project.owner_user_id == owner_user_id, GenerationBatch.project_id == project_id)
        )
        return int(self.session.scalar(statement) or 0)

    def list_lesson_plan_ids_by_batch(self, generation_batch_id: int) -> list[int]:
        """查询批次下全部教案主键。"""
        statement = (
            select(LessonPlan.id)
            .where(LessonPlan.generation_batch_id == generation_batch_id)
            .order_by(LessonPlan.class_session_no.asc(), LessonPlan.id.asc())
        )
        return [int(lesson_plan_id) for lesson_plan_id in self.session.scalars(statement)]

    def save(self, instance) -> None:
        """保存实体。"""
        self.session.add(instance)
        self.session.flush()
