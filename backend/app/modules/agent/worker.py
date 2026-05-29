"""
@Date: 2026-05-29
@Author: xisy
@Discription: 智能助手后台运行 worker：租约抢占、执行 Agent 循环、续租与终态流转
"""

from __future__ import annotations

import threading
import uuid

import structlog

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.exceptions import AppException, BusinessErrorCode
from app.modules.agent.executor import AgentRunCancelled, AgentRunExecutor
from app.modules.agent.models import AgentRun
from app.modules.agent.repository import AgentRepository
from app.modules.agent.run_service import AgentRunService
from app.modules.auth.repository import AuthRepository
from app.shared.queue.lease_queue import LeaseQueueRepository

logger = structlog.get_logger(__name__)

# 可重试的瞬时错误码
_RETRYABLE_ERROR_CODES = frozenset(
    {
        BusinessErrorCode.LLM_REQUEST_FAILED.value,
        BusinessErrorCode.EXTERNAL_SERVICE_ERROR.value,
    }
)


class AgentRunWorker:
    """后台 Agent 运行 worker（守护线程）。"""

    def __init__(self, worker_id: str | None = None) -> None:
        self.settings = get_settings()
        self.worker_id = worker_id or f"agent-worker-{uuid.uuid4().hex[:8]}"
        self._stop_event = threading.Event()

    def stop(self) -> None:
        """请求停止 worker。"""
        self._stop_event.set()

    def run_forever(self) -> None:
        """持续抢占并执行运行。"""
        logger.info("agent_worker_started", worker_id=self.worker_id)
        while not self._stop_event.is_set():
            try:
                worked = self._run_once()
            except Exception as exc:  # noqa: BLE001 - worker 主循环必须健壮
                logger.warning("agent_worker_loop_error", worker_id=self.worker_id, error=str(exc))
                worked = False
            if not worked:
                self._stop_event.wait(self.settings.agent_run_poll_interval_seconds)
        logger.info("agent_worker_stopped", worker_id=self.worker_id)

    def _run_once(self) -> bool:
        """抢占一条运行并执行；无可执行运行返回 False。"""
        with SessionLocal() as db:
            queue = LeaseQueueRepository(
                db,
                AgentRun,
                lease_seconds=self.settings.agent_run_lease_seconds,
                retry_base_seconds=self.settings.task_retry_backoff_base_seconds,
            )
            run = queue.claim_next(self.worker_id, include_expired_running=True)
            run_id = run.id if run is not None else None
        if run_id is None:
            return False
        self._execute_run(run_id)
        return True

    def _execute_run(self, run_id: int) -> None:
        """在独立会话中执行运行，并启动续租线程。"""
        renew_stop = threading.Event()
        renew_thread = threading.Thread(target=self._renew_loop, args=(run_id, renew_stop), daemon=True)
        renew_thread.start()
        try:
            with SessionLocal() as db:
                repository = AgentRepository(db)
                run_service = AgentRunService(db, repository)
                run = repository.get_run(run_id)
                if run is None:
                    return
                user = AuthRepository(db).get_by_id(run.user_id)
                if user is None:
                    run_service.mark_failed(run, error_code="UNAUTHORIZED", message="运行所属用户不存在")
                    return
                run_service.emit_event(
                    run,
                    event_type="started",
                    title="开始处理",
                    message="Agent 开始处理你的请求",
                )
                try:
                    executor = AgentRunExecutor(db, user, run)
                    final_text = executor.execute()
                    run_service.mark_succeeded(run, final_text)
                except AgentRunCancelled:
                    logger.info("agent_run_cancelled", run_id=run_id)
                except (AppException, Exception) as exc:  # noqa: BLE001
                    self._handle_failure(db, run_id, exc)
        finally:
            renew_stop.set()

    def _handle_failure(self, db, run_id: int, exc: Exception) -> None:
        """按可重试性流转失败运行并发出事件。"""
        if isinstance(exc, AppException):
            error_code = exc.code.value
            message = exc.message
        else:
            error_code = "AGENT_RUN_ERROR"
            message = str(exc)
        retryable = (not isinstance(exc, AppException)) or error_code in _RETRYABLE_ERROR_CODES
        logger.warning("agent_run_failed", run_id=run_id, error_code=error_code, message=message, retryable=retryable)

        repository = AgentRepository(db)
        run_service = AgentRunService(db, repository)
        queue = LeaseQueueRepository(
            db,
            AgentRun,
            lease_seconds=self.settings.agent_run_lease_seconds,
            retry_base_seconds=self.settings.task_retry_backoff_base_seconds,
        )
        is_terminal = queue.mark_attempt_failed(
            run_id,
            self.worker_id,
            message,
            error_code=error_code,
            retryable=retryable,
        )
        run = repository.get_run(run_id)
        if run is None:
            return
        if is_terminal:
            run_service.emit_event(
                run,
                event_type="failed",
                title="运行失败",
                message=message,
                payload={"error_code": error_code},
            )
        else:
            run_service.emit_event(
                run,
                event_type="retry",
                title="稍后重试",
                message=message,
                payload={"error_code": error_code},
            )

    def _renew_loop(self, run_id: int, stop_event: threading.Event) -> None:
        """周期续租，避免长任务被回收。"""
        interval = max(self.settings.agent_run_lease_seconds / 3, 5)
        while not stop_event.wait(interval):
            try:
                with SessionLocal() as db:
                    queue = LeaseQueueRepository(
                        db, AgentRun, lease_seconds=self.settings.agent_run_lease_seconds
                    )
                    queue.renew_lease(run_id, self.worker_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning("agent_run_renew_failed", run_id=run_id, error=str(exc))


class AgentWorkerPool:
    """管理一组后台 worker 线程。"""

    def __init__(self) -> None:
        self.settings = get_settings()
        self._workers: list[AgentRunWorker] = []
        self._threads: list[threading.Thread] = []

    def start(self) -> None:
        """启动配置数量的 worker 线程。"""
        if not self.settings.agent_run_worker_enabled:
            return
        for _ in range(max(1, self.settings.agent_run_worker_count)):
            worker = AgentRunWorker()
            thread = threading.Thread(target=worker.run_forever, daemon=True)
            self._workers.append(worker)
            self._threads.append(thread)
            thread.start()

    def stop(self) -> None:
        """停止全部 worker。"""
        for worker in self._workers:
            worker.stop()
        for thread in self._threads:
            thread.join(timeout=5)
