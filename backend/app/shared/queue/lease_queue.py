"""
@Date: 2026-05-29
@Author: xisy
@Discription: MySQL 租约队列通用数据访问层，统一抢占、续租、失败重试与过期回收
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Any, Generic, TypeVar

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.shared.utils.datetime_util import DateTimeUtil

QueueModelT = TypeVar("QueueModelT")
QueueCallback = Callable[[Any, Any], None]


class LeaseQueueRepository(Generic[QueueModelT]):
    """基于 status/available_at/locked_by/lease_expires_at 的通用租约队列封装。"""

    def __init__(
        self,
        db: Session,
        model: type[QueueModelT],
        *,
        lease_seconds: int,
        retry_base_seconds: int | None = None,
        terminal_statuses: set[str] | None = None,
    ) -> None:
        self.db = db
        self.model = model
        self.lease_seconds = lease_seconds
        self.retry_base_seconds = retry_base_seconds
        self.terminal_statuses = terminal_statuses or {"succeeded", "cancelled"}

    @staticmethod
    def calculate_backoff(attempt_count: int, retry_base_seconds: int) -> int:
        """根据已尝试次数计算指数退避秒数。"""
        return retry_base_seconds * (2 ** max(attempt_count - 1, 0))

    def claim_next(
        self,
        worker_id: str,
        *,
        include_expired_running: bool = True,
        on_claim: QueueCallback | None = None,
    ) -> QueueModelT | None:
        """抢占下一条 pending 或过期 running 记录。"""
        now = DateTimeUtil.now_utc()
        query = select(self.model).where(
            getattr(self.model, "attempt_count") < getattr(self.model, "max_attempts"),
        )
        pending_condition = (getattr(self.model, "status") == "pending") & (
            getattr(self.model, "available_at") <= now
        )
        if include_expired_running:
            running_condition = (
                (getattr(self.model, "status") == "running")
                & (getattr(self.model, "lease_expires_at").is_not(None))
                & (getattr(self.model, "lease_expires_at") <= now)
            )
            query = query.where(or_(pending_condition, running_condition))
        else:
            query = query.where(pending_condition)
        item = self.db.scalar(
            query.order_by(getattr(self.model, "created_at").asc(), getattr(self.model, "id").asc())
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if item is None:
            self.db.commit()
            return None

        item.status = "running"
        item.locked_by = worker_id
        item.lease_expires_at = now + timedelta(seconds=self.lease_seconds)
        item.attempt_count += 1
        if hasattr(item, "started_at") and getattr(item, "started_at") is None:
            item.started_at = now
        if hasattr(item, "error_message"):
            item.error_message = None
        item.updated_at = now
        if on_claim is not None:
            on_claim(item, now)
        self.db.add(item)
        self.db.commit()
        self.db.refresh(item)
        return item

    def renew_lease(self, item_id: int, worker_id: str) -> bool:
        """续期当前 Worker 持有的运行中记录。"""
        item = self.db.scalar(
            select(self.model).where(
                getattr(self.model, "id") == item_id,
                getattr(self.model, "locked_by") == worker_id,
                getattr(self.model, "status") == "running",
            )
        )
        if item is None:
            return False
        now = DateTimeUtil.now_utc()
        item.lease_expires_at = now + timedelta(seconds=self.lease_seconds)
        item.updated_at = now
        self.db.add(item)
        self.db.commit()
        return True

    def mark_attempt_failed(
        self,
        item_id: int,
        worker_id: str,
        message: str,
        *,
        error_code: str = "",
        retryable: bool = True,
        on_retry: QueueCallback | None = None,
        on_terminal: QueueCallback | None = None,
    ) -> bool:
        """标记一次执行失败；返回是否进入 failed 终态。"""
        item = self.db.scalar(
            select(self.model)
            .where(getattr(self.model, "id") == item_id, getattr(self.model, "locked_by") == worker_id)
            .with_for_update()
        )
        if item is None or item.status in self.terminal_statuses:
            self.db.commit()
            return False

        now = DateTimeUtil.now_utc()
        should_fail = not retryable or item.attempt_count >= item.max_attempts
        if hasattr(item, "error_message"):
            item.error_message = message
        if hasattr(item, "last_error_code"):
            item.last_error_code = error_code
        item.locked_by = ""
        item.lease_expires_at = None
        item.updated_at = now
        if should_fail:
            item.status = "failed"
            if hasattr(item, "completed_at"):
                item.completed_at = now
            if on_terminal is not None:
                on_terminal(item, now)
        else:
            item.status = "pending"
            if self.retry_base_seconds is None:
                item.available_at = now
            else:
                item.available_at = now + timedelta(
                    seconds=self.calculate_backoff(item.attempt_count, self.retry_base_seconds)
                )
            if on_retry is not None:
                on_retry(item, now)
        self.db.add(item)
        self.db.commit()
        return should_fail
