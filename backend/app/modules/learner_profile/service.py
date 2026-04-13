"""
@Date: 2026-04-13
@Author: xisy
@Discription: 学情模块业务服务
"""

import hashlib
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.constants import (
    LEARNER_PROFILE_MODULE_CODE,
    LEARNER_PROFILE_SOURCE_BIZ_TYPE,
    PROFILE_EXTRACT_TASK_TYPE,
    PROFILE_QUEUE_NAME,
    TASK_STATUS_PENDING,
)
from app.core.exceptions import AppException, BusinessErrorCode
from app.core.middleware import get_request_id
from app.modules.learner_profile.repository import LearnerProfileRepository
from app.modules.learner_profile.schemas import (
    LearnerProfileFileDetailResponse,
    LearnerProfileFileListItemResponse,
    LearnerProfileRecordResponse,
    LearnerProfileVersionResponse,
)
from app.modules.p0_models import FileObject, LearnerProfileFile
from app.modules.task_center.repository import TaskCenterRepository
from app.modules.textbook.schemas import FileObjectSummaryResponse
from app.shared.queue import dispatch_task
from app.shared.storage import ObsStorageClient
from app.shared.utils.datetime_util import DateTimeUtil


class LearnerProfileService:
    """学情模块服务。"""

    def __init__(
        self,
        session: Session,
        repository: LearnerProfileRepository | None = None,
        storage_client: ObsStorageClient | None = None,
    ) -> None:
        self.session = session
        self.repository = repository or LearnerProfileRepository(session)
        self.storage_client = storage_client or ObsStorageClient()
        self.task_repository = TaskCenterRepository(session)

    def upload_profile_file(
        self,
        *,
        owner_user_id: int,
        project_id: int,
        filename: str,
        content: bytes,
        content_type: str | None,
        title: str | None,
        grade_code: str | None,
        subject_scope: str | None,
        textbook_version_hint_id: int | None,
        auto_extract: bool,
        set_as_current: bool,
    ) -> LearnerProfileFileDetailResponse:
        """上传学情文件。"""
        project = self.repository.get_project_by_id_for_owner(project_id, owner_user_id)
        if project is None:
            raise AppException(BusinessErrorCode.PROJECT_NOT_FOUND, "项目不存在")

        file_ext = Path(filename).suffix.lower()
        if file_ext not in {".doc", ".docx"}:
            raise AppException(BusinessErrorCode.INVALID_FILE_TYPE, "学情文件仅支持 doc 或 docx")
        if not content:
            raise AppException(BusinessErrorCode.INVALID_FILE_TYPE, "学情文件不能为空")
        if textbook_version_hint_id is not None:
            textbook_hint = self.repository.get_textbook_version_in_project(project.id, textbook_version_hint_id)
            if textbook_hint is None:
                raise AppException(BusinessErrorCode.PROJECT_REFERENCE_INVALID, "教材提示版本不属于当前项目")

        file_hash = hashlib.sha256(content).hexdigest()
        object_key = self.storage_client.build_object_key(
            str(project.id),
            "learner_profiles",
            filename=filename,
        )
        try:
            self.storage_client.upload_bytes(object_key, content, content_type=content_type)
        except Exception as exc:  # noqa: BLE001
            raise AppException(BusinessErrorCode.FILE_UPLOAD_FAILED, "学情文件上传失败", {"error": str(exc)}) from exc

        profile_file = LearnerProfileFile(
            project_id=project.id,
            source_file_id=0,
            title=title or Path(filename).stem,
            file_status="processing" if auto_extract else "uploaded",
            uploaded_by=owner_user_id,
        )
        try:
            file_object = FileObject(
                project_id=project.id,
                biz_type=LEARNER_PROFILE_SOURCE_BIZ_TYPE,
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
            self.repository.create_file_object(file_object)
            profile_file.source_file_id = file_object.id
            self.repository.create_profile_file(profile_file)

            if auto_extract:
                task = self.task_repository.create_task(
                    project_id=project.id,
                    module_code=LEARNER_PROFILE_MODULE_CODE,
                    task_type=PROFILE_EXTRACT_TASK_TYPE,
                    task_status=TASK_STATUS_PENDING,
                    queue_name=PROFILE_QUEUE_NAME,
                    biz_key=f"profile_file:{profile_file.id}:extract",
                    operator_user_id=owner_user_id,
                    payload_json={
                        "project_id": project.id,
                        "profile_file_id": profile_file.id,
                        "title": profile_file.title,
                        "grade_code": grade_code,
                        "subject_scope": subject_scope,
                        "textbook_version_hint_id": textbook_version_hint_id,
                        "set_as_current": set_as_current,
                    },
                    request_id=get_request_id() or None,
                )
                self.task_repository.create_task_step(
                    task_record_id=task.id,
                    step_code="extract_profile",
                    step_name="抽取学情占位结果",
                    step_order=1,
                    step_status=TASK_STATUS_PENDING,
                )

            project.last_activity_at = DateTimeUtil.now_utc()
            self.repository.save(project)
            self.session.commit()
        except Exception:  # noqa: BLE001
            self.session.rollback()
            self.storage_client.delete_object(object_key)
            raise

        if auto_extract:
            dispatch_result = dispatch_task(
                "app.modules.learner_profile.tasks.run_placeholder_extract_task",
                {
                    "task_record_id": task.id,
                    "project_id": project.id,
                    "profile_file_id": profile_file.id,
                    "operator_user_id": owner_user_id,
                    "database_url": self.session.get_bind().url.render_as_string(hide_password=False),
                    "title": profile_file.title,
                    "grade_code": grade_code,
                    "subject_scope": subject_scope,
                    "textbook_version_hint_id": textbook_version_hint_id,
                    "set_as_current": set_as_current,
                },
            )
            if dispatch_result.worker_task_id:
                task.worker_task_id = dispatch_result.worker_task_id
                self.task_repository.save(task)
                self.session.commit()

        return self.get_profile_file_detail(owner_user_id=owner_user_id, project_id=project.id, profile_file_id=profile_file.id)

    def list_profile_files(
        self,
        *,
        owner_user_id: int,
        project_id: int,
        page: int,
        page_size: int,
    ) -> tuple[list[LearnerProfileFileListItemResponse], int]:
        """分页查询学情文件列表。"""
        project = self.repository.get_project_by_id_for_owner(project_id, owner_user_id)
        if project is None:
            raise AppException(BusinessErrorCode.PROJECT_NOT_FOUND, "项目不存在")
        offset = (page - 1) * page_size
        files = self.repository.list_profile_files(project.id, offset, page_size)
        total_count = self.repository.count_profile_files(project.id)
        items = [self.build_profile_file_response(item) for item in files]
        return items, total_count

    def get_profile_file_detail(
        self,
        *,
        owner_user_id: int,
        project_id: int,
        profile_file_id: int,
    ) -> LearnerProfileFileDetailResponse:
        """查询学情文件详情。"""
        project = self.repository.get_project_by_id_for_owner(project_id, owner_user_id)
        if project is None:
            raise AppException(BusinessErrorCode.PROJECT_NOT_FOUND, "项目不存在")
        profile_file = self.repository.get_profile_file(project.id, profile_file_id)
        if profile_file is None:
            raise AppException(BusinessErrorCode.LEARNER_PROFILE_NOT_FOUND, "学情文件不存在")
        return self.build_profile_file_response(profile_file)

    def get_profile_version_detail(self, *, owner_user_id: int, profile_version_id: int) -> LearnerProfileVersionResponse:
        """查询学情版本详情。"""
        profile_version = self.repository.get_profile_version_for_owner(profile_version_id, owner_user_id)
        if profile_version is None:
            raise AppException(BusinessErrorCode.LEARNER_PROFILE_NOT_FOUND, "学情版本不存在")
        return self.build_profile_version_response(profile_version)

    def build_profile_file_response(self, profile_file: LearnerProfileFile) -> LearnerProfileFileDetailResponse:
        """构造学情文件响应。"""
        file_object = self.repository.get_file_object(profile_file.source_file_id)
        if file_object is None:
            raise AppException(BusinessErrorCode.LEARNER_PROFILE_NOT_FOUND, "学情源文件不存在")
        latest_version = self.repository.get_latest_profile_version(profile_file.id)
        return LearnerProfileFileDetailResponse(
            id=profile_file.id,
            project_id=profile_file.project_id,
            source_file_id=profile_file.source_file_id,
            title=profile_file.title,
            file_status=profile_file.file_status,
            source_file=FileObjectSummaryResponse.model_validate(file_object, from_attributes=True),
            latest_version=self.build_profile_version_response(latest_version) if latest_version else None,
            created_at=profile_file.created_at,
            updated_at=profile_file.updated_at,
        )

    def build_profile_version_response(self, profile_version) -> LearnerProfileVersionResponse:
        """构造学情版本响应。"""
        records = self.repository.list_profile_records(profile_version.id)
        return LearnerProfileVersionResponse(
            id=profile_version.id,
            project_id=profile_version.project_id,
            profile_file_id=profile_version.profile_file_id,
            parent_version_id=profile_version.parent_version_id,
            version_no=profile_version.version_no,
            textbook_version_hint_id=profile_version.textbook_version_hint_id,
            grade_code=profile_version.grade_code,
            subject_scope=profile_version.subject_scope,
            extract_status=profile_version.extract_status,
            review_status=profile_version.review_status,
            version_status=profile_version.version_status,
            summary_text=profile_version.summary_text,
            raw_result_json=profile_version.raw_result_json,
            source_snapshot_json=profile_version.source_snapshot_json,
            created_by=profile_version.created_by,
            records=[LearnerProfileRecordResponse.model_validate(record, from_attributes=True) for record in records],
            created_at=profile_version.created_at,
            updated_at=profile_version.updated_at,
        )
