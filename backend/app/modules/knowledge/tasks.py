"""
@Date: 2026-05-27
@Author: xisy
@Discription: 知识结构化模块任务执行能力
"""

import json
from concurrent.futures import Future, ThreadPoolExecutor, as_completed

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.core.constants import REVIEW_STATUS_CONFIRMED, TASK_STATUS_PENDING, TASK_STATUS_PROCESSING, TASK_STATUS_SUCCESS
from app.core.database import SessionLocal
from app.core.exceptions import AppException, BusinessErrorCode
from app.modules.knowledge.domain import (
    build_chapter_drafts_from_boundaries,
    build_markdown_line_index,
    build_point_drafts_for_chapter,
    build_semantic_chunk_drafts_from_markdown_index,
    normalize_summary_json,
    persist_knowledge_snapshot,
)
from app.modules.knowledge.repository import KnowledgeRepository
from app.modules.knowledge.schemas import (
    KnowledgeChapterBoundaryResult,
    KnowledgeChapterPointExtractionResult,
)
from app.modules.knowledge.service import _build_knowledge_version_model, upsert_vectors_for_knowledge_version
from app.modules.task_center.heartbeat import (
    StaleAttemptError,
    TaskHeartbeat,
    TaskProgressPulse,
    ensure_attempt,
)
from app.modules.task_center.progress import assign_monotonic_progress
from app.modules.task_center.recovery import requeue_or_fail_task
from app.modules.task_center.repository import TaskCenterRepository
from app.shared.llm import ChatMessage, OpenAICompatibleEmbeddingService, OpenAICompatibleLlmService
from app.shared.utils import DateTimeUtil
from app.shared.vector import MilvusVectorService


