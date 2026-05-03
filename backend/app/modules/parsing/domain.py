"""
@Date: 2026-04-30
@Author: xisy
@Discription: 解析模块版本构建与快照辅助能力
"""

import io
import json
from dataclasses import dataclass, field
from typing import Any

from app.core.logging import get_logger
from app.modules.parsing.repository import ParsingRepository
from app.shared.mineru import NormalizedDocument

logger = get_logger(__name__)


@dataclass(slots=True)
class ParseBlockDraft:
    """待持久化的解析块草稿。"""

    block_no: int
    block_type: str
    text_content: str | None
    markdown_content: str | None
    heading_level: int | None = None
    bbox_json: dict[str, Any] | None = None
    asset_file_id: int | None = None
    origin_ref_json: dict[str, Any] | None = None
    is_deleted: int = 0


@dataclass(slots=True)
class ParsePageDraft:
    """待持久化的解析页草稿。"""

    page_no: int
    page_status: str
    text_content: str | None
    markdown_content: str | None
    layout_json: dict[str, Any] | None
    source_page_image_file_id: int | None = None
    blocks: list[ParseBlockDraft] = field(default_factory=list)


@dataclass(slots=True)
class ParseIssueDraft:
    """待持久化的解析异常草稿。"""

    page_no: int
    issue_type: str
    severity: str
    description: str | None
    detected_by: str = "system"
    issue_status: str = "open"
    block_no: int | None = None
    resolution_note: str | None = None
    created_by: int | None = None
    resolved_by: int | None = None
    related_reparse_version_id: int | None = None


def build_page_drafts_from_normalized_document(
    normalized_document: NormalizedDocument,
    *,
    asset_file_id_map: dict[str, int],
    page_image_file_id_map: dict[int, int] | None = None,
    page_no_mapping: list[int] | None = None,
) -> tuple[list[ParsePageDraft], list[ParseIssueDraft]]:
    """将 MinerU 归一化结果转换为解析页与异常草稿。"""
    page_image_file_id_map = page_image_file_id_map or {}
    page_drafts: list[ParsePageDraft] = []
    issue_drafts: list[ParseIssueDraft] = []

    for page_index, normalized_page in enumerate(normalized_document.pages):
        page_no = page_no_mapping[page_index] if page_no_mapping and page_index < len(page_no_mapping) else normalized_page.page_no
        block_drafts: list[ParseBlockDraft] = []
        for normalized_block in normalized_page.blocks:
            asset_file_id = None
            if normalized_block.asset_relative_path:
                asset_file_id = asset_file_id_map.get(normalized_block.asset_relative_path)
            block_drafts.append(
                ParseBlockDraft(
                    block_no=normalized_block.block_no,
                    block_type=normalized_block.block_type,
                    text_content=normalized_block.text_content,
                    markdown_content=normalized_block.markdown_content,
                    heading_level=normalized_block.heading_level,
                    bbox_json=normalized_block.bbox_json,
                    asset_file_id=asset_file_id,
                    origin_ref_json=normalized_block.origin_ref_json,
                    is_deleted=0,
                )
            )
        page_draft = ParsePageDraft(
            page_no=page_no,
            page_status="success" if block_drafts else "empty_page",
            text_content=normalized_page.text_content,
            markdown_content=normalized_page.markdown_content,
            layout_json=normalized_page.layout_json,
            source_page_image_file_id=page_image_file_id_map.get(page_no),
            blocks=block_drafts,
        )
        page_drafts.append(page_draft)
        issue_drafts.extend(detect_issue_drafts(page_draft))

    return page_drafts, issue_drafts


def detect_issue_drafts(page_draft: ParsePageDraft) -> list[ParseIssueDraft]:
    """基于页结果生成系统异常草稿。"""
    issues: list[ParseIssueDraft] = []
    if not page_draft.blocks:
        issues.append(
            ParseIssueDraft(
                page_no=page_draft.page_no,
                issue_type="empty_page",
                severity="medium",
                description="当前页未提取到有效结构块",
            )
        )
        return issues

    text_length = len((page_draft.text_content or "").strip())
    if text_length < 20:
        issues.append(
            ParseIssueDraft(
                page_no=page_draft.page_no,
                issue_type="low_text_density",
                severity="low",
                description="当前页文本密度较低，建议人工复核",
            )
        )

    for block in page_draft.blocks:
        if block.asset_file_id is None and _has_asset_reference(block.origin_ref_json):
            issues.append(
                ParseIssueDraft(
                    page_no=page_draft.page_no,
                    block_no=block.block_no,
                    issue_type="asset_missing",
                    severity="medium",
                    description="结构块引用的资源文件缺失",
                    detected_by="mineru",
                )
            )
        if block.block_type == "table" and not (block.text_content or block.markdown_content):
            issues.append(
                ParseIssueDraft(
                    page_no=page_draft.page_no,
                    block_no=block.block_no,
                    issue_type="table_empty",
                    severity="medium",
                    description="表格块缺少正文内容",
                )
            )
        if block.block_type in {"equation", "formula"} and not (block.text_content or block.markdown_content):
            issues.append(
                ParseIssueDraft(
                    page_no=page_draft.page_no,
                    block_no=block.block_no,
                    issue_type="formula_missing",
                    severity="medium",
                    description="公式块缺少可用文本表达",
                )
            )
    return issues


