"""
@Date: 2026-04-14
@Author: xisy
@Discription: 解析模块业务服务
"""

import hashlib
import json
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.constants import (
    PARSING_MODULE_CODE,
    PARSING_QUEUE_NAME,
    REVIEW_STATUS_CONFIRMED,
    TASK_STATUS_PENDING,
    TEXTBOOK_PARSE_TASK_TYPE,
    TEXTBOOK_REPARSE_TASK_TYPE,
    VERSION_STATUS_ARCHIVED,
    VERSION_STATUS_READY,
)
from app.core.exceptions import AppException, BusinessErrorCode
from app.core.middleware import get_request_id
from app.modules.p0_models import FileObject, ParseVersion
from app.modules.parsing.domain import (
    ParseBlockDraft,
    ParseIssueDraft,
    ParsePageDraft,
    build_parse_snapshot_payload,
    clone_page_drafts_from_records,
    detect_issue_drafts,
    merge_issue_drafts,
    merge_page_drafts,
    persist_parse_tree,
)
from app.modules.parsing.repository import ParsingRepository
from app.modules.parsing.schemas import (
    ParseBlockResponse,
    ParseIssueResponse,
    ParseManualRevisionPageRequest,
    ParseManualRevisionRequest,
    ParsePageResponse,
    ParseReparseTaskCreateRequest,
    ParseTaskCreateRequest,
    ParseVersionDetailResponse,
    ParseVersionListItemResponse,
)
from app.modules.task_center.repository import TaskCenterRepository
from app.modules.task_center.schemas import TaskListItemResponse
from app.modules.task_center.service import TaskCenterService
from app.shared.mineru import MineruDocumentService
from app.shared.queue import dispatch_task
from app.shared.storage import ObsStorageClient
from app.shared.utils import DateTimeUtil
from app.shared.utils.page_range_util import parse_page_range_text


