"""
@Date: 2026-05-29
@Author: xisy
@Discription: 智能助手模块路由：会话、运行、SSE 事件流
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.database import SessionLocal, get_db_session
from app.core.exceptions import AppException, BusinessErrorCode
from app.core.security import get_current_user
from app.modules.agent.repository import AgentRepository
from app.modules.agent.run_service import TERMINAL_RUN_STATUSES, AgentRunService
from app.modules.agent.schemas import (
    AgentMessageResponse,
    AgentRunResponse,
    AgentSessionResponse,
    CreateRunRequest,
    CreateSessionRequest,
)
from app.modules.agent.session_service import AgentSessionService
from app.modules.auth.models import SysUser
from app.schemas.response import ApiResponse, PaginatedData, ResponseFactory

router = APIRouter(prefix="/agent", tags=["智能助手"])


def get_session_service(session: Annotated[Session, Depends(get_db_session)]) -> AgentSessionService:
    """构造会话服务依赖。"""
    return AgentSessionService(session)


@router.post(
    "/sessions",
    summary="创建助手会话",
    description="创建一个项目级智能助手会话；必须绑定 project_id。",
    operation_id="agent_create_session",
    response_model=ApiResponse[AgentSessionResponse],
    status_code=status.HTTP_200_OK,
)
def create_session(
    payload: CreateSessionRequest,
    service: Annotated[AgentSessionService, Depends(get_session_service)],
    current_user: Annotated[SysUser, Depends(get_current_user)],
):
    """创建助手会话。"""
    session = service.create_session(user=current_user, project_id=payload.project_id, title=payload.title)
    data = AgentSessionResponse.model_validate(session).model_dump(mode="json")
    return ResponseFactory.success(data, "创建会话成功")


@router.get(
    "/sessions",
    summary="获取助手会话列表",
    description="分页获取当前教师的助手会话，可按 project_id 过滤。",
    operation_id="agent_list_sessions",
    response_model=ApiResponse[PaginatedData[AgentSessionResponse]],
    status_code=status.HTTP_200_OK,
)
def list_sessions(
    service: Annotated[AgentSessionService, Depends(get_session_service)],
    current_user: Annotated[SysUser, Depends(get_current_user)],
    project_id: int | None = Query(default=None, description="按项目过滤"),
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页大小"),
):
    """获取助手会话列表。"""
    sessions = service.list_sessions(user=current_user, project_id=project_id, page=page, page_size=page_size)
    items = [AgentSessionResponse.model_validate(item).model_dump(mode="json") for item in sessions]
    return ResponseFactory.paginated(
        items=items, total_count=len(items), page=page, page_size=page_size, message="获取会话列表成功"
    )


@router.post(
    "/sessions/{session_id}/runs",
    summary="提交助手运行",
    description=(
        "向指定会话提交一条用户消息并创建待执行运行。context 携带「所在课次教案」上下文，"
        "贯穿整个运行；项目范围由会话绑定，独立页可仅传 project_id。运行异步执行，通过 SSE 事件流获取过程与结果。"
    ),
    operation_id="agent_create_run",
    response_model=ApiResponse[AgentRunResponse],
    status_code=status.HTTP_200_OK,
)
def create_run(
    payload: CreateRunRequest,
    service: Annotated[AgentSessionService, Depends(get_session_service)],
    current_user: Annotated[SysUser, Depends(get_current_user)],
    session_id: int = Path(..., description="会话主键"),
):
    """提交助手运行。"""
    context = payload.context.model_dump(exclude_none=True) if payload.context is not None else None
    run = service.submit_run(user=current_user, session_id=session_id, content=payload.content, context=context)
    data = AgentRunResponse.model_validate(run).model_dump(mode="json")
    return ResponseFactory.success(data, "提交运行成功")


@router.get(
    "/sessions/{session_id}/messages",
    summary="获取会话消息",
    description="获取指定会话的历史消息（按时间升序）。",
    operation_id="agent_list_messages",
    response_model=ApiResponse[list[AgentMessageResponse]],
    status_code=status.HTTP_200_OK,
)
def list_messages(
    service: Annotated[AgentSessionService, Depends(get_session_service)],
    current_user: Annotated[SysUser, Depends(get_current_user)],
    session_id: int = Path(..., description="会话主键"),
    limit: int = Query(default=50, ge=1, le=200, description="返回条数"),
):
    """获取会话消息。"""
    service.get_session(user=current_user, session_id=session_id)
    messages = service.repository.list_messages(session_id, limit=limit)
    data = [AgentMessageResponse.model_validate(item).model_dump(mode="json") for item in messages]
    return ResponseFactory.success(data, "获取会话消息成功")


@router.get(
    "/runs/{run_id}",
    summary="获取运行状态",
    description="获取单个运行的状态与最终回答。",
    operation_id="agent_get_run",
    response_model=ApiResponse[AgentRunResponse],
    status_code=status.HTTP_200_OK,
)
def get_run(
    session: Annotated[Session, Depends(get_db_session)],
    current_user: Annotated[SysUser, Depends(get_current_user)],
    run_id: int = Path(..., description="运行主键"),
):
    """获取运行状态。"""
    run = AgentRepository(session).get_run_for_owner(run_id, current_user.id)
    if run is None:
        raise AppException(BusinessErrorCode.GENERATION_RUN_NOT_FOUND, "运行不存在或无权访问")
    data = AgentRunResponse.model_validate(run).model_dump(mode="json")
    return ResponseFactory.success(data, "获取运行状态成功")


@router.get(
    "/runs/{run_id}/events/list",
    summary="增量拉取运行事件",
    description="按 after_seq 增量拉取运行事件，用于断线补拉。",
    operation_id="agent_list_run_events",
    status_code=status.HTTP_200_OK,
)
def list_run_events(
    session: Annotated[Session, Depends(get_db_session)],
    current_user: Annotated[SysUser, Depends(get_current_user)],
    run_id: int = Path(..., description="运行主键"),
    after_seq: int = Query(default=0, ge=0, description="起始事件序号"),
):
    """增量拉取运行事件。"""
    repository = AgentRepository(session)
    run = repository.get_run_for_owner(run_id, current_user.id)
    if run is None:
        raise AppException(BusinessErrorCode.GENERATION_RUN_NOT_FOUND, "运行不存在或无权访问")
    events = repository.list_events(run_id, after_seq=after_seq)
    data = [AgentRunService.to_event_response(event) for event in events]
    return ResponseFactory.success(data, "获取运行事件成功")


@router.get(
    "/runs/{run_id}/events",
    summary="订阅运行事件流(SSE)",
    description="以 Server-Sent Events 实时推送运行的工具调用过程与最终结果；支持 after_seq 续传。",
    operation_id="agent_stream_run_events",
)
async def stream_run_events(
    current_user: Annotated[SysUser, Depends(get_current_user)],
    run_id: int = Path(..., description="运行主键"),
    after_seq: int = Query(default=0, ge=0, description="起始事件序号"),
) -> StreamingResponse:
    """订阅运行事件流。"""
    user_id = current_user.id
    # 鉴权：确认运行归属
    with SessionLocal() as db:
        run = AgentRepository(db).get_run_for_owner(run_id, user_id)
        if run is None:
            raise AppException(BusinessErrorCode.GENERATION_RUN_NOT_FOUND, "运行不存在或无权访问")

    async def event_stream() -> AsyncIterator[str]:
        last_seq = after_seq
        while True:
            terminal = False
            with SessionLocal() as db:
                repository = AgentRepository(db)
                run = repository.get_run_for_owner(run_id, user_id)
                if run is None:
                    yield f"data: {json.dumps({'event_type': 'error', 'message': '运行不存在'})}\n\n"
                    return
                for event in repository.list_events(run_id, after_seq=last_seq):
                    last_seq = event.seq
                    yield f"data: {json.dumps(AgentRunService.to_event_response(event), ensure_ascii=False)}\n\n"
                terminal = run.status in TERMINAL_RUN_STATUSES
            if terminal:
                # 终态后补拉一次，确保末尾事件不丢
                await asyncio.sleep(0.2)
                with SessionLocal() as db:
                    for event in AgentRepository(db).list_events(run_id, after_seq=last_seq):
                        last_seq = event.seq
                        yield f"data: {json.dumps(AgentRunService.to_event_response(event), ensure_ascii=False)}\n\n"
                yield "event: done\ndata: {}\n\n"
                return
            await asyncio.sleep(0.5)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post(
    "/runs/{run_id}/cancel",
    summary="取消运行",
    description="取消一个进行中或排队中的运行。",
    operation_id="agent_cancel_run",
    response_model=ApiResponse[AgentRunResponse],
    status_code=status.HTTP_200_OK,
)
def cancel_run(
    session: Annotated[Session, Depends(get_db_session)],
    current_user: Annotated[SysUser, Depends(get_current_user)],
    run_id: int = Path(..., description="运行主键"),
):
    """取消运行。"""
    repository = AgentRepository(session)
    run = repository.get_run_for_owner(run_id, current_user.id)
    if run is None:
        raise AppException(BusinessErrorCode.GENERATION_RUN_NOT_FOUND, "运行不存在或无权访问")
    if run.status in TERMINAL_RUN_STATUSES:
        data = AgentRunResponse.model_validate(run).model_dump(mode="json")
        return ResponseFactory.success(data, "运行已处于终态")
    AgentRunService(session, repository).cancel_run(run)
    data = AgentRunResponse.model_validate(run).model_dump(mode="json")
    return ResponseFactory.success(data, "已取消运行")