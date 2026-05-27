"""
@Date: 2026-04-14
@Author: xisy
@Discription: 解析模块真实任务执行能力
"""

import hashlib
import json
from collections.abc import Callable
from pathlib import Path, PurePosixPath

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.constants import (
    REVIEW_STATUS_PENDING,
    TASK_STATUS_PENDING,
    TASK_STATUS_PROCESSING,
    TASK_STATUS_SUCCESS,
    VERSION_STATUS_ARCHIVED,
    VERSION_STATUS_READY,
)
from app.core.database import SessionLocal
from app.core.exceptions import AppException, BusinessErrorCode
from app.modules.p0_models import FileObject, ParseVersion
from app.modules.parsing.domain import (
    build_page_drafts_from_normalized_document,
    build_parse_snapshot_payload,
    clone_page_drafts_from_records,
    extract_pdf_subset,
    merge_issue_drafts,
    merge_page_drafts,
    persist_parse_tree,
    render_pdf_page_images,
)
from app.modules.parsing.repository import ParsingRepository
from app.modules.task_center.heartbeat import (
    StaleAttemptError,
    TaskHeartbeat,
    ensure_attempt,
)
from app.modules.task_center.progress import assign_monotonic_progress
from app.modules.task_center.recovery import requeue_or_fail_task
from app.modules.task_center.repository import TaskCenterRepository
from app.shared.mineru import MineruBatchFileResult, MineruDocumentService
from app.shared.storage import ObsStorageClient
from app.shared.utils import DateTimeUtil
from app.shared.utils.page_range_util import parse_page_range_text


