"""
@Date: 2026-05-26
@Author: xisy
@Discription: 生成过程展示模块业务服务，把内部任务聚合成 6 步产品化展示
"""

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.constants import (
    COVERAGE_ANALYZE_TASK_TYPE,
    COVERAGE_MODULE_CODE,
    CURRICULUM_GENERATE_TASK_TYPE,
    CURRICULUM_MODULE_CODE,
    KNOWLEDGE_EXTRACT_TASK_TYPE,
    KNOWLEDGE_MODULE_CODE,
    LEARNER_PROFILE_MODULE_CODE,
    LESSON_PLAN_GENERATE_TASK_TYPE,
    LESSON_PLAN_MODULE_CODE,
    PARSING_MODULE_CODE,
    PROFILE_EXTRACT_TASK_TYPE,
    TASK_STATUS_CANCELLED,
    TASK_STATUS_FAILURE,
    TASK_STATUS_PARTIAL_SUCCESS,
    TASK_STATUS_PENDING,
    TASK_STATUS_PROCESSING,
    TASK_STATUS_SUCCESS,
    TEXTBOOK_PARSE_TASK_TYPE,
)
from app.core.exceptions import AppException, BusinessErrorCode
from app.modules.generation_process.schemas import (
    GenerationProcessResponse,
    GenerationProcessStepResponse,
)
from app.modules.p0_models import (
    CoverageReport,
    LearnerProfileVersion,
    Project,
    TaskRecord,
)
from app.modules.parsing.repository import ParsingRepository
from app.modules.project.repository import ProjectRepository
from app.modules.task_center.repository import TaskCenterRepository

# 展示步骤编码常量
STEP_MINERU_PARSE = "mineru_parse"
STEP_LEARNER_PROFILE = "learner_profile"
STEP_KNOWLEDGE_STRUCTURE = "knowledge_structure"
STEP_CURRICULUM_PLAN = "curriculum_plan"
STEP_LESSON_PLAN_GENERATE = "lesson_plan_generate"
STEP_COVERAGE_CHECK = "coverage_check"

# 展示步骤静态文案，顺序即页面渲染顺序
DISPLAY_STEPS: list[dict[str, str]] = [
    {
        "code": STEP_MINERU_PARSE,
        "display_name": "调用 MinerU 教材解析工具",
        "description": "识别教材章节、页码、图表、题目和知识点。",
    },
    {
        "code": STEP_LEARNER_PROFILE,
        "display_name": "调用学情理解工具",
        "description": "分析学生基础、薄弱点、学习习惯和班级画像。",
    },
    {
        "code": STEP_KNOWLEDGE_STRUCTURE,
        "display_name": "调用知识点梳理工具",
        "description": "整理课程知识点、能力目标、重点难点和关联关系。",
    },
    {
        "code": STEP_CURRICULUM_PLAN,
        "display_name": "调用课程规划工具",
        "description": "生成整套课程课次安排、教学目标和课时规划。",
    },
    {
        "code": STEP_LESSON_PLAN_GENERATE,
        "display_name": "调用教案生成工具",
        "description": "为每一课生成教学目标、重点难点、教学流程和课后安排。",
    },
    {
        "code": STEP_COVERAGE_CHECK,
        "display_name": "调用覆盖检查工具",
        "description": "检查课程、教案、题目和课件的知识点覆盖情况。",
    },
]

# 内部任务状态到展示状态的固定映射
INTERNAL_TO_DISPLAY_STATUS: dict[str, str] = {
    TASK_STATUS_PENDING: "pending",
    TASK_STATUS_PROCESSING: "running",
    TASK_STATUS_SUCCESS: "succeeded",
    TASK_STATUS_PARTIAL_SUCCESS: "succeeded",
    TASK_STATUS_FAILURE: "failed",
    TASK_STATUS_CANCELLED: "failed",
}

# 运行中固定占位摘要，避免页面空白
RUNNING_SUMMARY_BY_STEP: dict[str, str] = {
    STEP_MINERU_PARSE: "正在调用 MinerU 解析教材，请稍候。",
    STEP_LEARNER_PROFILE: "正在分析学情，请稍候。",
    STEP_KNOWLEDGE_STRUCTURE: "正在梳理知识点，请稍候。",
    STEP_CURRICULUM_PLAN: "正在生成课程总纲，请稍候。",
    STEP_LESSON_PLAN_GENERATE: "正在生成多课时教案，请稍候。",
    STEP_COVERAGE_CHECK: "正在分析知识点覆盖情况，请稍候。",
}

