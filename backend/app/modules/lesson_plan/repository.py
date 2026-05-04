"""
@Date: 2026-05-04
@Author: xisy
@Discription: 教案模块数据访问层
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.p0_models import (
    ChapterNode,
    CurriculumPlan,
    GenerationBatch,
    KnowledgePoint,
    LearnerProfileRecord,
    LearnerProfileVersion,
    LessonPlan,
    Project,
)


class LessonPlanRepository:
    """教案模块仓储。"""

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

    def get_curriculum_plan(self, curriculum_plan_id: int) -> CurriculumPlan | None:
        """按主键查询课程大纲。"""
        statement = select(CurriculumPlan).where(CurriculumPlan.id == curriculum_plan_id)
        return self.session.scalar(statement)

    def get_learner_profile_version(self, learner_profile_version_id: int) -> LearnerProfileVersion | None:
        """按主键查询学情版本。"""
        statement = select(LearnerProfileVersion).where(LearnerProfileVersion.id == learner_profile_version_id)
        return self.session.scalar(statement)

    def list_knowledge_points(self, knowledge_version_id: int) -> list[KnowledgePoint]:
        """查询知识版本下知识点。"""
        statement = (
            select(KnowledgePoint)
            .where(KnowledgePoint.knowledge_version_id == knowledge_version_id)
            .order_by(KnowledgePoint.sort_order.asc(), KnowledgePoint.id.asc())
        )
        return list(self.session.scalars(statement))

    def list_chapter_nodes(self, knowledge_version_id: int) -> list[ChapterNode]:
        """查询知识版本下章节节点。"""
        statement = (
            select(ChapterNode)
            .where(ChapterNode.knowledge_version_id == knowledge_version_id)
            .order_by(ChapterNode.node_path.asc(), ChapterNode.id.asc())
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

    def get_next_lesson_plan_version_no(self, curriculum_plan_id: int) -> int:
        """获取课程大纲下一个教案版本号。"""
        statement = select(func.max(LessonPlan.version_no)).where(LessonPlan.curriculum_plan_id == curriculum_plan_id)
        current_max = self.session.scalar(statement)
        return int(current_max or 0) + 1

    def create_lesson_plan(self, lesson_plan: LessonPlan) -> LessonPlan:
        """创建教案。"""
        self.session.add(lesson_plan)
        self.session.flush()
        return lesson_plan

    def list_lesson_plans_by_batch(self, generation_batch_id: int) -> list[LessonPlan]:
        """查询批次下全部教案。"""
        statement = (
            select(LessonPlan)
            .where(LessonPlan.generation_batch_id == generation_batch_id)
            .order_by(LessonPlan.class_session_no.asc(), LessonPlan.id.asc())
        )
        return list(self.session.scalars(statement))

    def get_curriculum_plan_for_owner(self, curriculum_plan_id: int, owner_user_id: int) -> CurriculumPlan | None:
        """查询当前教师可见的课程大纲。"""
        statement = (
            select(CurriculumPlan)
            .join(Project, Project.id == CurriculumPlan.project_id)
            .where(CurriculumPlan.id == curriculum_plan_id, Project.owner_user_id == owner_user_id)
        )
        return self.session.scalar(statement)

    def get_lesson_plan_for_owner(self, lesson_plan_id: int, owner_user_id: int) -> LessonPlan | None:
        """查询当前教师可见的教案。"""
        statement = (
            select(LessonPlan)
            .join(CurriculumPlan, CurriculumPlan.id == LessonPlan.curriculum_plan_id)
            .join(Project, Project.id == CurriculumPlan.project_id)
            .where(LessonPlan.id == lesson_plan_id, Project.owner_user_id == owner_user_id)
        )
        return self.session.scalar(statement)

    def list_lesson_plans_for_owner(
        self,
        owner_user_id: int,
        *,
        curriculum_plan_id: int,
        offset: int,
        limit: int,
    ) -> list[LessonPlan]:
        """分页查询当前教师可见的教案。"""
        statement = (
            select(LessonPlan)
            .join(CurriculumPlan, CurriculumPlan.id == LessonPlan.curriculum_plan_id)
            .join(Project, Project.id == CurriculumPlan.project_id)
            .where(Project.owner_user_id == owner_user_id, LessonPlan.curriculum_plan_id == curriculum_plan_id)
            .order_by(LessonPlan.class_session_no.asc(), LessonPlan.version_no.asc(), LessonPlan.id.asc())
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.scalars(statement))

    def count_lesson_plans_for_owner(self, owner_user_id: int, *, curriculum_plan_id: int) -> int:
        """统计当前教师可见的教案数量。"""
        statement = (
            select(func.count())
            .select_from(LessonPlan)
            .join(CurriculumPlan, CurriculumPlan.id == LessonPlan.curriculum_plan_id)
            .join(Project, Project.id == CurriculumPlan.project_id)
            .where(Project.owner_user_id == owner_user_id, LessonPlan.curriculum_plan_id == curriculum_plan_id)
        )
        return int(self.session.scalar(statement) or 0)

    def save(self, instance) -> None:
        """保存实体。"""
        self.session.add(instance)
        self.session.flush()