def run_parse_task(payload: dict) -> dict[str, int | str]:
    """执行教材全量解析任务。"""
    session = _create_session(payload)
    repository = ParsingRepository(session)
    task_repository = TaskCenterRepository(session)
    storage_client = ObsStorageClient()
    mineru_service = MineruDocumentService()
    task = task_repository.get_task_by_id(payload["task_record_id"])
    step_map = _get_step_map(task_repository, payload["task_record_id"])
    now = DateTimeUtil.now_utc()
    attempt_id = ensure_attempt(task_repository, payload["task_record_id"], payload.get("execution_attempt_id"))
    heartbeat = TaskHeartbeat(session, payload["task_record_id"], attempt_id)

    try:
        if task is None:
            raise AppException(BusinessErrorCode.TASK_NOT_FOUND, "解析任务不存在")
        if task.execution_attempt_id and task.execution_attempt_id != attempt_id:
            raise StaleAttemptError(task.id, attempt_id)
        _mark_task(task, task_status=TASK_STATUS_PROCESSING, current_stage="prepare_source", progress_percent=5, started_at=now)
        _mark_step(step_map["prepare_source"], TASK_STATUS_PROCESSING, 10, started_at=now)
        task_repository.save(task)
        task_repository.save(step_map["prepare_source"])
        session.commit()

        textbook_version = repository.get_textbook_version(payload["textbook_version_id"])
        if textbook_version is None:
            raise AppException(BusinessErrorCode.TEXTBOOK_NOT_FOUND, "教材版本不存在")
        source_file = repository.get_file_object(textbook_version.source_file_id)
        if source_file is None:
            raise AppException(BusinessErrorCode.FILE_NOT_FOUND, "教材源文件不存在")
        source_content = storage_client.download_bytes(source_file.object_key)
        page_image_bytes = render_pdf_page_images(source_content)
        _mark_step(
            step_map["prepare_source"],
            TASK_STATUS_SUCCESS,
            100,
            detail_json={"source_file_id": source_file.id, "page_image_count": len(page_image_bytes)},
            finished_at=DateTimeUtil.now_utc(),
        )
        _mark_step(step_map["submit_mineru"], TASK_STATUS_PROCESSING, 20, started_at=DateTimeUtil.now_utc())
        _mark_task(task, task_status=TASK_STATUS_PROCESSING, current_stage="submit_mineru", progress_percent=20)
        task_repository.save(task)
        task_repository.save(step_map["prepare_source"])
        task_repository.save(step_map["submit_mineru"])
        session.commit()

        # MinerU 同步轮询可能长达数分钟，前后 touch 心跳避免被 reaper 误判
        heartbeat.touch()
        normalized_document = mineru_service.parse_document(
            file_name=source_file.original_filename,
            content=source_content,
            strategy_code=payload["strategy_code"],
            data_id=f"textbook_{textbook_version.id}_task_{task.id}",
            on_progress=_build_mineru_progress_callback(
                heartbeat=heartbeat,
                step_id=step_map["poll_mineru_result"].id,
                current_stage="poll_mineru_result",
                task_progress_start=20,
                task_progress_end=54,
            ),
        )
        heartbeat.touch()
        _mark_step(
            step_map["submit_mineru"],
            TASK_STATUS_SUCCESS,
            100,
            detail_json={"batch_id": normalized_document.batch_id, "data_id": normalized_document.data_id},
            finished_at=DateTimeUtil.now_utc(),
        )
        _mark_step(step_map["poll_mineru_result"], TASK_STATUS_SUCCESS, 100, detail_json={"batch_id": normalized_document.batch_id}, started_at=now, finished_at=DateTimeUtil.now_utc())
        _mark_step(step_map["persist_parse_result"], TASK_STATUS_PROCESSING, 40, started_at=DateTimeUtil.now_utc())
        _mark_task(task, task_status=TASK_STATUS_PROCESSING, current_stage="persist_parse_result", progress_percent=55)
        task_repository.save(task)
        for step in step_map.values():
            task_repository.save(step)
        session.commit()

        version_no = repository.get_next_parse_version_no(textbook_version.id)
        raw_zip_file = _upload_binary_artifact(
            repository=repository,
            storage_client=storage_client,
            project_id=textbook_version.project_id,
            operator_user_id=payload["operator_user_id"],
            textbook_version_id=textbook_version.id,
            version_no=version_no,
            filename="full.zip",
            content=normalized_document.full_zip_bytes,
            biz_type="parse_raw_zip",
            mime_type="application/zip",
        )
        markdown_bytes = normalized_document.markdown_text.encode("utf-8")
        markdown_file = _upload_binary_artifact(
            repository=repository,
            storage_client=storage_client,
            project_id=textbook_version.project_id,
            operator_user_id=payload["operator_user_id"],
            textbook_version_id=textbook_version.id,
            version_no=version_no,
            filename="full.md",
            content=markdown_bytes,
            biz_type="parse_markdown",
            mime_type="text/markdown",
        )
        content_list_bytes = json.dumps(normalized_document.content_list_json, ensure_ascii=False, indent=2).encode("utf-8")
        content_list_file = _upload_binary_artifact(
            repository=repository,
            storage_client=storage_client,
            project_id=textbook_version.project_id,
            operator_user_id=payload["operator_user_id"],
            textbook_version_id=textbook_version.id,
            version_no=version_no,
            filename="content_list.json",
            content=content_list_bytes,
            biz_type="parse_json",
            mime_type="application/json",
        )
        asset_file_id_map = _upload_asset_files(
            repository=repository,
            storage_client=storage_client,
            project_id=textbook_version.project_id,
            operator_user_id=payload["operator_user_id"],
            textbook_version_id=textbook_version.id,
            version_no=version_no,
            asset_files=normalized_document.asset_files,
        )
        page_image_file_id_map = _upload_page_images(
            repository=repository,
            storage_client=storage_client,
            project_id=textbook_version.project_id,
            operator_user_id=payload["operator_user_id"],
            textbook_version_id=textbook_version.id,
            version_no=version_no,
            page_image_bytes=page_image_bytes,
        )
        page_drafts, issue_drafts = build_page_drafts_from_normalized_document(
            normalized_document,
            asset_file_id_map=asset_file_id_map,
            page_image_file_id_map=page_image_file_id_map,
        )
        version_status = _determine_new_version_status(
            repository=repository,
            textbook_version_id=textbook_version.id,
            set_as_current=payload["set_as_current_on_success"],
        )
        parse_version = ParseVersion(
            project_id=textbook_version.project_id,
            textbook_version_id=textbook_version.id,
            parent_parse_version_id=None,
            version_no=version_no,
            parse_mode="full",
            page_range_text=None,
            strategy_code=payload["strategy_code"],
            mineru_model=normalized_document.model_version,
            parse_status="success",
            review_status=REVIEW_STATUS_PENDING,
            version_status=version_status,
            page_count=len(page_drafts),
            source_markdown_file_id=markdown_file.id,
            source_json_file_id=content_list_file.id,
            asset_manifest_json={
                "raw_zip_file_id": raw_zip_file.id,
                "source_markdown_file_id": markdown_file.id,
                "source_json_file_id": content_list_file.id,
                "assets": asset_file_id_map,
                "page_images": page_image_file_id_map,
                "batch_id": normalized_document.batch_id,
            },
            diff_json=None,
            error_summary=None,
            started_at=now,
            finished_at=DateTimeUtil.now_utc(),
        )
        repository.create_parse_version(parse_version)
        persist_parse_tree(repository, parse_version_id=parse_version.id, pages=page_drafts, issues=issue_drafts)
        if version_status == VERSION_STATUS_READY:
            repository.archive_other_parse_versions(textbook_version.id, parse_version.id)
        textbook_version.parse_status = "success"
        repository.save(textbook_version)

        _mark_step(
            step_map["persist_parse_result"],
            TASK_STATUS_SUCCESS,
            100,
            detail_json={
                "parse_version_id": parse_version.id,
                "source_markdown_file_id": markdown_file.id,
                "source_json_file_id": content_list_file.id,
                "issue_count": len(issue_drafts),
            },
            finished_at=DateTimeUtil.now_utc(),
        )
        _mark_task(
            task,
            task_status=TASK_STATUS_SUCCESS,
            current_stage="persist_parse_result",
            progress_percent=100,
            result_json={
                "parse_version_id": parse_version.id,
                "page_count": len(page_drafts),
                "issue_count": len(issue_drafts),
                "batch_id": normalized_document.batch_id,
            },
            finished_at=DateTimeUtil.now_utc(),
        )
        task_repository.save(task)
        for step in step_map.values():
            task_repository.save(step)
        session.commit()
        _notify_orchestrator_parse_success(session=session, task=task, parse_version=parse_version)
        return {"parse_version_id": parse_version.id, "page_count": len(page_drafts), "batch_id": normalized_document.batch_id}
    except StaleAttemptError:
        session.rollback()
        return {"stale_attempt": True}
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        _mark_task_failure(task_repository, repository, payload, exc)
        raise
    finally:
        session.close()


