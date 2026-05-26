"""
@Date: 2026-05-25
@Author: xisy
@Discription: 课后作业模块数据访问层
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.constants import HOMEWORK_GENERATE_TASK_TYPE, HOMEWORK_MODULE_CODE, TASK_STATUS_SUCCESS
from app.modules.p0_models import (
    ChapterNode,
    CurriculumPlan,
    GenerationBatch,
    HomeworkBlueprint,
    HomeworkQuestion,
    HomeworkResult,
    KnowledgePoint,
    LessonPlan,
    Project,
    TaskRecord,
)


class HomeworkRepository:
    """课后作业模块仓储。"""

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

    def get_lesson_plan_for_owner(self, lesson_plan_id: int, owner_user_id: int) -> LessonPlan | None:
        """查询当前教师可见的教案。"""
        statement = (
            select(LessonPlan)
            .join(CurriculumPlan, CurriculumPlan.id == LessonPlan.curriculum_plan_id)
            .join(Project, Project.id == CurriculumPlan.project_id)
            .where(LessonPlan.id == lesson_plan_id, Project.owner_user_id == owner_user_id)
        )
        return self.session.scalar(statement)

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

    def get_homework_blueprint(self, homework_blueprint_id: int) -> HomeworkBlueprint | None:
        """按主键查询作业蓝图。"""
        statement = select(HomeworkBlueprint).where(HomeworkBlueprint.id == homework_blueprint_id)
        return self.session.scalar(statement)

    def get_next_homework_blueprint_version_no(self, lesson_plan_id: int) -> int:
        """获取指定教案下一个作业蓝图版本号。"""
        statement = select(func.max(HomeworkBlueprint.version_no)).where(
            HomeworkBlueprint.lesson_plan_id == lesson_plan_id,
        )
        current_max = self.session.scalar(statement)
        return int(current_max or 0) + 1

    def create_homework_blueprint(self, blueprint: HomeworkBlueprint) -> HomeworkBlueprint:
        """创建作业蓝图。"""
        self.session.add(blueprint)
        self.session.flush()
        return blueprint

    def create_homework_result(self, homework_result: HomeworkResult) -> HomeworkResult:
        """创建作业结果。"""
        self.session.add(homework_result)
        self.session.flush()
        return homework_result

    def create_homework_questions(self, homework_questions: list[HomeworkQuestion]) -> list[HomeworkQuestion]:
        """批量创建作业题目。"""
        self.session.add_all(homework_questions)
        self.session.flush()
        return homework_questions

    def get_success_homework_result_by_lesson(self, lesson_plan_id: int) -> HomeworkResult | None:
        """查询课次下已成功的作业结果。"""
        statement = select(HomeworkResult).where(
            HomeworkResult.lesson_plan_id == lesson_plan_id,
            HomeworkResult.result_status == TASK_STATUS_SUCCESS,
        )
        return self.session.scalar(statement)

    def get_active_homework_task(self, lesson_plan_id: int) -> TaskRecord | None:
        """查询课次下运行中的作业生成任务。"""
        statement = (
            select(TaskRecord)
            .where(
                TaskRecord.module_code == HOMEWORK_MODULE_CODE,
                TaskRecord.task_type == HOMEWORK_GENERATE_TASK_TYPE,
                TaskRecord.biz_key == f"lesson_plan:{lesson_plan_id}:homework",
                TaskRecord.task_status.in_(["pending", "processing"]),
            )
            .order_by(TaskRecord.id.desc())
        )
        return self.session.scalar(statement)

    def get_homework_result(self, homework_result_id: int) -> HomeworkResult | None:
        """按主键查询作业结果。"""
        statement = select(HomeworkResult).where(HomeworkResult.id == homework_result_id)
        return self.session.scalar(statement)

    def get_homework_result_by_lesson(self, lesson_plan_id: int) -> HomeworkResult | None:
        """按教案查询作业结果。"""
        statement = select(HomeworkResult).where(HomeworkResult.lesson_plan_id == lesson_plan_id)
        return self.session.scalar(statement)

    def get_homework_result_for_owner(self, homework_result_id: int, owner_user_id: int) -> HomeworkResult | None:
        """查询当前教师可见的作业结果。"""
        statement = (
            select(HomeworkResult)
            .join(LessonPlan, LessonPlan.id == HomeworkResult.lesson_plan_id)
            .join(CurriculumPlan, CurriculumPlan.id == LessonPlan.curriculum_plan_id)
            .join(Project, Project.id == CurriculumPlan.project_id)
            .where(HomeworkResult.id == homework_result_id, Project.owner_user_id == owner_user_id)
        )
        return self.session.scalar(statement)

    def get_homework_result_by_lesson_for_owner(
        self,
        lesson_plan_id: int,
        owner_user_id: int,
    ) -> HomeworkResult | None:
        """按教案 + 教师权限查询作业结果。"""
        statement = (
            select(HomeworkResult)
            .join(LessonPlan, LessonPlan.id == HomeworkResult.lesson_plan_id)
            .join(CurriculumPlan, CurriculumPlan.id == LessonPlan.curriculum_plan_id)
            .join(Project, Project.id == CurriculumPlan.project_id)
            .where(HomeworkResult.lesson_plan_id == lesson_plan_id, Project.owner_user_id == owner_user_id)
        )
        return self.session.scalar(statement)

    def get_homework_blueprint_for_owner(
        self,
        homework_blueprint_id: int,
        owner_user_id: int,
    ) -> HomeworkBlueprint | None:
        """查询当前教师可见的作业蓝图。"""
        statement = (
            select(HomeworkBlueprint)
            .join(LessonPlan, LessonPlan.id == HomeworkBlueprint.lesson_plan_id)
            .join(CurriculumPlan, CurriculumPlan.id == LessonPlan.curriculum_plan_id)
            .join(Project, Project.id == CurriculumPlan.project_id)
            .where(HomeworkBlueprint.id == homework_blueprint_id, Project.owner_user_id == owner_user_id)
        )
        return self.session.scalar(statement)

    def list_homework_results_for_owner(
        self,
        owner_user_id: int,
        *,
        curriculum_plan_id: int | None,
        generation_batch_id: int | None,
        offset: int,
        limit: int,
    ) -> list[tuple[HomeworkResult, LessonPlan]]:
        """分页查询当前教师可见的作业结果。"""
        statement = (
            select(HomeworkResult, LessonPlan)
            .join(LessonPlan, LessonPlan.id == HomeworkResult.lesson_plan_id)
            .join(CurriculumPlan, CurriculumPlan.id == LessonPlan.curriculum_plan_id)
            .join(Project, Project.id == CurriculumPlan.project_id)
            .where(Project.owner_user_id == owner_user_id)
        )
        if curriculum_plan_id is not None:
            statement = statement.where(LessonPlan.curriculum_plan_id == curriculum_plan_id)
        if generation_batch_id is not None:
            statement = statement.where(HomeworkResult.generation_batch_id == generation_batch_id)
        statement = (
            statement.order_by(LessonPlan.class_session_no.asc(), HomeworkResult.id.asc()).offset(offset).limit(limit)
        )
        return [(row[0], row[1]) for row in self.session.execute(statement).all()]

    def count_homework_results_for_owner(
        self,
        owner_user_id: int,
        *,
        curriculum_plan_id: int | None,
        generation_batch_id: int | None,
    ) -> int:
        """统计当前教师可见的作业结果数量。"""
        statement = (
            select(func.count())
            .select_from(HomeworkResult)
            .join(LessonPlan, LessonPlan.id == HomeworkResult.lesson_plan_id)
            .join(CurriculumPlan, CurriculumPlan.id == LessonPlan.curriculum_plan_id)
            .join(Project, Project.id == CurriculumPlan.project_id)
            .where(Project.owner_user_id == owner_user_id)
        )
        if curriculum_plan_id is not None:
            statement = statement.where(LessonPlan.curriculum_plan_id == curriculum_plan_id)
        if generation_batch_id is not None:
            statement = statement.where(HomeworkResult.generation_batch_id == generation_batch_id)
        return int(self.session.scalar(statement) or 0)

    def list_homework_questions(self, homework_result_id: int) -> list[HomeworkQuestion]:
        """查询作业题目明细。"""
        statement = (
            select(HomeworkQuestion)
            .where(HomeworkQuestion.homework_result_id == homework_result_id)
            .order_by(HomeworkQuestion.question_no.asc(), HomeworkQuestion.id.asc())
        )
        return list(self.session.scalars(statement))

    def list_homework_questions_for_owner(
        self,
        owner_user_id: int,
        *,
        lesson_plan_id: int | None,
        homework_result_id: int | None,
        knowledge_point_id: int | None,
        question_type: str | None,
        difficulty_level: int | None,
        offset: int,
        limit: int,
    ) -> list[tuple[HomeworkQuestion, HomeworkResult, LessonPlan]]:
        """分页查询当前教师可见的作业题目与所属作业。"""
        statement = (
            select(HomeworkQuestion, HomeworkResult, LessonPlan)
            .join(HomeworkResult, HomeworkResult.id == HomeworkQuestion.homework_result_id)
            .join(LessonPlan, LessonPlan.id == HomeworkResult.lesson_plan_id)
            .join(CurriculumPlan, CurriculumPlan.id == LessonPlan.curriculum_plan_id)
            .join(Project, Project.id == CurriculumPlan.project_id)
            .where(Project.owner_user_id == owner_user_id)
        )
        if lesson_plan_id is not None:
            statement = statement.where(HomeworkQuestion.lesson_plan_id == lesson_plan_id)
        if homework_result_id is not None:
            statement = statement.where(HomeworkQuestion.homework_result_id == homework_result_id)
        if knowledge_point_id is not None:
            statement = statement.where(HomeworkQuestion.knowledge_point_id == knowledge_point_id)
        if question_type:
            statement = statement.where(HomeworkQuestion.question_type == question_type)
        if difficulty_level is not None:
            statement = statement.where(HomeworkQuestion.difficulty_level == difficulty_level)
        statement = (
            statement.order_by(HomeworkQuestion.created_at.desc(), HomeworkQuestion.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return [(row[0], row[1], row[2]) for row in self.session.execute(statement).all()]

    def count_homework_questions_for_owner(
        self,
        owner_user_id: int,
        *,
        lesson_plan_id: int | None,
        homework_result_id: int | None,
        knowledge_point_id: int | None,
        question_type: str | None,
        difficulty_level: int | None,
    ) -> int:
        """统计当前教师可见的作业题目数量。"""
        statement = (
            select(func.count())
            .select_from(HomeworkQuestion)
            .join(HomeworkResult, HomeworkResult.id == HomeworkQuestion.homework_result_id)
            .join(LessonPlan, LessonPlan.id == HomeworkResult.lesson_plan_id)
            .join(CurriculumPlan, CurriculumPlan.id == LessonPlan.curriculum_plan_id)
            .join(Project, Project.id == CurriculumPlan.project_id)
            .where(Project.owner_user_id == owner_user_id)
        )
        if lesson_plan_id is not None:
            statement = statement.where(HomeworkQuestion.lesson_plan_id == lesson_plan_id)
        if homework_result_id is not None:
            statement = statement.where(HomeworkQuestion.homework_result_id == homework_result_id)
        if knowledge_point_id is not None:
            statement = statement.where(HomeworkQuestion.knowledge_point_id == knowledge_point_id)
        if question_type:
            statement = statement.where(HomeworkQuestion.question_type == question_type)
        if difficulty_level is not None:
            statement = statement.where(HomeworkQuestion.difficulty_level == difficulty_level)
        return int(self.session.scalar(statement) or 0)

    def save(self, instance) -> None:
        """保存实体。"""
        self.session.add(instance)
        self.session.flush()
