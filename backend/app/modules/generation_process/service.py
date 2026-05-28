"""
@Date: 2026-05-28
@Author: xisy
@Discription: 生成过程展示模块业务服务，把内部任务聚合成 6 步产品化展示
"""

from dataclasses import dataclass
from decimal import Decimal
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
    CurriculumPlan,
    GenerationRun,
    LearnerProfileVersion,
    Project,
    TaskRecord,
    TaskStepRecord,
)
from app.modules.orchestrator.repository import OrchestratorRepository
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

# 允许透给项目页的步骤进度指标。内部主键、任务编排字段、LLM usage 等均不在白名单内。
PUBLIC_PROGRESS_DETAIL_KEYS: set[str] = {
    "page_count",
    "issue_count",
    "edited_page_count",
    "page_range_text",
    "block_count",
    "record_count",
    "profile_record_count",
    "chapter_count",
    "point_count",
    "knowledge_point_count",
    "processed_chunks",
    "total_chunks",
    "processed_sessions",
    "total_sessions",
    "session_count",
    "lesson_plan_count",
    "last_completed_chapter_path",
    "last_completed_class_session_no",
    "failed_session_no",
    "failed_session_title",
    "session_retry_count",
    "parallel_limit",
    "cache_warmup_completed",
    "coverage_rate",
    "warning_count",
    "total_count",
    "covered_count",
    "uncovered_count",
    "important_total_count",
    "important_covered_count",
    "important_coverage_rate",
    "trace_count",
    "semantic_chunk_vector_count",
    "knowledge_point_vector_count",
}

