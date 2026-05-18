"""
@Date: 2026-05-17
@Author: xisy
@Discription: 证据图片加载器，将 OBS 图片资产编码为 data URL 供多模态 LLM 使用
"""

import base64

import structlog

from app.shared.storage import ObsStorageClient

logger = structlog.get_logger(__name__)

_EXT_MIME_MAP = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "gif": "image/gif",
    "bmp": "image/bmp",
}
_DEFAULT_IMAGE_MIME = "image/png"


def _resolve_mime_type(mime_type: str | None, file_ext: str | None) -> str:
    """优先用 file_object.mime_type，缺失时按扩展名兜底。"""
    if mime_type and mime_type.startswith("image/"):
        return mime_type
    if file_ext:
        normalized_ext = file_ext.lstrip(".").lower()
        if normalized_ext in _EXT_MIME_MAP:
            return _EXT_MIME_MAP[normalized_ext]
    return _DEFAULT_IMAGE_MIME


def load_evidence_image_data_urls(
    *,
    assets: list[tuple[int, str, str | None, str | None]],
    max_images: int,
    storage_client: ObsStorageClient | None = None,
) -> list[str]:
    """把证据图片资产编码为 data URL 列表。

    assets 元素为 (file_object_id, object_key, mime_type, file_ext)。按 file_object_id
    去重并保留原始顺序，截断到 max_images，再逐个从 OBS 拉取并 base64 编码为
    ``data:{mime};base64,{...}``。单图失败仅记 warning 并跳过，不阻断教案生成。
    """
    if max_images <= 0 or not assets:
        return []

    seen_file_ids: set[int] = set()
    deduped: list[tuple[str, str | None, str | None]] = []
    for file_object_id, object_key, mime_type, file_ext in assets:
        if file_object_id in seen_file_ids:
            continue
        seen_file_ids.add(file_object_id)
        deduped.append((object_key, mime_type, file_ext))
        if len(deduped) >= max_images:
            break

    client = storage_client or ObsStorageClient()
    data_urls: list[str] = []
    for object_key, mime_type, file_ext in deduped:
        try:
            content = client.download_bytes(object_key)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "evidence_image_download_failed",
                object_key=object_key,
                error=str(exc),
            )
            continue
        if not content:
            logger.warning("evidence_image_empty", object_key=object_key)
            continue
        resolved_mime = _resolve_mime_type(mime_type, file_ext)
        encoded = base64.b64encode(content).decode("ascii")
        data_urls.append(f"data:{resolved_mime};base64,{encoded}")
    return data_urls