def run_reparse_task(payload: dict) -> dict[str, int | str]:
    """执行页级重解析任务。"""
    session = _create_session(payload)
    repository = ParsingRepository(session)
    task_repository = TaskCenterRepository(session)
    storage_client = ObsStorageClient()
    mineru_service = MineruDocumentService()
    task = task_repository.get_task_by_id(payload["task_record_id"])
    step_map = _get_step_map(task_repository, payload["task_record_id"])
    now = DateTimeUtil.now_utc()
    attempt_id = ensure_attempt(task_repository, payload["task_record_id"], payload.get("execution_attempt_id"))
    heartbeat = TaskHeartbeat(session, payload["task_record_id"], attempt_id)

    try:
        if task is None:
            raise AppException(BusinessErrorCode.TASK_NOT_FOUND, "重解析任务不存在")
        if task.execution_attempt_id and task.execution_attempt_id != attempt_id:
            raise StaleAttemptError(task.id, attempt_id)
        parent_parse_version = repository.get_parse_version(payload["parse_version_id"])
        if parent_parse_version is None:
            raise AppException(BusinessErrorCode.PARSE_VERSION_NOT_FOUND, "父解析版本不存在")
        textbook_version = repository.get_textbook_version(parent_parse_version.textbook_version_id)
        if textbook_version is None:
            raise AppException(BusinessErrorCode.TEXTBOOK_NOT_FOUND, "教材版本不存在")
        source_file = repository.get_file_object(textbook_version.source_file_id)
        if source_file is None:
            raise AppException(BusinessErrorCode.FILE_NOT_FOUND, "教材源文件不存在")

        _mark_task(task, task_status=TASK_STATUS_PROCESSING, current_stage="prepare_source", progress_percent=5, started_at=now)
        _mark_step(step_map["prepare_source"], TASK_STATUS_PROCESSING, 15, started_at=now)
        task_repository.save(task)
        task_repository.save(step_map["prepare_source"])
        session.commit()

        source_content = storage_client.download_bytes(source_file.object_key)
        total_pages = parent_parse_version.page_count or repository.count_parse_pages(parent_parse_version.id)
        page_nos = parse_page_range_text(payload["page_range_text"], total_pages)
        subset_pdf_bytes = extract_pdf_subset(source_content, page_nos)
        parent_pages = repository.list_all_parse_pages(parent_parse_version.id)
        parent_blocks = repository.list_all_blocks_by_version(parent_parse_version.id)
        parent_issues = repository.list_all_parse_issues(parent_parse_version.id)
        base_pages, base_issues = clone_page_drafts_from_records(parent_pages, parent_blocks, parent_issues)
        parent_page_image_map = {page.page_no: page.source_page_image_file_id for page in base_pages}
        _mark_step(
            step_map["prepare_source"],
            TASK_STATUS_SUCCESS,
            100,
            detail_json={"page_range_text": payload["page_range_text"], "page_count": len(page_nos)},
            finished_at=DateTimeUtil.now_utc(),
        )
        _mark_step(step_map["submit_mineru"], TASK_STATUS_PROCESSING, 20, started_at=DateTimeUtil.now_utc())
        _mark_task(task, task_status=TASK_STATUS_PROCESSING, current_stage="submit_mineru", progress_percent=25)
        task_repository.save(task)
        for step in step_map.values():
            task_repository.save(step)
        session.commit()

        heartbeat.touch()
        normalized_document = mineru_service.parse_document(
            file_name=f"reparse_{textbook_version.id}.pdf",
            content=subset_pdf_bytes,
            strategy_code=payload["strategy_code"],
            data_id=f"reparse_{parent_parse_version.id}_task_{task.id}",
            on_progress=_build_mineru_progress_callback(
                heartbeat=heartbeat,
                step_id=step_map["poll_mineru_result"].id,
                current_stage="poll_mineru_result",
                task_progress_start=25,
                task_progress_end=59,
            ),
        )
        heartbeat.touch()
        _mark_step(
            step_map["submit_mineru"],
            TASK_STATUS_SUCCESS,
            100,
            detail_json={"batch_id": normalized_document.batch_id, "data_id": normalized_document.data_id},
            finished_at=DateTimeUtil.now_utc(),
        )
        _mark_step(step_map["poll_mineru_result"], TASK_STATUS_SUCCESS, 100, detail_json={"batch_id": normalized_document.batch_id}, started_at=now, finished_at=DateTimeUtil.now_utc())
        _mark_step(step_map["persist_parse_result"], TASK_STATUS_PROCESSING, 50, started_at=DateTimeUtil.now_utc())
        _mark_task(task, task_status=TASK_STATUS_PROCESSING, current_stage="persist_parse_result", progress_percent=60)
        task_repository.save(task)
        for step in step_map.values():
            task_repository.save(step)
        session.commit()

        version_no = repository.get_next_parse_version_no(textbook_version.id)
        raw_zip_file = _upload_binary_artifact(
            repository=repository,
            storage_client=storage_client,
            project_id=textbook_version.project_id,
            operator_user_id=payload["operator_user_id"],
            textbook_version_id=textbook_version.id,
            version_no=version_no,
            filename="reparse_full.zip",
            content=normalized_document.full_zip_bytes,
            biz_type="parse_raw_zip",
            mime_type="application/zip",
        )
        asset_file_id_map = _upload_asset_files(
            repository=repository,
            storage_client=storage_client,
            project_id=textbook_version.project_id,
            operator_user_id=payload["operator_user_id"],
            textbook_version_id=textbook_version.id,
            version_no=version_no,
            asset_files=normalized_document.asset_files,
        )
        replacement_pages, replacement_issues = build_page_drafts_from_normalized_document(
            normalized_document,
            asset_file_id_map=asset_file_id_map,
            page_image_file_id_map=parent_page_image_map,
            page_no_mapping=page_nos,
        )
        merged_pages = merge_page_drafts(base_pages, replacement_pages)
        merged_issues = merge_issue_drafts(base_pages, base_issues, replacement_pages, replacement_issues)
        markdown_text, snapshot_json_bytes = build_parse_snapshot_payload(merged_pages, merged_issues)
        markdown_file = _upload_binary_artifact(
            repository=repository,
            storage_client=storage_client,
            project_id=textbook_version.project_id,
            operator_user_id=payload["operator_user_id"],
            textbook_version_id=textbook_version.id,
            version_no=version_no,
            filename="full.md",
            content=markdown_text.encode("utf-8"),
            biz_type="parse_markdown",
            mime_type="text/markdown",
        )
        snapshot_file = _upload_binary_artifact(
            repository=repository,
            storage_client=storage_client,
            project_id=textbook_version.project_id,
            operator_user_id=payload["operator_user_id"],
            textbook_version_id=textbook_version.id,
            version_no=version_no,
            filename="content_list.json",
            content=snapshot_json_bytes,
            biz_type="parse_json",
            mime_type="application/json",
        )
        version_status = _determine_new_version_status(
            repository=repository,
            textbook_version_id=textbook_version.id,
            set_as_current=payload["set_as_current_on_success"],
        )
        parse_version = ParseVersion(
            project_id=textbook_version.project_id,
            textbook_version_id=textbook_version.id,
            parent_parse_version_id=parent_parse_version.id,
            version_no=version_no,
            parse_mode=parent_parse_version.parse_mode,
            page_range_text=payload["page_range_text"],
            strategy_code=payload["strategy_code"],
            mineru_model=normalized_document.model_version,
            parse_status="success",
            review_status=REVIEW_STATUS_PENDING,
            version_status=version_status,
            page_count=len(merged_pages),
            source_markdown_file_id=markdown_file.id,
            source_json_file_id=snapshot_file.id,
            asset_manifest_json={
                **(parent_parse_version.asset_manifest_json or {}),
                "reparse": {
                    "raw_zip_file_id": raw_zip_file.id,
                    "replacement_page_nos": page_nos,
                    "source_markdown_file_id": markdown_file.id,
                    "source_json_file_id": snapshot_file.id,
                    "asset_file_id_map": asset_file_id_map,
                    "batch_id": normalized_document.batch_id,
                },
            },
            diff_json={
                "revision_type": "reparse",
                "edited_page_nos": page_nos,
                "edited_page_count": len(page_nos),
            },
            error_summary=None,
            started_at=now,
            finished_at=DateTimeUtil.now_utc(),
        )
        repository.create_parse_version(parse_version)
        persist_parse_tree(repository, parse_version_id=parse_version.id, pages=merged_pages, issues=merged_issues)
        if version_status == VERSION_STATUS_READY:
            repository.archive_other_parse_versions(textbook_version.id, parse_version.id)

        _mark_step(
            step_map["persist_parse_result"],
            TASK_STATUS_SUCCESS,
            100,
            detail_json={
                "parse_version_id": parse_version.id,
                "page_range_text": payload["page_range_text"],
                "issue_count": len(merged_issues),
            },
            finished_at=DateTimeUtil.now_utc(),
        )
        _mark_task(
            task,
            task_status=TASK_STATUS_SUCCESS,
            current_stage="persist_parse_result",
            progress_percent=100,
            result_json={
                "parse_version_id": parse_version.id,
                "page_range_text": payload["page_range_text"],
                "issue_count": len(merged_issues),
                "batch_id": normalized_document.batch_id,
            },
            finished_at=DateTimeUtil.now_utc(),
        )
        task_repository.save(task)
        for step in step_map.values():
            task_repository.save(step)
        session.commit()
        return {"parse_version_id": parse_version.id, "page_count": len(merged_pages), "batch_id": normalized_document.batch_id}
    except StaleAttemptError:
        session.rollback()
        return {"stale_attempt": True}
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        _mark_task_failure(task_repository, repository, payload, exc)
        raise
    finally:
        session.close()