def run_extract_task(payload: dict) -> dict[str, int]:
    """执行知识结构化抽取任务。"""
    session = _create_session(payload)
    repository = KnowledgeRepository(session)
    task_repository = TaskCenterRepository(session)
    llm_service = OpenAICompatibleLlmService()
    embedding_service = OpenAICompatibleEmbeddingService()
    vector_service = MilvusVectorService()
    task = task_repository.get_task_by_id(payload["task_record_id"])
    step_map = _get_step_map(task_repository, payload["task_record_id"])
    now = DateTimeUtil.now_utc()
    attempt_id = ensure_attempt(task_repository, payload["task_record_id"], payload.get("execution_attempt_id"))
    heartbeat = TaskHeartbeat(session, payload["task_record_id"], attempt_id)

    try:
        if task is None:
            raise AppException(BusinessErrorCode.TASK_NOT_FOUND, "知识抽取任务不存在")
        if task.execution_attempt_id and task.execution_attempt_id != attempt_id:
            raise StaleAttemptError(task.id, attempt_id)
        _mark_task(task, task_status=TASK_STATUS_PROCESSING, current_stage="prepare_parse_source", progress_percent=10, started_at=now)
        _mark_step(step_map["prepare_parse_source"], TASK_STATUS_PROCESSING, 20, started_at=now)
        task_repository.save(task)
        task_repository.save(step_map["prepare_parse_source"])
        session.commit()

        parse_version = repository.get_parse_version(payload["parse_version_id"])
        if parse_version is None:
            raise AppException(BusinessErrorCode.PARSE_VERSION_NOT_FOUND, "解析版本不存在")
        if parse_version.parse_status != "success" or parse_version.review_status != REVIEW_STATUS_CONFIRMED:
            raise AppException(
                BusinessErrorCode.PARSE_VERSION_NOT_CONFIRMED,
                "解析版本尚未确认，无法执行知识抽取",
                {"parse_status": parse_version.parse_status, "review_status": parse_version.review_status},
            )
        if repository.get_ready_knowledge_version(parse_version.id) is not None and not payload.get("force_regenerate", False):
            raise AppException(BusinessErrorCode.TASK_CONFLICT, "当前解析版本已存在可用知识版本")

        textbook_version = repository.get_textbook_version(parse_version.textbook_version_id)
        if textbook_version is None:
            raise AppException(BusinessErrorCode.TEXTBOOK_NOT_FOUND, "教材版本不存在")
        parse_pages = repository.list_parse_pages(parse_version.id)
        parse_blocks = repository.list_parse_blocks(parse_version.id)
        if not parse_pages or not parse_blocks:
            raise AppException(BusinessErrorCode.LLM_RESULT_INVALID, "解析版本缺少可供抽取的页或结构块")
        line_index = build_markdown_line_index(parse_pages)
        if not line_index.lines:
            raise AppException(BusinessErrorCode.LLM_RESULT_INVALID, "解析版本缺少可用页级 Markdown，无法执行章节识别")

        _mark_step(
            step_map["prepare_parse_source"],
            TASK_STATUS_SUCCESS,
            100,
            detail_json={"parse_version_id": parse_version.id, "page_count": len(parse_pages), "block_count": len(parse_blocks)},
            finished_at=DateTimeUtil.now_utc(),
        )
        _mark_step(step_map["invoke_llm_extract"], TASK_STATUS_PROCESSING, 0, started_at=DateTimeUtil.now_utc())
        _mark_task(task, task_status=TASK_STATUS_PROCESSING, current_stage="invoke_llm_extract", progress_percent=35)
        task_repository.save(task)
        for step in step_map.values():
            task_repository.save(step)
        session.commit()

        # 章节边界识别 LLM 调用——耗时较长，调用前后 touch 心跳
        heartbeat.touch()
        with TaskProgressPulse.from_session(
            session,
            task_id=task.id,
            attempt_id=attempt_id,
            current_stage="invoke_llm_extract",
            start_progress=35,
            max_progress=44,
        ):
            boundary_result = llm_service.generate_structured_output(
                messages=_build_chapter_boundary_messages(parse_version=parse_version, line_index=line_index),
                response_model=KnowledgeChapterBoundaryResult,
            )
        heartbeat.touch()
        try:
            chapter_drafts = build_chapter_drafts_from_boundaries(boundary_result.items, line_index)
        except ValueError as exc:
            raise AppException(BusinessErrorCode.LLM_RESULT_INVALID, str(exc)) from exc
        semantic_chunk_drafts = build_semantic_chunk_drafts_from_markdown_index(
            parse_pages=parse_pages,
            parse_blocks=parse_blocks,
            chapter_drafts=chapter_drafts,
            line_index=line_index,
        )
        if not semantic_chunk_drafts:
            raise AppException(BusinessErrorCode.LLM_RESULT_INVALID, "章节切块结果为空")

        # 切块完成后初始化 step detail，让前端立刻能看到总块数
        total_chunks = len(semantic_chunk_drafts)
        heartbeat.update_step_detail(
            step_id=step_map["invoke_llm_extract"].id,
            progress_percent=20,
            detail_json={
                "processed_chunks": 0,
                "total_chunks": total_chunks,
                "chapter_count": len(chapter_drafts),
            },
        )

        point_drafts = []
        chapter_summaries: list[dict] = []
        parallel_limit = min(get_settings().knowledge_extract_max_concurrency, total_chunks)
        with TaskProgressPulse.from_session(
            session,
            task_id=task.id,
            attempt_id=attempt_id,
            current_stage="invoke_llm_extract",
            start_progress=45,
            max_progress=79,
        ):
            chunk_extraction_results = _extract_chunk_points_in_parallel(
                llm_service=llm_service,
                parse_version_id=parse_version.id,
                chapter_drafts=chapter_drafts,
                semantic_chunk_drafts=semantic_chunk_drafts,
                parse_pages=parse_pages,
                parse_blocks=parse_blocks,
                heartbeat=heartbeat,
                step_id=step_map["invoke_llm_extract"].id,
                parallel_limit=parallel_limit,
                total_chunks=total_chunks,
            )
        for chunk_extraction_result in chunk_extraction_results:
            chapter_draft = chunk_extraction_result["chapter_draft"]
            semantic_chunk_draft = chunk_extraction_result["semantic_chunk_draft"]
            point_result = chunk_extraction_result["point_result"]
            point_drafts.extend(
                build_point_drafts_for_chapter(
                    parse_version=parse_version,
                    source_file_id=textbook_version.source_file_id,
                    chapter_ref_id=chapter_draft.draft_id,
                    semantic_chunk_ref_id=semantic_chunk_draft.draft_id,
                    parse_pages=parse_pages,
                    parse_blocks=parse_blocks,
                    point_drafts=point_result.knowledge_points,
                    start_sort_order=len(point_drafts),
                )
            )
            chapter_summaries.append(
                {
                    "chapter_path": chapter_draft.node_path,
                    "chapter_title": chapter_draft.title,
                    "summary_json": point_result.summary_json,
                }
            )
        if not point_drafts:
            raise AppException(BusinessErrorCode.LLM_RESULT_INVALID, "LLM 未返回可落库的知识点")

        _mark_step(
            step_map["invoke_llm_extract"],
            TASK_STATUS_SUCCESS,
            100,
            detail_json={
                "chapter_count": len(chapter_drafts),
                "point_count": len(point_drafts),
                "llm_call_count": len(semantic_chunk_drafts) + 1,
                "parallel_limit": parallel_limit,
                # 保留循环中累积的处理进度，便于复盘
                "processed_chunks": len(semantic_chunk_drafts),
                "total_chunks": len(semantic_chunk_drafts),
            },
            finished_at=DateTimeUtil.now_utc(),
        )
        _mark_step(step_map["persist_knowledge_result"], TASK_STATUS_PROCESSING, 40, started_at=DateTimeUtil.now_utc())
        _mark_task(task, task_status=TASK_STATUS_PROCESSING, current_stage="persist_knowledge_result", progress_percent=80)
        task_repository.save(task)
        for step in step_map.values():
            task_repository.save(step)
        session.commit()

        latest_knowledge_version = repository.get_ready_knowledge_version(parse_version.id) or repository.get_latest_knowledge_version(parse_version.id)
        knowledge_version = repository.create_knowledge_version(
            _build_knowledge_version_model(
                project_id=parse_version.project_id,
                parse_version_id=parse_version.id,
                parent_knowledge_version_id=latest_knowledge_version.id if latest_knowledge_version is not None else None,
                version_no=repository.get_next_knowledge_version_no(parse_version.project_id),
                summary_json=normalize_summary_json(
                    {"chapter_summaries": chapter_summaries},
                    chapter_count=len(chapter_drafts),
                    point_count=len(point_drafts),
                ),
                created_by=payload.get("operator_user_id"),
            )
        )
        snapshot = persist_knowledge_snapshot(
            repository,
            knowledge_version=knowledge_version,
            chapter_drafts=chapter_drafts,
            point_drafts=point_drafts,
            semantic_chunk_drafts=semantic_chunk_drafts,
        )
        repository.archive_other_ready_knowledge_versions(parse_version.id, knowledge_version.id)

        _mark_step(
            step_map["persist_knowledge_result"],
            TASK_STATUS_SUCCESS,
            100,
            detail_json={"knowledge_version_id": knowledge_version.id, "chapter_count": len(snapshot.chapters), "point_count": len(snapshot.points)},
            finished_at=DateTimeUtil.now_utc(),
        )
        _mark_step(step_map["upsert_vectors"], TASK_STATUS_PROCESSING, 60, started_at=DateTimeUtil.now_utc())
        _mark_task(task, task_status=TASK_STATUS_PROCESSING, current_stage="upsert_vectors", progress_percent=90)
        task_repository.save(task)
        for step in step_map.values():
            task_repository.save(step)
        session.commit()

        # 向量写入是较长的 IO+embedding 阶段，触发前后各 touch 一次
        heartbeat.touch()
        vector_counts = upsert_vectors_for_knowledge_version(
            repository=repository,
            parse_version=parse_version,
            textbook_version=textbook_version,
            knowledge_version=knowledge_version,
            snapshot=snapshot,
            embedding_service=embedding_service,
            vector_service=vector_service,
        )
        heartbeat.touch()

        _mark_step(
            step_map["upsert_vectors"],
            TASK_STATUS_SUCCESS,
            100,
            detail_json=vector_counts,
            finished_at=DateTimeUtil.now_utc(),
        )
        _mark_task(
            task,
            task_status=TASK_STATUS_SUCCESS,
            current_stage="upsert_vectors",
            progress_percent=100,
            result_json={
                "knowledge_version_id": knowledge_version.id,
                "chapter_count": len(snapshot.chapters),
                "point_count": len(snapshot.points),
                **vector_counts,
            },
            finished_at=DateTimeUtil.now_utc(),
        )
        task_repository.save(task)
        for step in step_map.values():
            task_repository.save(step)
        session.commit()
        _notify_orchestrator_knowledge_success(session=session, task=task, knowledge_version_id=knowledge_version.id)
        return {
            "knowledge_version_id": knowledge_version.id,
            "chapter_count": len(snapshot.chapters),
            "point_count": len(snapshot.points),
            **vector_counts,
        }
    except StaleAttemptError:
        # 被新 attempt 抢占，安静退出；新 worker 已接管，不再写任何 task 状态
        session.rollback()
        return {"stale_attempt": True}
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        _mark_task_failure(task_repository, repository, payload, exc)
        raise
    finally:
        session.close()


