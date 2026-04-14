"""
@Date: 2026-04-14
@Author: xisy
@Discription: 文件访问模块业务服务
"""

from app.core.config import get_settings
from app.core.exceptions import AppException, BusinessErrorCode
from app.modules.file_asset.repository import FileAssetRepository
from app.modules.file_asset.schemas import FileDownloadUrlResponse
from app.shared.storage import ObsStorageClient
from app.shared.utils import DateTimeUtil


class FileAssetService:
    """文件访问模块服务。"""

    def __init__(
        self,
        repository: FileAssetRepository,
        storage_client: ObsStorageClient | None = None,
    ) -> None:
        self.repository = repository
        self.storage_client = storage_client or ObsStorageClient()
        self.settings = get_settings()

    def get_download_url(self, *, owner_user_id: int, file_object_id: int) -> FileDownloadUrlResponse:
        """获取文件签名下载地址。"""
        file_object = self.repository.get_file_object_for_owner(file_object_id, owner_user_id)
        if file_object is None:
            raise AppException(BusinessErrorCode.FILE_NOT_FOUND, "文件不存在")
        try:
            signed_url = self.storage_client.create_download_signed_url(file_object.object_key)
        except Exception as exc:  # noqa: BLE001
            raise AppException(
                BusinessErrorCode.EXTERNAL_SERVICE_ERROR,
                "生成文件下载地址失败",
                {"file_object_id": file_object_id, "error": str(exc)},
            ) from exc
        return FileDownloadUrlResponse(
            file_object_id=file_object.id,
            bucket_name=file_object.bucket_name,
            object_key=file_object.object_key,
            signed_url=signed_url,
            expires_in_seconds=self.settings.obs_signed_url_expire_seconds,
            generated_at=DateTimeUtil.now_utc(),
        )
