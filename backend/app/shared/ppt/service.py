"""
@Date: 2026-05-03
@Author: xisy
@Discription: Raccoon PPT 任务服务封装
"""

import time

from app.core.config import Settings, get_settings
from app.core.exceptions import AppException, BusinessErrorCode
from app.shared.ppt.client import RaccoonPptClient
from app.shared.ppt.schemas import RaccoonPptJobState


TERMINAL_RACCOON_STATUSES = {"succeeded", "failed", "canceled"}
WAITING_RACCOON_STATUS = "waiting_user_input"


class RaccoonPptService:
    """提供创建、轮询与下载 PPTX 的业务友好接口。"""

    def __init__(self, client: RaccoonPptClient | None = None, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.client = client or RaccoonPptClient(self.settings)

    def create_job_and_short_poll(self, *, prompt: str, role: str, scene: str, audience: str) -> RaccoonPptJobState:
        """创建远程任务并执行短轮询。"""
        initial_state = self.client.create_ppt_job(prompt=prompt, role=role, scene=scene, audience=audience)
        return self.short_poll_job(initial_state.job_id, initial_state=initial_state)

    def short_poll_job(self, job_id: str, initial_state: RaccoonPptJobState | None = None) -> RaccoonPptJobState:
        """短时间轮询任务状态，未完成时返回最后一次状态。"""
        state = initial_state
        deadline = time.monotonic() + self.settings.raccoon_short_poll_timeout_seconds
        while True:
            if state is None:
                state = self.client.get_ppt_job(job_id)
            normalized_status = state.status.lower()
            if normalized_status in TERMINAL_RACCOON_STATUSES or normalized_status == WAITING_RACCOON_STATUS:
                return state
            if time.monotonic() >= deadline:
                return state
            time.sleep(self.settings.raccoon_poll_interval_seconds)
            state = self.client.get_ppt_job(job_id)

    def reply_and_short_poll(self, *, job_id: str, answer: str) -> RaccoonPptJobState:
        """回复补充问题并继续短轮询。"""
        state = self.client.reply_ppt_job(job_id=job_id, answer=answer)
        return self.short_poll_job(job_id, initial_state=state)

    def download_pptx(self, download_url: str | None) -> bytes:
        """下载已生成的 PPTX 文件。"""
        if not download_url:
            raise AppException(BusinessErrorCode.RACCOON_RESULT_INVALID, "Raccoon PPT 结果缺少下载地址")
        return self.client.download_pptx(download_url)