def _upload_binary_artifact(
    *,
    repository: ParsingRepository,
    storage_client: ObsStorageClient,
    project_id: int,
    operator_user_id: int,
    textbook_version_id: int,
    version_no: int,
    filename: str,
    content: bytes,
    biz_type: str,
    mime_type: str,
    subdir_segments: list[str] | None = None,
) -> FileObject:
    subdir_segments = subdir_segments or []
    object_key = storage_client.build_object_key(
        str(project_id),
        "parsing",
        f"textbook_{textbook_version_id}",
        f"version_{version_no}",
        *subdir_segments,
        filename=filename,
    )
    storage_client.upload_bytes(object_key, content, content_type=mime_type)
    file_object = FileObject(
        project_id=project_id,
        biz_type=biz_type,
        bucket_name=storage_client.settings.obs_bucket,
        object_key=object_key,
        original_filename=filename,
        file_ext=Path(filename).suffix.lower() or None,
        mime_type=mime_type,
        file_size=len(content),
        content_hash=hashlib.sha256(content).hexdigest(),
        source_type="system_generated",
        upload_status="uploaded",
        uploaded_by=operator_user_id,
        metadata_json={"generated_at": DateTimeUtil.to_isoformat(DateTimeUtil.now_utc())},
    )
    repository.create_file_object(file_object)
    return file_object


