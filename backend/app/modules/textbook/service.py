"""
@Date: 2026-04-13
@Author: xisy
@Discription: 教材模块业务服务
"""

import hashlib
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader
from sqlalchemy.orm import Session

from app.core.constants import TEXTBOOK_SOURCE_BIZ_TYPE
from app.core.exceptions import AppException, BusinessErrorCode
from app.modules.p0_models import FileObject, TextbookVersion
from app.modules.textbook.repository import TextbookRepository
from app.modules.textbook.schemas import (
    FileObjectSummaryResponse,
    TextbookVersionDetailResponse,
    TextbookVersionListItemResponse,
)
from app.shared.storage import ObsStorageClient
from app.shared.utils.datetime_util import DateTimeUtil


class TextbookService:
    """教材模块服务。"""

    def __init__(
        self,
        session: Session,
        repository: TextbookRepository | None = None,
        storage_client: ObsStorageClient | None = None,
    ) -> None:
        self.session = session
        self.repository = repository or TextbookRepository(session)
        self.storage_client = storage_client or ObsStorageClient()

    def upload_textbook(
        self,
        *,
        owner_user_id: int,
        project_id: int,
        filename: str,
        content: bytes,
        content_type: str | None,
        textbook_name: str | None,
        publisher: str | None,
        subject_code: str | None,
        grade_code: str | None,
        volume_code: str | None,
        edition_label: str | None,
        isbn: str | None,
        remark: str | None,
        set_as_current: bool,
    ) -> TextbookVersionDetailResponse:
        """上传教材并创建版本。"""
        project = self.repository.get_project_by_id_for_owner(project_id, owner_user_id)
        if project is None:
            raise AppException(BusinessErrorCode.PROJECT_NOT_FOUND, "项目不存在")

        file_ext = Path(filename).suffix.lower()
        if file_ext != ".pdf":
            raise AppException(BusinessErrorCode.INVALID_FILE_TYPE, "教材文件仅支持 PDF")
        if not content:
            raise AppException(BusinessErrorCode.INVALID_FILE_TYPE, "教材文件不能为空")

        version_no = self.repository.get_next_version_no(project.id)
        file_hash = hashlib.sha256(content).hexdigest()
        object_key = self.storage_client.build_object_key(
            str(project.id),
            "textbooks",
            str(version_no),
            filename=filename,
        )
        try:
            self.storage_client.upload_bytes(object_key, content, content_type=content_type)
        except Exception as exc:  # noqa: BLE001
            raise AppException(BusinessErrorCode.FILE_UPLOAD_FAILED, "教材文件上传失败", {"error": str(exc)}) from exc

        file_object = FileObject(
            project_id=project.id,
            biz_type=TEXTBOOK_SOURCE_BIZ_TYPE,
            bucket_name=self.storage_client.settings.obs_bucket,
            object_key=object_key,
            original_filename=filename,
            file_ext=file_ext,
            mime_type=content_type,
            file_size=len(content),
            content_hash=file_hash,
            source_type="user_upload",
            upload_status="uploaded",
            uploaded_by=owner_user_id,
        )
        try:
            self.repository.create_file_object(file_object)
            textbook_version = TextbookVersion(
                project_id=project.id,
                source_file_id=file_object.id,
                version_no=version_no,
                textbook_name=textbook_name or Path(filename).stem,
                publisher=publisher,
                subject_code=subject_code or project.subject_code,
                grade_code=grade_code or project.grade_code,
                volume_code=volume_code,
                edition_label=edition_label,
                isbn=isbn,
                file_hash=file_hash,
                page_count=self._detect_page_count(content),
                parse_status="pending",
                version_status="ready",
                auto_identify_json={"source": "manual_or_filename", "filename": filename},
                remark=remark,
                uploaded_by=owner_user_id,
            )
            self.repository.create_textbook_version(textbook_version)
            if project.current_textbook_version_id is None or set_as_current:
                project.current_textbook_version_id = textbook_version.id
            project.last_activity_at = DateTimeUtil.now_utc()
            self.repository.save(project)
            self.session.commit()
            self.session.refresh(textbook_version)
            self.session.refresh(file_object)
            self.session.refresh(project)
        except Exception:  # noqa: BLE001
            self.session.rollback()
            self.storage_client.delete_object(object_key)
            raise

        return self.build_textbook_detail(textbook_version, project.current_textbook_version_id)

    def list_textbooks(
        self,
        *,
        owner_user_id: int,
        project_id: int,
        page: int,
        page_size: int,
    ) -> tuple[list[TextbookVersionListItemResponse], int]:
        """分页查询教材版本列表。"""
        project = self.repository.get_project_by_id_for_owner(project_id, owner_user_id)
        if project is None:
            raise AppException(BusinessErrorCode.PROJECT_NOT_FOUND, "项目不存在")
        offset = (page - 1) * page_size
        textbooks = self.repository.list_textbook_versions(project.id, offset, page_size)
        total_count = self.repository.count_textbook_versions(project.id)
        items = [self.build_textbook_item(item, project.current_textbook_version_id) for item in textbooks]
        return items, total_count

    def get_textbook_detail(
        self,
        *,
        owner_user_id: int,
        project_id: int,
        textbook_version_id: int,
    ) -> TextbookVersionDetailResponse:
        """查询教材版本详情。"""
        project = self.repository.get_project_by_id_for_owner(project_id, owner_user_id)
        if project is None:
            raise AppException(BusinessErrorCode.PROJECT_NOT_FOUND, "项目不存在")
        textbook_version = self.repository.get_textbook_version(project.id, textbook_version_id)
        if textbook_version is None:
            raise AppException(BusinessErrorCode.TEXTBOOK_NOT_FOUND, "教材版本不存在")
        return self.build_textbook_detail(textbook_version, project.current_textbook_version_id)

    def build_textbook_item(
        self,
        textbook_version: TextbookVersion,
        current_textbook_version_id: int | None,
    ) -> TextbookVersionListItemResponse:
        """构造教材版本列表项。"""
        file_object = self.repository.get_file_object(textbook_version.source_file_id)
        if file_object is None:
            raise AppException(BusinessErrorCode.TEXTBOOK_NOT_FOUND, "教材源文件不存在")
        return TextbookVersionListItemResponse(
            id=textbook_version.id,
            project_id=textbook_version.project_id,
            version_no=textbook_version.version_no,
            textbook_name=textbook_version.textbook_name,
            publisher=textbook_version.publisher,
            subject_code=textbook_version.subject_code,
            grade_code=textbook_version.grade_code,
            volume_code=textbook_version.volume_code,
            edition_label=textbook_version.edition_label,
            isbn=textbook_version.isbn,
            page_count=textbook_version.page_count,
            parse_status=textbook_version.parse_status,
            version_status=textbook_version.version_status,
            remark=textbook_version.remark,
            is_current=textbook_version.id == current_textbook_version_id,
            source_file=FileObjectSummaryResponse.model_validate(file_object, from_attributes=True),
            created_at=textbook_version.created_at,
            updated_at=textbook_version.updated_at,
        )

    def build_textbook_detail(
        self,
        textbook_version: TextbookVersion,
        current_textbook_version_id: int | None,
    ) -> TextbookVersionDetailResponse:
        """构造教材版本详情。"""
        file_object = self.repository.get_file_object(textbook_version.source_file_id)
        if file_object is None:
            raise AppException(BusinessErrorCode.TEXTBOOK_NOT_FOUND, "教材源文件不存在")
        return TextbookVersionDetailResponse(
            id=textbook_version.id,
            project_id=textbook_version.project_id,
            version_no=textbook_version.version_no,
            textbook_name=textbook_version.textbook_name,
            publisher=textbook_version.publisher,
            subject_code=textbook_version.subject_code,
            grade_code=textbook_version.grade_code,
            volume_code=textbook_version.volume_code,
            edition_label=textbook_version.edition_label,
            isbn=textbook_version.isbn,
            page_count=textbook_version.page_count,
            parse_status=textbook_version.parse_status,
            version_status=textbook_version.version_status,
            remark=textbook_version.remark,
            auto_identify_json=textbook_version.auto_identify_json,
            is_current=textbook_version.id == current_textbook_version_id,
            source_file=FileObjectSummaryResponse.model_validate(file_object, from_attributes=True),
            created_at=textbook_version.created_at,
            updated_at=textbook_version.updated_at,
        )

    @staticmethod
    def _detect_page_count(content: bytes) -> int | None:
        """检测 PDF 页数。"""
        try:
            reader = PdfReader(BytesIO(content))
            return len(reader.pages)
        except Exception:  # noqa: BLE001
            return None