def clone_page_drafts_from_records(parse_pages: list, parse_blocks: list, parse_issues: list) -> tuple[list[ParsePageDraft], list[ParseIssueDraft]]:
    """从数据库记录克隆页与异常草稿。"""
    blocks_by_page_id: dict[int, list] = {}
    block_id_to_no: dict[int, int] = {}
    for block in parse_blocks:
        blocks_by_page_id.setdefault(block.parse_page_id, []).append(block)
        block_id_to_no[block.id] = block.block_no

    issues_by_page_id: dict[int, list] = {}
    for issue in parse_issues:
        if issue.parse_page_id is not None:
            issues_by_page_id.setdefault(issue.parse_page_id, []).append(issue)

    page_drafts: list[ParsePageDraft] = []
    issue_drafts: list[ParseIssueDraft] = []
    for parse_page in sorted(parse_pages, key=lambda item: item.page_no):
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
                is_deleted=block.is_deleted,
            )
            for block in sorted(blocks_by_page_id.get(parse_page.id, []), key=lambda item: item.block_no)
        ]
        page_drafts.append(
            ParsePageDraft(
                page_no=parse_page.page_no,
                page_status=parse_page.page_status,
                text_content=parse_page.text_content,
                markdown_content=parse_page.markdown_content,
                layout_json=parse_page.layout_json,
                source_page_image_file_id=parse_page.source_page_image_file_id,
                blocks=block_drafts,
            )
        )
        for issue in issues_by_page_id.get(parse_page.id, []):
            issue_drafts.append(
                ParseIssueDraft(
                    page_no=parse_page.page_no,
                    block_no=block_id_to_no.get(issue.parse_block_id) if issue.parse_block_id is not None else None,
                    issue_type=issue.issue_type,
                    severity=issue.severity,
                    description=issue.description,
                    detected_by=issue.detected_by,
                    issue_status=issue.issue_status,
                    resolution_note=issue.resolution_note,
                    created_by=issue.created_by,
                    resolved_by=issue.resolved_by,
                    related_reparse_version_id=issue.related_reparse_version_id,
                )
            )
    return page_drafts, issue_drafts


def merge_page_drafts(base_pages: list[ParsePageDraft], replacement_pages: list[ParsePageDraft]) -> list[ParsePageDraft]:
    """按页码合并解析页草稿。"""
    merged_page_map = {page.page_no: page for page in base_pages}
    for page in replacement_pages:
        merged_page_map[page.page_no] = page
    return [merged_page_map[key] for key in sorted(merged_page_map)]


def merge_issue_drafts(
    base_pages: list[ParsePageDraft],
    base_issues: list[ParseIssueDraft],
    replacement_pages: list[ParsePageDraft],
    replacement_issues: list[ParseIssueDraft],
) -> list[ParseIssueDraft]:
    """按页码合并异常草稿。"""
    replacement_page_nos = {page.page_no for page in replacement_pages}
    merged_issues = [issue for issue in base_issues if issue.page_no not in replacement_page_nos]
    merged_issues.extend(replacement_issues)
    valid_page_nos = {page.page_no for page in base_pages} | replacement_page_nos
    return [issue for issue in merged_issues if issue.page_no in valid_page_nos]


def build_parse_snapshot_payload(
    pages: list[ParsePageDraft],
    issues: list[ParseIssueDraft],
) -> tuple[str, bytes]:
    """将页与异常草稿序列化为 Markdown 和 JSON 快照。"""
    markdown_parts: list[str] = []
    for page in sorted(pages, key=lambda item: item.page_no):
        markdown_parts.append(f"<!-- page:{page.page_no} -->")
        markdown_parts.append(page.markdown_content or page.text_content or "")
    snapshot_payload = {
        "pages": [
            {
                "page_no": page.page_no,
                "page_status": page.page_status,
                "text_content": page.text_content,
                "markdown_content": page.markdown_content,
                "layout_json": page.layout_json,
                "source_page_image_file_id": page.source_page_image_file_id,
                "blocks": [
                    {
                        "block_no": block.block_no,
                        "block_type": block.block_type,
                        "heading_level": block.heading_level,
                        "bbox_json": block.bbox_json,
                        "text_content": block.text_content,
                        "markdown_content": block.markdown_content,
                        "asset_file_id": block.asset_file_id,
                        "origin_ref_json": block.origin_ref_json,
                        "is_deleted": block.is_deleted,
                    }
                    for block in page.blocks
                ],
            }
            for page in sorted(pages, key=lambda item: item.page_no)
        ],
        "issues": [
            {
                "page_no": issue.page_no,
                "block_no": issue.block_no,
                "issue_type": issue.issue_type,
                "severity": issue.severity,
                "issue_status": issue.issue_status,
                "detected_by": issue.detected_by,
                "description": issue.description,
                "resolution_note": issue.resolution_note,
                "created_by": issue.created_by,
                "resolved_by": issue.resolved_by,
                "related_reparse_version_id": issue.related_reparse_version_id,
            }
            for issue in issues
        ],
    }
    markdown_text = "\n\n".join(markdown_parts).strip()
    return markdown_text, json.dumps(snapshot_payload, ensure_ascii=False, indent=2).encode("utf-8")