def _upload_asset_files(
    *,
    repository: ParsingRepository,
    storage_client: ObsStorageClient,
    project_id: int,
    operator_user_id: int,
    textbook_version_id: int,
    version_no: int,
    asset_files: dict[str, bytes],
) -> dict[str, int]:
    asset_file_id_map: dict[str, int] = {}
    for relative_path, content in asset_files.items():
        pure_path = PurePosixPath(relative_path)
        subdir_segments = ["assets", *list(pure_path.parts[:-1])]
        file_object = _upload_binary_artifact(
            repository=repository,
            storage_client=storage_client,
            project_id=project_id,
            operator_user_id=operator_user_id,
            textbook_version_id=textbook_version_id,
            version_no=version_no,
            filename=pure_path.name,
            content=content,
            biz_type="parse_asset",
            mime_type=_guess_mime_type(pure_path.name),
            subdir_segments=subdir_segments,
        )
        asset_file_id_map[relative_path] = file_object.id
    return asset_file_id_map


def _upload_page_images(
    *,
    repository: ParsingRepository,
    storage_client: ObsStorageClient,
    project_id: int,
    operator_user_id: int,
    textbook_version_id: int,
    version_no: int,
    page_image_bytes: dict[int, bytes],
) -> dict[int, int]:
    page_image_file_id_map: dict[int, int] = {}
    for page_no, content in page_image_bytes.items():
        file_object = _upload_binary_artifact(
            repository=repository,
            storage_client=storage_client,
            project_id=project_id,
            operator_user_id=operator_user_id,
            textbook_version_id=textbook_version_id,
            version_no=version_no,
            filename=f"page_{page_no}.png",
            content=content,
            biz_type="parse_page_image",
            mime_type="image/png",
            subdir_segments=["page_images"],
        )
        page_image_file_id_map[page_no] = file_object.id
    return page_image_file_id_map


