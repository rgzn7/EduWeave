"""
@Date: 2026-04-14
@Author: xisy
@Discription: 学情模块真实任务执行能力
"""

import hashlib
import json
from pathlib import Path, PurePosixPath
import re

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.constants import (
    MINERU_STRATEGY_DOC_DEFAULT,
    REVIEW_STATUS_PENDING,
    TASK_STATUS_FAILURE,
    TASK_STATUS_PROCESSING,
    TASK_STATUS_SUCCESS,
)
from app.core.database import SessionLocal
from app.core.exceptions import AppException
from app.modules.learner_profile.repository import LearnerProfileRepository
from app.modules.learner_profile.rules import LearnerProfileRecordDraft, parse_learner_profile_text
from app.modules.p0_models import FileObject, LearnerProfileRecord, LearnerProfileVersion
from app.modules.task_center.repository import TaskCenterRepository
from app.shared.mineru import MineruDocumentService
from app.shared.storage import ObsStorageClient
from app.shared.utils import DateTimeUtil


def run_extract_task(payload: dict) -> dict[str, int | str]:
    """执行学情抽取任务。"""
    session = _create_session(payload)
    repository = LearnerProfileRepository(session)
    task_repository = TaskCenterRepository(session)
    storage_client = ObsStorageClient()
    mineru_service = MineruDocumentService()
    task = task_repository.get_task_by_id(payload["task_record_id"])
    step_map = _get_step_map(task_repository, payload["task_record_id"])
    now = DateTimeUtil.now_utc()

    try:
        if task is None:
            raise RuntimeError("学情抽取任务不存在")
        _mark_task(task, task_status=TASK_STATUS_PROCESSING, current_stage="prepare_source", progress_percent=5, started_at=now)
        _mark_step(step_map["prepare_source"], TASK_STATUS_PROCESSING, 15, started_at=now)
        task_repository.save(task)
        task_repository.save(step_map["prepare_source"])
        session.commit()

        profile_file = repository.get_profile_file_by_id(payload["profile_file_id"])
        if profile_file is None:
            raise RuntimeError("学情文件不存在")
        project = repository.get_project(payload["project_id"])
        if project is None:
            raise RuntimeError("项目不存在")
        source_file = repository.get_file_object(profile_file.source_file_id)
        if source_file is None:
            raise RuntimeError("学情源文件不存在")

        source_content = storage_client.download_bytes(source_file.object_key)
        _mark_step(
            step_map["prepare_source"],
            TASK_STATUS_SUCCESS,
            100,
            detail_json={"source_file_id": source_file.id},
            finished_at=DateTimeUtil.now_utc(),
        )
        _mark_step(step_map["submit_mineru"], TASK_STATUS_PROCESSING, 20, started_at=DateTimeUtil.now_utc())
        _mark_task(task, task_status=TASK_STATUS_PROCESSING, current_stage="submit_mineru", progress_percent=20)
        task_repository.save(task)
        for step in step_map.values():
            task_repository.save(step)
        session.commit()

        normalized_document = mineru_service.parse_document(
            file_name=source_file.original_filename,
            content=source_content,
            strategy_code=MINERU_STRATEGY_DOC_DEFAULT,
            data_id=f"profile_{profile_file.id}_task_{task.id}",
        )
        _mark_step(
            step_map["submit_mineru"],
            TASK_STATUS_SUCCESS,
            100,
            detail_json={"batch_id": normalized_document.batch_id, "data_id": normalized_document.data_id},
            finished_at=DateTimeUtil.now_utc(),
        )
        _mark_step(step_map["poll_mineru_result"], TASK_STATUS_SUCCESS, 100, detail_json={"batch_id": normalized_document.batch_id}, started_at=now, finished_at=DateTimeUtil.now_utc())
        _mark_step(step_map["build_profile_version"], TASK_STATUS_PROCESSING, 40, started_at=DateTimeUtil.now_utc())
        _mark_task(task, task_status=TASK_STATUS_PROCESSING, current_stage="build_profile_version", progress_percent=55)
        task_repository.save(task)
        for step in step_map.values():
            task_repository.save(step)
        session.commit()

        parse_result = parse_learner_profile_text(
            normalized_document.markdown_text,
            fallback_title=payload.get("title") or profile_file.title,
            fallback_filename=source_file.original_filename,
        )
        if not parse_result.records:
            raise RuntimeError("未能从学情文档中抽取到有效学科记录")

        version_no = repository.get_next_version_no(profile_file.id)
        raw_zip_file = _upload_binary_artifact(
            repository=repository,
            storage_client=storage_client,
            project_id=project.id,
            operator_user_id=payload["operator_user_id"],
            profile_file_id=profile_file.id,
            version_no=version_no,
            filename="full.zip",
            content=normalized_document.full_zip_bytes,
            biz_type="learner_profile_raw_zip",
            mime_type="application/zip",
        )
        markdown_file = _upload_binary_artifact(
            repository=repository,
            storage_client=storage_client,
            project_id=project.id,
            operator_user_id=payload["operator_user_id"],
            profile_file_id=profile_file.id,
            version_no=version_no,
            filename="full.md",
            content=normalized_document.markdown_text.encode("utf-8"),
            biz_type="learner_profile_markdown",
            mime_type="text/markdown",
        )
        content_list_file = _upload_binary_artifact(
            repository=repository,
            storage_client=storage_client,
            project_id=project.id,
            operator_user_id=payload["operator_user_id"],
            profile_file_id=profile_file.id,
            version_no=version_no,
            filename="content_list.json",
            content=json.dumps(normalized_document.content_list_json, ensure_ascii=False, indent=2).encode("utf-8"),
            biz_type="learner_profile_json",
            mime_type="application/json",
        )
        asset_file_id_map = _upload_asset_files(
            repository=repository,
            storage_client=storage_client,
            project_id=project.id,
            operator_user_id=payload["operator_user_id"],
            profile_file_id=profile_file.id,
            version_no=version_no,
            asset_files=normalized_document.asset_files,
        )

        profile_version = LearnerProfileVersion(
            project_id=project.id,
            profile_file_id=profile_file.id,
            parent_version_id=None,
            version_no=version_no,
            textbook_version_hint_id=payload.get("textbook_version_hint_id"),
            grade_code=payload.get("grade_code") or parse_result.grade_code or project.grade_code,
            subject_scope=payload.get("subject_scope") or parse_result.subject_scope,
            extract_status="success",
            review_status=REVIEW_STATUS_PENDING,
            version_status="ready",
            summary_text=parse_result.summary_text,
            raw_result_json={
                **parse_result.raw_result_json,
                "artifacts": {
                    "raw_zip_file_id": raw_zip_file.id,
                    "source_markdown_file_id": markdown_file.id,
                    "source_json_file_id": content_list_file.id,
                    "asset_file_id_map": asset_file_id_map,
                    "batch_id": normalized_document.batch_id,
                },
            },
            source_snapshot_json=parse_result.source_snapshot_json,
            created_by=payload.get("operator_user_id"),
        )
        repository.create_profile_version(profile_version)

        textbook_versions = repository.list_textbook_versions(project.id)
        current_textbook = repository.get_textbook_version_in_project(project.id, project.current_textbook_version_id) if project.current_textbook_version_id else None
        created_records = []
        for sort_order, record_draft in enumerate(parse_result.records):
            textbook_version_hint_id = _resolve_textbook_version_hint_id(
                project_textbook_versions=textbook_versions,
                current_textbook_version=current_textbook,
                record_draft=record_draft,
                requested_textbook_version_hint_id=payload.get("textbook_version_hint_id"),
            )
            record = LearnerProfileRecord(
                project_id=project.id,
                profile_version_id=profile_version.id,
                student_key=record_draft.student_key,
                student_name=record_draft.student_name,
                is_anonymous=record_draft.is_anonymous,
                region_name=record_draft.region_name,
                grade_code=record_draft.grade_code or parse_result.grade_code or project.grade_code,
                subject_code=record_draft.subject_code,
                textbook_version_hint_id=textbook_version_hint_id,
                score_value=record_draft.score_value,
                advantage_tags_json=record_draft.advantage_tags_json,
                weakness_tags_json=record_draft.weakness_tags_json,
                ability_tags_json=record_draft.ability_tags_json,
                habit_tags_json=record_draft.habit_tags_json,
                behavior_traits_json=record_draft.behavior_traits_json,
                time_plan_json=record_draft.time_plan_json,
                summary_text=record_draft.summary_text,
                evidence_json=record_draft.evidence_json,
                sort_order=sort_order,
            )
            repository.create_profile_record(record)
            created_records.append(record)

        profile_file.file_status = "success"
        if project.current_learner_profile_version_id is None or payload.get("set_as_current"):
            project.current_learner_profile_version_id = profile_version.id
        project.last_activity_at = DateTimeUtil.now_utc()
        repository.save(profile_file)
        repository.save(project)

        _mark_step(
            step_map["build_profile_version"],
            TASK_STATUS_SUCCESS,
            100,
            detail_json={"profile_version_id": profile_version.id, "record_count": len(created_records)},
            finished_at=DateTimeUtil.now_utc(),
        )
        _mark_task(
            task,
            task_status=TASK_STATUS_SUCCESS,
            current_stage="build_profile_version",
            progress_percent=100,
            result_json={
                "profile_version_id": profile_version.id,
                "record_count": len(created_records),
                "batch_id": normalized_document.batch_id,
            },
            finished_at=DateTimeUtil.now_utc(),
        )
        task_repository.save(task)
        for step in step_map.values():
            task_repository.save(step)
        session.commit()
        return {"profile_version_id": profile_version.id, "record_count": len(created_records), "batch_id": normalized_document.batch_id}
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        _mark_task_failure(task_repository, repository, payload, exc)
        raise
    finally:
        session.close()


