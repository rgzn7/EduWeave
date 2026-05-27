"""
@Date: 2026-05-04
@Author: xisy
@Discription: 覆盖率分析模块数据访问层
"""

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.constants import COVERAGE_ANALYZE_TASK_TYPE, COVERAGE_MODULE_CODE, TASK_STATUS_SUCCESS
from app.modules.p0_models import (
    ChapterNode,
    CoursewareResult,
    CoverageReport,
    CurriculumPlan,
    GenerationBatch,
    GenerationTrace,
    HomeworkQuestion,
    HomeworkResult,
    KnowledgeEvidence,
    KnowledgePoint,
    LearnerProfileRecord,
    LessonPlan,
    PaperResult,
    Project,
    QuestionItem,
    TaskRecord,
)


class CoverageRepository:
    """覆盖率分析模块仓储。"""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_generation_batch(self, generation_batch_id: int) -> GenerationBatch | None:
        """按主键查询生成批次。"""
        statement = select(GenerationBatch).where(GenerationBatch.id == generation_batch_id)
        return self.session.scalar(statement)

    def get_generation_batch_for_owner(self, generation_batch_id: int, owner_user_id: int) -> GenerationBatch | None:
        """查询当前教师可见的生成批次。"""
        statement = (
            select(GenerationBatch)
            .join(Project, Project.id == GenerationBatch.project_id)
            .where(GenerationBatch.id == generation_batch_id, Project.owner_user_id == owner_user_id)
        )
        return self.session.scalar(statement)

    def get_project(self, project_id: int) -> Project | None:
        """按主键查询项目。"""
        statement = select(Project).where(Project.id == project_id)
        return self.session.scalar(statement)

    def list_knowledge_points(self, knowledge_version_id: int) -> list[KnowledgePoint]:
        """查询知识版本下的知识点。"""
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

    def list_knowledge_evidence_by_point_ids(self, point_ids: list[int]) -> list[KnowledgeEvidence]:
        """批量查询知识点教材证据。"""
        if not point_ids:
            return []
        statement = (
            select(KnowledgeEvidence)
            .where(KnowledgeEvidence.knowledge_point_id.in_(point_ids))
            .order_by(KnowledgeEvidence.knowledge_point_id.asc(), KnowledgeEvidence.id.asc())
        )
        return list(self.session.scalars(statement))

    def list_learner_profile_records(self, profile_version_id: int) -> list[LearnerProfileRecord]:
        """查询学情版本下画像记录。"""
        statement = (
            select(LearnerProfileRecord)
            .where(LearnerProfileRecord.profile_version_id == profile_version_id)
            .order_by(LearnerProfileRecord.sort_order.asc(), LearnerProfileRecord.id.asc())
        )
        return list(self.session.scalars(statement))

    def get_curriculum_plan(self, curriculum_plan_id: int | None) -> CurriculumPlan | None:
        """查询课程大纲。"""
        if curriculum_plan_id is None:
            return None
        return self.session.scalar(select(CurriculumPlan).where(CurriculumPlan.id == curriculum_plan_id))

    def get_lesson_plan(self, lesson_plan_id: int | None) -> LessonPlan | None:
        """查询教案。"""
        if lesson_plan_id is None:
            return None
        return self.session.scalar(select(LessonPlan).where(LessonPlan.id == lesson_plan_id))

    def list_lesson_plans_by_batch(self, generation_batch_id: int) -> list[LessonPlan]:
        """查询批次下全部教案。"""
        statement = (
            select(LessonPlan)
            .where(LessonPlan.generation_batch_id == generation_batch_id)
            .order_by(LessonPlan.class_session_no.asc(), LessonPlan.id.asc())
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

    def list_paper_results_by_batch(self, generation_batch_id: int) -> list[PaperResult]:
        """查询批次下全部试卷结果。"""
        statement = (
            select(PaperResult)
            .where(PaperResult.generation_batch_id == generation_batch_id)
            .order_by(PaperResult.id.asc())
        )
        return list(self.session.scalars(statement))

    def list_question_items_by_batch(self, generation_batch_id: int) -> list[QuestionItem]:
        """查询批次下题目明细。"""
        statement = (
            select(QuestionItem)
            .where(QuestionItem.generation_batch_id == generation_batch_id)
            .order_by(QuestionItem.question_no.asc(), QuestionItem.id.asc())
        )
        return list(self.session.scalars(statement))

    def list_homework_results_by_batch(self, generation_batch_id: int) -> list[HomeworkResult]:
        """查询批次下全部课后作业（仅 result_status=success 视为有效覆盖输入）。"""
        statement = (
            select(HomeworkResult)
            .where(
                HomeworkResult.generation_batch_id == generation_batch_id,
                HomeworkResult.result_status == TASK_STATUS_SUCCESS,
            )
            .order_by(HomeworkResult.lesson_plan_id.asc(), HomeworkResult.id.asc())
        )
        return list(self.session.scalars(statement))

    def list_homework_questions_by_batch(self, generation_batch_id: int) -> list[HomeworkQuestion]:
        """查询批次下成功课后作业的题目明细。"""
        statement = (
            select(HomeworkQuestion)
            .join(HomeworkResult, HomeworkResult.id == HomeworkQuestion.homework_result_id)
            .where(
                HomeworkQuestion.generation_batch_id == generation_batch_id,
                HomeworkResult.result_status == TASK_STATUS_SUCCESS,
            )
            .order_by(
                HomeworkQuestion.lesson_plan_id.asc(),
                HomeworkQuestion.question_no.asc(),
                HomeworkQuestion.id.asc(),
            )
        )
        return list(self.session.scalars(statement))

    def get_courseware_result_by_batch(self, generation_batch_id: int) -> CoursewareResult | None:
        """查询批次课件结果。"""
        statement = select(CoursewareResult).where(CoursewareResult.generation_batch_id == generation_batch_id)
        return self.session.scalar(statement)

    def list_courseware_results_by_batch(self, generation_batch_id: int) -> list[CoursewareResult]:
        """查询批次下有效课件结果（仅 result_status=success），作为覆盖率统计输入。"""
        statement = (
            select(CoursewareResult)
            .where(
                CoursewareResult.generation_batch_id == generation_batch_id,
                CoursewareResult.result_status == TASK_STATUS_SUCCESS,
            )
            .order_by(CoursewareResult.lesson_plan_id.asc(), CoursewareResult.id.asc())
        )
        return list(self.session.scalars(statement))

    def get_coverage_report_by_batch(self, generation_batch_id: int) -> CoverageReport | None:
        """查询批次覆盖率报告。"""
        statement = select(CoverageReport).where(CoverageReport.generation_batch_id == generation_batch_id)
        return self.session.scalar(statement)

    def get_coverage_report_for_owner(self, coverage_report_id: int, owner_user_id: int) -> CoverageReport | None:
        """查询当前教师可见的覆盖率报告。"""
        statement = (
            select(CoverageReport)
            .join(GenerationBatch, GenerationBatch.id == CoverageReport.generation_batch_id)
            .join(Project, Project.id == GenerationBatch.project_id)
            .where(CoverageReport.id == coverage_report_id, Project.owner_user_id == owner_user_id)
        )
        return self.session.scalar(statement)

    def list_coverage_reports_for_owner(
        self,
        owner_user_id: int,
        *,
        generation_batch_id: int,
        offset: int,
        limit: int,
    ) -> list[CoverageReport]:
        """分页查询当前教师可见的覆盖率报告。"""
        statement = (
            select(CoverageReport)
            .join(GenerationBatch, GenerationBatch.id == CoverageReport.generation_batch_id)
            .join(Project, Project.id == GenerationBatch.project_id)
            .where(Project.owner_user_id == owner_user_id, CoverageReport.generation_batch_id == generation_batch_id)
            .order_by(CoverageReport.created_at.desc(), CoverageReport.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.scalars(statement))

    def count_coverage_reports_for_owner(self, owner_user_id: int, *, generation_batch_id: int) -> int:
        """统计当前教师可见覆盖率报告数量。"""
        statement = (
            select(func.count())
            .select_from(CoverageReport)
            .join(GenerationBatch, GenerationBatch.id == CoverageReport.generation_batch_id)
            .join(Project, Project.id == GenerationBatch.project_id)
            .where(Project.owner_user_id == owner_user_id, CoverageReport.generation_batch_id == generation_batch_id)
        )
        return int(self.session.scalar(statement) or 0)

    def get_existing_coverage_task(self, generation_batch_id: int) -> TaskRecord | None:
        """查询批次下已存在的覆盖率任务。"""
        statement = (
            select(TaskRecord)
            .where(
                TaskRecord.generation_batch_id == generation_batch_id,
                TaskRecord.module_code == COVERAGE_MODULE_CODE,
                TaskRecord.task_type == COVERAGE_ANALYZE_TASK_TYPE,
                TaskRecord.task_status.in_(["pending", "processing", "success"]),
            )
            .order_by(TaskRecord.id.desc())
        )
        return self.session.scalar(statement)

    def create_coverage_report(self, coverage_report: CoverageReport) -> CoverageReport:
        """创建覆盖率报告。"""
        self.session.add(coverage_report)
        self.session.flush()
        return coverage_report

    def create_generation_trace(self, generation_trace: GenerationTrace) -> GenerationTrace:
        """创建生成追溯记录。"""
        self.session.add(generation_trace)
        self.session.flush()
        return generation_trace

    def delete_generation_traces_for_report(self, coverage_report_id: int) -> None:
        """删除指定覆盖率报告的旧追溯记录。"""
        self.session.execute(
            delete(GenerationTrace).where(
                GenerationTrace.target_type == "coverage_report",
                GenerationTrace.target_id == coverage_report_id,
            )
        )
        self.session.flush()

    def save(self, instance) -> None:
        """保存实体。"""
        self.session.add(instance)
        self.session.flush()
