"""
@Date: 2026-05-04
@Author: xisy
@Discription: 课件模块数据访问层
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.constants import COURSEWARE_GENERATE_TASK_TYPE, COURSEWARE_MODULE_CODE
from app.modules.p0_models import (
    ChapterNode,
    CoursewareResult,
    CurriculumPlan,
    FileObject,
    GenerationBatch,
    KnowledgePoint,
    LearnerProfileRecord,
    LearnerProfileVersion,
    LessonPlan,
    PaperResult,
    Project,
    TaskRecord,
    TaskStepRecord,
)


class CoursewareRepository:
    """课件模块仓储。"""

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

    def get_generation_batch_by_lesson_plan(self, lesson_plan: LessonPlan) -> GenerationBatch | None:
        """按教案查询所属生成批次。"""
        if lesson_plan.generation_batch_id is not None:
            return self.get_generation_batch(lesson_plan.generation_batch_id)
        statement = select(GenerationBatch).where(GenerationBatch.lesson_plan_id == lesson_plan.id)
        return self.session.scalar(statement)

    def get_learner_profile_version(self, profile_version_id: int) -> LearnerProfileVersion | None:
        """按主键查询学情版本。"""
        statement = select(LearnerProfileVersion).where(LearnerProfileVersion.id == profile_version_id)
        return self.session.scalar(statement)

    def list_profile_records(self, profile_version_id: int) -> list[LearnerProfileRecord]:
        """查询学情画像记录。"""
        statement = (
            select(LearnerProfileRecord)
            .where(LearnerProfileRecord.profile_version_id == profile_version_id)
            .order_by(LearnerProfileRecord.sort_order.asc(), LearnerProfileRecord.id.asc())
        )
        return list(self.session.scalars(statement))

    def list_knowledge_points(self, knowledge_version_id: int) -> list[KnowledgePoint]:
        """查询知识点列表。"""
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

    def get_paper_result_by_batch(self, generation_batch_id: int) -> PaperResult | None:
        """查询批次下首个试卷结果。"""
        statement = (
            select(PaperResult)
            .where(PaperResult.generation_batch_id == generation_batch_id)
            .order_by(PaperResult.id.asc())
        )
        return self.session.scalar(statement)

    def get_courseware_result_by_batch(self, generation_batch_id: int) -> CoursewareResult | None:
        """查询批次课件结果。"""
        statement = select(CoursewareResult).where(CoursewareResult.generation_batch_id == generation_batch_id)
        return self.session.scalar(statement)

    def get_courseware_result_by_batch_lesson(
        self,
        generation_batch_id: int,
        lesson_plan_id: int,
    ) -> CoursewareResult | None:
        """查询批次下指定教案课件结果。"""
        statement = select(CoursewareResult).where(
            CoursewareResult.generation_batch_id == generation_batch_id,
            CoursewareResult.lesson_plan_id == lesson_plan_id,
        )
        return self.session.scalar(statement)

    def create_courseware_result(self, courseware_result: CoursewareResult) -> CoursewareResult:
        """创建课件结果。"""
        self.session.add(courseware_result)
        self.session.flush()
        return courseware_result

    def create_file_object(self, file_object: FileObject) -> FileObject:
        """创建文件对象。"""
        self.session.add(file_object)
        self.session.flush()
        return file_object

    def get_courseware_result_for_owner(self, courseware_result_id: int, owner_user_id: int) -> CoursewareResult | None:
        """查询当前教师可见的课件结果。"""
        statement = (
            select(CoursewareResult)
            .join(GenerationBatch, GenerationBatch.id == CoursewareResult.generation_batch_id)
            .join(Project, Project.id == GenerationBatch.project_id)
            .where(CoursewareResult.id == courseware_result_id, Project.owner_user_id == owner_user_id)
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

    def list_courseware_results_for_owner(
        self,
        owner_user_id: int,
        *,
        generation_batch_id: int,
        offset: int,
        limit: int,
    ) -> list[CoursewareResult]:
        """分页查询当前教师可见的课件结果。"""
        statement = (
            select(CoursewareResult)
            .join(GenerationBatch, GenerationBatch.id == CoursewareResult.generation_batch_id)
            .join(Project, Project.id == GenerationBatch.project_id)
            .where(Project.owner_user_id == owner_user_id, CoursewareResult.generation_batch_id == generation_batch_id)
            .order_by(CoursewareResult.created_at.desc(), CoursewareResult.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.scalars(statement))

    def count_courseware_results_for_owner(self, owner_user_id: int, *, generation_batch_id: int) -> int:
        """统计当前教师可见课件结果数量。"""
        statement = (
            select(func.count())
            .select_from(CoursewareResult)
            .join(GenerationBatch, GenerationBatch.id == CoursewareResult.generation_batch_id)
            .join(Project, Project.id == GenerationBatch.project_id)
            .where(Project.owner_user_id == owner_user_id, CoursewareResult.generation_batch_id == generation_batch_id)
        )
        return int(self.session.scalar(statement) or 0)

    def get_courseware_task_by_batch_lesson(self, generation_batch_id: int, lesson_plan_id: int) -> TaskRecord | None:
        """查询批次下指定教案的课件任务。"""
        statement = (
            select(TaskRecord)
            .where(
                TaskRecord.generation_batch_id == generation_batch_id,
                TaskRecord.module_code == COURSEWARE_MODULE_CODE,
                TaskRecord.task_type == COURSEWARE_GENERATE_TASK_TYPE,
                TaskRecord.biz_key == f"generation_batch:{generation_batch_id}:lesson_plan:{lesson_plan_id}:courseware",
            )
            .order_by(TaskRecord.id.desc())
        )
        return self.session.scalar(statement)

    def get_active_courseware_task(self, generation_batch_id: int, lesson_plan_id: int) -> TaskRecord | None:
        """查询指定教案运行中的课件任务。"""
        statement = (
            select(TaskRecord)
            .where(
                TaskRecord.generation_batch_id == generation_batch_id,
                TaskRecord.module_code == COURSEWARE_MODULE_CODE,
                TaskRecord.task_type == COURSEWARE_GENERATE_TASK_TYPE,
                TaskRecord.biz_key == f"generation_batch:{generation_batch_id}:lesson_plan:{lesson_plan_id}:courseware",
                TaskRecord.task_status.in_(["pending", "processing"]),
            )
            .order_by(TaskRecord.id.desc())
        )
        return self.session.scalar(statement)

    def get_task_step(self, task_record_id: int, step_code: str) -> TaskStepRecord | None:
        """查询课件任务步骤。"""
        statement = select(TaskStepRecord).where(
            TaskStepRecord.task_record_id == task_record_id,
            TaskStepRecord.step_code == step_code,
        )
        return self.session.scalar(statement)

    def save(self, instance) -> None:
        """保存实体。"""
        self.session.add(instance)
        self.session.flush()