def _extract_chunk_points_in_parallel(
    *,
    llm_service: OpenAICompatibleLlmService,
    parse_version_id: int,
    chapter_drafts: list,
    semantic_chunk_drafts: list,
    parse_pages: list,
    parse_blocks: list,
    heartbeat: TaskHeartbeat,
    step_id: int,
    parallel_limit: int,
    total_chunks: int,
) -> list[dict]:
    """并行抽取语义块知识点；数据库状态只由主线程更新。"""
    chapter_by_draft_id = {chapter.draft_id: chapter for chapter in chapter_drafts}
    results: list[dict] = []
    futures: list[Future] = []
    completed_chunks = 0
    heartbeat.touch()
    with ThreadPoolExecutor(max_workers=parallel_limit, thread_name_prefix="knowledge-extract") as executor:
        for chunk_index, semantic_chunk_draft in enumerate(semantic_chunk_drafts, start=1):
            chapter_draft = chapter_by_draft_id[semantic_chunk_draft.chapter_ref_id]
            futures.append(
                executor.submit(
                    _extract_single_chunk_points,
                    llm_service=llm_service,
                    parse_version_id=parse_version_id,
                    chapter_draft=chapter_draft,
                    semantic_chunk_draft=semantic_chunk_draft,
                    parse_pages=parse_pages,
                    parse_blocks=parse_blocks,
                    chunk_index=chunk_index,
                )
            )
        try:
            for future in as_completed(futures):
                result = future.result()
                completed_chunks += 1
                results.append(result)
                chapter_draft = result["chapter_draft"]
                chunk_progress = 35 + int(45 * completed_chunks / total_chunks)
                heartbeat.tick(progress_percent=chunk_progress, current_stage="invoke_llm_extract")
                heartbeat.update_step_detail(
                    step_id=step_id,
                    progress_percent=20 + int(80 * completed_chunks / total_chunks),
                    detail_json={
                        "processed_chunks": completed_chunks,
                        "total_chunks": total_chunks,
                        "chapter_count": len(chapter_drafts),
                        "last_completed_chapter_path": chapter_draft.node_path,
                        "parallel_limit": parallel_limit,
                    },
                )
        except Exception:
            for pending_future in futures:
                pending_future.cancel()
            raise
    results.sort(key=lambda item: item["chunk_index"])
    return results