# 错误码 → 面向用户的错误文案。未命中则回退到 DEFAULT_ERROR_MESSAGE_BY_STEP。
ERROR_MESSAGE_MAP: dict[str, str] = {
    "MINERU_SUBMIT_FAILED": "教材解析失败，请确认上传文件是否为清晰的 PDF。",
    "MINERU_POLL_TIMEOUT": "教材解析超时，请稍后重试。",
    "MINERU_TASK_FAILED": "教材解析失败，请稍后重试。",
    "MINERU_RESULT_INVALID": "教材解析结果无法识别，请更换文件后重试。",
    "PARSE_TASK_FAILED": "教材解析失败，请稍后重试。",
    "PROFILE_EXTRACT_FAILED": "学情分析失败，请检查上传的学情文档。",
    "LLM_REQUEST_FAILED": "AI 工具暂时不可用，请稍后重试。",
    "LLM_RESULT_INVALID": "AI 工具返回结果异常，请稍后重试。",
    "KNOWLEDGE_TASK_FAILED": "知识点梳理失败，请稍后重试。",
    "CURRICULUM_TASK_FAILED": "课程规划失败，请稍后重试。",
    "LESSON_PLAN_TASK_FAILED": "教案生成失败，请稍后重试；已保留当前教材解析和知识点结果。",
    "COVERAGE_TASK_FAILED": "覆盖检查失败，请稍后重试。",
    "EXTERNAL_SERVICE_ERROR": "外部服务暂时不可用，请稍后重试。",
    "DEPENDENCY_NOT_READY": "前置数据尚未就绪，请稍后重试。",
}

DEFAULT_ERROR_MESSAGE_BY_STEP: dict[str, str] = {
    STEP_MINERU_PARSE: "教材解析失败，请稍后重试。",
    STEP_LEARNER_PROFILE: "学情分析失败，请稍后重试。",
    STEP_KNOWLEDGE_STRUCTURE: "知识点梳理失败，请稍后重试。",
    STEP_CURRICULUM_PLAN: "课程规划失败，请稍后重试。",
    STEP_LESSON_PLAN_GENERATE: "教案生成失败，请稍后重试。",
    STEP_COVERAGE_CHECK: "覆盖检查失败，请稍后重试。",
}


@dataclass(slots=True)
class _StepContext:
    """展示步骤聚合上下文，绑定源任务（可空）与展示元数据。"""

    code: str
    display_name: str
    description: str
    task: TaskRecord | None
    summary_extra: dict[str, Any]