def persist_parse_tree(
    repository: ParsingRepository,
    *,
    parse_version_id: int,
    pages: list[ParsePageDraft],
    issues: list[ParseIssueDraft],
) -> None:
    """将解析页和异常草稿落库。"""
    page_id_map: dict[int, int] = {}
    block_id_map: dict[tuple[int, int], int] = {}
    for page in sorted(pages, key=lambda item: item.page_no):
        parse_page = repository.create_parse_page(
            repository.build_parse_page_model(
                parse_version_id=parse_version_id,
                page_no=page.page_no,
                source_page_image_file_id=page.source_page_image_file_id,
                page_status=page.page_status,
                has_issue=0,
                text_content=page.text_content,
                markdown_content=page.markdown_content,
                layout_json=page.layout_json,
            )
        )
        page_id_map[page.page_no] = parse_page.id
        for block in sorted(page.blocks, key=lambda item: item.block_no):
            parse_block = repository.create_parse_block(
                repository.build_parse_block_model(
                    parse_version_id=parse_version_id,
                    parse_page_id=parse_page.id,
                    block_no=block.block_no,
                    block_type=block.block_type,
                    heading_level=block.heading_level,
                    bbox_json=block.bbox_json,
                    text_content=block.text_content,
                    markdown_content=block.markdown_content,
                    asset_file_id=block.asset_file_id,
                    origin_ref_json=block.origin_ref_json,
                    is_deleted=block.is_deleted,
                )
            )
            block_id_map[(page.page_no, block.block_no)] = parse_block.id

    issue_page_no_set = {issue.page_no for issue in issues}
    for issue in issues:
        page_id = page_id_map.get(issue.page_no)
        if page_id is None:
            continue
        repository.create_parse_issue(
            repository.build_parse_issue_model(
                parse_version_id=parse_version_id,
                parse_page_id=page_id,
                parse_block_id=block_id_map.get((issue.page_no, issue.block_no)) if issue.block_no is not None else None,
                related_reparse_version_id=issue.related_reparse_version_id,
                issue_type=issue.issue_type,
                severity=issue.severity,
                issue_status=issue.issue_status,
                detected_by=issue.detected_by,
                description=issue.description,
                resolution_note=issue.resolution_note,
                created_by=issue.created_by,
                resolved_by=issue.resolved_by,
            )
        )

    for page in pages:
        if page.page_no in issue_page_no_set:
            parse_page = repository.get_parse_page_by_version_and_page_no(parse_version_id, page.page_no)
            if parse_page is not None:
                parse_page.has_issue = 1
                repository.save(parse_page)


def render_pdf_page_images(pdf_bytes: bytes) -> dict[int, bytes]:
    """渲染 PDF 页图；缺少依赖时降级为空。"""
    try:
        import fitz
    except Exception as exc:  # noqa: BLE001
        logger.warning("PyMuPDF 不可用，跳过页图生成", error=str(exc))
        return {}

    page_images: dict[int, bytes] = {}
    try:
        with fitz.open(stream=pdf_bytes, filetype="pdf") as document:
            for page_index in range(document.page_count):
                page = document.load_page(page_index)
                pixmap = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
                page_images[page_index + 1] = pixmap.tobytes("png")
    except Exception as exc:  # noqa: BLE001
        logger.warning("PDF 页图生成失败，跳过页图预览", error=str(exc))
        return {}
    return page_images


def extract_pdf_subset(pdf_bytes: bytes, page_nos: list[int]) -> bytes:
    """按页码提取子 PDF。"""
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(io.BytesIO(pdf_bytes))
    writer = PdfWriter()
    for page_no in page_nos:
        writer.add_page(reader.pages[page_no - 1])
    output_buffer = io.BytesIO()
    writer.write(output_buffer)
    return output_buffer.getvalue()


def _has_asset_reference(origin_ref_json: dict[str, Any] | None) -> bool:
    if not origin_ref_json:
        return False
    sources = [origin_ref_json]
    content_value = origin_ref_json.get("content")
    if isinstance(content_value, dict):
        sources.append(content_value)
    for source in sources:
        for key in ("asset_path", "image_path", "img_path", "image_source", "path", "file_path", "resource_path"):
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                return True
    return False