def _extract_single_chunk_points(
    *,
    llm_service: OpenAICompatibleLlmService,
    parse_version_id: int,
    chapter_draft,
    semantic_chunk_draft,
    parse_pages: list,
    parse_blocks: list,
    chunk_index: int,
) -> dict:
    """抽取单个语义块的知识点；仅做 LLM 调用和内存校验。"""
    point_result = llm_service.generate_structured_output(
        messages=_build_chapter_point_extraction_messages(
            parse_version_id=parse_version_id,
            chapter_draft=chapter_draft,
            semantic_chunk_draft=semantic_chunk_draft,
        ),
        response_model=KnowledgeChapterPointExtractionResult,
    )
    _validate_point_extraction_result(point_result, parse_pages=parse_pages, parse_blocks=parse_blocks)
    return {
        "chunk_index": chunk_index,
        "chapter_draft": chapter_draft,
        "semantic_chunk_draft": semantic_chunk_draft,
        "point_result": point_result,
    }


def _build_chapter_boundary_messages(*, parse_version, line_index) -> list[ChatMessage]:
    """构造章节边界识别提示词。"""
    system_prompt = (
        "你是教材章节边界识别助手。"
        "用户会提供带 L 行号的页级 Markdown。"
        "请只识别教材正文的一级大章开始行，不要输出封面、版权页、目录、前言、习题汇总、栏目标题或小节标题。"
        "严格输出 JSON 对象，字段只包含 items。"
        "items 是平铺数组，每项必须包含 title、start_line、line_text、confidence。"
        "start_line 必须是不带 L 前缀的整数行号，line_text 必须复制该行 Markdown 原文。"
        "不要输出 node_path、node_type、page_end、end_line，也不要输出额外说明。"
    )
    user_payload = {
        "parse_version_id": parse_version.id,
        "line_count": line_index.total_lines,
        "numbered_markdown": line_index.numbered_text,
    }
    return [
        ChatMessage(role="system", content=system_prompt),
        ChatMessage(role="user", content=json.dumps(user_payload, ensure_ascii=False)),
    ]