class GenerationProcessService:
    """生成过程展示服务。"""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.project_repository = ProjectRepository(session)
        self.task_repository = TaskCenterRepository(session)
        self.parsing_repository = ParsingRepository(session)

    def get_process(self, *, owner_user_id: int, project_id: int) -> GenerationProcessResponse:
        """聚合并返回项目当前生成过程。"""
        project = self.project_repository.get_project_by_id_for_owner(project_id, owner_user_id)
        if project is None:
            raise AppException(BusinessErrorCode.PROJECT_NOT_FOUND, "项目不存在")

        step_contexts = self._collect_step_contexts(project)
        steps = [self._build_step_response(ctx) for ctx in step_contexts]
        overall_status, current_step_code = self._compute_overall_status(steps)

        return GenerationProcessResponse(
            project_id=project.id,
            batch_id=project.latest_generation_batch_id,
            status=overall_status,
            current_step_code=current_step_code,
            steps=steps,
        )

    def _collect_step_contexts(self, project: Project) -> list[_StepContext]:
        """按 6 步顺序收集源任务与可补充的摘要数据。"""
        # 1. MinerU 教材解析：按 current_textbook_version_id 精确匹配 full 解析任务。
        mineru_task: TaskRecord | None = None
        if project.current_textbook_version_id is not None:
            mineru_task = self.task_repository.get_latest_task_by_biz_key(
                module_code=PARSING_MODULE_CODE,
                task_type=TEXTBOOK_PARSE_TASK_TYPE,
                biz_key=f"textbook_version:{project.current_textbook_version_id}:full",
            )

        # 2. 学情理解：通过当前学情版本反查 profile_file_id 后定位抽取任务。
        learner_task: TaskRecord | None = None
        if project.current_learner_profile_version_id is not None:
            profile_version = self.session.get(LearnerProfileVersion, project.current_learner_profile_version_id)
            if profile_version is not None:
                learner_task = self.task_repository.get_latest_task_by_biz_key(
                    module_code=LEARNER_PROFILE_MODULE_CODE,
                    task_type=PROFILE_EXTRACT_TASK_TYPE,
                    biz_key=f"profile_file:{profile_version.profile_file_id}:extract",
                )

        # 3. 知识点梳理：通过当前教材的最近一个 ready 解析版本定位知识抽取任务。
        knowledge_task: TaskRecord | None = None
        if project.current_textbook_version_id is not None:
            active_parse_version = self.parsing_repository.get_active_parse_version(project.current_textbook_version_id)
            if active_parse_version is not None:
                knowledge_task = self.task_repository.get_latest_task_by_biz_key(
                    module_code=KNOWLEDGE_MODULE_CODE,
                    task_type=KNOWLEDGE_EXTRACT_TASK_TYPE,
                    biz_key=f"parse_version:{active_parse_version.id}:knowledge",
                )

        # 4~6. 课程 / 教案 / 覆盖：取最近一次生成批次下的对应任务。
        curriculum_task: TaskRecord | None = None
        lesson_plan_task: TaskRecord | None = None
        coverage_task: TaskRecord | None = None
        coverage_report: CoverageReport | None = None
        if project.latest_generation_batch_id is not None:
            batch_tasks = self.task_repository.list_tasks_by_generation_batch(project.latest_generation_batch_id)
            curriculum_task = self._pick_latest_by_type(batch_tasks, CURRICULUM_MODULE_CODE, CURRICULUM_GENERATE_TASK_TYPE)
            lesson_plan_task = self._pick_latest_by_type(batch_tasks, LESSON_PLAN_MODULE_CODE, LESSON_PLAN_GENERATE_TASK_TYPE)
            coverage_task = self._pick_latest_by_type(batch_tasks, COVERAGE_MODULE_CODE, COVERAGE_ANALYZE_TASK_TYPE)
            coverage_report = self._get_coverage_report(project.latest_generation_batch_id)

        contexts: list[_StepContext] = []
        task_map: dict[str, TaskRecord | None] = {
            STEP_MINERU_PARSE: mineru_task,
            STEP_LEARNER_PROFILE: learner_task,
            STEP_KNOWLEDGE_STRUCTURE: knowledge_task,
            STEP_CURRICULUM_PLAN: curriculum_task,
            STEP_LESSON_PLAN_GENERATE: lesson_plan_task,
            STEP_COVERAGE_CHECK: coverage_task,
        }
        summary_extras: dict[str, dict[str, Any]] = {
            STEP_COVERAGE_CHECK: {"coverage_report": coverage_report},
        }
        for meta in DISPLAY_STEPS:
            code = meta["code"]
            contexts.append(
                _StepContext(
                    code=code,
                    display_name=meta["display_name"],
                    description=meta["description"],
                    task=task_map.get(code),
                    summary_extra=summary_extras.get(code, {}),
                )
            )
        return contexts

    def _build_step_response(self, ctx: _StepContext) -> GenerationProcessStepResponse:
        """根据源任务把上下文渲染成展示响应。"""
        task = ctx.task
        if task is None:
            return GenerationProcessStepResponse(
                code=ctx.code,
                display_name=ctx.display_name,
                description=ctx.description,
                status="pending",
                progress_percent=0,
                summary=None,
                started_at=None,
                finished_at=None,
                error_message=None,
            )

        display_status = INTERNAL_TO_DISPLAY_STATUS.get(task.task_status, "pending")
        summary = self._build_summary(ctx, display_status)
        error_message = self._build_error_message(ctx.code, task, display_status)
        return GenerationProcessStepResponse(
            code=ctx.code,
            display_name=ctx.display_name,
            description=ctx.description,
            status=display_status,
            progress_percent=int(task.progress_percent or 0),
            summary=summary,
            started_at=task.started_at,
            finished_at=task.finished_at,
            error_message=error_message,
        )

    def _build_summary(self, ctx: _StepContext, display_status: str) -> str | None:
        """根据展示状态拼接面向用户的摘要文案。"""
        if display_status == "running":
            return RUNNING_SUMMARY_BY_STEP.get(ctx.code)
        if display_status != "succeeded":
            return None

        task = ctx.task
        if task is None:
            return None
        result = task.result_json or {}

        if ctx.code == STEP_MINERU_PARSE:
            page_count = result.get("page_count")
            if page_count:
                return f"已识别 {page_count} 页教材内容。"
            return "教材解析已完成。"
        if ctx.code == STEP_LEARNER_PROFILE:
            record_count = result.get("record_count")
            if record_count:
                return f"已分析 {record_count} 份学情记录。"
            return "学情分析已完成。"
        if ctx.code == STEP_KNOWLEDGE_STRUCTURE:
            chapter_count = result.get("chapter_count")
            point_count = result.get("point_count")
            if chapter_count and point_count:
                return f"已识别 {chapter_count} 个章节、{point_count} 个知识点。"
            if point_count:
                return f"已识别 {point_count} 个知识点。"
            return "知识点结构已生成。"
        if ctx.code == STEP_CURRICULUM_PLAN:
            return "课程总纲已生成。"
        if ctx.code == STEP_LESSON_PLAN_GENERATE:
            lesson_plan_count = result.get("lesson_plan_count")
            if lesson_plan_count:
                return f"已生成 {lesson_plan_count} 课时教案。"
            return "教案已生成。"
        if ctx.code == STEP_COVERAGE_CHECK:
            coverage_rate = result.get("coverage_rate")
            if coverage_rate is None:
                coverage_report = ctx.summary_extra.get("coverage_report")
                if coverage_report is not None:
                    coverage_rate = coverage_report.coverage_rate
            if coverage_rate is not None:
                return f"知识点覆盖 {float(coverage_rate):.2f}%。"
            return "知识点覆盖检查已完成。"
        return None

    @staticmethod
    def _build_error_message(step_code: str, task: TaskRecord, display_status: str) -> str | None:
        """根据错误码映射出面向用户的错误文案，绝不回显内部 last_error_message。"""
        if display_status != "failed":
            return None
        if task.last_error_code:
            mapped = ERROR_MESSAGE_MAP.get(task.last_error_code)
            if mapped:
                return mapped
        return DEFAULT_ERROR_MESSAGE_BY_STEP.get(step_code, "生成失败，请稍后重试。")

    @staticmethod
    def _pick_latest_by_type(
        batch_tasks: list[TaskRecord],
        module_code: str,
        task_type: str,
    ) -> TaskRecord | None:
        """从批次任务列表中按 created_at 取最近一条匹配的任务。"""
        matched = [
            task
            for task in batch_tasks
            if task.module_code == module_code and task.task_type == task_type
        ]
        if not matched:
            return None
        matched.sort(key=lambda task: (task.created_at, task.id), reverse=True)
        return matched[0]

    def _get_coverage_report(self, generation_batch_id: int) -> CoverageReport | None:
        """读取批次对应的覆盖率报告，用于在 result_json 缺失时兜底拼摘要。"""
        statement = (
            select(CoverageReport)
            .where(CoverageReport.generation_batch_id == generation_batch_id)
            .order_by(CoverageReport.created_at.desc(), CoverageReport.id.desc())
            .limit(1)
        )
        return self.session.scalar(statement)

    @staticmethod
    def _compute_overall_status(
        steps: list[GenerationProcessStepResponse],
    ) -> tuple[str, str | None]:
        """根据 6 步状态计算整体状态与当前步骤编码。"""
        for step in steps:
            if step.status == "failed":
                return "failed", step.code
        for step in steps:
            if step.status == "running":
                return "running", step.code
        if all(step.status == "succeeded" for step in steps):
            return "succeeded", None
        if any(step.status == "succeeded" for step in steps):
            for step in steps:
                if step.status == "pending":
                    return "running", step.code
            return "running", None
        return "pending", None