def _resolve_textbook_version_hint_id(
    *,
    project_textbook_versions: list,
    current_textbook_version,
    record_draft: LearnerProfileRecordDraft,
    requested_textbook_version_hint_id: int | None,
) -> int | None:
    if requested_textbook_version_hint_id is not None:
        matched_requested_textbook = next(
            (item for item in project_textbook_versions if item.id == requested_textbook_version_hint_id),
            None,
        )
        if matched_requested_textbook is not None and matched_requested_textbook.subject_code == record_draft.subject_code:
            return matched_requested_textbook.id

    if record_draft.textbook_version_name:
        normalized_textbook_name = _normalize_textbook_label(record_draft.textbook_version_name)
        for textbook_version in project_textbook_versions:
            if textbook_version.subject_code != record_draft.subject_code:
                continue
            candidate_values = [
                textbook_version.textbook_name,
                textbook_version.publisher,
                textbook_version.grade_code,
                textbook_version.volume_code,
            ]
            normalized_candidate = _normalize_textbook_label("-".join(item for item in candidate_values if item))
            if normalized_candidate and (
                normalized_candidate in normalized_textbook_name or normalized_textbook_name in normalized_candidate
            ):
                return textbook_version.id

    if current_textbook_version is not None and current_textbook_version.subject_code == record_draft.subject_code:
        return current_textbook_version.id
    return None


