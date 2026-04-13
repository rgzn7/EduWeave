"""
@Date: 2026-04-13
@Author: xisy
@Discription: 解析模块占位任务
"""

import re
from io import BytesIO

from pypdf import PdfReader
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.constants import (
    REVIEW_STATUS_PENDING,
    TASK_STATUS_FAILURE,
    TASK_STATUS_PROCESSING,
    TASK_STATUS_SUCCESS,
    VERSION_STATUS_READY,
)
from app.core.database import SessionLocal
from app.modules.parsing.repository import ParsingRepository
from app.modules.p0_models import ParseBlock, ParseIssue, ParsePage, ParseVersion
from app.modules.task_center.repository import TaskCenterRepository
from app.shared.storage import ObsStorageClient
from app.shared.utils.datetime_util import DateTimeUtil

HEADING_PATTERN = re.compile(r"^(第[一二三四五六七八九十百0-9]+[单元课章节]|[一二三四五六七八九十]+、|\d+\.)")


def run_placeholder_parse_task(payload: dict) -> dict[str, int]:
    """执行教材占位解析任务。"""
    session = _create_session(payload)
    repository = ParsingRepository(session)
    task_repository = TaskCenterRepository(session)
    storage_client = ObsStorageClient()
    task = task_repository.get_task_by_id(payload["task_record_id"])
    step = task_repository.get_task_step(payload["task_record_id"], "extract_textbook")
    now = DateTimeUtil.now_utc()

    try:
        if task is None or step is None:
            raise RuntimeError("解析任务不存在")

        textbook_version = repository.get_textbook_version(payload["textbook_version_id"])
        if textbook_version is None:
            raise RuntimeError("教材版本不存在")

        task.task_status = TASK_STATUS_PROCESSING
        task.current_stage = "extract_textbook"
        task.progress_percent = 5
        task.started_at = task.started_at or now
        step.step_status = TASK_STATUS_PROCESSING
        step.progress_percent = 5
        step.started_at = step.started_at or now
        textbook_version.parse_status = "processing"
        task_repository.save(task)
        task_repository.save(step)
        repository.save(textbook_version)
        session.commit()

        source_file = repository.get_file_object(textbook_version.source_file_id)
        if source_file is None:
            raise RuntimeError("教材源文件不存在")

        source_content = storage_client.download_bytes(source_file.object_key)
        reader = PdfReader(BytesIO(source_content))

        parse_version = ParseVersion(
            project_id=payload["project_id"],
            textbook_version_id=payload["textbook_version_id"],
            parent_parse_version_id=None,
            version_no=repository.get_next_parse_version_no(payload["textbook_version_id"]),
            parse_mode=payload["parse_mode"],
            page_range_text=None,
            strategy_code=payload["strategy_code"],
            mineru_model=None,
            parse_status="processing",
            review_status=REVIEW_STATUS_PENDING,
            version_status=VERSION_STATUS_READY,
            page_count=len(reader.pages),
            source_markdown_file_id=None,
            source_json_file_id=None,
            asset_manifest_json=None,
            diff_json=None,
            error_summary=None,
            started_at=DateTimeUtil.now_utc(),
            finished_at=None,
        )
        repository.create_parse_version(parse_version)

        issue_count = 0
        for page_index, page in enumerate(reader.pages, start=1):
            page_text = (page.extract_text() or "").strip()
            page_status = "success" if page_text else "empty_page"
            parse_page = ParsePage(
                parse_version_id=parse_version.id,
                page_no=page_index,
                source_page_image_file_id=None,
                page_status=page_status,
                has_issue=0,
                text_content=page_text or None,
                markdown_content=page_text or None,
                layout_json=None,
            )
            repository.create_parse_page(parse_page)

            blocks = _build_blocks(page_text)
            if not blocks:
                blocks = [{"block_type": "empty_page", "text": "", "heading_level": None}]

            first_block_id = None
            for block_index, block_data in enumerate(blocks, start=1):
                parse_block = ParseBlock(
                    parse_version_id=parse_version.id,
                    parse_page_id=parse_page.id,
                    block_no=block_index,
                    block_type=block_data["block_type"],
                    heading_level=block_data.get("heading_level"),
                    bbox_json=None,
                    text_content=block_data["text"] or None,
                    markdown_content=block_data["text"] or None,
                    asset_file_id=None,
                    origin_ref_json={"page_no": page_index},
                    is_deleted=0,
                )
                repository.create_parse_block(parse_block)
                if first_block_id is None:
                    first_block_id = parse_block.id

            page_issue = _build_issue(page_text, parse_version.id, parse_page.id, first_block_id)
            if page_issue is not None:
                parse_page.has_issue = 1
                repository.save(parse_page)
                repository.create_parse_issue(page_issue)
                issue_count += 1

        parse_version.parse_status = "success"
        parse_version.finished_at = DateTimeUtil.now_utc()
        textbook_version.parse_status = "success"
        task.task_status = TASK_STATUS_SUCCESS
        task.current_stage = "save_parse_result"
        task.progress_percent = 100
        task.result_json = {"parse_version_id": parse_version.id, "page_count": parse_version.page_count, "issue_count": issue_count}
        task.finished_at = DateTimeUtil.now_utc()
        step.step_status = TASK_STATUS_SUCCESS
        step.progress_percent = 100
        step.detail_json = {"parse_version_id": parse_version.id, "issue_count": issue_count}
        step.finished_at = DateTimeUtil.now_utc()
        repository.save(parse_version)
        repository.save(textbook_version)
        task_repository.save(task)
        task_repository.save(step)
        session.commit()
        return {"parse_version_id": parse_version.id, "page_count": int(parse_version.page_count or 0)}
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        task = task_repository.get_task_by_id(payload["task_record_id"])
        step = task_repository.get_task_step(payload["task_record_id"], "extract_textbook")
        textbook_version = repository.get_textbook_version(payload["textbook_version_id"])
        if textbook_version is not None:
            textbook_version.parse_status = "failure"
            repository.save(textbook_version)
        if task is not None:
            task.task_status = TASK_STATUS_FAILURE
            task.last_error_code = "PLACEHOLDER_PARSE_FAILED"
            task.last_error_message = str(exc)
            task.finished_at = DateTimeUtil.now_utc()
            task_repository.save(task)
        if step is not None:
            step.step_status = TASK_STATUS_FAILURE
            step.detail_json = {"error": str(exc)}
            step.finished_at = DateTimeUtil.now_utc()
            task_repository.save(step)
        session.commit()
        raise
    finally:
        session.close()


