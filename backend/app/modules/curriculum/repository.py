"""
@Date: 2026-04-26
@Author: xisy
@Discription: 课程大纲模块数据访问层
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.p0_models import (
    ChapterNode,
    CurriculumPlan,
    GenerationBatch,
    KnowledgePoint,
    KnowledgeVersion,
    LearnerProfileRecord,
    LearnerProfileVersion,
    Project,
)


class CurriculumRepository:
    """课程大纲模块仓储。"""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_generation_batch(self, generation_batch_id: int) -> GenerationBatch | None:
        """按主键查询生成批次。"""
        statement = select(GenerationBatch).where(GenerationBatch.id == generation_batch_id)
        return self.session.scalar(statement)

    def get_project(self, project_id: int) -> Project | None:
        """按主键查询项目。"""
        statement = select(Project).where(Project.id == project_id)
        return self.session.scalar(statement)

    def get_knowledge_version(self, knowledge_version_id: int) -> KnowledgeVersion | None:
        """按主键查询知识版本。"""
        statement = select(KnowledgeVersion).where(KnowledgeVersion.id == knowledge_version_id)
        return self.session.scalar(statement)

    def get_learner_profile_version(self, learner_profile_version_id: int) -> LearnerProfileVersion | None:
        """按主键查询学情版本。"""
        statement = select(LearnerProfileVersion).where(LearnerProfileVersion.id == learner_profile_version_id)
        return self.session.scalar(statement)

    def list_chapter_nodes(self, knowledge_version_id: int) -> list[ChapterNode]:
        """查询知识版本下章节节点。"""
        statement = (
            select(ChapterNode)
            .where(ChapterNode.knowledge_version_id == knowledge_version_id)
            .order_by(ChapterNode.node_path.asc(), ChapterNode.id.asc())
        )
        return list(self.session.scalars(statement))

    def list_knowledge_points(self, knowledge_version_id: int) -> list[KnowledgePoint]:
        """查询知识版本下知识点。"""
        statement = (
            select(KnowledgePoint)
            .where(KnowledgePoint.knowledge_version_id == knowledge_version_id)
            .order_by(KnowledgePoint.sort_order.asc(), KnowledgePoint.id.asc())
        )
        return list(self.session.scalars(statement))

    def list_profile_records(self, learner_profile_version_id: int) -> list[LearnerProfileRecord]:
        """查询学情版本下画像记录。"""
        statement = (
            select(LearnerProfileRecord)
            .where(LearnerProfileRecord.profile_version_id == learner_profile_version_id)
            .order_by(LearnerProfileRecord.sort_order.asc(), LearnerProfileRecord.id.asc())
        )
        return list(self.session.scalars(statement))

    def get_next_curriculum_version_no(self, project_id: int) -> int:
        """获取项目下一个课程大纲版本号。"""
        statement = select(func.max(CurriculumPlan.version_no)).where(CurriculumPlan.project_id == project_id)
        current_max = self.session.scalar(statement)
        return int(current_max or 0) + 1

    def create_curriculum_plan(self, curriculum_plan: CurriculumPlan) -> CurriculumPlan:
        """创建课程大纲。"""
        self.session.add(curriculum_plan)
        self.session.flush()
        return curriculum_plan

    def get_curriculum_plan_for_owner(self, curriculum_plan_id: int, owner_user_id: int) -> CurriculumPlan | None:
        """查询当前教师可见的课程大纲。"""
        statement = (
            select(CurriculumPlan)
            .join(Project, Project.id == CurriculumPlan.project_id)
            .where(CurriculumPlan.id == curriculum_plan_id, Project.owner_user_id == owner_user_id)
        )
        return self.session.scalar(statement)

    def list_curriculum_plans_for_owner(
        self,
        owner_user_id: int,
        *,
        project_id: int,
        knowledge_version_id: int | None,
        offset: int,
        limit: int,
    ) -> list[CurriculumPlan]:
        """分页查询当前教师可见的课程大纲。"""
        statement = (
            select(CurriculumPlan)
            .join(Project, Project.id == CurriculumPlan.project_id)
            .where(Project.owner_user_id == owner_user_id, CurriculumPlan.project_id == project_id)
        )
        if knowledge_version_id is not None:
            statement = statement.where(CurriculumPlan.knowledge_version_id == knowledge_version_id)
        statement = statement.order_by(CurriculumPlan.version_no.desc(), CurriculumPlan.id.desc()).offset(offset).limit(limit)
        return list(self.session.scalars(statement))

    def count_curriculum_plans_for_owner(
        self,
        owner_user_id: int,
        *,
        project_id: int,
        knowledge_version_id: int | None,
    ) -> int:
        """统计当前教师可见的课程大纲数量。"""
        statement = (
            select(func.count())
            .select_from(CurriculumPlan)
            .join(Project, Project.id == CurriculumPlan.project_id)
            .where(Project.owner_user_id == owner_user_id, CurriculumPlan.project_id == project_id)
        )
        if knowledge_version_id is not None:
            statement = statement.where(CurriculumPlan.knowledge_version_id == knowledge_version_id)
        return int(self.session.scalar(statement) or 0)

    def save(self, instance) -> None:
        """保存实体。"""
        self.session.add(instance)
        self.session.flush()
