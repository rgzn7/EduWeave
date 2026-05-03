"""
@Date: 2026-04-29
@Author: xisy
@Discription: 测评模块数据访问层
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.p0_models import (
    AssessmentBlueprint,
    CurriculumPlan,
    GenerationBatch,
    KnowledgePoint,
    LessonPlan,
    PaperResult,
    Project,
    QuestionItem,
)


class AssessmentRepository:
    """测评模块仓储。"""

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

    def get_lesson_plan(self, lesson_plan_id: int) -> LessonPlan | None:
        """按主键查询教案。"""
        statement = select(LessonPlan).where(LessonPlan.id == lesson_plan_id)
        return self.session.scalar(statement)

    def list_knowledge_points(self, knowledge_version_id: int) -> list[KnowledgePoint]:
        """查询知识版本下知识点。"""
        statement = (
            select(KnowledgePoint)
            .where(KnowledgePoint.knowledge_version_id == knowledge_version_id)
            .order_by(KnowledgePoint.sort_order.asc(), KnowledgePoint.id.asc())
        )
        return list(self.session.scalars(statement))

    def get_next_blueprint_version_no(self, curriculum_plan_id: int, scenario_type: str) -> int:
        """获取指定课程大纲与场景下一个蓝图版本号。"""
        statement = select(func.max(AssessmentBlueprint.version_no)).where(
            AssessmentBlueprint.curriculum_plan_id == curriculum_plan_id,
            AssessmentBlueprint.scenario_type == scenario_type,
        )
        current_max = self.session.scalar(statement)
        return int(current_max or 0) + 1

    def create_assessment_blueprint(self, blueprint: AssessmentBlueprint) -> AssessmentBlueprint:
        """创建测评蓝图。"""
        self.session.add(blueprint)
        self.session.flush()
        return blueprint

    def create_paper_result(self, paper_result: PaperResult) -> PaperResult:
        """创建试卷结果。"""
        self.session.add(paper_result)
        self.session.flush()
        return paper_result

    def create_question_items(self, question_items: list[QuestionItem]) -> list[QuestionItem]:
        """批量创建题目明细。"""
        self.session.add_all(question_items)
        self.session.flush()
        return question_items

    def get_curriculum_plan_for_owner(self, curriculum_plan_id: int, owner_user_id: int) -> CurriculumPlan | None:
        """查询当前教师可见的课程大纲。"""
        statement = (
            select(CurriculumPlan)
            .join(Project, Project.id == CurriculumPlan.project_id)
            .where(CurriculumPlan.id == curriculum_plan_id, Project.owner_user_id == owner_user_id)
        )
        return self.session.scalar(statement)

    def get_generation_batch_for_owner(self, generation_batch_id: int, owner_user_id: int) -> GenerationBatch | None:
        """查询当前教师可见的生成批次。"""
        statement = (
            select(GenerationBatch)
            .join(Project, Project.id == GenerationBatch.project_id)
            .where(GenerationBatch.id == generation_batch_id, Project.owner_user_id == owner_user_id)
        )
        return self.session.scalar(statement)

    def get_assessment_blueprint_for_owner(
        self,
        assessment_blueprint_id: int,
        owner_user_id: int,
    ) -> AssessmentBlueprint | None:
        """查询当前教师可见的测评蓝图。"""
        statement = (
            select(AssessmentBlueprint)
            .join(CurriculumPlan, CurriculumPlan.id == AssessmentBlueprint.curriculum_plan_id)
            .join(Project, Project.id == CurriculumPlan.project_id)
            .where(AssessmentBlueprint.id == assessment_blueprint_id, Project.owner_user_id == owner_user_id)
        )
        return self.session.scalar(statement)

    def list_assessment_blueprints_for_owner(
        self,
        owner_user_id: int,
        *,
        curriculum_plan_id: int,
        scenario_type: str | None,
        offset: int,
        limit: int,
    ) -> list[AssessmentBlueprint]:
        """分页查询当前教师可见的测评蓝图。"""
        statement = (
            select(AssessmentBlueprint)
            .join(CurriculumPlan, CurriculumPlan.id == AssessmentBlueprint.curriculum_plan_id)
            .join(Project, Project.id == CurriculumPlan.project_id)
            .where(Project.owner_user_id == owner_user_id, AssessmentBlueprint.curriculum_plan_id == curriculum_plan_id)
        )
        if scenario_type:
            statement = statement.where(AssessmentBlueprint.scenario_type == scenario_type)
        statement = statement.order_by(AssessmentBlueprint.version_no.desc(), AssessmentBlueprint.id.desc()).offset(offset).limit(limit)
        return list(self.session.scalars(statement))

    def count_assessment_blueprints_for_owner(
        self,
        owner_user_id: int,
        *,
        curriculum_plan_id: int,
        scenario_type: str | None,
    ) -> int:
        """统计当前教师可见的测评蓝图数量。"""
        statement = (
            select(func.count())
            .select_from(AssessmentBlueprint)
            .join(CurriculumPlan, CurriculumPlan.id == AssessmentBlueprint.curriculum_plan_id)
            .join(Project, Project.id == CurriculumPlan.project_id)
            .where(Project.owner_user_id == owner_user_id, AssessmentBlueprint.curriculum_plan_id == curriculum_plan_id)
        )
        if scenario_type:
            statement = statement.where(AssessmentBlueprint.scenario_type == scenario_type)
        return int(self.session.scalar(statement) or 0)

    def get_paper_result_for_owner(self, paper_result_id: int, owner_user_id: int) -> PaperResult | None:
        """查询当前教师可见的试卷结果。"""
        statement = (
            select(PaperResult)
            .join(GenerationBatch, GenerationBatch.id == PaperResult.generation_batch_id)
            .join(Project, Project.id == GenerationBatch.project_id)
            .where(PaperResult.id == paper_result_id, Project.owner_user_id == owner_user_id)
        )
        return self.session.scalar(statement)

    def list_paper_results_for_owner(
        self,
        owner_user_id: int,
        *,
        generation_batch_id: int,
        scene_type: str | None,
        offset: int,
        limit: int,
    ) -> list[PaperResult]:
        """分页查询当前教师可见的试卷结果。"""
        statement = (
            select(PaperResult)
            .join(GenerationBatch, GenerationBatch.id == PaperResult.generation_batch_id)
            .join(Project, Project.id == GenerationBatch.project_id)
            .where(Project.owner_user_id == owner_user_id, PaperResult.generation_batch_id == generation_batch_id)
        )
        if scene_type:
            statement = statement.where(PaperResult.scene_type == scene_type)
        statement = statement.order_by(PaperResult.created_at.desc(), PaperResult.id.desc()).offset(offset).limit(limit)
        return list(self.session.scalars(statement))

    def count_paper_results_for_owner(
        self,
        owner_user_id: int,
        *,
        generation_batch_id: int,
        scene_type: str | None,
    ) -> int:
        """统计当前教师可见的试卷结果数量。"""
        statement = (
            select(func.count())
            .select_from(PaperResult)
            .join(GenerationBatch, GenerationBatch.id == PaperResult.generation_batch_id)
            .join(Project, Project.id == GenerationBatch.project_id)
            .where(Project.owner_user_id == owner_user_id, PaperResult.generation_batch_id == generation_batch_id)
        )
        if scene_type:
            statement = statement.where(PaperResult.scene_type == scene_type)
        return int(self.session.scalar(statement) or 0)

    def list_question_items(self, paper_result_id: int) -> list[QuestionItem]:
        """查询试卷题目明细。"""
        statement = (
            select(QuestionItem)
            .where(QuestionItem.paper_result_id == paper_result_id)
            .order_by(QuestionItem.question_no.asc(), QuestionItem.id.asc())
        )
        return list(self.session.scalars(statement))

    def save(self, instance) -> None:
        """保存实体。"""
        self.session.add(instance)
        self.session.flush()