def _build_chapter_point_extraction_messages(*, parse_version_id: int, chapter_draft, semantic_chunk_draft) -> list[ChatMessage]:
    """构造单章节知识点抽取提示词。"""
    system_prompt = (
        "你是教材知识点抽取助手。"
        "用户会提供一个一级章节的 Markdown 正文。"
        "请只基于该章节内容抽取知识点，严格输出 JSON 对象，字段只包含 summary_json、knowledge_points。"
        "summary_json 是对象，可包含 overview、key_terms 等字段；不要使用数组。"
        "knowledge_points 每项提供 point_code（字符串，不超过 64 字符）、point_name（字符串，不超过 64 字符）、point_type（字符串，例如 vocabulary/grammar/dialogue，不超过 32 字符）、"
        "importance_level（1-5 之间的整数，5 最重要）、difficulty_level（1-5 之间的整数，5 最难）、"
        "mastery_level_hint（字符串，仅 12 字以内的极简标签，例如 \"识记\"/\"理解\"/\"应用\"，禁止整句描述）、"
        "tags_json（对象，固定形如 {\"tags\":[\"重点\",\"易错\"]}，不要直接返回数组）、"
        "summary_text（字符串）、sort_order（从 0 开始的整数）、evidences（数组）。"
        "evidences 每项必须至少包含 page_no（整数）和 excerpt_text（字符串）；如果能判断解析块序号，可以补充 block_no（整数）。"
        "page_no 必须严格落在用户提供的 chapter.page_start 与 chapter.page_end 闭区间内（含两端），不允许使用区间外、章节外或自行推算的页码。"
        "excerpt_text 必须从用户提供的 markdown 字段中原样摘录，不要改写或翻译。"
        "不要输出 chapters，不要输出额外说明，不要编造章节外内容。"
    )
    user_payload = {
        "parse_version_id": parse_version_id,
        "chapter": {
            "node_path": chapter_draft.node_path,
            "title": chapter_draft.title,
            "page_start": semantic_chunk_draft.page_start,
            "page_end": semantic_chunk_draft.page_end,
            "line_start": semantic_chunk_draft.line_start,
            "line_end": semantic_chunk_draft.line_end,
        },
        "markdown": semantic_chunk_draft.chunk_text,
    }
    return [
        ChatMessage(role="system", content=system_prompt),
        ChatMessage(role="user", content=json.dumps(user_payload, ensure_ascii=False)),
    ]


