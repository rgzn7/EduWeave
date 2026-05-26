"""
@Date: 2026-05-26
@Author: xisy
@Discription: 一键生成编排服务

后端持有 Phase2 的完整编排权：
- POST /projects/{id}/generation-runs 创建一次「运行」（generation_run），决定下一步该派发什么任务
- 每个上游任务（parse / profile / knowledge）成功后通过 advance_after_*_success 钩子续跑下一步
- 4→5→6（curriculum → lesson_plan → coverage）维持现有内部 dispatch 自动链；orchestrator 只观察并更新 run 状态
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.constants import (
    KNOWLEDGE_EXTRACT_TASK_TYPE,
    KNOWLEDGE_MODULE_CODE,
    KNOWLEDGE_QUEUE_NAME,
    PARSING_MODULE_CODE,
    PARSING_QUEUE_NAME,
    PARSE_MODE_FULL,
    REVIEW_STATUS_CONFIRMED,
    TASK_STATUS_PENDING,
    TASK_STATUS_SUCCESS,
    TEXTBOOK_PARSE_TASK_TYPE,
    VERSION_STATUS_READY,
)
from app.core.exceptions import AppException, BusinessErrorCode
from app.core.logging import get_logger
from app.core.middleware import get_request_id
from app.modules.knowledge.repository import KnowledgeRepository
from app.modules.learner_profile.repository import LearnerProfileRepository
from app.modules.orchestrator.repository import OrchestratorRepository
from app.modules.orchestrator.schemas import GenerationRunCreateRequest, GenerationRunResponse
from app.modules.p0_models import GenerationRun, LearnerProfileVersion, ParseVersion, TaskRecord
from app.modules.parsing.repository import ParsingRepository
from app.modules.pipeline.repository import PipelineRepository
from app.modules.pipeline.schemas import GenerationBatchCreateRequest
from app.modules.pipeline.service import PipelineService
from app.modules.project.repository import ProjectRepository
from app.modules.task_center.heartbeat import dispatch_with_attempt
from app.modules.task_center.repository import TaskCenterRepository
from app.shared.utils import DateTimeUtil

logger = get_logger(__name__)


# 阻塞原因编码：用于 generation_run.blocked_reason 与对外展示
BLOCKED_NO_TEXTBOOK = "NO_CURRENT_TEXTBOOK"
BLOCKED_NO_LEARNER_PROFILE = "NO_CURRENT_LEARNER_PROFILE"
BLOCKED_LEARNER_PROFILE_NOT_READY = "LEARNER_PROFILE_NOT_READY"
BLOCKED_WAITING_USER_CONFIRM = "WAITING_USER_CONFIRM"


class OrchestratorService:
    """一键生成编排服务。"""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.repository = OrchestratorRepository(session)
        self.project_repository = ProjectRepository(session)
        self.parsing_repository = ParsingRepository(session)
        self.profile_repository = LearnerProfileRepository(session)
        self.knowledge_repository = KnowledgeRepository(session)
        self.task_repository = TaskCenterRepository(session)
        self.pipeline_repository = PipelineRepository(session)

    # ------------------------------ 入口接口 ------------------------------

    def start_generation_run(
        self,
        *,
        owner_user_id: int,
        project_id: int,
        request: GenerationRunCreateRequest,
    ) -> GenerationRunResponse:
        """创建一次一键生成运行，并立即触发下一步任务。

        幂等保护：同一 project 同时只允许一个活跃 run。命中已有活跃 run 时直接返回它。
        """
        project = self.repository.lock_project_for_run(project_id, owner_user_id)
        if project is None:
            raise AppException(BusinessErrorCode.PROJECT_NOT_FOUND, "项目不存在")

        existing = self.repository.get_active_run_for_project(project_id)
        if existing is not None:
            return _build_run_response(existing)

        if project.current_textbook_version_id is None:
            raise AppException(
                BusinessErrorCode.GENERATION_BASELINE_INVALID,
                "项目尚未设置当前教材版本，无法启动一键生成",
            )
        if project.current_learner_profile_version_id is None:
            raise AppException(
                BusinessErrorCode.GENERATION_BASELINE_INVALID,
                "项目尚未上传学情文件，无法启动一键生成",
            )

        now = DateTimeUtil.now_utc()
        run = self.repository.create_run(
            GenerationRun(
                project_id=project_id,
                run_status="running",
                course_count=request.course_count,
                session_duration_minutes=request.session_duration_minutes,
                chapter_range_json=request.chapter_range_json,
                auto_confirm_parse=1 if request.auto_confirm_parse else 0,
                started_at=now,
                created_by=owner_user_id,
            )
        )
        project.active_generation_run_id = run.id
        project.last_activity_at = now
        self.project_repository.save(project)
        self.session.commit()

        # 入口决定从哪一步开始：parse → knowledge → batch
        try:
            self._dispatch_next_step(run, owner_user_id=owner_user_id)
        except Exception:  # noqa: BLE001
            # 派发失败：把 run 标为 failed，避免长期挂着
            self._mark_run_failed_internal(run, error_code="DISPATCH_FAILED", error_message="启动一键生成失败")
            raise

        self.session.expire(run)
        fresh_run = self.repository.get_run(run.id)
        return _build_run_response(fresh_run)

    def get_active_run(self, *, owner_user_id: int, project_id: int) -> GenerationRunResponse | None:
        """查询当前活跃运行，无则返回 None。"""
        project = self.project_repository.get_project_by_id_for_owner(project_id, owner_user_id)
        if project is None:
            raise AppException(BusinessErrorCode.PROJECT_NOT_FOUND, "项目不存在")
        run = self.repository.get_active_run_for_project(project_id)
        if run is None:
            return None
        return _build_run_response(run)

    # ------------------------------ 任务成功钩子 ------------------------------

    def advance_after_parse_success(self, *, task: TaskRecord, parse_version: ParseVersion) -> None:
        """parse 任务成功后续跑：根据 auto_confirm_parse 决定是否自动确认并触发 knowledge。"""
        run = self._get_run_for_task(task)
        if run is None:
            return
        if run.parse_version_id is None:
            run.parse_version_id = parse_version.id
            self.repository.save(run)
        if run.run_status != "running":
            return

        if run.auto_confirm_parse and parse_version.review_status != REVIEW_STATUS_CONFIRMED:
            parse_version.review_status = REVIEW_STATUS_CONFIRMED
            self.parsing_repository.save(parse_version)
            self.session.commit()
            logger.info("orchestrator 自动确认解析版本", run_id=run.id, parse_version_id=parse_version.id)

        if not run.auto_confirm_parse:
            run.run_status = "waiting_user_confirm"
            run.blocked_reason = BLOCKED_WAITING_USER_CONFIRM
            self.repository.save(run)
            self.session.commit()
            return

        self._dispatch_knowledge_if_needed(run, owner_user_id=task.operator_user_id, parse_version=parse_version)

    def advance_after_parse_confirmed(self, *, parse_version: ParseVersion, owner_user_id: int | None) -> None:
        """confirm_parse_version 完成后调用：让停在 waiting_user_confirm 的 run 续跑。"""
        if parse_version is None or parse_version.review_status != REVIEW_STATUS_CONFIRMED:
            return
        run = self.repository.get_active_run_for_project(parse_version.project_id)
        if run is None or run.run_status != "waiting_user_confirm":
            return
        run.run_status = "running"
        run.blocked_reason = None
        if run.parse_version_id is None:
            run.parse_version_id = parse_version.id
        self.repository.save(run)
        self.session.commit()
        self._dispatch_knowledge_if_needed(run, owner_user_id=owner_user_id, parse_version=parse_version)

    def advance_after_profile_success(self, *, task: TaskRecord, profile_version: LearnerProfileVersion) -> None:
        """学情抽取成功钩子：若知识版本已就绪，可能立刻 ready 去创建 batch。"""
        run = self._get_run_for_task(task)
        if run is None or run.run_status != "running":
            return
        # 学情仅作为 batch 前置之一；真正决策由 _dispatch_batch_if_ready 完成
        self._try_dispatch_batch(run, owner_user_id=task.operator_user_id, profile_version=profile_version)

    def advance_after_knowledge_success(
        self,
        *,
        task: TaskRecord,
        knowledge_version_id: int,
    ) -> None:
        """知识抽取成功钩子：若学情已 ready，则创建 generation_batch；否则 run 挂 blocked。"""
        run = self._get_run_for_task(task)
        if run is None:
            return
        if run.knowledge_version_id is None:
            run.knowledge_version_id = knowledge_version_id
            self.repository.save(run)
        if run.run_status != "running":
            return

        project = self.project_repository.get_project_by_id_for_owner(
            run.project_id, owner_user_id=run.created_by or 0
        )
        if project is None:
            return
        profile_version = (
            self.session.get(LearnerProfileVersion, project.current_learner_profile_version_id)
            if project.current_learner_profile_version_id is not None
            else None
        )
        self._try_dispatch_batch(run, owner_user_id=task.operator_user_id, profile_version=profile_version)

    def advance_after_curriculum_success(self, *, task: TaskRecord) -> None:
        """课程规划成功，记录到 run 上，run 状态保持 running（lesson_plan 自动链承担下一步）。"""
        run = self._get_run_for_task(task)
        if run is None:
            return
        if run.generation_batch_id is None and task.generation_batch_id is not None:
            run.generation_batch_id = task.generation_batch_id
            self.repository.save(run)
            self.session.commit()

    def advance_after_lesson_plan_success(self, *, task: TaskRecord) -> None:
        """教案生成成功，状态由 coverage 继续推进，无需在此切 succeeded。"""
        run = self._get_run_for_task(task)
        if run is None:
            return
        if run.generation_batch_id is None and task.generation_batch_id is not None:
            run.generation_batch_id = task.generation_batch_id
            self.repository.save(run)
            self.session.commit()

    def advance_after_coverage_success(self, *, task: TaskRecord) -> None:
        """覆盖检查成功 → 整个 run 标记 succeeded。"""
        run = self._get_run_for_task(task)
        if run is None:
            return
        run.run_status = "succeeded"
        run.finished_at = DateTimeUtil.now_utc()
        run.blocked_reason = None
        self.repository.save(run)
        self.session.commit()

    def mark_run_failed(self, *, task: TaskRecord, error_code: str | None, error_message: str | None) -> None:
        """任务终态失败时把关联 run 也标为 failed。"""
        run = self._get_run_for_task(task)
        if run is None:
            return
        if run.run_status in {"succeeded", "failed", "cancelled"}:
            return
        self._mark_run_failed_internal(run, error_code=error_code, error_message=error_message)

    # ------------------------------ 内部辅助 ------------------------------

    def _get_run_for_task(self, task: TaskRecord) -> GenerationRun | None:
        """从 task.payload_json 反查 generation_run；未关联则返回 None。"""
        if task is None:
            return None
        payload = task.payload_json or {}
        run_id = payload.get("generation_run_id")
        if run_id is None:
            return None
        return self.repository.get_run(int(run_id))

    def _dispatch_next_step(self, run: GenerationRun, *, owner_user_id: int) -> None:
        """根据当前数据状态决定首次派发哪个任务。"""
        project = self.project_repository.get_project_by_id_for_owner(run.project_id, owner_user_id)
        if project is None:
            return
        parse_version = self.parsing_repository.get_active_parse_version(project.current_textbook_version_id)
        if parse_version is None or parse_version.review_status != REVIEW_STATUS_CONFIRMED or parse_version.parse_status != TASK_STATUS_SUCCESS:
            # 没有可用 parse_version → 触发 parse_task
            self._dispatch_parse(run, owner_user_id=owner_user_id, textbook_version_id=project.current_textbook_version_id)
            return
        # parse 已就绪 → 检查 knowledge
        knowledge_version = self.knowledge_repository.get_ready_knowledge_version(parse_version.id)
        if knowledge_version is None:
            self._dispatch_knowledge_if_needed(run, owner_user_id=owner_user_id, parse_version=parse_version)
            return
        # knowledge 已就绪 → 直接创建 batch
        run.parse_version_id = parse_version.id
        run.knowledge_version_id = knowledge_version.id
        self.repository.save(run)
        self.session.commit()
        profile_version = (
            self.session.get(LearnerProfileVersion, project.current_learner_profile_version_id)
            if project.current_learner_profile_version_id is not None
            else None
        )
        self._try_dispatch_batch(run, owner_user_id=owner_user_id, profile_version=profile_version)

    def _dispatch_parse(self, run: GenerationRun, *, owner_user_id: int, textbook_version_id: int) -> None:
        """直接创建并派发一个 textbook_parse 任务，并把 run 关联到任务 payload。"""
        payload_json: dict[str, object] = {
            "textbook_version_id": textbook_version_id,
            "strategy_code": "mineru_vlm_default",
            "set_as_current_on_success": True,
            "generation_run_id": run.id,
        }
        task = self.task_repository.create_task(
            project_id=run.project_id,
            module_code=PARSING_MODULE_CODE,
            task_type=TEXTBOOK_PARSE_TASK_TYPE,
            task_status=TASK_STATUS_PENDING,
            queue_name=PARSING_QUEUE_NAME,
            biz_key=f"textbook_version:{textbook_version_id}:{PARSE_MODE_FULL}",
            operator_user_id=owner_user_id,
            payload_json=payload_json,
            request_id=get_request_id() or None,
        )
        step_names = [
            ("prepare_source", "准备源文件"),
            ("submit_mineru", "提交 MinerU 任务"),
            ("poll_mineru_result", "轮询 MinerU 结果"),
            ("persist_parse_result", "落库解析结果"),
        ]
        for step_order, (step_code, step_name) in enumerate(step_names, start=1):
            self.task_repository.create_task_step(
                task_record_id=task.id,
                step_code=step_code,
                step_name=step_name,
                step_order=step_order,
                step_status=TASK_STATUS_PENDING,
            )
        self.session.commit()

        dispatch_result = dispatch_with_attempt(
            self.task_repository,
            task=task,
            callable_path="app.modules.parsing.tasks.run_parse_task",
            payload={
                "task_record_id": task.id,
                "textbook_version_id": textbook_version_id,
                "operator_user_id": owner_user_id,
                "strategy_code": "mineru_vlm_default",
                "set_as_current_on_success": True,
                "generation_run_id": run.id,
            },
            queue=PARSING_QUEUE_NAME,
        )
        if dispatch_result.worker_task_id:
            task.worker_task_id = dispatch_result.worker_task_id
            self.task_repository.save(task)
            self.session.commit()

    def _dispatch_knowledge_if_needed(
        self,
        run: GenerationRun,
        *,
        owner_user_id: int | None,
        parse_version: ParseVersion,
    ) -> None:
        """触发知识抽取任务（若尚无活跃任务且无可用知识版本）。"""
        ready_knowledge = self.knowledge_repository.get_ready_knowledge_version(parse_version.id)
        if ready_knowledge is not None:
            run.knowledge_version_id = ready_knowledge.id
            self.repository.save(run)
            self.session.commit()
            project = self.project_repository.get_project_by_id_for_owner(
                run.project_id, owner_user_id or run.created_by or 0
            )
            profile_version = (
                self.session.get(LearnerProfileVersion, project.current_learner_profile_version_id)
                if project is not None and project.current_learner_profile_version_id is not None
                else None
            )
            self._try_dispatch_batch(run, owner_user_id=owner_user_id, profile_version=profile_version)
            return

        active_task = self.task_repository.get_active_task_by_biz_key(
            module_code=KNOWLEDGE_MODULE_CODE,
            task_type=KNOWLEDGE_EXTRACT_TASK_TYPE,
            biz_key=f"parse_version:{parse_version.id}:knowledge",
        )
        if active_task is not None:
            # 已经在跑，等待 advance_after_knowledge_success 续推
            return

        payload_json: dict[str, object] = {
            "parse_version_id": parse_version.id,
            "force_regenerate": False,
            "generation_run_id": run.id,
        }
        task = self.task_repository.create_task(
            project_id=run.project_id,
            module_code=KNOWLEDGE_MODULE_CODE,
            task_type=KNOWLEDGE_EXTRACT_TASK_TYPE,
            task_status=TASK_STATUS_PENDING,
            queue_name=KNOWLEDGE_QUEUE_NAME,
            biz_key=f"parse_version:{parse_version.id}:knowledge",
            operator_user_id=owner_user_id,
            payload_json=payload_json,
            request_id=get_request_id() or None,
        )
        step_names = [
            ("prepare_parse_source", "准备解析源"),
            ("invoke_llm_extract", "调用 LLM 抽取知识"),
            ("persist_knowledge_result", "落库知识结果"),
            ("upsert_vectors", "写入知识向量"),
        ]
        for step_order, (step_code, step_name) in enumerate(step_names, start=1):
            self.task_repository.create_task_step(
                task_record_id=task.id,
                step_code=step_code,
                step_name=step_name,
                step_order=step_order,
                step_status=TASK_STATUS_PENDING,
            )
        self.session.commit()

        dispatch_result = dispatch_with_attempt(
            self.task_repository,
            task=task,
            callable_path="app.modules.knowledge.tasks.run_extract_task",
            payload={
                "task_record_id": task.id,
                "parse_version_id": parse_version.id,
                "operator_user_id": owner_user_id,
                "force_regenerate": False,
                "generation_run_id": run.id,
            },
            queue=KNOWLEDGE_QUEUE_NAME,
        )
        if dispatch_result.worker_task_id:
            task.worker_task_id = dispatch_result.worker_task_id
            self.task_repository.save(task)
            self.session.commit()

    def _try_dispatch_batch(
        self,
        run: GenerationRun,
        *,
        owner_user_id: int | None,
        profile_version: LearnerProfileVersion | None,
    ) -> None:
        """前置满足时创建 generation_batch；否则把 run 挂 blocked。"""
        if run.run_status != "running" or run.generation_batch_id is not None:
            return
        if run.knowledge_version_id is None:
            return
        if profile_version is None:
            run.blocked_reason = BLOCKED_NO_LEARNER_PROFILE
            self.repository.save(run)
            self.session.commit()
            return
        if profile_version.version_status != VERSION_STATUS_READY or profile_version.extract_status != "success":
            run.blocked_reason = BLOCKED_LEARNER_PROFILE_NOT_READY
            self.repository.save(run)
            self.session.commit()
            return

        request = GenerationBatchCreateRequest(
            project_id=run.project_id,
            knowledge_version_id=run.knowledge_version_id,
            learner_profile_version_id=profile_version.id,
            batch_name=None,
            chapter_range_json=run.chapter_range_json,
            course_count=run.course_count,
            session_duration_minutes=run.session_duration_minutes,
        )
        pipeline_service = PipelineService(self.session, self.pipeline_repository)
        detail = pipeline_service.create_generation_batch(
            owner_user_id=owner_user_id or run.created_by or 0,
            request=request,
            generation_run_id=run.id,
        )
        run.generation_batch_id = detail.id
        run.blocked_reason = None
        self.repository.save(run)
        self.session.commit()

    def _mark_run_failed_internal(
        self,
        run: GenerationRun,
        *,
        error_code: str | None,
        error_message: str | None,
    ) -> None:
        """run 标记终态失败的内部实现。"""
        run.run_status = "failed"
        run.last_error_code = error_code
        run.last_error_message = (error_message or "")[:500] if error_message else None
        run.finished_at = DateTimeUtil.now_utc()
        self.repository.save(run)
        self.session.commit()


def _build_run_response(run: GenerationRun) -> GenerationRunResponse:
    """把 ORM 实体映射成响应模型。"""
    return GenerationRunResponse(
        id=run.id,
        project_id=run.project_id,
        run_status=run.run_status,
        course_count=run.course_count,
        session_duration_minutes=run.session_duration_minutes,
        chapter_range_json=run.chapter_range_json,
        auto_confirm_parse=bool(run.auto_confirm_parse),
        parse_version_id=run.parse_version_id,
        knowledge_version_id=run.knowledge_version_id,
        generation_batch_id=run.generation_batch_id,
        blocked_reason=run.blocked_reason,
        last_error_code=run.last_error_code,
        last_error_message=run.last_error_message,
        started_at=run.started_at,
        finished_at=run.finished_at,
        created_at=run.created_at,
        updated_at=run.updated_at,
    )