def _normalize_textbook_label(label: str) -> str:
    return re.sub(r"[\s\-_]+", "", label).lower()


def _upload_binary_artifact(
    *,
    repository: LearnerProfileRepository,
    storage_client: ObsStorageClient,
    project_id: int,
    operator_user_id: int,
    profile_file_id: int,
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
        "learner_profiles",
        f"profile_{profile_file_id}",
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
    repository: LearnerProfileRepository,
    storage_client: ObsStorageClient,
    project_id: int,
    operator_user_id: int,
    profile_file_id: int,
    version_no: int,
    asset_files: dict[str, bytes],
) -> dict[str, int]:
    asset_file_id_map: dict[str, int] = {}
    for relative_path, content in asset_files.items():
        pure_path = PurePosixPath(relative_path)
        file_object = _upload_binary_artifact(
            repository=repository,
            storage_client=storage_client,
            project_id=project_id,
            operator_user_id=operator_user_id,
            profile_file_id=profile_file_id,
            version_no=version_no,
            filename=pure_path.name,
            content=content,
            biz_type="learner_profile_asset",
            mime_type=_guess_mime_type(pure_path.name),
            subdir_segments=["assets", *list(pure_path.parts[:-1])],
        )
        asset_file_id_map[relative_path] = file_object.id
    return asset_file_id_map


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
        for step_code in ("prepare_source", "submit_mineru", "poll_mineru_result", "build_profile_version")
    }


def _mark_task_failure(task_repository: TaskCenterRepository, repository: LearnerProfileRepository, payload: dict, exc: Exception) -> None:
    session = repository.session
    task = task_repository.get_task_by_id(payload["task_record_id"])
    if task is not None:
        task.task_status = TASK_STATUS_FAILURE
        task.last_error_code = getattr(exc, "code", None).value if isinstance(exc, AppException) and getattr(exc, "code", None) is not None else "PROFILE_EXTRACT_FAILED"
        task.last_error_message = getattr(exc, "message", None) if isinstance(exc, AppException) else str(exc)
        task.finished_at = DateTimeUtil.now_utc()
        task_repository.save(task)

    for step_code in ("prepare_source", "submit_mineru", "poll_mineru_result", "build_profile_version"):
        step = task_repository.get_task_step(payload["task_record_id"], step_code)
        if step is None or step.step_status == TASK_STATUS_SUCCESS:
            continue
        step.step_status = TASK_STATUS_FAILURE
        step.detail_json = {"error": str(exc)}
        step.finished_at = DateTimeUtil.now_utc()
        task_repository.save(step)
        break

    profile_file = repository.get_profile_file_by_id(payload["profile_file_id"])
    if profile_file is not None:
        profile_file.file_status = "failure"
        repository.save(profile_file)
    session.commit()


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
