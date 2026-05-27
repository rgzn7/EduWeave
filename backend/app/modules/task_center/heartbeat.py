"""
@Date: 2026-05-26
@Author: xisy
@Discription: 长任务心跳与执行实例（attempt）机制

设计动机：
- 旧实现仅依赖 `task_record.updated_at` 判定 stale，长 LLM 阶段不写库会被 reaper 误判
- reaper 重排时只重置 DB 状态、未确保原 worker 失效，可能出现两个 worker 并发写库

本模块提供两类能力：
- `start_attempt`：在任务派发前/reaper 重排前生成新的 attempt_id 并写库，作为「当前唯一权威 worker」标记
- `TaskHeartbeat`：长任务期间使用的上下文管理器，所有写库都走带 `WHERE execution_attempt_id=?` 的 CAS UPDATE，
  若 rowcount==0 说明本 worker 已被抢占，抛 `StaleAttemptError` 直接退出，避免与新 worker 并发写库
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from threading import Event, Thread
from time import monotonic
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.core.exceptions import AppException, BusinessErrorCode
from app.modules.task_center.progress import clamp_progress
from app.modules.task_center.repository import TaskCenterRepository


class StaleAttemptError(AppException):
    """当前 worker 的 attempt_id 已被新 attempt 抢占。"""

    def __init__(self, task_id: int, attempt_id: str) -> None:
        super().__init__(
            BusinessErrorCode.TASK_STALE_ATTEMPT,
            f"任务 {task_id} 的 attempt {attempt_id} 已被新 attempt 取代，本 worker 终止",
            {"task_id": task_id, "execution_attempt_id": attempt_id},
        )


def start_attempt(task_repository: TaskCenterRepository, task_id: int) -> str:
    """生成新的 attempt_id 并写入 task_record，返回新值。

    必须在 commit 后再 dispatch 任务，确保 worker 看到的 attempt_id 与 payload 中一致。
    """
    attempt_id = str(uuid.uuid4())
    task_repository.session.execute(
        text("UPDATE task_record SET execution_attempt_id = :attempt_id WHERE id = :task_id"),
        {"attempt_id": attempt_id, "task_id": task_id},
    )
    return attempt_id


@dataclass(slots=True)
class _HeartbeatBinding:
    """心跳绑定的最小上下文。"""

    session: Session
    task_id: int
    attempt_id: str


class TaskHeartbeat:
    """长任务专用心跳与进度上下文管理器。

    用法：
        attempt_id = payload["execution_attempt_id"]
        with TaskHeartbeat(session, task_id, attempt_id) as hb:
            hb.tick(progress_percent=35, current_stage="invoke_llm_extract")
            for i, chunk in enumerate(chunks):
                ...
                hb.tick(progress_percent=35 + int(25 * (i + 1) / total),
                        detail={"processed_chunks": i + 1, "total_chunks": total})
            hb.touch()  # LLM 调用前后只刷心跳，不动业务字段

    所有写入都带 `WHERE execution_attempt_id = :attempt_id`；若 rowcount==0
    表示 attempt 已被抢占，抛 `StaleAttemptError`。
    """

    def __init__(self, session: Session, task_id: int, attempt_id: str | None) -> None:
        # attempt_id 允许为 None 用于兼容历史调用方，调用方应在入口处生成
        self._binding = _HeartbeatBinding(session=session, task_id=task_id, attempt_id=attempt_id or "")

    def __enter__(self) -> "TaskHeartbeat":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        # 上下文退出本身不触发额外写库，避免压住调用方的事务边界
        return None

    @property
    def attempt_id(self) -> str:
        return self._binding.attempt_id

    def touch(self) -> None:
        """只刷新 last_heartbeat_at；用于 LLM 长阻塞前后宣告 worker 仍在工作。"""
        result = self._binding.session.execute(
            text(
                "UPDATE task_record SET last_heartbeat_at = CURRENT_TIMESTAMP(3) "
                "WHERE id = :task_id AND (execution_attempt_id IS NULL OR execution_attempt_id = :attempt_id)"
            ),
            {"task_id": self._binding.task_id, "attempt_id": self._binding.attempt_id},
        )
        if result.rowcount == 0:
            raise StaleAttemptError(self._binding.task_id, self._binding.attempt_id)
        self._binding.session.commit()

    def tick(
        self,
        *,
        progress_percent: int | None = None,
        current_stage: str | None = None,
        task_status: str | None = None,
    ) -> None:
        """更新进度/阶段/状态，并刷新心跳；走 CAS UPDATE 防止与重排后的新 worker 并发写。

        - progress_percent / current_stage / task_status 传入 None 表示该字段不动
        - 调用本方法本身会 commit，便于循环内即时落库
        """
        binding = self._binding
        params: dict[str, Any] = {
            "task_id": binding.task_id,
            "attempt_id": binding.attempt_id,
        }
        assignments = ["last_heartbeat_at = CURRENT_TIMESTAMP(3)"]
        if progress_percent is not None:
            params["progress_percent"] = clamp_progress(progress_percent)
            assignments.append(
                "progress_percent = CASE "
                "WHEN progress_percent > :progress_percent THEN progress_percent "
                "ELSE :progress_percent END"
            )
        if current_stage is not None:
            params["current_stage"] = current_stage
            assignments.append("current_stage = :current_stage")
        if task_status is not None:
            params["task_status"] = task_status
            assignments.append("task_status = :task_status")
        sql = (
            "UPDATE task_record SET "
            + ", ".join(assignments)
            + " WHERE id = :task_id AND (execution_attempt_id IS NULL OR execution_attempt_id = :attempt_id)"
        )
        result = binding.session.execute(text(sql), params)
        if result.rowcount == 0:
            raise StaleAttemptError(binding.task_id, binding.attempt_id)
        binding.session.commit()

    def update_step_detail(
        self,
        *,
        step_id: int,
        progress_percent: int | None = None,
        detail_json: dict[str, Any] | None = None,
    ) -> None:
        """更新指定 step 的进度与 detail_json。

        step 表无 attempt_id 列，但本方法只在 tick / touch 校验当前 attempt 通过后调用，
        语义上仍受 attempt CAS 保护。
        """
        params: dict[str, Any] = {"step_id": step_id}
        assignments: list[str] = []
        if progress_percent is not None:
            params["progress_percent"] = clamp_progress(progress_percent)
            assignments.append(
                "progress_percent = CASE "
                "WHEN progress_percent > :progress_percent THEN progress_percent "
                "ELSE :progress_percent END"
            )
        if detail_json is not None:
            import json as _json

            params["detail_json"] = _json.dumps(detail_json, ensure_ascii=False)
            assignments.append("detail_json = CAST(:detail_json AS JSON)")
        if not assignments:
            return
        sql = "UPDATE task_step_record SET " + ", ".join(assignments) + " WHERE id = :step_id"
        self._binding.session.execute(text(sql), params)
        self._binding.session.commit()


class TaskProgressPulse:
    """长阻塞阶段估算进度脉冲。

    该工具使用独立短生命周期 Session 周期性刷新 task_record，避免主线程卡在同步 LLM
    或外部接口调用时，页面长期停留在固定跳点。
    """

    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        task_id: int,
        attempt_id: str | None,
        current_stage: str,
        start_progress: int,
        max_progress: int,
        interval_seconds: float = 5.0,
    ) -> None:
        self._session_factory = session_factory
        self._task_id = task_id
        self._attempt_id = attempt_id
        self._current_stage = current_stage
        self._start_progress = clamp_progress(start_progress)
        self._max_progress = max(self._start_progress, clamp_progress(max_progress))
        self._interval_seconds = max(0.05, float(interval_seconds))
        self._stop_event = Event()
        self._thread: Thread | None = None
        self._started_at = 0.0
        self._stale_error: StaleAttemptError | None = None

    def __enter__(self) -> "TaskProgressPulse":
        self._started_at = monotonic()
        self._thread = Thread(target=self._run, name=f"task-progress-pulse-{self._task_id}", daemon=True)
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=max(1.0, self._interval_seconds))
        if exc_type is None and self._stale_error is not None:
            raise self._stale_error
        return None

    @classmethod
    def from_session(
        cls,
        session: Session,
        *,
        task_id: int,
        attempt_id: str | None,
        current_stage: str,
        start_progress: int,
        max_progress: int,
        interval_seconds: float = 5.0,
    ) -> "TaskProgressPulse":
        """基于当前 Session 的 bind 创建脉冲，实际刷新使用独立 Session。"""
        factory = sessionmaker(
            bind=session.get_bind(),
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
            class_=Session,
        )
        return cls(
            session_factory=factory,
            task_id=task_id,
            attempt_id=attempt_id,
            current_stage=current_stage,
            start_progress=start_progress,
            max_progress=max_progress,
            interval_seconds=interval_seconds,
        )

    def _run(self) -> None:
        while not self._stop_event.wait(self._interval_seconds):
            elapsed_steps = int((monotonic() - self._started_at) / self._interval_seconds)
            target_progress = min(self._max_progress, self._start_progress + max(1, elapsed_steps))
            pulse_session = self._session_factory()
            try:
                TaskHeartbeat(pulse_session, self._task_id, self._attempt_id).tick(
                    progress_percent=target_progress,
                    current_stage=self._current_stage,
                )
            except StaleAttemptError as exc:
                self._stale_error = exc
                self._stop_event.set()
            except Exception:
                pulse_session.rollback()
            finally:
                pulse_session.close()


def ensure_attempt(task_repository: TaskCenterRepository, task_id: int, attempt_id: str | None) -> str:
    """worker 入口兼容工具：若 payload 未带 attempt_id，则现场生成一个并 commit。"""
    if attempt_id:
        return attempt_id
    new_attempt = start_attempt(task_repository, task_id)
    task_repository.session.commit()
    return new_attempt


def assert_current_attempt(task_repository: TaskCenterRepository, task_id: int, attempt_id: str) -> None:
    """worker 入口快速失败：若 DB 上 attempt_id 已被替换，立即抛 StaleAttemptError。

    用于 worker 启动时排除「我是被 reaper 替换掉的旧 attempt 派发的任务」场景。
    后续长循环里的 hb.tick/hb.touch 会通过 CAS UPDATE 持续校验。
    """
    current = task_repository.session.execute(
        text("SELECT execution_attempt_id FROM task_record WHERE id = :task_id"),
        {"task_id": task_id},
    ).scalar()
    # current 为 NULL 说明本任务还没人写过 attempt（兼容老数据），直接放行
    if current is None or current == attempt_id:
        return
    raise StaleAttemptError(task_id, attempt_id)


def dispatch_with_attempt(
    task_repository: TaskCenterRepository,
    *,
    task,
    callable_path: str,
    payload: dict[str, Any],
    queue: str | None = None,
) -> Any:
    """统一的「轮换 attempt_id + 派发」入口。

    调用前确保 task 已落库（task.id 非空）。返回 dispatch_task 的 TaskDispatchResult。
    会自动把新 attempt_id 写到 payload；调用方仍需在派发结果回填 worker_task_id 后 commit。
    """
    from app.shared.queue import dispatch_task  # 延迟导入避免循环依赖

    attempt_id = start_attempt(task_repository, task.id)
    task.execution_attempt_id = attempt_id
    task_repository.session.commit()
    enriched_payload = dict(payload)
    enriched_payload["execution_attempt_id"] = attempt_id
    return dispatch_task(
        callable_path,
        enriched_payload,
        queue=queue,
        session=task_repository.session,
    )