def _determine_new_version_status(
    *,
    repository: ParsingRepository,
    textbook_version_id: int,
    set_as_current: bool,
) -> str:
    if set_as_current:
        return VERSION_STATUS_READY
    active_parse_version = repository.get_active_parse_version(textbook_version_id)
    return VERSION_STATUS_READY if active_parse_version is None else VERSION_STATUS_ARCHIVED


def _build_mineru_progress_callback(
    *,
    heartbeat: TaskHeartbeat,
    step_id: int,
    current_stage: str,
    task_progress_start: int,
    task_progress_end: int,
) -> Callable[[MineruBatchFileResult], None]:
    """构造 MinerU 轮询进度回调，把外部等待阶段映射到任务进度区间。"""
    poll_state = {"count": 0}

    def _on_progress(result: MineruBatchFileResult) -> None:
        poll_state["count"] += 1
        external_percent = _extract_mineru_progress_percent(result.extract_progress)
        if external_percent is None:
            progress_ratio = min(0.95, poll_state["count"] / 20)
        else:
            progress_ratio = min(0.95, max(0.0, external_percent / 100))
        task_progress = task_progress_start + int((task_progress_end - task_progress_start) * progress_ratio)
        step_progress = 20 + int(75 * progress_ratio)
        heartbeat.tick(progress_percent=task_progress, current_stage=current_stage)
        heartbeat.update_step_detail(
            step_id=step_id,
            progress_percent=step_progress,
            detail_json={
                "mineru_state": result.state,
                "poll_count": poll_state["count"],
                "mineru_progress_percent": external_percent,
            },
        )

    return _on_progress


