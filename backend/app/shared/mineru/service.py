"""
@Date: 2026-04-14
@Author: xisy
@Discription: MinerU 文档解析服务与结果归一化
"""

import io
import json
from pathlib import PurePosixPath
from typing import Any
from zipfile import ZipFile

from app.core.config import Settings, get_settings
from app.core.constants import (
    MINERU_STRATEGY_DOC_DEFAULT,
    MINERU_STRATEGY_VLM_DEFAULT,
    MINERU_STRATEGY_VLM_OCR,
    SUPPORTED_MINERU_STRATEGIES,
)
from app.core.exceptions import AppException, BusinessErrorCode
from app.shared.mineru.client import MineruClient
from app.shared.mineru.schemas import NormalizedBlock, NormalizedDocument, NormalizedPage


class MineruDocumentService:
    """封装上传、轮询、下载和结果归一化的一体化服务。"""

    def __init__(self, client: MineruClient | None = None, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.client = client or MineruClient(self.settings)

    def parse_document(
        self,
        *,
        file_name: str,
        content: bytes,
        strategy_code: str,
        data_id: str,
        language: str | None = None,
    ) -> NormalizedDocument:
        """执行文档解析并返回归一化结果。"""
        strategy = self.resolve_strategy(strategy_code)
        upload_batch = self.client.request_upload_urls(
            files=[
                {
                    "name": file_name,
                    "data_id": data_id,
                    "is_ocr": strategy["is_ocr"],
                }
            ],
            model_version=strategy["model_version"],
            language=language or self.settings.mineru_default_language,
            enable_formula=strategy["enable_formula"],
            enable_table=strategy["enable_table"],
        )
        self.client.upload_file(upload_batch.file_urls[0], content)
        batch_result = self.client.poll_batch_result(batch_id=upload_batch.batch_id, data_id=data_id, file_name=file_name)
        full_zip_bytes = self.client.download_full_zip(batch_result.full_zip_url or "")
        return self.normalize_zip_payload(
            batch_id=upload_batch.batch_id,
            file_name=file_name,
            data_id=data_id,
            model_version=strategy["model_version"],
            full_zip_bytes=full_zip_bytes,
        )

    @staticmethod
    def resolve_strategy(strategy_code: str) -> dict[str, Any]:
        """将策略编码映射为 MinerU 请求参数。"""
        if strategy_code not in SUPPORTED_MINERU_STRATEGIES:
            raise AppException(
                BusinessErrorCode.INVALID_PARSE_STRATEGY,
                "不支持的解析策略编码",
                {"strategy_code": strategy_code},
            )
        strategy_mapping = {
            MINERU_STRATEGY_VLM_DEFAULT: {
                "model_version": "vlm",
                "is_ocr": False,
                "enable_formula": True,
                "enable_table": True,
            },
            MINERU_STRATEGY_VLM_OCR: {
                "model_version": "vlm",
                "is_ocr": True,
                "enable_formula": True,
                "enable_table": True,
            },
            MINERU_STRATEGY_DOC_DEFAULT: {
                "model_version": "vlm",
                "is_ocr": False,
                "enable_formula": False,
                "enable_table": True,
            },
        }
        return strategy_mapping[strategy_code]

    def normalize_zip_payload(
        self,
        *,
        batch_id: str,
        file_name: str,
        data_id: str | None,
        model_version: str,
        full_zip_bytes: bytes,
    ) -> NormalizedDocument:
        """解压 MinerU 结果并归一化为后端结构。"""
        with ZipFile(io.BytesIO(full_zip_bytes)) as archive:
            file_names = archive.namelist()
            markdown_name = self._find_archive_member(file_names, "full.md")
            content_list_name = self._find_archive_member(file_names, "content_list.json") or self._find_archive_member(file_names, "content_list_v2.json")
            if markdown_name is None or content_list_name is None:
                raise AppException(
                    BusinessErrorCode.MINERU_RESULT_INVALID,
                    "MinerU 结果压缩包缺少必要产物",
                    {"file_name": file_name, "archive_files": file_names},
                )

            markdown_text = archive.read(markdown_name).decode("utf-8", errors="ignore")
            content_list_json = json.loads(archive.read(content_list_name).decode("utf-8", errors="ignore"))
            raw_blocks = self._normalize_content_list(content_list_json)
            root_prefix = self._detect_root_prefix(markdown_name, content_list_name)
            asset_files: dict[str, bytes] = {}
            for entry in file_names:
                if entry.endswith("/") or entry in {markdown_name, content_list_name}:
                    continue
                relative_path = self._normalize_relative_path(entry, root_prefix)
                asset_files[relative_path] = archive.read(entry)

        pages = self._build_pages(raw_blocks)
        return NormalizedDocument(
            batch_id=batch_id,
            file_name=file_name,
            data_id=data_id,
            model_version=model_version,
            markdown_text=markdown_text,
            content_list_json=raw_blocks,
            pages=pages,
            full_zip_bytes=full_zip_bytes,
            asset_files=asset_files,
            raw_metadata={
                "markdown_archive_path": markdown_name,
                "content_list_archive_path": content_list_name,
                "asset_relative_paths": sorted(asset_files),
            },
        )

    @staticmethod
    def _find_archive_member(file_names: list[str], suffix: str) -> str | None:
        for item in file_names:
            if item.endswith(suffix):
                return item
        return None

    @staticmethod
    def _detect_root_prefix(markdown_name: str, content_list_name: str) -> tuple[str, ...]:
        markdown_parts = PurePosixPath(markdown_name).parts
        content_parts = PurePosixPath(content_list_name).parts
        shared_parts: list[str] = []
        for markdown_part, content_part in zip(markdown_parts[:-1], content_parts[:-1], strict=False):
            if markdown_part != content_part:
                break
            shared_parts.append(markdown_part)
        return tuple(shared_parts)

    @staticmethod
    def _normalize_relative_path(archive_path: str, root_prefix: tuple[str, ...]) -> str:
        parts = PurePosixPath(archive_path).parts
        if root_prefix and parts[: len(root_prefix)] == root_prefix:
            return str(PurePosixPath(*parts[len(root_prefix) :]))
        return str(PurePosixPath(*parts))

    @staticmethod
    def _normalize_content_list(content_list_payload: Any) -> list[dict[str, Any]]:
        if isinstance(content_list_payload, list):
            normalized_items: list[dict[str, Any]] = []
            for item in content_list_payload:
                if isinstance(item, dict):
                    normalized_items.append(item)
                elif isinstance(item, list):
                    normalized_items.extend(sub_item for sub_item in item if isinstance(sub_item, dict))
            return normalized_items
        if isinstance(content_list_payload, dict):
            for key in ("content_list", "items", "data"):
                value = content_list_payload.get(key)
                if isinstance(value, list):
                    return [item for item in value if isinstance(item, dict)]
        raise AppException(
            BusinessErrorCode.MINERU_RESULT_INVALID,
            "MinerU content_list.json 结构非法",
            {"payload_type": type(content_list_payload).__name__},
        )

    def _build_pages(self, raw_blocks: list[dict[str, Any]]) -> list[NormalizedPage]:
        blocks_by_page: dict[int, list[NormalizedBlock]] = {}
        raw_items_by_page: dict[int, list[dict[str, Any]]] = {}
        for item in raw_blocks:
            page_no = self._extract_page_no(item)
            block_list = blocks_by_page.setdefault(page_no, [])
            block_no = len(block_list) + 1
            normalized_block = NormalizedBlock(
                page_no=page_no,
                block_no=block_no,
                block_type=self._extract_block_type(item),
                text_content=self._extract_text_content(item),
                markdown_content=self._extract_markdown_content(item),
                heading_level=self._extract_heading_level(item),
                bbox_json=self._extract_bbox(item),
                asset_relative_path=self._extract_asset_path(item),
                origin_ref_json=item,
            )
            block_list.append(normalized_block)
            raw_items_by_page.setdefault(page_no, []).append(item)

        pages: list[NormalizedPage] = []
        for page_no in sorted(blocks_by_page):
            page_blocks = blocks_by_page[page_no]
            page_text_parts = [item.text_content.strip() for item in page_blocks if item.text_content and item.text_content.strip()]
            page_md_parts = [
                item.markdown_content.strip()
                for item in page_blocks
                if item.markdown_content and item.markdown_content.strip()
            ]
            pages.append(
                NormalizedPage(
                    page_no=page_no,
                    text_content="\n\n".join(page_text_parts) if page_text_parts else None,
                    markdown_content="\n\n".join(page_md_parts) if page_md_parts else None,
                    layout_json={"raw_items": raw_items_by_page.get(page_no, [])},
                    blocks=page_blocks,
                )
            )
        return pages

    @staticmethod
    def _extract_page_no(item: dict[str, Any]) -> int:
        for key in ("page_no", "page_num"):
            value = item.get(key)
            if isinstance(value, int) and value > 0:
                return value
        page_idx = item.get("page_idx")
        if isinstance(page_idx, int):
            return page_idx + 1
        return 1

    @staticmethod
    def _extract_block_type(item: dict[str, Any]) -> str:
        for key in ("block_type", "type", "category_type"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip().lower().replace(" ", "_")
        return "paragraph"

    @staticmethod
    def _extract_text_content(item: dict[str, Any]) -> str | None:
        for key in ("text", "content", "latex", "caption", "html"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        for key in ("text", "content"):
            value = item.get("text_block", {}).get(key) if isinstance(item.get("text_block"), dict) else None
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    @classmethod
    def _extract_markdown_content(cls, item: dict[str, Any]) -> str | None:
        for key in ("markdown", "md_content", "markdown_content"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return cls._extract_text_content(item)

    @staticmethod
    def _extract_heading_level(item: dict[str, Any]) -> int | None:
        for key in ("heading_level", "level", "title_level"):
            value = item.get(key)
            if isinstance(value, int):
                return value
        return None

    @staticmethod
    def _extract_bbox(item: dict[str, Any]) -> dict[str, Any] | None:
        for key in ("bbox", "box", "position", "poly"):
            value = item.get(key)
            if isinstance(value, dict):
                return value
            if isinstance(value, list):
                return {"points": value}
        return None

    @staticmethod
    def _extract_asset_path(item: dict[str, Any]) -> str | None:
        for key in ("asset_path", "image_path", "img_path", "path", "file_path", "resource_path"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip().lstrip("/")
        return None