def _build_blocks(page_text: str) -> list[dict[str, object]]:
    """根据页文本构造占位解析块。"""
    normalized_text = page_text.strip()
    if not normalized_text:
        return []

    blocks: list[dict[str, object]] = []
    paragraphs = [item.strip() for item in re.split(r"\n{2,}", normalized_text) if item.strip()]
    if not paragraphs:
        paragraphs = [line.strip() for line in normalized_text.splitlines() if line.strip()]

    for paragraph in paragraphs:
        first_line = paragraph.splitlines()[0].strip()
        if HEADING_PATTERN.match(first_line):
            blocks.append({"block_type": "heading", "text": paragraph, "heading_level": 1})
        else:
            blocks.append({"block_type": "paragraph", "text": paragraph, "heading_level": None})
    return blocks


def _build_issue(page_text: str, parse_version_id: int, parse_page_id: int, parse_block_id: int | None) -> ParseIssue | None:
    """根据页文本判断是否生成解析异常。"""
    normalized_text = page_text.strip()
    if not normalized_text:
        return ParseIssue(
            parse_version_id=parse_version_id,
            parse_page_id=parse_page_id,
            parse_block_id=parse_block_id,
            related_reparse_version_id=None,
            issue_type="empty_page",
            severity="medium",
            issue_status="open",
            detected_by="system",
            description="当前页未提取到有效文本内容",
            resolution_note=None,
            created_by=None,
            resolved_by=None,
        )
    if len(normalized_text) < 20:
        return ParseIssue(
            parse_version_id=parse_version_id,
            parse_page_id=parse_page_id,
            parse_block_id=parse_block_id,
            related_reparse_version_id=None,
            issue_type="low_text_density",
            severity="low",
            issue_status="open",
            detected_by="system",
            description="当前页提取文本较少，建议人工复核",
            resolution_note=None,
            created_by=None,
            resolved_by=None,
        )
    return None


def _create_session(payload: dict) -> Session:
    """为任务创建数据库会话。"""
    database_url = payload.get("database_url")
    if not database_url:
        return SessionLocal()
    engine = create_engine(database_url, pool_pre_ping=True, future=True)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, class_=Session)
    return factory()