def _extract_mineru_progress_percent(extract_progress: dict | None) -> float | None:
    """兼容解析 MinerU 可能返回的进度结构。"""
    if not isinstance(extract_progress, dict):
        return None
    for key in ("progress_percent", "percent", "progress", "extract_percent"):
        raw_value = extract_progress.get(key)
        if isinstance(raw_value, (int, float)):
            return raw_value * 100 if 0 <= raw_value <= 1 else float(raw_value)
    done = extract_progress.get("done") or extract_progress.get("processed") or extract_progress.get("current")
    total = extract_progress.get("total")
    if isinstance(done, (int, float)) and isinstance(total, (int, float)) and total > 0:
        return float(done) * 100 / float(total)
    return None


def _mark_task(
    task,
    *,
    task_status: str,
    current_stage: str,
    progress_percent: int,
    started_at=None,
    finished_at=None,
    result_json: dict | None = None,
) -> None:
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
        for step_code in ("prepare_source", "submit_mineru", "poll_mineru_result", "persist_parse_result")
    }


def _mark_task_failure(task_repository: TaskCenterRepository, repository: ParsingRepository, payload: dict, exc: Exception) -> None:
    """处理解析任务失败：可重试错误重排重试，终态失败时级联标记教材解析状态。"""
    task = task_repository.get_task_by_id(payload["task_record_id"])
    if task is None:
        return
    terminal_failed = not requeue_or_fail_task(
        task_repository,
        task,
        exc=exc,
        fallback_error_code=BusinessErrorCode.PARSE_TASK_FAILED,
    )
    if not terminal_failed:
        return

    textbook_version_id = payload.get("textbook_version_id")
    parse_version_id = payload.get("parse_version_id")
    textbook_version = None
    if textbook_version_id is not None:
        textbook_version = repository.get_textbook_version(textbook_version_id)
    elif parse_version_id is not None:
        parent_parse_version = repository.get_parse_version(parse_version_id)
        if parent_parse_version is not None:
            textbook_version = repository.get_textbook_version(parent_parse_version.textbook_version_id)
    if textbook_version is not None:
        textbook_version.parse_status = "failure"
        repository.save(textbook_version)
        repository.session.commit()
    _notify_orchestrator_failure(session=repository.session, task=task, exc=exc)


def _notify_orchestrator_parse_success(*, session, task, parse_version) -> None:
    """成功后通知 orchestrator 续跑。失败不阻塞任务结果。"""
    try:
        from app.modules.orchestrator.service import OrchestratorService  # 延迟导入避免循环

        OrchestratorService(session).advance_after_parse_success(task=task, parse_version=parse_version)
    except Exception:  # noqa: BLE001
        from app.core.logging import get_logger as _get_logger

        _get_logger(__name__).warning("orchestrator parse hook 调用失败", task_id=task.id, exc_info=True)


def _notify_orchestrator_failure(*, session, task, exc) -> None:
    """终态失败时通知 orchestrator 把 run 标为 failed。"""
    try:
        from app.core.exceptions import AppException as _AppException
        from app.modules.orchestrator.service import OrchestratorService

        error_code = exc.code.value if isinstance(exc, _AppException) else type(exc).__name__
        error_message = exc.message if isinstance(exc, _AppException) else str(exc)
        OrchestratorService(session).mark_run_failed(
            task=task,
            error_code=error_code,
            error_message=error_message,
        )
    except Exception:  # noqa: BLE001
        from app.core.logging import get_logger as _get_logger

        _get_logger(__name__).warning("orchestrator failure hook 调用失败", task_id=task.id, exc_info=True)


def _guess_mime_type(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix == ".png":
        return "image/png"
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".json":
        return "application/json"
    if suffix == ".md":
        return "text/markdown"
    if suffix == ".html":
        return "text/html"
    if suffix == ".svg":
        return "image/svg+xml"
    return "application/octet-stream"


def _create_session(payload: dict) -> Session:
    """为任务创建数据库会话。"""
    database_url = payload.get("database_url")
    if not database_url:
        return SessionLocal()
    engine = create_engine(database_url, pool_pre_ping=True, future=True)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, class_=Session)
    return factory()
