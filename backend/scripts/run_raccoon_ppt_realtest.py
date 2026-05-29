"""
@Date: 2026-05-28
@Author: xisy
@Discription: 真实调用 Raccoon PPT(小浣熊)外部服务，做一次简单的创建->轮询->下载生成测试
"""

import sys
import time
from pathlib import Path

from app.core.config import get_settings
from app.core.exceptions import AppException
from app.shared.ppt import RaccoonPptClient
from app.shared.ppt.service import (
    TERMINAL_RACCOON_STATUSES,
    WAITING_RACCOON_STATUS,
    RaccoonPptService,
)


DEFAULT_PROMPT = "请生成一份面向小学三年级学生的《认识时间：时、分、秒》数学课件，包含教学目标、核心知识点、3 个课堂互动环节与课堂小结，约 8 页。"
MAX_WAIT_SECONDS = 600
POLL_INTERVAL_SECONDS = 10


def _print_state(label: str, state) -> None:
    """打印任务状态摘要，便于人工核对。"""
    print(
        f"[{label}] job_id={state.job_id} status={state.status} "
        f"download_url={state.download_url} required_input={state.required_user_input} "
        f"error={state.error_message}"
    )


def main() -> int:
    """执行一次真实的 Raccoon PPT 生成测试。"""
    settings = get_settings()
    print(f"[config] host={settings.raccoon_api_host} token_set={bool(settings.raccoon_api_token)}")
    if not settings.raccoon_api_token:
        print("[error] RACCOON_API_TOKEN 未配置，无法进行真实测试")
        return 2

    prompt = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PROMPT
    print(f"[prompt] {prompt}")

    client = RaccoonPptClient(settings=settings)
    service = RaccoonPptService(client=client, settings=settings)

    try:
        state = service.create_job_and_short_poll(
            prompt=prompt, role="教师", scene="培训教学", audience="学生"
        )
    except AppException as exc:
        print(f"[error] 创建任务失败: code={exc.code} message={exc} details={exc.details}")
        return 1

    _print_state("created", state)

    deadline = time.monotonic() + MAX_WAIT_SECONDS
    while state.status.lower() not in TERMINAL_RACCOON_STATUSES:
        if state.status.lower() == WAITING_RACCOON_STATUS:
            print("[warn] 远程任务需要补充信息，本次测试不自动回复，提前结束")
            return 1
        if time.monotonic() >= deadline:
            print(f"[timeout] 超过 {MAX_WAIT_SECONDS}s 仍未完成，最后状态: {state.status}")
            return 1
        time.sleep(POLL_INTERVAL_SECONDS)
        try:
            state = service.get_job_state(state.job_id)
        except AppException as exc:
            print(f"[error] 轮询失败: code={exc.code} message={exc}")
            return 1
        _print_state("polling", state)

    if state.status.lower() != "succeeded":
        # 创建接口的响应不带 error_message，终态失败时补查一次拿失败原因
        reason = state.error_message
        if not reason:
            try:
                reason = service.get_job_state(state.job_id).error_message
            except AppException as exc:
                reason = f"(补查失败原因出错: {exc})"
        print(f"[failed] 任务终态为 {state.status}，原因: {reason}")
        return 1

    try:
        content = service.download_pptx(state.download_url)
    except AppException as exc:
        print(f"[error] 下载失败: code={exc.code} message={exc}")
        return 1

    output_dir = Path(__file__).resolve().parent.parent / "tests" / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"raccoon_ppt_{state.job_id}.pptx"
    output_path.write_bytes(content)
    print(f"[success] 已生成 PPTX，大小={len(content)} 字节，保存至 {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
