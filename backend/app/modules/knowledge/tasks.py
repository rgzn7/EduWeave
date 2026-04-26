"""
@Date: 2026-04-14
@Author: xisy
@Discription: 知识结构化模块任务执行能力
"""

import json

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.constants import REVIEW_STATUS_CONFIRMED, TASK_STATUS_FAILURE, TASK_STATUS_PENDING, TASK_STATUS_PROCESSING, TASK_STATUS_SUCCESS
from app.core.database import SessionLocal
from app.core.exceptions import AppException, BusinessErrorCode
from app.modules.knowledge.domain import (
    build_chapter_drafts_from_extraction,
    build_point_drafts_from_extraction,
    normalize_summary_json,
    persist_knowledge_snapshot,
)
from app.modules.knowledge.repository import KnowledgeRepository
from app.modules.knowledge.schemas import KnowledgeExtractionResult
from app.modules.knowledge.service import _build_knowledge_version_model, upsert_vectors_for_knowledge_version
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

    try:
        if task is None:
            raise RuntimeError("知识抽取任务不存在")
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

        _mark_step(
            step_map["prepare_parse_source"],
            TASK_STATUS_SUCCESS,
            100,
            detail_json={"parse_version_id": parse_version.id, "page_count": len(parse_pages), "block_count": len(parse_blocks)},
            finished_at=DateTimeUtil.now_utc(),
        )
        _mark_step(step_map["invoke_llm_extract"], TASK_STATUS_PROCESSING, 30, started_at=DateTimeUtil.now_utc())
        _mark_task(task, task_status=TASK_STATUS_PROCESSING, current_stage="invoke_llm_extract", progress_percent=35)
        task_repository.save(task)
        for step in step_map.values():
            task_repository.save(step)
        session.commit()

        llm_messages = _build_extraction_messages(parse_version=parse_version, parse_pages=parse_pages, parse_blocks=parse_blocks)
        extraction_result = llm_service.generate_structured_output(
            messages=llm_messages,
            response_model=KnowledgeExtractionResult,
        )
        _validate_extraction_result(extraction_result, parse_pages=parse_pages, parse_blocks=parse_blocks)

        _mark_step(
            step_map["invoke_llm_extract"],
            TASK_STATUS_SUCCESS,
            100,
            detail_json={"chapter_count": len(extraction_result.chapters), "point_count": len(extraction_result.knowledge_points)},
            finished_at=DateTimeUtil.now_utc(),
        )
        _mark_step(step_map["persist_knowledge_result"], TASK_STATUS_PROCESSING, 40, started_at=DateTimeUtil.now_utc())
        _mark_task(task, task_status=TASK_STATUS_PROCESSING, current_stage="persist_knowledge_result", progress_percent=60)
        task_repository.save(task)
        for step in step_map.values():
            task_repository.save(step)
        session.commit()

        chapter_drafts = build_chapter_drafts_from_extraction(extraction_result.chapters)
        chapter_path_to_draft_id = {chapter.node_path: chapter.draft_id for chapter in chapter_drafts}
        point_drafts = build_point_drafts_from_extraction(
            parse_version=parse_version,
            source_file_id=textbook_version.source_file_id,
            chapter_path_to_draft_id=chapter_path_to_draft_id,
            parse_pages=parse_pages,
            parse_blocks=parse_blocks,
            point_drafts=extraction_result.knowledge_points,
        )
        latest_knowledge_version = repository.get_ready_knowledge_version(parse_version.id) or repository.get_latest_knowledge_version(parse_version.id)
        knowledge_version = repository.create_knowledge_version(
            _build_knowledge_version_model(
                project_id=parse_version.project_id,
                parse_version_id=parse_version.id,
                parent_knowledge_version_id=latest_knowledge_version.id if latest_knowledge_version is not None else None,
                version_no=repository.get_next_knowledge_version_no(parse_version.project_id),
                summary_json=normalize_summary_json(
                    extraction_result.summary_json,
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
        _mark_task(task, task_status=TASK_STATUS_PROCESSING, current_stage="upsert_vectors", progress_percent=85)
        task_repository.save(task)
        for step in step_map.values():
            task_repository.save(step)
        session.commit()

        vector_counts = upsert_vectors_for_knowledge_version(
            repository=repository,
            parse_version=parse_version,
            textbook_version=textbook_version,
            knowledge_version=knowledge_version,
            snapshot=snapshot,
            embedding_service=embedding_service,
            vector_service=vector_service,
        )

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
        return {
            "knowledge_version_id": knowledge_version.id,
            "chapter_count": len(snapshot.chapters),
            "point_count": len(snapshot.points),
            **vector_counts,
        }
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        _mark_task_failure(task_repository, repository, payload, exc)
        raise
    finally:
        session.close()


def _build_extraction_messages(*, parse_version, parse_pages: list, parse_blocks: list) -> list[ChatMessage]:
    """构造知识抽取提示词。"""
    page_id_to_page_no = {page.id: page.page_no for page in parse_pages}
    blocks_payload = [
        {
            "page_no": page_id_to_page_no.get(block.parse_page_id),
            "block_no": block.block_no,
            "block_type": block.block_type,
            "heading_level": block.heading_level,
            "text_content": block.text_content,
            "markdown_content": block.markdown_content,
        }
        for block in parse_blocks
        if block.is_deleted == 0 and (block.text_content or block.markdown_content)
    ]
    user_payload = {
        "parse_version_id": parse_version.id,
        "page_count": len(parse_pages),
        "blocks": blocks_payload,
    }
    system_prompt = (
        "你是教材知识结构抽取助手。"
        "请严格输出 JSON 对象，字段必须包含 summary_json、chapters、knowledge_points。"
        "chapters 必须是平铺数组，每个节点提供 node_path、node_no、node_level、node_type、title、summary_text、page_start、page_end、sort_order。"
        "knowledge_points 必须提供 chapter_path、point_name、point_type、importance_level、difficulty_level、mastery_level_hint、tags_json、summary_text、sort_order、evidences。"
        "evidences 中必须至少包含 page_no，可选 block_no、excerpt_text、bbox_json、score_value。"
        "如果解析内容不足，请基于现有结构尽量抽取，不要输出额外说明文字。"
    )
    return [
        ChatMessage(role="system", content=system_prompt),
        ChatMessage(role="user", content=json.dumps(user_payload, ensure_ascii=False)),
    ]


def _validate_extraction_result(result: KnowledgeExtractionResult, *, parse_pages: list, parse_blocks: list) -> None:
    """校验知识抽取结果引用合法。"""
    chapter_paths = [chapter.node_path for chapter in result.chapters]
    if len(set(chapter_paths)) != len(chapter_paths):
        raise AppException(BusinessErrorCode.LLM_RESULT_INVALID, "LLM 返回了重复的章节路径")
    chapter_path_set = set(chapter_paths)
    for chapter in result.chapters:
        parent_path = chapter.node_path.rsplit(".", 1)[0] if "." in chapter.node_path else None
        if parent_path and parent_path not in chapter_path_set:
            raise AppException(
                BusinessErrorCode.LLM_RESULT_INVALID,
                "LLM 返回的章节父路径不存在",
                {"node_path": chapter.node_path, "parent_path": parent_path},
            )

    page_set = {page.page_no for page in parse_pages}
    block_set = {
        (page.page_no, block.block_no)
        for block in parse_blocks
        for page in parse_pages
        if page.id == block.parse_page_id
    }
    for point in result.knowledge_points:
        if point.chapter_path and point.chapter_path not in chapter_path_set:
            raise AppException(
                BusinessErrorCode.LLM_RESULT_INVALID,
                "LLM 返回的知识点引用了不存在的章节路径",
                {"point_name": point.point_name, "chapter_path": point.chapter_path},
            )
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
    task.progress_percent = progress_percent
    if started_at is not None:
        task.started_at = task.started_at or started_at
    if finished_at is not None:
        task.finished_at = finished_at
    if result_json is not None:
        task.result_json = result_json


def _mark_step(step, step_status: str, progress_percent: int, *, detail_json: dict | None = None, started_at=None, finished_at=None) -> None:
    step.step_status = step_status
    step.progress_percent = progress_percent
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
    task = task_repository.get_task_by_id(payload["task_record_id"])
    if task is not None:
        task.task_status = TASK_STATUS_FAILURE
        task.last_error_code = getattr(exc, "code", None).value if isinstance(exc, AppException) else "KNOWLEDGE_TASK_FAILED"
        task.last_error_message = getattr(exc, "message", None) if isinstance(exc, AppException) else str(exc)
        task.finished_at = DateTimeUtil.now_utc()
        task_repository.save(task)
    for step_code in ("prepare_parse_source", "invoke_llm_extract", "persist_knowledge_result", "upsert_vectors"):
        step = task_repository.get_task_step(payload["task_record_id"], step_code)
        if step is None or step.step_status == TASK_STATUS_SUCCESS:
            continue
        step.step_status = TASK_STATUS_FAILURE
        step.detail_json = {"error": str(exc)}
        step.finished_at = DateTimeUtil.now_utc()
        task_repository.save(step)
        break
    repository.session.commit()


def _create_session(payload: dict) -> Session:
    """为知识抽取任务创建数据库会话。"""
    database_url = payload.get("database_url")
    if not database_url:
        return SessionLocal()
    engine = create_engine(database_url, pool_pre_ping=True, future=True)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, class_=Session)
    return factory()