def _validate_point_extraction_result(result: KnowledgeChapterPointExtractionResult, *, parse_pages: list, parse_blocks: list) -> None:
    """校验单章节知识点抽取结果引用合法。"""
    page_set = {page.page_no for page in parse_pages}
    block_set = {
        (page.page_no, block.block_no)
        for block in parse_blocks
        for page in parse_pages
        if page.id == block.parse_page_id
    }
    for point in result.knowledge_points:
        if not point.evidences:
            raise AppException(
                BusinessErrorCode.LLM_RESULT_INVALID,
                "LLM 返回的知识点缺少证据映射",
                {"point_name": point.point_name},
            )
        for evidence in point.evidences:
            if evidence.page_no not in page_set:
                raise AppException(
                    BusinessErrorCode.LLM_RESULT_INVALID,
                    "LLM 返回的证据页码不存在于解析结果中",
                    {"point_name": point.point_name, "page_no": evidence.page_no},
                )
            if evidence.block_no is not None and (evidence.page_no, evidence.block_no) not in block_set:
                raise AppException(
                    BusinessErrorCode.LLM_RESULT_INVALID,
                    "LLM 返回的证据块不存在于解析结果中",
                    {"point_name": point.point_name, "page_no": evidence.page_no, "block_no": evidence.block_no},
                )


def _mark_task(task, *, task_status: str, current_stage: str, progress_percent: int, started_at=None, finished_at=None, result_json: dict | None = None) -> None:
    task.task_status = task_status
    task.current_stage = current_stage
    assign_monotonic_progress(task, progress_percent)
    if started_at is not None:
        task.started_at = task.started_at or started_at
    if finished_at is not None:
        task.finished_at = finished_at
    if result_json is not None:
        task.result_json = result_json


def _mark_step(step, step_status: str, progress_percent: int, *, detail_json: dict | None = None, started_at=None, finished_at=None) -> None:
    step.step_status = step_status
    assign_monotonic_progress(step, progress_percent)
    if detail_json is not None:
        step.detail_json = detail_json
    if started_at is not None:
        step.started_at = step.started_at or started_at
    if finished_at is not None:
        step.finished_at = finished_at


def _get_step_map(task_repository: TaskCenterRepository, task_record_id: int) -> dict[str, object]:
    return {
        step_code: task_repository.get_task_step(task_record_id, step_code)
        for step_code in ("prepare_parse_source", "invoke_llm_extract", "persist_knowledge_result", "upsert_vectors")
    }


def _mark_task_failure(task_repository: TaskCenterRepository, repository: KnowledgeRepository, payload: dict, exc: Exception) -> None:
    """处理知识抽取任务失败：可重试错误重排重试，否则判终态失败。"""
    task = task_repository.get_task_by_id(payload["task_record_id"])
    if task is None:
        return
    terminal_failed = not requeue_or_fail_task(
        task_repository,
        task,
        exc=exc,
        fallback_error_code=BusinessErrorCode.KNOWLEDGE_TASK_FAILED,
    )
    if terminal_failed:
        _notify_orchestrator_failure(session=task_repository.session, task=task, exc=exc)


def _notify_orchestrator_knowledge_success(*, session, task, knowledge_version_id: int) -> None:
    """知识抽取成功后通知 orchestrator 续跑课程规划。"""
    try:
        from app.modules.orchestrator.service import OrchestratorService

        OrchestratorService(session).advance_after_knowledge_success(task=task, knowledge_version_id=knowledge_version_id)
    except Exception:  # noqa: BLE001
        from app.core.logging import get_logger as _get_logger

        _get_logger(__name__).warning("orchestrator knowledge hook 调用失败", task_id=task.id, exc_info=True)


def _notify_orchestrator_failure(*, session, task, exc) -> None:
    """终态失败时通知 orchestrator 把 run 标为 failed。"""
    try:
        from app.core.exceptions import AppException as _AppException
        from app.modules.orchestrator.service import OrchestratorService

        error_code = exc.code.value if isinstance(exc, _AppException) else type(exc).__name__
        error_message = exc.message if isinstance(exc, _AppException) else str(exc)
        OrchestratorService(session).mark_run_failed(task=task, error_code=error_code, error_message=error_message)
    except Exception:  # noqa: BLE001
        from app.core.logging import get_logger as _get_logger

        _get_logger(__name__).warning("orchestrator failure hook 调用失败", task_id=task.id, exc_info=True)


def _create_session(payload: dict) -> Session:
    """为知识抽取任务创建数据库会话。"""
    database_url = payload.get("database_url")
    if not database_url:
        return SessionLocal()
    engine = create_engine(database_url, pool_pre_ping=True, future=True)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, class_=Session)
    return factory()