# 成功态优先读取的内部步骤。运行态会优先读取 task.current_stage 对应步骤。
STEP_PROGRESS_DETAIL_CODES: dict[str, tuple[str, ...]] = {
    STEP_MINERU_PARSE: ("persist_parse_result", "submit_mineru", "poll_mineru_result", "prepare_source"),
    STEP_LEARNER_PROFILE: ("build_profile_version", "extract_local", "prepare_source"),
    STEP_KNOWLEDGE_STRUCTURE: ("invoke_llm_extract", "persist_knowledge_result", "upsert_vectors", "prepare_parse_source"),
    STEP_CURRICULUM_PLAN: ("invoke_llm_curriculum", "prepare_generation_baseline", "persist_curriculum_plan"),
    STEP_LESSON_PLAN_GENERATE: ("invoke_llm_lesson_plan", "persist_lesson_plan", "prepare_lesson_baseline"),
    STEP_COVERAGE_CHECK: ("persist_coverage_report", "collect_artifact_refs", "write_generation_trace"),
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
        self.orchestrator_repository = OrchestratorRepository(session)

    def get_process(self, *, owner_user_id: int, project_id: int) -> GenerationProcessResponse:
        """聚合并返回项目当前生成过程。"""
        project = self.project_repository.get_project_by_id_for_owner(project_id, owner_user_id)
        if project is None:
            raise AppException(BusinessErrorCode.PROJECT_NOT_FOUND, "项目不存在")

        # 当前活跃的一键生成 run 决定整体细化状态（waiting_dispatch / blocked / waiting_user_confirm）
        active_run = self.orchestrator_repository.get_active_run_for_project(project.id)
        display_batch_id = self._resolve_display_batch_id(project, active_run)
        step_contexts = self._collect_step_contexts(project, display_batch_id)
        steps = [self._build_step_response(ctx) for ctx in step_contexts]
        overall_status, status_detail, blocked_reason, current_step_code = self._compute_overall_status(
            steps, active_run
        )

        return GenerationProcessResponse(
            project_id=project.id,
            batch_id=display_batch_id,
            generation_run_id=active_run.id if active_run is not None else None,
            status=overall_status,
            status_detail=status_detail,
            blocked_reason=blocked_reason,
            current_step_code=current_step_code,
            steps=steps,
        )

    @staticmethod
    def _resolve_display_batch_id(project: Project, active_run: GenerationRun | None) -> int | None:
        """解析当前展示批次：活跃 run 优先，无活跃 run 时回退项目最近批次。"""
        if active_run is not None:
            return active_run.generation_batch_id
        return project.latest_generation_batch_id

    def _collect_step_contexts(self, project: Project, display_batch_id: int | None) -> list[_StepContext]:
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
        else:
            learner_task = self.task_repository.get_latest_task_by_project_and_type(
                project_id=project.id,
                module_code=LEARNER_PROFILE_MODULE_CODE,
                task_type=PROFILE_EXTRACT_TASK_TYPE,
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

        # 4~6. 课程 / 教案 / 覆盖：按当前展示批次取任务，避免活跃 run 混入旧批次。
        curriculum_task: TaskRecord | None = None
        lesson_plan_task: TaskRecord | None = None
        coverage_task: TaskRecord | None = None
        coverage_report: CoverageReport | None = None
        if display_batch_id is not None:
            batch_tasks = self.task_repository.list_tasks_by_generation_batch(display_batch_id)
            curriculum_task = self._pick_latest_by_type(batch_tasks, CURRICULUM_MODULE_CODE, CURRICULUM_GENERATE_TASK_TYPE)
            lesson_plan_task = self._pick_latest_by_type(batch_tasks, LESSON_PLAN_MODULE_CODE, LESSON_PLAN_GENERATE_TASK_TYPE)
            coverage_task = self._pick_latest_by_type(batch_tasks, COVERAGE_MODULE_CODE, COVERAGE_ANALYZE_TASK_TYPE)
            coverage_report = self._get_coverage_report(display_batch_id)

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
                status_detail=None,
                progress_percent=0,
                current_stage=None,
                progress_detail=None,
                result_detail=None,
                summary=None,
                started_at=None,
                finished_at=None,
                error_message=None,
            )

        display_status = INTERNAL_TO_DISPLAY_STATUS.get(task.task_status, "pending")
        progress_step = self._select_progress_step(ctx, display_status)
        progress_detail = self._build_progress_detail(progress_step)
        result_detail = self._build_result_detail(ctx, display_status)
        summary = self._build_summary(ctx, display_status, result_detail)
        error_message = self._build_error_message(ctx.code, task, display_status)
        step_status_detail = self._compute_step_status_detail(task, display_status)
        return GenerationProcessStepResponse(
            code=ctx.code,
            display_name=ctx.display_name,
            description=ctx.description,
            status=display_status,
            status_detail=step_status_detail,
            progress_percent=int(task.progress_percent or 0),
            current_stage=task.current_stage,
            progress_detail=progress_detail,
            result_detail=result_detail,
            summary=summary,
            started_at=task.started_at,
            finished_at=task.finished_at,
            error_message=error_message,
        )

    def _select_progress_step(self, ctx: _StepContext, display_status: str) -> TaskStepRecord | None:
        """选择最适合项目页展示进度明细的内部步骤。"""
        task = ctx.task
        if task is None:
            return None

        steps = self.task_repository.list_task_steps(task.id)
        if not steps:
            return None
        step_by_code = {step.step_code: step for step in steps}

        if display_status == "running" and task.current_stage:
            current_step = step_by_code.get(task.current_stage)
            if current_step is not None and self._build_progress_detail(current_step) is not None:
                return current_step

        for step_code in STEP_PROGRESS_DETAIL_CODES.get(ctx.code, ()):
            step = step_by_code.get(step_code)
            if step is not None and self._build_progress_detail(step) is not None:
                return step

        processing_step = next(
            (
                step
                for step in steps
                if step.step_status == TASK_STATUS_PROCESSING and self._build_progress_detail(step) is not None
            ),
            None,
        )
        if processing_step is not None:
            return processing_step

        if display_status == "running" and task.current_stage:
            return step_by_code.get(task.current_stage)
        return None

    def _build_progress_detail(self, step: TaskStepRecord | None) -> dict[str, Any] | None:
        """从内部 step.detail_json 提取公开进度指标。"""
        if step is None:
            return None
        return self._filter_public_detail(step.detail_json, PUBLIC_PROGRESS_DETAIL_KEYS)

    def _build_result_detail(self, ctx: _StepContext, display_status: str) -> dict[str, Any] | None:
        """构造面向项目页的结果指标，不直接透传任务原始 result_json。"""
        task = ctx.task
        if task is None or display_status != "succeeded":
            return None
        result = task.result_json or {}

        if ctx.code == STEP_MINERU_PARSE:
            return self._build_textbook_result_detail(result)
        if ctx.code == STEP_LEARNER_PROFILE:
            return self._build_learner_profile_result_detail(result)
        if ctx.code == STEP_KNOWLEDGE_STRUCTURE:
            return self._build_knowledge_result_detail(result)
        if ctx.code == STEP_CURRICULUM_PLAN:
            return self._build_curriculum_result_detail(result)
        if ctx.code == STEP_LESSON_PLAN_GENERATE:
            return self._build_lesson_plan_result_detail(result)
        if ctx.code == STEP_COVERAGE_CHECK:
            return self._build_coverage_result_detail(ctx, result)
        return None

    def _build_textbook_result_detail(self, result: dict[str, Any]) -> dict[str, Any] | None:
        detail: dict[str, Any] = {}
        self._put_metric(detail, "page_count", result.get("page_count"))
        self._put_metric(detail, "issue_count", result.get("issue_count"))
        return detail or None

    def _build_learner_profile_result_detail(self, result: dict[str, Any]) -> dict[str, Any] | None:
        detail: dict[str, Any] = {}
        self._put_metric(detail, "profile_record_count", result.get("record_count"))
        return detail or None

    def _build_knowledge_result_detail(self, result: dict[str, Any]) -> dict[str, Any] | None:
        detail: dict[str, Any] = {}
        for key in (
            "chapter_count",
            "point_count",
            "semantic_chunk_vector_count",
            "knowledge_point_vector_count",
        ):
            self._put_metric(detail, key, result.get(key))
        return detail or None

    def _build_curriculum_result_detail(self, result: dict[str, Any]) -> dict[str, Any] | None:
        detail: dict[str, Any] = {}
        curriculum_plan = self._get_curriculum_plan_from_result(result)
        if curriculum_plan is not None:
            self._put_metric(detail, "plan_title", curriculum_plan.plan_title)
            self._put_metric(detail, "course_count", curriculum_plan.course_count)
            self._put_metric(detail, "session_duration_minutes", curriculum_plan.session_duration_minutes)
            lesson_sessions = (curriculum_plan.content_json or {}).get("lesson_sessions")
            if isinstance(lesson_sessions, list):
                self._put_metric(detail, "lesson_session_count", len(lesson_sessions))

        for key in ("plan_title", "course_count", "session_duration_minutes", "lesson_session_count"):
            if key not in detail:
                self._put_metric(detail, key, result.get(key))
        return detail or None

    def _build_lesson_plan_result_detail(self, result: dict[str, Any]) -> dict[str, Any] | None:
        detail: dict[str, Any] = {}
        self._put_metric(detail, "lesson_plan_count", result.get("lesson_plan_count"))
        return detail or None

    def _build_coverage_result_detail(self, ctx: _StepContext, result: dict[str, Any]) -> dict[str, Any] | None:
        detail: dict[str, Any] = {}
        coverage_report = ctx.summary_extra.get("coverage_report")
        summary_json = None
        if coverage_report is not None:
            summary_json = coverage_report.coverage_summary_json or {}

        coverage_rate = result.get("coverage_rate")
        if coverage_rate is None and coverage_report is not None:
            coverage_rate = coverage_report.coverage_rate
        self._put_metric(detail, "coverage_rate", coverage_rate)

        warning_count = result.get("warning_count")
        if warning_count is None and coverage_report is not None:
            warning_count = coverage_report.warning_count
        if warning_count is None and isinstance(summary_json, dict):
            warning_count = summary_json.get("warning_count")
        self._put_metric(detail, "warning_count", warning_count)

        if isinstance(summary_json, dict):
            for key in (
                "total_count",
                "covered_count",
                "uncovered_count",
                "important_total_count",
                "important_covered_count",
                "important_coverage_rate",
            ):
                self._put_metric(detail, key, summary_json.get(key))
        return detail or None

    def _get_curriculum_plan_from_result(self, result: dict[str, Any]) -> CurriculumPlan | None:
        """按任务结果中的课程大纲主键读取课程大纲，用于补齐标题和课次数。"""
        curriculum_plan_id = result.get("curriculum_plan_id")
        if curriculum_plan_id is None:
            return None
        try:
            return self.session.get(CurriculumPlan, int(curriculum_plan_id))
        except (TypeError, ValueError):
            return None

    @classmethod
    def _filter_public_detail(
        cls,
        source: dict[str, Any] | None,
        allowed_keys: set[str],
    ) -> dict[str, Any] | None:
        """按白名单过滤公开指标，避免原样透出内部 detail_json/result_json。"""
        if not isinstance(source, dict):
            return None
        detail: dict[str, Any] = {}
        for key in allowed_keys:
            cls._put_metric(detail, key, source.get(key))
        return detail or None

    @classmethod
    def _put_metric(cls, target: dict[str, Any], key: str, value: Any) -> None:
        normalized = cls._normalize_metric_value(value)
        if normalized is not None:
            target[key] = normalized

    @staticmethod
    def _normalize_metric_value(value: Any) -> Any:
        """把数据库类型归一成可 JSON 化的公开指标值。"""
        if value is None:
            return None
        if isinstance(value, Decimal):
            return float(value)
        if isinstance(value, (str, int, float, bool)):
            return value
        return None

    @staticmethod
    def _compute_step_status_detail(task: TaskRecord, display_status: str) -> str | None:
        """识别 step 的 retrying 状态：task 因 reaper 重排后回到 pending 且带历史错误码。"""
        if display_status != "pending":
            return None
        if (task.retry_count or 0) > 0 and task.last_error_code:
            return "retrying"
        return None

    def _build_summary(
        self,
        ctx: _StepContext,
        display_status: str,
        result_detail: dict[str, Any] | None,
    ) -> str | None:
        """根据展示状态拼接面向用户的摘要文案。"""
        if display_status == "running":
            return RUNNING_SUMMARY_BY_STEP.get(ctx.code)
        if display_status != "succeeded":
            return None

        task = ctx.task
        if task is None:
            return None
        result_detail = result_detail or {}

        if ctx.code == STEP_MINERU_PARSE:
            page_count = result_detail.get("page_count")
            issue_count = result_detail.get("issue_count")
            if page_count is not None and issue_count is not None:
                if int(issue_count) == 0:
                    return f"已识别 {page_count} 页教材内容，暂无待核查项。"
                return f"已识别 {page_count} 页教材内容，待核查项 {issue_count} 个。"
            if page_count is not None:
                return f"已识别 {page_count} 页教材内容。"
            return "教材解析已完成。"
        if ctx.code == STEP_LEARNER_PROFILE:
            record_count = result_detail.get("profile_record_count")
            if record_count is not None:
                return f"已生成 {record_count} 条学情画像记录。"
            return "学情分析已完成。"
        if ctx.code == STEP_KNOWLEDGE_STRUCTURE:
            chapter_count = result_detail.get("chapter_count")
            point_count = result_detail.get("point_count")
            if chapter_count and point_count:
                return f"已识别 {chapter_count} 个章节、{point_count} 个知识点。"
            if point_count:
                return f"已识别 {point_count} 个知识点。"
            return "知识点结构已生成。"
        if ctx.code == STEP_CURRICULUM_PLAN:
            plan_title = result_detail.get("plan_title")
            course_count = result_detail.get("course_count")
            lesson_session_count = result_detail.get("lesson_session_count")
            if plan_title and course_count:
                return f"课程总纲《{plan_title}》已生成，共 {course_count} 课次。"
            if course_count:
                return f"课程总纲已生成，共 {course_count} 课次。"
            if lesson_session_count:
                return f"课程总纲已生成，包含 {lesson_session_count} 个课次安排。"
            return "课程总纲已生成。"
        if ctx.code == STEP_LESSON_PLAN_GENERATE:
            lesson_plan_count = result_detail.get("lesson_plan_count")
            if lesson_plan_count:
                return f"已生成 {lesson_plan_count} 课时教案。"
            return "教案已生成。"
        if ctx.code == STEP_COVERAGE_CHECK:
            coverage_rate = result_detail.get("coverage_rate")
            if coverage_rate is not None:
                covered_count = result_detail.get("covered_count")
                total_count = result_detail.get("total_count")
                warning_count = result_detail.get("warning_count")
                if covered_count is not None and total_count is not None and warning_count is not None:
                    return (
                        f"知识点覆盖 {float(coverage_rate):.2f}%，"
                        f"已覆盖 {covered_count}/{total_count}，告警 {warning_count} 个。"
                    )
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
        active_run=None,
    ) -> tuple[str, str | None, str | None, str | None]:
        """根据 6 步状态计算 (整体状态, 细化状态, blocked_reason, 当前步骤编码)。

        细化状态优先级：blocked > waiting_user_confirm > retrying > waiting_dispatch。
        整体状态保持 pending/running/succeeded/failed 四值；细化状态不参与该枚举。
        """
        # 失败优先
        for step in steps:
            if step.status == "failed":
                return "failed", None, None, step.code

        # 来自 active_run 的高优先级细化语义
        run_blocked_reason = None
        run_detail: str | None = None
        if active_run is not None:
            if active_run.run_status == "waiting_user_confirm":
                run_detail = "waiting_user_confirm"
            elif active_run.run_status == "running" and active_run.blocked_reason:
                run_detail = "blocked"
                run_blocked_reason = active_run.blocked_reason

        # 来自 step 的 retrying 细化
        retrying_step = next((step for step in steps if step.status_detail == "retrying"), None)
        # 有 running step → integrate 步骤层级 retrying，整体仍 running
        for step in steps:
            if step.status == "running":
                if run_detail is not None:
                    return "running", run_detail, run_blocked_reason, step.code
                if retrying_step is not None:
                    return "running", "retrying", None, retrying_step.code
                return "running", None, None, step.code

        if all(step.status == "succeeded" for step in steps):
            return "succeeded", None, None, None

        if any(step.status == "succeeded" for step in steps):
            # 部分完成但没有 running step → 一定是「等待后端调度下一步」的语义，
            # 不管 active_run 是否存在：
            # - 走新 orchestrator 流程时，active_run.run_status='running' → status_detail=waiting_dispatch
            # - 没有 active_run（旧手动流程），后端确实不会自动调度下一步 → 同样标 waiting_dispatch，
            #   前端可据此提示用户启动 orchestrator 而不是误认为还在跑
            next_pending = next((step for step in steps if step.status == "pending"), None)
            if run_detail is not None:
                return "running", run_detail, run_blocked_reason, (next_pending.code if next_pending else None)
            if retrying_step is not None:
                return "running", "retrying", None, retrying_step.code
            return "running", "waiting_dispatch", None, (next_pending.code if next_pending else None)

        # 全 pending：若 active_run 在跑，说明等后端调度起步
        if active_run is not None and active_run.run_status in {"running", "pending", "waiting_user_confirm"}:
            next_pending = next((step for step in steps if step.status == "pending"), None)
            if run_detail is not None:
                return "running", run_detail, run_blocked_reason, (next_pending.code if next_pending else None)
            return "running", "waiting_dispatch", None, (next_pending.code if next_pending else None)
        return "pending", None, None, None
