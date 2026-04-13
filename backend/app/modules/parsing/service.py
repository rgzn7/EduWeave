"""
@Date: 2026-04-13
@Author: xisy
@Discription: 解析模块业务服务
"""

from sqlalchemy.orm import Session

from app.core.constants import PARSE_MODE_FULL, PARSING_MODULE_CODE, PARSING_QUEUE_NAME, TASK_STATUS_PENDING, TEXTBOOK_PARSE_TASK_TYPE
from app.core.exceptions import AppException, BusinessErrorCode
from app.core.middleware import get_request_id
from app.modules.parsing.repository import ParsingRepository
from app.modules.parsing.schemas import (
    ParseBlockResponse,
    ParseIssueResponse,
    ParsePageResponse,
    ParseTaskCreateRequest,
    ParseVersionDetailResponse,
    ParseVersionListItemResponse,
)
from app.modules.task_center.repository import TaskCenterRepository
from app.modules.task_center.schemas import TaskListItemResponse
from app.modules.task_center.service import TaskCenterService
from app.shared.queue import dispatch_task
from app.shared.utils.datetime_util import DateTimeUtil


class ParsingService:
    """解析模块服务。"""

    def __init__(self, session: Session, repository: ParsingRepository | None = None) -> None:
        self.session = session
        self.repository = repository or ParsingRepository(session)
        self.task_repository = TaskCenterRepository(session)

    def create_parse_task(
        self,
        *,
        owner_user_id: int,
        textbook_version_id: int,
        request: ParseTaskCreateRequest,
    ) -> TaskListItemResponse:
        """创建解析任务。"""
        if request.parse_mode != PARSE_MODE_FULL:
            raise AppException(BusinessErrorCode.PROJECT_REFERENCE_INVALID, "当前仅支持 full 全量解析模式")
        textbook_version = self.repository.get_textbook_version_for_owner(textbook_version_id, owner_user_id)
        if textbook_version is None:
            raise AppException(BusinessErrorCode.TEXTBOOK_NOT_FOUND, "教材版本不存在")

        biz_key = f"textbook_version:{textbook_version.id}:{request.parse_mode}"
        active_task = self.task_repository.get_active_task_by_biz_key(
            module_code=PARSING_MODULE_CODE,
            task_type=TEXTBOOK_PARSE_TASK_TYPE,
            biz_key=biz_key,
        )
        if active_task is not None:
            raise AppException(BusinessErrorCode.TASK_CONFLICT, "当前教材已有运行中的解析任务")

        task = self.task_repository.create_task(
            project_id=textbook_version.project_id,
            module_code=PARSING_MODULE_CODE,
            task_type=TEXTBOOK_PARSE_TASK_TYPE,
            task_status=TASK_STATUS_PENDING,
            queue_name=PARSING_QUEUE_NAME,
            biz_key=biz_key,
            operator_user_id=owner_user_id,
            payload_json={
                "project_id": textbook_version.project_id,
                "textbook_version_id": textbook_version.id,
                "parse_mode": request.parse_mode,
                "strategy_code": request.strategy_code,
                "set_as_current_on_success": request.set_as_current_on_success,
            },
            request_id=get_request_id() or None,
        )
        self.task_repository.create_task_step(
            task_record_id=task.id,
            step_code="extract_textbook",
            step_name="解析教材文本",
            step_order=1,
            step_status=TASK_STATUS_PENDING,
        )
        textbook_version.parse_status = "processing"
        self.repository.save(textbook_version)
        self.session.commit()

        dispatch_result = dispatch_task(
            "app.modules.parsing.tasks.run_placeholder_parse_task",
            {
                "task_record_id": task.id,
                "project_id": textbook_version.project_id,
                "textbook_version_id": textbook_version.id,
                "operator_user_id": owner_user_id,
                "database_url": self.session.get_bind().url.render_as_string(hide_password=False),
                "parse_mode": request.parse_mode,
                "strategy_code": request.strategy_code,
                "set_as_current_on_success": request.set_as_current_on_success,
            },
        )
        if dispatch_result.worker_task_id:
            task.worker_task_id = dispatch_result.worker_task_id
            self.task_repository.save(task)
            self.session.commit()

        self.session.expire_all()
        fresh_task = self.task_repository.get_task_by_id(task.id)
        return TaskCenterService.build_task_list_item(fresh_task)

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
            asset_manifest_json=parse_version.asset_manifest_json,
            diff_json=parse_version.diff_json,
            error_summary=parse_version.error_summary,
            started_at=parse_version.started_at,
            finished_at=parse_version.finished_at,
            created_at=parse_version.created_at,
            updated_at=parse_version.updated_at,
        )