class ParsingService:
    """解析模块服务。"""

    def __init__(
        self,
        session: Session,
        repository: ParsingRepository | None = None,
        storage_client: ObsStorageClient | None = None,
    ) -> None:
        self.session = session
        self.repository = repository or ParsingRepository(session)
        self.storage_client = storage_client or ObsStorageClient()
        self.task_repository = TaskCenterRepository(session)

    def create_parse_task(
        self,
        *,
        owner_user_id: int,
        textbook_version_id: int,
        request: ParseTaskCreateRequest,
    ) -> TaskListItemResponse:
        """创建教材全量解析任务。"""
        MineruDocumentService.resolve_strategy(request.strategy_code)
        parse_task = self._create_task_record(
            owner_user_id=owner_user_id,
            textbook_version_id=textbook_version_id,
            task_type=TEXTBOOK_PARSE_TASK_TYPE,
            biz_key=f"textbook_version:{textbook_version_id}:full",
            payload_json={
                "textbook_version_id": textbook_version_id,
                "strategy_code": request.strategy_code,
                "set_as_current_on_success": request.set_as_current_on_success,
            },
        )
        dispatch_result = dispatch_task(
            "app.modules.parsing.tasks.run_parse_task",
            {
                "task_record_id": parse_task.id,
                "textbook_version_id": textbook_version_id,
                "operator_user_id": owner_user_id,
                "strategy_code": request.strategy_code,
                "set_as_current_on_success": request.set_as_current_on_success,
            },
            queue=PARSING_QUEUE_NAME,
            session=self.session,
        )
        if dispatch_result.worker_task_id:
            parse_task.worker_task_id = dispatch_result.worker_task_id
            self.task_repository.save(parse_task)
            self.session.commit()

        self.session.expire_all()
        fresh_task = self.task_repository.get_task_by_id(parse_task.id)
        return TaskCenterService.build_task_list_item(fresh_task)

    def create_reparse_task(
        self,
        *,
        owner_user_id: int,
        parse_version_id: int,
        request: ParseReparseTaskCreateRequest,
    ) -> TaskListItemResponse:
        """创建页级重解析任务。"""
        MineruDocumentService.resolve_strategy(request.strategy_code)
        parse_version = self.repository.get_parse_version_for_owner(parse_version_id, owner_user_id)
        if parse_version is None:
            raise AppException(BusinessErrorCode.PARSE_VERSION_NOT_FOUND, "解析版本不存在")
        page_count = parse_version.page_count or self.repository.count_parse_pages(parse_version.id)
        page_nos = parse_page_range_text(request.page_range_text, page_count)
        page_range_text = ",".join(str(item) for item in page_nos)
        task = self._create_task_record(
            owner_user_id=owner_user_id,
            textbook_version_id=parse_version.textbook_version_id,
            task_type=TEXTBOOK_REPARSE_TASK_TYPE,
            biz_key=f"parse_version:{parse_version_id}:reparse:{page_range_text}",
            payload_json={
                "parse_version_id": parse_version_id,
                "page_range_text": page_range_text,
                "strategy_code": request.strategy_code,
                "set_as_current_on_success": request.set_as_current_on_success,
            },
        )
        dispatch_result = dispatch_task(
            "app.modules.parsing.tasks.run_reparse_task",
            {
                "task_record_id": task.id,
                "parse_version_id": parse_version_id,
                "operator_user_id": owner_user_id,
                "page_range_text": page_range_text,
                "strategy_code": request.strategy_code,
                "set_as_current_on_success": request.set_as_current_on_success,
            },
            queue=PARSING_QUEUE_NAME,
            session=self.session,
        )
        if dispatch_result.worker_task_id:
            task.worker_task_id = dispatch_result.worker_task_id
            self.task_repository.save(task)
            self.session.commit()

        self.session.expire_all()
        fresh_task = self.task_repository.get_task_by_id(task.id)
        return TaskCenterService.build_task_list_item(fresh_task)

    def create_manual_revision(
        self,
        *,
        owner_user_id: int,
        parse_version_id: int,
        request: ParseManualRevisionRequest,
    ) -> ParseVersionDetailResponse:
        """保存解析版本人工修正结果。"""
        parent_parse_version = self.repository.get_parse_version_for_owner(parse_version_id, owner_user_id)
        if parent_parse_version is None:
            raise AppException(BusinessErrorCode.PARSE_VERSION_NOT_FOUND, "解析版本不存在")
        textbook_version = self.repository.get_textbook_version(parent_parse_version.textbook_version_id)
        if textbook_version is None:
            raise AppException(BusinessErrorCode.TEXTBOOK_NOT_FOUND, "教材版本不存在")

        parent_pages = self.repository.list_all_parse_pages(parent_parse_version.id)
        parent_blocks = self.repository.list_all_blocks_by_version(parent_parse_version.id)
        parent_issues = self.repository.list_all_parse_issues(parent_parse_version.id)
        base_pages, base_issues = clone_page_drafts_from_records(parent_pages, parent_blocks, parent_issues)
        base_page_map = {page.page_no: page for page in base_pages}

        replacement_pages = [self._build_page_draft_from_request(item, base_page_map) for item in request.pages]
        replacement_issues: list[ParseIssueDraft] = []
        for page in replacement_pages:
            replacement_issues.extend(detect_issue_drafts(page))

        merged_pages = merge_page_drafts(base_pages, replacement_pages)
        merged_issues = merge_issue_drafts(base_pages, base_issues, replacement_pages, replacement_issues)
        version_status = self._determine_new_version_status(textbook_version.id, request.set_as_current_on_success)
        version_no = self.repository.get_next_parse_version_no(textbook_version.id)
        markdown_text, snapshot_json_bytes = build_parse_snapshot_payload(merged_pages, merged_issues)
        markdown_file = self._upload_artifact_file(
            project_id=parent_parse_version.project_id,
            operator_user_id=owner_user_id,
            textbook_version_id=textbook_version.id,
            version_no=version_no,
            filename="full.md",
            content=markdown_text.encode("utf-8"),
            biz_type="parse_markdown",
            mime_type="text/markdown",
        )
        snapshot_file = self._upload_artifact_file(
            project_id=parent_parse_version.project_id,
            operator_user_id=owner_user_id,
            textbook_version_id=textbook_version.id,
            version_no=version_no,
            filename="content_list.json",
            content=snapshot_json_bytes,
            biz_type="parse_json",
            mime_type="application/json",
        )

        parse_version = ParseVersion(
            project_id=parent_parse_version.project_id,
            textbook_version_id=textbook_version.id,
            parent_parse_version_id=parent_parse_version.id,
            version_no=version_no,
            parse_mode=parent_parse_version.parse_mode,
            page_range_text=None,
            strategy_code=parent_parse_version.strategy_code,
            mineru_model=parent_parse_version.mineru_model,
            parse_status="success",
            review_status=REVIEW_STATUS_CONFIRMED,
            version_status=version_status,
            page_count=len(merged_pages),
            source_markdown_file_id=markdown_file.id,
            source_json_file_id=snapshot_file.id,
            asset_manifest_json={
                **(parent_parse_version.asset_manifest_json or {}),
                "manual_revision": {
                    "edited_page_nos": sorted({page.page_no for page in replacement_pages}),
                    "source_markdown_file_id": markdown_file.id,
                    "source_json_file_id": snapshot_file.id,
                },
            },
            diff_json={
                "revision_type": "manual",
                "edited_page_nos": sorted({page.page_no for page in replacement_pages}),
                "edited_page_count": len(replacement_pages),
            },
            error_summary=None,
            started_at=DateTimeUtil.now_utc(),
            finished_at=DateTimeUtil.now_utc(),
        )
        self.repository.create_parse_version(parse_version)
        persist_parse_tree(self.repository, parse_version_id=parse_version.id, pages=merged_pages, issues=merged_issues)
        if version_status == VERSION_STATUS_READY:
            self.repository.archive_other_parse_versions(textbook_version.id, parse_version.id)

        self.session.commit()
        self.session.refresh(parse_version)
        return self.get_parse_version_detail(owner_user_id=owner_user_id, parse_version_id=parse_version.id)

    def list_parse_versions(
        self,
        *,
        owner_user_id: int,
        textbook_version_id: int,
        page: int,
        page_size: int,
    ) -> tuple[list[ParseVersionListItemResponse], int]:
        """分页查询解析版本。"""
        textbook_version = self.repository.get_textbook_version_for_owner(textbook_version_id, owner_user_id)
        if textbook_version is None:
            raise AppException(BusinessErrorCode.TEXTBOOK_NOT_FOUND, "教材版本不存在")
        offset = (page - 1) * page_size
        versions = self.repository.list_parse_versions(textbook_version.id, offset, page_size)
        total_count = self.repository.count_parse_versions(textbook_version.id)
        items = [self.build_parse_version_response(version) for version in versions]
        return items, total_count

    def get_parse_version_detail(self, *, owner_user_id: int, parse_version_id: int) -> ParseVersionDetailResponse:
        """查询解析版本详情。"""
        parse_version = self.repository.get_parse_version_for_owner(parse_version_id, owner_user_id)
        if parse_version is None:
            raise AppException(BusinessErrorCode.PARSE_VERSION_NOT_FOUND, "解析版本不存在")
        return ParseVersionDetailResponse(**self.build_parse_version_response(parse_version).model_dump())

    def confirm_parse_version(self, *, owner_user_id: int, parse_version_id: int) -> ParseVersionDetailResponse:
        """确认解析版本可用于后续知识抽取。"""
        parse_version = self.repository.get_parse_version_for_owner(parse_version_id, owner_user_id)
        if parse_version is None:
            raise AppException(BusinessErrorCode.PARSE_VERSION_NOT_FOUND, "解析版本不存在")
        if parse_version.review_status == REVIEW_STATUS_CONFIRMED:
            return ParseVersionDetailResponse(**self.build_parse_version_response(parse_version).model_dump())
        if parse_version.parse_status != "success":
            raise AppException(
                BusinessErrorCode.PARSE_VERSION_NOT_CONFIRMED,
                "仅解析成功的版本才可确认",
                {"parse_status": parse_version.parse_status, "review_status": parse_version.review_status},
            )
        parse_version.review_status = REVIEW_STATUS_CONFIRMED
        self.repository.save(parse_version)
        self.session.commit()
        self.session.refresh(parse_version)
        return ParseVersionDetailResponse(**self.build_parse_version_response(parse_version).model_dump())

    def list_parse_pages(
        self,
        *,
        owner_user_id: int,
        parse_version_id: int,
        page: int,
        page_size: int,
    ) -> tuple[list[ParsePageResponse], int]:
        """分页查询解析页。"""
        parse_version = self.repository.get_parse_version_for_owner(parse_version_id, owner_user_id)
        if parse_version is None:
            raise AppException(BusinessErrorCode.PARSE_VERSION_NOT_FOUND, "解析版本不存在")
        offset = (page - 1) * page_size
        pages = self.repository.list_parse_pages(parse_version.id, offset, page_size)
        total_count = self.repository.count_parse_pages(parse_version.id)
        blocks = self.repository.list_blocks_by_page_ids([item.id for item in pages])
        blocks_by_page_id: dict[int, list] = {}
        for block in blocks:
            blocks_by_page_id.setdefault(block.parse_page_id, []).append(block)
        items = [
            ParsePageResponse(
                id=parse_page.id,
                parse_version_id=parse_page.parse_version_id,
                page_no=parse_page.page_no,
                source_page_image_file_id=parse_page.source_page_image_file_id,
                page_status=parse_page.page_status,
                has_issue=parse_page.has_issue,
                text_content=parse_page.text_content,
                markdown_content=parse_page.markdown_content,
                layout_json=parse_page.layout_json,
                blocks=[
                    ParseBlockResponse.model_validate(block, from_attributes=True)
                    for block in blocks_by_page_id.get(parse_page.id, [])
                ],
                created_at=parse_page.created_at,
                updated_at=parse_page.updated_at,
            )
            for parse_page in pages
        ]
        return items, total_count

    def list_parse_issues(
        self,
        *,
        owner_user_id: int,
        parse_version_id: int,
        page: int,
        page_size: int,
    ) -> tuple[list[ParseIssueResponse], int]:
        """分页查询解析异常。"""
        parse_version = self.repository.get_parse_version_for_owner(parse_version_id, owner_user_id)
        if parse_version is None:
            raise AppException(BusinessErrorCode.PARSE_VERSION_NOT_FOUND, "解析版本不存在")
        offset = (page - 1) * page_size
        issues = self.repository.list_parse_issues(parse_version.id, offset, page_size)
        total_count = self.repository.count_parse_issues(parse_version.id)
        return [ParseIssueResponse.model_validate(issue, from_attributes=True) for issue in issues], total_count

    def build_parse_version_response(self, parse_version) -> ParseVersionListItemResponse:
        """构造解析版本响应。"""
        return ParseVersionListItemResponse(
            id=parse_version.id,
            project_id=parse_version.project_id,
            textbook_version_id=parse_version.textbook_version_id,
            parent_parse_version_id=parse_version.parent_parse_version_id,
            version_no=parse_version.version_no,
            parse_mode=parse_version.parse_mode,
            page_range_text=parse_version.page_range_text,
            strategy_code=parse_version.strategy_code,
            mineru_model=parse_version.mineru_model,
            parse_status=parse_version.parse_status,
            review_status=parse_version.review_status,
            version_status=parse_version.version_status,
            page_count=parse_version.page_count,
            issue_count=self.repository.count_parse_issues(parse_version.id),
            source_markdown_file_id=parse_version.source_markdown_file_id,
            source_json_file_id=parse_version.source_json_file_id,
            asset_manifest_json=parse_version.asset_manifest_json,
            diff_json=parse_version.diff_json,
            error_summary=parse_version.error_summary,
            started_at=parse_version.started_at,
            finished_at=parse_version.finished_at,
            created_at=parse_version.created_at,
            updated_at=parse_version.updated_at,
        )

    def _create_task_record(
        self,
        *,
        owner_user_id: int,
        textbook_version_id: int,
        task_type: str,
        biz_key: str,
        payload_json: dict,
    ):
        textbook_version = self.repository.get_textbook_version_for_owner(textbook_version_id, owner_user_id)
        if textbook_version is None:
            raise AppException(BusinessErrorCode.TEXTBOOK_NOT_FOUND, "教材版本不存在")
        active_task = self.task_repository.get_active_task_by_biz_key(
            module_code=PARSING_MODULE_CODE,
            task_type=task_type,
            biz_key=biz_key,
        )
        if active_task is not None:
            raise AppException(BusinessErrorCode.TASK_CONFLICT, "当前已有运行中的解析任务")

        task = self.task_repository.create_task(
            project_id=textbook_version.project_id,
            module_code=PARSING_MODULE_CODE,
            task_type=task_type,
            task_status=TASK_STATUS_PENDING,
            queue_name=PARSING_QUEUE_NAME,
            biz_key=biz_key,
            operator_user_id=owner_user_id,
            payload_json=payload_json,
            request_id=get_request_id() or None,
        )
        step_names = [
            ("prepare_source", "准备源文件"),
            ("submit_mineru", "提交 MinerU 任务"),
            ("poll_mineru_result", "轮询 MinerU 结果"),
            ("persist_parse_result", "落库解析结果"),
        ]
        for step_order, (step_code, step_name) in enumerate(step_names, start=1):
            self.task_repository.create_task_step(
                task_record_id=task.id,
                step_code=step_code,
                step_name=step_name,
                step_order=step_order,
                step_status=TASK_STATUS_PENDING,
            )
        textbook_version.parse_status = "processing"
        self.repository.save(textbook_version)
        self.session.commit()
        return task

    def _build_page_draft_from_request(
        self,
        request_page: ParseManualRevisionPageRequest,
        base_page_map: dict[int, ParsePageDraft],
    ) -> ParsePageDraft:
        base_page = base_page_map.get(request_page.page_no)
        if base_page is None:
            raise AppException(
                BusinessErrorCode.INVALID_PAGE_RANGE,
                "人工修正页码不存在于当前解析版本",
                {"page_no": request_page.page_no},
            )
        block_drafts = [
            ParseBlockDraft(
                block_no=block.block_no,
                block_type=block.block_type,
                text_content=block.text_content,
                markdown_content=block.markdown_content,
                heading_level=block.heading_level,
                bbox_json=block.bbox_json,
                asset_file_id=block.asset_file_id,
                origin_ref_json=block.origin_ref_json,
                is_deleted=1 if block.is_deleted else 0,
            )
            for block in sorted(request_page.blocks, key=lambda item: item.block_no)
        ]
        return ParsePageDraft(
            page_no=request_page.page_no,
            page_status=request_page.page_status,
            text_content=request_page.text_content,
            markdown_content=request_page.markdown_content,
            layout_json=request_page.layout_json,
            source_page_image_file_id=base_page.source_page_image_file_id,
            blocks=block_drafts,
        )

    def _determine_new_version_status(self, textbook_version_id: int, set_as_current: bool) -> str:
        if set_as_current:
            return VERSION_STATUS_READY
        active_parse_version = self.repository.get_active_parse_version(textbook_version_id)
        return VERSION_STATUS_READY if active_parse_version is None else VERSION_STATUS_ARCHIVED

    def _upload_artifact_file(
        self,
        *,
        project_id: int,
        operator_user_id: int,
        textbook_version_id: int,
        version_no: int,
        filename: str,
        content: bytes,
        biz_type: str,
        mime_type: str,
    ) -> FileObject:
        object_key = self.storage_client.build_object_key(
            str(project_id),
            "parsing",
            f"textbook_{textbook_version_id}",
            f"version_{version_no}",
            filename=filename,
        )
        self.storage_client.upload_bytes(object_key, content, content_type=mime_type)
        file_object = FileObject(
            project_id=project_id,
            biz_type=biz_type,
            bucket_name=self.storage_client.settings.obs_bucket,
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
        self.repository.create_file_object(file_object)
        self.repository.save(file_object)
        return file_object
