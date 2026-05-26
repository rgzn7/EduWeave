"""
@Date: 2026-05-04
@Author: xisy
@Discription: 测评模块数据访问层
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.constants import ASSESSMENT_GENERATE_TASK_TYPE, ASSESSMENT_MODULE_CODE, TASK_STATUS_SUCCESS
from app.modules.p0_models import (
    AssessmentBlueprint,
    ChapterNode,
    CurriculumPlan,
    GenerationBatch,
    KnowledgePoint,
    LessonPlan,
    PaperResult,
    Project,
    QuestionItem,
    TaskRecord,
)


class AssessmentRepository:
    """测评模块仓储。"""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_generation_batch(self, generation_batch_id: int) -> GenerationBatch | None:
        """按主键查询生成批次。"""
        statement = select(GenerationBatch).where(GenerationBatch.id == generation_batch_id)
        return self.session.scalar(statement)

    def get_generation_batch_by_curriculum_plan(self, curriculum_plan_id: int) -> GenerationBatch | None:
        """按课程大纲查询所属生成批次。"""
        statement = (
            select(GenerationBatch)
            .where(GenerationBatch.curriculum_plan_id == curriculum_plan_id)
            .order_by(GenerationBatch.id.desc())
        )
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

    def list_lesson_plans_by_batch(self, generation_batch_id: int) -> list[LessonPlan]:
        """查询批次下全部教案。"""
        statement = (
            select(LessonPlan)
            .where(LessonPlan.generation_batch_id == generation_batch_id)
            .order_by(LessonPlan.class_session_no.asc(), LessonPlan.id.asc())
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

    def list_knowledge_points_by_ids(self, ids: list[int]) -> list[KnowledgePoint]:
        """按主键批量查询知识点。"""
        if not ids:
            return []
        statement = select(KnowledgePoint).where(KnowledgePoint.id.in_(ids))
        return list(self.session.scalars(statement))

    def list_chapter_nodes(self, knowledge_version_id: int) -> list[ChapterNode]:
        """查询知识版本下章节节点。"""
        statement = (
            select(ChapterNode)
            .where(ChapterNode.knowledge_version_id == knowledge_version_id)
            .order_by(ChapterNode.node_path.asc(), ChapterNode.id.asc())
        )
        return list(self.session.scalars(statement))

    def list_chapter_nodes_by_ids(self, ids: list[int]) -> list[ChapterNode]:
        """按主键批量查询章节节点。"""
        if not ids:
            return []
        statement = select(ChapterNode).where(ChapterNode.id.in_(ids))
        return list(self.session.scalars(statement))

    def get_assessment_blueprint(self, assessment_blueprint_id: int) -> AssessmentBlueprint | None:
        """按主键查询测评蓝图。"""
        statement = select(AssessmentBlueprint).where(AssessmentBlueprint.id == assessment_blueprint_id)
        return self.session.scalar(statement)

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

    def get_success_paper_result_by_batch_scene(self, generation_batch_id: int, scene_type: str) -> PaperResult | None:
        """查询批次下指定场景已成功试卷。"""
        statement = select(PaperResult).where(
            PaperResult.generation_batch_id == generation_batch_id,
            PaperResult.scene_type == scene_type,
            PaperResult.result_status == TASK_STATUS_SUCCESS,
        )
        return self.session.scalar(statement)

    def get_active_assessment_task(self, generation_batch_id: int, scene_type: str) -> TaskRecord | None:
        """查询批次下指定场景运行中的测评任务。"""
        statement = (
            select(TaskRecord)
            .where(
                TaskRecord.generation_batch_id == generation_batch_id,
                TaskRecord.module_code == ASSESSMENT_MODULE_CODE,
                TaskRecord.task_type == ASSESSMENT_GENERATE_TASK_TYPE,
                TaskRecord.biz_key == f"generation_batch:{generation_batch_id}:assessment:{scene_type}",
                TaskRecord.task_status.in_(["pending", "processing"]),
            )
            .order_by(TaskRecord.id.desc())
        )
        return self.session.scalar(statement)

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

    def list_question_items_for_owner(
        self,
        owner_user_id: int,
        *,
        generation_batch_id: int | None,
        paper_result_id: int | None,
        knowledge_point_id: int | None,
        question_type: str | None,
        difficulty_level: int | None,
        scene_type: str | None,
        offset: int,
        limit: int,
    ) -> list[tuple[QuestionItem, PaperResult]]:
        """分页查询当前教师可见的题目与所属试卷。"""
        statement = (
            select(QuestionItem, PaperResult)
            .join(PaperResult, PaperResult.id == QuestionItem.paper_result_id)
            .join(GenerationBatch, GenerationBatch.id == QuestionItem.generation_batch_id)
            .join(Project, Project.id == GenerationBatch.project_id)
            .where(Project.owner_user_id == owner_user_id)
        )
        if generation_batch_id is not None:
            statement = statement.where(QuestionItem.generation_batch_id == generation_batch_id)
        if paper_result_id is not None:
            statement = statement.where(QuestionItem.paper_result_id == paper_result_id)
        if knowledge_point_id is not None:
            statement = statement.where(QuestionItem.knowledge_point_id == knowledge_point_id)
        if question_type:
            statement = statement.where(QuestionItem.question_type == question_type)
        if difficulty_level is not None:
            statement = statement.where(QuestionItem.difficulty_level == difficulty_level)
        if scene_type:
            statement = statement.where(PaperResult.scene_type == scene_type)
        statement = (
            statement.order_by(QuestionItem.created_at.desc(), QuestionItem.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return [(row[0], row[1]) for row in self.session.execute(statement).all()]

    def count_question_items_for_owner(
        self,
        owner_user_id: int,
        *,
        generation_batch_id: int | None,
        paper_result_id: int | None,
        knowledge_point_id: int | None,
        question_type: str | None,
        difficulty_level: int | None,
        scene_type: str | None,
    ) -> int:
        """统计当前教师可见的题目数量。"""
        statement = (
            select(func.count())
            .select_from(QuestionItem)
            .join(PaperResult, PaperResult.id == QuestionItem.paper_result_id)
            .join(GenerationBatch, GenerationBatch.id == QuestionItem.generation_batch_id)
            .join(Project, Project.id == GenerationBatch.project_id)
            .where(Project.owner_user_id == owner_user_id)
        )
        if generation_batch_id is not None:
            statement = statement.where(QuestionItem.generation_batch_id == generation_batch_id)
        if paper_result_id is not None:
            statement = statement.where(QuestionItem.paper_result_id == paper_result_id)
        if knowledge_point_id is not None:
            statement = statement.where(QuestionItem.knowledge_point_id == knowledge_point_id)
        if question_type:
            statement = statement.where(QuestionItem.question_type == question_type)
        if difficulty_level is not None:
            statement = statement.where(QuestionItem.difficulty_level == difficulty_level)
        if scene_type:
            statement = statement.where(PaperResult.scene_type == scene_type)
        return int(self.session.scalar(statement) or 0)

    def save(self, instance) -> None:
        """保存实体。"""
        self.session.add(instance)
        self.session.flush()
