"""
@Date: 2026-04-30
@Author: xisy
@Discription: 知识结构化模块领域辅助函数
"""

import hashlib
from dataclasses import dataclass, field
from typing import Any

from app.modules.knowledge.repository import KnowledgeRepository
from app.modules.knowledge.schemas import (
    KnowledgeChapterBoundaryItem,
    KnowledgeExtractionChapterDraft,
    KnowledgeExtractionEvidenceDraft,
    KnowledgeExtractionPointDraft,
)
from app.modules.p0_models import (
    ChapterNode,
    KnowledgeEvidence,
    KnowledgePoint,
    KnowledgeVersion,
    ParseBlock,
    ParsePage,
    ParseVersion,
    SemanticChunk,
)
from app.shared.vector import VectorRecord


@dataclass(slots=True)
class KnowledgeEvidenceDraft:
    """待持久化的知识证据草稿。"""

    parse_version_id: int
    parse_page_id: int | None
    parse_block_id: int | None
    semantic_chunk_ref_id: int | None
    source_file_id: int | None
    evidence_type: str
    page_no: int | None
    excerpt_text: str | None
    bbox_json: dict[str, Any] | None = None
    score_value: float | None = None


@dataclass(slots=True)
class KnowledgePointDraft:
    """待持久化的知识点草稿。"""

    draft_id: int | str
    chapter_ref_id: int | None
    point_name: str
    point_code: str | None = None
    point_type: str = "knowledge"
    importance_level: int | None = None
    difficulty_level: int | None = None
    mastery_level_hint: str | None = None
    tags_json: dict[str, Any] | None = None
    summary_text: str | None = None
    sort_order: int = 0
    evidences: list[KnowledgeEvidenceDraft] = field(default_factory=list)


@dataclass(slots=True)
class ChapterDraft:
    """待持久化的章节草稿。"""

    draft_id: int
    parent_ref_id: int | None
    node_path: str
    node_no: int
    node_level: int
    node_type: str
    title: str
    summary_text: str | None = None
    page_start: int | None = None
    page_end: int | None = None
    line_start: int | None = None
    line_end: int | None = None
    sort_order: int = 0


@dataclass(slots=True)
class SemanticChunkDraft:
    """待持久化的教材语义块草稿。"""

    draft_id: int
    chapter_ref_id: int | None
    chunk_no: int
    chunk_title: str | None
    chunk_type: str = "semantic"
    page_start: int | None = None
    page_end: int | None = None
    line_start: int | None = None
    line_end: int | None = None
    source_block_refs_json: dict[str, Any] | None = None
    source_text_hash: str | None = None
    chunk_text: str = ""
    summary_text: str | None = None
    metadata_json: dict[str, Any] | None = None


@dataclass(slots=True)
class PersistedKnowledgeSnapshot:
    """知识版本持久化结果。"""

    chapters: list[ChapterNode]
    semantic_chunks: list[SemanticChunk]
    points: list[KnowledgePoint]
    evidences_by_point_id: dict[int, list[KnowledgeEvidence]]


@dataclass(slots=True)
class MarkdownLine:
    """带页码的 Markdown 行。"""

    line_no: int
    text: str
    page_no: int
    is_page_marker: bool = False


@dataclass(slots=True)
class MarkdownLineIndex:
    """页级 Markdown 行索引。"""

    lines: list[MarkdownLine]

    @property
    def total_lines(self) -> int:
        """返回总行数。"""
        return len(self.lines)

    @property
    def numbered_text(self) -> str:
        """返回带 L 行号的 Markdown。"""
        return "\n".join(f"L{line.line_no:06d} {line.text}" for line in self.lines)

    def get_line_text(self, line_no: int) -> str | None:
        """按行号取原文。"""
        if line_no < 1 or line_no > self.total_lines:
            return None
        return self.lines[line_no - 1].text

    def slice_content(self, line_start: int, line_end: int) -> str:
        """按行号切出正文内容，不包含页标记。"""
        selected_lines = [
            line.text
            for line in self.lines
            if line_start <= line.line_no <= line_end and not line.is_page_marker
        ]
        return "\n".join(selected_lines).strip()

    def resolve_page_range(self, line_start: int, line_end: int) -> tuple[int | None, int | None]:
        """根据行号范围推导页码范围。"""
        content_pages = [
            line.page_no
            for line in self.lines
            if line_start <= line.line_no <= line_end and not line.is_page_marker
        ]
        if not content_pages:
            content_pages = [
                line.page_no
                for line in self.lines
                if line_start <= line.line_no <= line_end and line.is_page_marker
            ]
        if not content_pages:
            return None, None
        return min(content_pages), max(content_pages)


def parent_node_path(node_path: str) -> str | None:
    """从路径编码推导父路径。"""
    normalized_path = node_path.strip()
    if "." not in normalized_path:
        return None
    return normalized_path.rsplit(".", 1)[0]


def sort_node_path(node_path: str) -> tuple:
    """将路径编码转换为稳定排序键。"""
    sort_items: list[int | str] = []
    for part in node_path.split("."):
        stripped_part = part.strip()
        if stripped_part.isdigit():
            sort_items.append(int(stripped_part))
            continue
        sort_items.append(stripped_part)
    return tuple(sort_items)


def build_markdown_line_index(parse_pages: list[ParsePage]) -> MarkdownLineIndex:
    """基于页级 Markdown 构造全书行索引。"""
    lines: list[MarkdownLine] = []
    for page in sorted(parse_pages, key=lambda item: item.page_no):
        page_content = (page.markdown_content or "").strip()
        if not page_content:
            continue
        lines.append(
            MarkdownLine(
                line_no=len(lines) + 1,
                text=f"<!-- page:{page.page_no} -->",
                page_no=page.page_no,
                is_page_marker=True,
            )
        )
        for raw_line in page_content.splitlines():
            lines.append(
                MarkdownLine(
                    line_no=len(lines) + 1,
                    text=raw_line,
                    page_no=page.page_no,
                    is_page_marker=False,
                )
            )
    return MarkdownLineIndex(lines=lines)


def build_chapter_drafts_from_boundaries(
    boundaries: list[KnowledgeChapterBoundaryItem],
    line_index: MarkdownLineIndex,
) -> list[ChapterDraft]:
    """根据 LLM 返回的章节起始行构造一级章节草稿。"""
    if not line_index.lines:
        raise ValueError("解析版本缺少可用页级 Markdown")
    if not boundaries:
        raise ValueError("LLM 未返回章节起始行")

    resolved_items: list[tuple[int, KnowledgeChapterBoundaryItem]] = []
    seen_lines: set[int] = set()
    for boundary in boundaries:
        resolved_line = _resolve_boundary_start_line(boundary, line_index)
        if resolved_line in seen_lines:
            raise ValueError("LLM 返回了重复的章节起始行")
        seen_lines.add(resolved_line)
        resolved_items.append((resolved_line, boundary))

    resolved_items.sort(key=lambda item: item[0])
    drafts: list[ChapterDraft] = []
    for index, (line_start, boundary) in enumerate(resolved_items, start=1):
        next_line_start = resolved_items[index][0] if index < len(resolved_items) else line_index.total_lines + 1
        line_end = next_line_start - 1
        chunk_text = line_index.slice_content(line_start, line_end)
        if not chunk_text:
            raise ValueError("LLM 返回的章节范围没有正文内容")
        page_start, page_end = line_index.resolve_page_range(line_start, line_end)
        drafts.append(
            ChapterDraft(
                draft_id=index,
                parent_ref_id=None,
                node_path=str(index),
                node_no=index,
                node_level=1,
                node_type="chapter",
                title=boundary.title.strip(),
                summary_text=None,
                page_start=page_start,
                page_end=page_end,
                line_start=line_start,
                line_end=line_end,
                sort_order=index - 1,
            )
        )
    return drafts


def build_chapter_drafts_from_extraction(chapters: list[KnowledgeExtractionChapterDraft]) -> list[ChapterDraft]:
    """将 LLM 章节结果转换为章节草稿。"""
    normalized_drafts: list[ChapterDraft] = []
    ordered_chapters = sorted(chapters, key=lambda item: (item.node_level, sort_node_path(item.node_path)))
    node_path_to_draft_id: dict[str, int] = {}
    for index, chapter in enumerate(ordered_chapters, start=1):
        normalized_node_path = chapter.node_path.strip()
        draft_id = index
        node_path_to_draft_id[normalized_node_path] = draft_id
        parent_path = parent_node_path(normalized_node_path)
        normalized_drafts.append(
            ChapterDraft(
                draft_id=draft_id,
                parent_ref_id=node_path_to_draft_id.get(parent_path),
                node_path=normalized_node_path,
                node_no=chapter.node_no,
                node_level=len(normalized_node_path.split(".")),
                node_type=chapter.node_type,
                title=chapter.title,
                summary_text=chapter.summary_text,
                page_start=chapter.page_start,
                page_end=chapter.page_end,
                line_start=None,
                line_end=None,
                sort_order=chapter.sort_order,
            )
        )
    return normalized_drafts


def build_point_drafts_from_extraction(
    *,
    parse_version: ParseVersion,
    source_file_id: int | None,
    chapter_path_to_draft_id: dict[str, int],
    parse_pages: list[ParsePage],
    parse_blocks: list[ParseBlock],
    point_drafts: list[KnowledgeExtractionPointDraft],
) -> list[KnowledgePointDraft]:
    """将 LLM 知识点结果转换为知识点草稿。"""
    page_map = {page.page_no: page for page in parse_pages}
    block_map = {
        (page_map[page.page_no].page_no, block.block_no): block
        for block in parse_blocks
        for page in parse_pages
        if page.id == block.parse_page_id
    }

    drafts: list[KnowledgePointDraft] = []
    for index, point in enumerate(point_drafts, start=1):
        evidences = [
            KnowledgeEvidenceDraft(
                parse_version_id=parse_version.id,
                parse_page_id=page_map.get(evidence.page_no).id if page_map.get(evidence.page_no) is not None else None,
                parse_block_id=block_map.get((evidence.page_no, evidence.block_no)).id
                if evidence.block_no is not None and block_map.get((evidence.page_no, evidence.block_no)) is not None
                else None,
                semantic_chunk_ref_id=None,
                source_file_id=source_file_id,
                evidence_type=evidence.evidence_type,
                page_no=evidence.page_no,
                excerpt_text=evidence.excerpt_text,
                bbox_json=evidence.bbox_json,
                score_value=evidence.score_value,
            )
            for evidence in point.evidences
        ]
        drafts.append(
            KnowledgePointDraft(
                draft_id=index,
                chapter_ref_id=chapter_path_to_draft_id.get(point.chapter_path) if point.chapter_path else None,
                point_name=point.point_name,
                point_code=point.point_code,
                point_type=point.point_type,
                importance_level=point.importance_level,
                difficulty_level=point.difficulty_level,
                mastery_level_hint=point.mastery_level_hint,
                tags_json=point.tags_json,
                summary_text=point.summary_text,
                sort_order=point.sort_order,
                evidences=evidences,
            )
        )
    return drafts


def build_point_drafts_for_chapter(
    *,
    parse_version: ParseVersion,
    source_file_id: int | None,
    chapter_ref_id: int,
    semantic_chunk_ref_id: int,
    parse_pages: list[ParsePage],
    parse_blocks: list[ParseBlock],
    point_drafts: list[KnowledgeExtractionPointDraft],
    start_sort_order: int = 0,
) -> list[KnowledgePointDraft]:
    """将单章节 LLM 知识点结果转换为知识点草稿。"""
    page_map = {page.page_no: page for page in parse_pages}
    blocks_by_page_no: dict[int, list[ParseBlock]] = {}
    page_id_to_no = {page.id: page.page_no for page in parse_pages}
    for block in parse_blocks:
        if block.is_deleted == 0:
            blocks_by_page_no.setdefault(page_id_to_no.get(block.parse_page_id, 0), []).append(block)

    drafts: list[KnowledgePointDraft] = []
    for index, point in enumerate(point_drafts, start=1):
        evidences: list[KnowledgeEvidenceDraft] = []
        for evidence in point.evidences:
            parse_page = page_map.get(evidence.page_no)
            parse_block = _resolve_evidence_parse_block(evidence, blocks_by_page_no.get(evidence.page_no, []))
            evidences.append(
                KnowledgeEvidenceDraft(
                    parse_version_id=parse_version.id,
                    parse_page_id=parse_page.id if parse_page is not None else None,
                    parse_block_id=parse_block.id if parse_block is not None else None,
                    semantic_chunk_ref_id=semantic_chunk_ref_id,
                    source_file_id=(
                        parse_block.asset_file_id
                        if parse_block is not None and parse_block.asset_file_id is not None
                        else parse_page.source_page_image_file_id if parse_page is not None else source_file_id
                    ),
                    evidence_type=evidence.evidence_type,
                    page_no=evidence.page_no,
                    excerpt_text=evidence.excerpt_text,
                    bbox_json=evidence.bbox_json or (parse_block.bbox_json if parse_block is not None else None),
                    score_value=evidence.score_value,
                )
            )
        drafts.append(
            KnowledgePointDraft(
                draft_id=f"{chapter_ref_id}_{index}",
                chapter_ref_id=chapter_ref_id,
                point_name=point.point_name,
                point_code=point.point_code,
                point_type=point.point_type,
                importance_level=point.importance_level,
                difficulty_level=point.difficulty_level,
                mastery_level_hint=point.mastery_level_hint,
                tags_json=point.tags_json,
                summary_text=point.summary_text,
                sort_order=start_sort_order + index - 1,
                evidences=evidences,
            )
        )
    return drafts


def build_semantic_chunk_drafts_from_markdown_index(
    *,
    parse_pages: list[ParsePage],
    parse_blocks: list[ParseBlock],
    chapter_drafts: list[ChapterDraft],
    line_index: MarkdownLineIndex,
) -> list[SemanticChunkDraft]:
    """按章节行号范围切出语义块。"""
    page_by_no = {page.page_no: page for page in parse_pages}
    blocks_by_page_id, page_id_to_no = _build_block_lookup(parse_pages, parse_blocks)
    drafts: list[SemanticChunkDraft] = []
    for chapter in sorted(chapter_drafts, key=lambda item: item.sort_order):
        if chapter.line_start is None or chapter.line_end is None:
            continue
        chunk_text = line_index.slice_content(chapter.line_start, chapter.line_end)
        if not chunk_text:
            continue
        page_start, page_end = line_index.resolve_page_range(chapter.line_start, chapter.line_end)
        if page_start is None or page_end is None:
            continue
        page_numbers = [page_no for page_no in sorted(page_by_no) if page_start <= page_no <= page_end]
        source_refs = _build_source_block_refs(page_numbers, page_by_no, blocks_by_page_id, page_id_to_no)
        drafts.append(
            SemanticChunkDraft(
                draft_id=len(drafts) + 1,
                chapter_ref_id=chapter.draft_id,
                chunk_no=len(drafts) + 1,
                chunk_title=chapter.title,
                page_start=page_start,
                page_end=page_end,
                line_start=chapter.line_start,
                line_end=chapter.line_end,
                source_block_refs_json=source_refs,
                source_text_hash=_hash_text(chunk_text),
                chunk_text=chunk_text,
                summary_text=chapter.summary_text,
                metadata_json={
                    "source": "chapter_markdown_line_range",
                    "chapter_path": chapter.node_path,
                    "chapter_node_type": chapter.node_type,
                },
            )
        )
    return drafts


def build_semantic_chunk_drafts_from_parse_content(
    *,
    parse_pages: list[ParsePage],
    parse_blocks: list[ParseBlock],
    chapter_drafts: list[ChapterDraft],
) -> list[SemanticChunkDraft]:
    """基于章节页码范围整理教材语义块，不再使用 MinerU 小块作为向量主块。"""
    line_index = build_markdown_line_index(parse_pages)
    if line_index.lines and all(chapter.line_start is not None and chapter.line_end is not None for chapter in chapter_drafts):
        line_drafts = build_semantic_chunk_drafts_from_markdown_index(
            parse_pages=parse_pages,
            parse_blocks=parse_blocks,
            chapter_drafts=chapter_drafts,
            line_index=line_index,
        )
        if line_drafts:
            return line_drafts

    page_by_no = {page.page_no: page for page in parse_pages}
    blocks_by_page_id, page_id_to_no = _build_block_lookup(parse_pages, parse_blocks)

    candidate_chapters = _resolve_leaf_chapter_drafts(chapter_drafts)
    drafts: list[SemanticChunkDraft] = []
    for chapter in candidate_chapters:
        if chapter.page_start is None or chapter.page_end is None:
            continue
        page_numbers = [
            page_no
            for page_no in sorted(page_by_no)
            if chapter.page_start <= page_no <= chapter.page_end
        ]
        chunk_text = _build_chunk_text_from_pages(page_numbers, page_by_no, blocks_by_page_id)
        if not chunk_text:
            continue
        source_refs = _build_source_block_refs(page_numbers, page_by_no, blocks_by_page_id, page_id_to_no)
        drafts.append(
            SemanticChunkDraft(
                draft_id=len(drafts) + 1,
                chapter_ref_id=chapter.draft_id,
                chunk_no=len(drafts) + 1,
                chunk_title=chapter.title,
                page_start=chapter.page_start,
                page_end=chapter.page_end,
                source_block_refs_json=source_refs,
                source_text_hash=_hash_text(chunk_text),
                chunk_text=chunk_text,
                summary_text=chapter.summary_text,
                metadata_json={
                    "source": "chapter_page_range",
                    "chapter_path": chapter.node_path,
                    "chapter_node_type": chapter.node_type,
                },
            )
        )

    if drafts:
        return drafts

    for page in sorted(parse_pages, key=lambda item: item.page_no):
        chunk_text = _build_chunk_text_from_pages([page.page_no], page_by_no, blocks_by_page_id)
        if not chunk_text:
            continue
        source_refs = _build_source_block_refs([page.page_no], page_by_no, blocks_by_page_id, page_id_to_no)
        drafts.append(
            SemanticChunkDraft(
                draft_id=len(drafts) + 1,
                chapter_ref_id=None,
                chunk_no=len(drafts) + 1,
                chunk_title=f"第{page.page_no}页",
                page_start=page.page_no,
                page_end=page.page_no,
                source_block_refs_json=source_refs,
                source_text_hash=_hash_text(chunk_text),
                chunk_text=chunk_text,
                metadata_json={"source": "page_fallback"},
            )
        )
    return drafts


def persist_knowledge_snapshot(
    repository: KnowledgeRepository,
    *,
    knowledge_version: KnowledgeVersion,
    chapter_drafts: list[ChapterDraft],
    point_drafts: list[KnowledgePointDraft],
    semantic_chunk_drafts: list[SemanticChunkDraft] | None = None,
) -> PersistedKnowledgeSnapshot:
    """按草稿持久化知识版本内容。"""
    draft_id_to_chapter_id: dict[int, int] = {}
    created_chapters: list[ChapterNode] = []
    for chapter_draft in sorted(chapter_drafts, key=lambda item: (item.node_level, sort_node_path(item.node_path))):
        chapter_node = ChapterNode(
            knowledge_version_id=knowledge_version.id,
            parent_id=draft_id_to_chapter_id.get(chapter_draft.parent_ref_id),
            node_path=chapter_draft.node_path,
            node_no=chapter_draft.node_no,
            node_level=chapter_draft.node_level,
            node_type=chapter_draft.node_type,
            title=chapter_draft.title,
            summary_text=chapter_draft.summary_text,
            page_start=chapter_draft.page_start,
            page_end=chapter_draft.page_end,
            line_start=chapter_draft.line_start,
            line_end=chapter_draft.line_end,
            sort_order=chapter_draft.sort_order,
        )
        repository.create_chapter_node(chapter_node)
        created_chapters.append(chapter_node)
        draft_id_to_chapter_id[chapter_draft.draft_id] = chapter_node.id

    created_semantic_chunks: list[SemanticChunk] = []
    for semantic_chunk_draft in sorted(semantic_chunk_drafts or [], key=lambda item: item.chunk_no):
        semantic_chunk = SemanticChunk(
            project_id=knowledge_version.project_id,
            parse_version_id=knowledge_version.parse_version_id,
            knowledge_version_id=knowledge_version.id,
            chapter_node_id=draft_id_to_chapter_id.get(semantic_chunk_draft.chapter_ref_id),
            chunk_no=semantic_chunk_draft.chunk_no,
            chunk_title=semantic_chunk_draft.chunk_title,
            chunk_type=semantic_chunk_draft.chunk_type,
            page_start=semantic_chunk_draft.page_start,
            page_end=semantic_chunk_draft.page_end,
            line_start=semantic_chunk_draft.line_start,
            line_end=semantic_chunk_draft.line_end,
            source_block_refs_json=semantic_chunk_draft.source_block_refs_json,
            source_text_hash=semantic_chunk_draft.source_text_hash,
            chunk_text=semantic_chunk_draft.chunk_text,
            summary_text=semantic_chunk_draft.summary_text,
            metadata_json=semantic_chunk_draft.metadata_json,
            created_by=knowledge_version.created_by,
        )
        repository.create_semantic_chunk(semantic_chunk)
        created_semantic_chunks.append(semantic_chunk)
    semantic_chunk_id_by_draft_id = {
        semantic_chunk_draft.draft_id: semantic_chunk.id
        for semantic_chunk_draft, semantic_chunk in zip(
            sorted(semantic_chunk_drafts or [], key=lambda item: item.chunk_no),
            created_semantic_chunks,
            strict=False,
        )
    }

    created_points: list[KnowledgePoint] = []
    evidences_by_point_id: dict[int, list[KnowledgeEvidence]] = {}
    for point_draft in sorted(point_drafts, key=lambda item: (item.sort_order, str(item.draft_id))):
        knowledge_point = KnowledgePoint(
            knowledge_version_id=knowledge_version.id,
            chapter_node_id=draft_id_to_chapter_id.get(point_draft.chapter_ref_id) if point_draft.chapter_ref_id is not None else None,
            point_code=point_draft.point_code,
            point_name=point_draft.point_name,
            point_type=point_draft.point_type,
            importance_level=point_draft.importance_level,
            difficulty_level=point_draft.difficulty_level,
            mastery_level_hint=point_draft.mastery_level_hint,
            tags_json=point_draft.tags_json,
            summary_text=point_draft.summary_text,
            sort_order=point_draft.sort_order,
        )
        repository.create_knowledge_point(knowledge_point)
        created_points.append(knowledge_point)
        evidences_by_point_id[knowledge_point.id] = []
        for evidence_draft in point_draft.evidences:
            semantic_chunk = resolve_semantic_chunk_for_page(evidence_draft.page_no, created_semantic_chunks)
            semantic_chunk_id = None
            if evidence_draft.semantic_chunk_ref_id is not None:
                semantic_chunk_id = semantic_chunk_id_by_draft_id.get(evidence_draft.semantic_chunk_ref_id)
            if semantic_chunk_id is None and semantic_chunk is not None:
                semantic_chunk_id = semantic_chunk.id
            knowledge_evidence = KnowledgeEvidence(
                knowledge_point_id=knowledge_point.id,
                semantic_chunk_id=semantic_chunk_id,
                parse_version_id=evidence_draft.parse_version_id,
                parse_page_id=evidence_draft.parse_page_id,
                parse_block_id=evidence_draft.parse_block_id,
                source_file_id=evidence_draft.source_file_id,
                evidence_type=evidence_draft.evidence_type,
                page_no=evidence_draft.page_no,
                excerpt_text=evidence_draft.excerpt_text,
                bbox_json=evidence_draft.bbox_json,
                score_value=evidence_draft.score_value,
            )
            repository.create_knowledge_evidence(knowledge_evidence)
            evidences_by_point_id[knowledge_point.id].append(knowledge_evidence)
    return PersistedKnowledgeSnapshot(
        chapters=created_chapters,
        semantic_chunks=created_semantic_chunks,
        points=created_points,
        evidences_by_point_id=evidences_by_point_id,
    )


def normalize_summary_json(summary_json: dict[str, Any] | None, *, chapter_count: int, point_count: int) -> dict[str, Any]:
    """补齐知识摘要统计字段。"""
    normalized_summary = dict(summary_json or {})
    normalized_summary["chapter_count"] = chapter_count
    normalized_summary["knowledge_point_count"] = point_count
    return normalized_summary


def resolve_chapter_for_page(page_no: int | None, chapters: list[ChapterNode]) -> ChapterNode | None:
    """按页码解析最深层章节。"""
    if page_no is None:
        return None
    matched_chapters = [
        chapter
        for chapter in chapters
        if chapter.page_start is not None and chapter.page_end is not None and chapter.page_start <= page_no <= chapter.page_end
    ]
    if not matched_chapters:
        return None
    matched_chapters.sort(key=lambda item: (item.node_level, len(item.node_path)), reverse=True)
    return matched_chapters[0]


def resolve_semantic_chunk_for_page(page_no: int | None, semantic_chunks: list[SemanticChunk]) -> SemanticChunk | None:
    """按页码解析语义块。"""
    if page_no is None:
        return None
    matched_chunks = [
        chunk
        for chunk in semantic_chunks
        if chunk.page_start is not None and chunk.page_end is not None and chunk.page_start <= page_no <= chunk.page_end
    ]
    if not matched_chunks:
        return None
    matched_chunks.sort(key=lambda item: ((item.page_end or page_no) - (item.page_start or page_no), item.chunk_no))
    return matched_chunks[0]


def build_semantic_chunk_embedding_text(chunk: SemanticChunk) -> str:
    """构造教材语义块向量文本。"""
    parts = [f"语义块：{chunk.chunk_title or f'第{chunk.chunk_no}块'}"]
    if chunk.summary_text:
        parts.append(f"摘要：{chunk.summary_text}")
    parts.append(f"内容：{chunk.chunk_text}")
    return "\n".join(parts).strip()


def build_knowledge_point_embedding_text(point: KnowledgePoint, chapter_title: str | None) -> str:
    """构造知识点向量文本。"""
    tags = ""
    if point.tags_json:
        tags = str(point.tags_json)
    parts = [
        f"章节：{chapter_title or '未归类'}",
        f"知识点：{point.point_name}",
    ]
    if point.summary_text:
        parts.append(f"摘要：{point.summary_text}")
    if tags:
        parts.append(f"标签：{tags}")
    return "\n".join(parts)


def build_semantic_chunk_vector_records(
    *,
    project_id: int,
    textbook_version_id: int,
    parse_version: ParseVersion,
    semantic_chunks: list[SemanticChunk],
    chapters: list[ChapterNode],
    embeddings: list[list[float]],
    embedding_model: str,
) -> list[VectorRecord]:
    """构造教材语义块向量写入记录。"""
    chapter_map = {chapter.id: chapter for chapter in chapters}
    records: list[VectorRecord] = []
    for chunk, embedding in zip(semantic_chunks, embeddings, strict=True):
        chapter = chapter_map.get(chunk.chapter_node_id) if chunk.chapter_node_id is not None else None
        records.append(
            VectorRecord(
                id=f"semantic_chunk:{chunk.id}",
                semantic_chunk_id=chunk.id,
                project_id=project_id,
                textbook_version_id=textbook_version_id,
                parse_version_id=parse_version.id,
                knowledge_version_id=chunk.knowledge_version_id,
                chapter_node_id=chapter.id if chapter is not None else None,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
                chunk_type=chunk.chunk_type,
                embedding_model=embedding_model,
                content=chunk.chunk_text.strip()[:8192],
                metadata={
                    "semantic_chunk_id": chunk.id,
                    "chunk_no": chunk.chunk_no,
                    "chunk_title": chunk.chunk_title,
                    "page_start": chunk.page_start,
                    "page_end": chunk.page_end,
                    "line_start": chunk.line_start,
                    "line_end": chunk.line_end,
                    "source_text_hash": chunk.source_text_hash,
                    "knowledge_version_parse_version_id": parse_version.id,
                    "chapter_title": chapter.title if chapter is not None else None,
                    "chapter_path": chapter.node_path if chapter is not None else None,
                    "source_block_refs_json": chunk.source_block_refs_json,
                },
                embedding=embedding,
            )
        )
    return records


def _resolve_boundary_start_line(boundary: KnowledgeChapterBoundaryItem, line_index: MarkdownLineIndex) -> int:
    """校验并纠偏章节起始行。"""
    candidate_line_nos = [boundary.start_line]
    candidate_line_nos.extend(
        line_no
        for line_no in range(boundary.start_line - 3, boundary.start_line + 4)
        if line_no != boundary.start_line
    )
    expected_texts = [
        _normalize_match_text(boundary.line_text),
        _normalize_match_text(boundary.title),
    ]
    expected_texts = [text for text in expected_texts if text]
    for line_no in candidate_line_nos:
        line_text = line_index.get_line_text(line_no)
        if line_text is None:
            continue
        normalized_line = _normalize_match_text(line_text)
        if not normalized_line:
            continue
        if any(expected == normalized_line or expected in normalized_line or normalized_line in expected for expected in expected_texts):
            return line_no
    raise ValueError("LLM 返回的章节起始行与 Markdown 原文不匹配")


def _normalize_match_text(value: str | None) -> str:
    """归一化文本用于行号校验。"""
    if not value:
        return ""
    normalized = value.strip()
    prefix_parts = normalized.split(maxsplit=1)
    if len(prefix_parts) == 2 and prefix_parts[0].startswith("L") and prefix_parts[0][1:].isdigit():
        normalized = prefix_parts[1].strip()
    while normalized.startswith("#"):
        normalized = normalized[1:].strip()
    return "".join(normalized.split())


def _resolve_evidence_parse_block(
    evidence: KnowledgeExtractionEvidenceDraft,
    page_blocks: list[ParseBlock],
) -> ParseBlock | None:
    """按块号或证据片段定位解析块。"""
    if evidence.block_no is not None:
        return next((block for block in page_blocks if block.block_no == evidence.block_no), None)
    excerpt_text = _normalize_match_text(evidence.excerpt_text)
    if not excerpt_text:
        return None
    for block in sorted(page_blocks, key=lambda item: (item.block_no, item.id)):
        block_text = _normalize_match_text(block.markdown_content or block.text_content)
        if block_text and (excerpt_text in block_text or block_text in excerpt_text):
            return block
    return None


def _build_block_lookup(
    parse_pages: list[ParsePage],
    parse_blocks: list[ParseBlock],
) -> tuple[dict[int, list[ParseBlock]], dict[int, int]]:
    """构造解析块页内索引。"""
    blocks_by_page_id: dict[int, list[ParseBlock]] = {}
    page_id_to_no = {page.id: page.page_no for page in parse_pages}
    for block in parse_blocks:
        if block.is_deleted == 0:
            blocks_by_page_id.setdefault(block.parse_page_id, []).append(block)
    return blocks_by_page_id, page_id_to_no


def _resolve_leaf_chapter_drafts(chapter_drafts: list[ChapterDraft]) -> list[ChapterDraft]:
    """选取叶子章节作为语义块边界，避免父子章节重复向量化。"""
    sorted_chapters = sorted(chapter_drafts, key=lambda item: sort_node_path(item.node_path))
    parent_paths = {
        candidate.node_path
        for candidate in sorted_chapters
        for other in sorted_chapters
        if other.node_path.startswith(f"{candidate.node_path}.")
    }
    leaf_chapters = [chapter for chapter in sorted_chapters if chapter.node_path not in parent_paths]
    return leaf_chapters or sorted_chapters


def _build_chunk_text_from_pages(
    page_numbers: list[int],
    page_by_no: dict[int, ParsePage],
    blocks_by_page_id: dict[int, list[ParseBlock]],
) -> str:
    """按页组合语义块正文。"""
    page_texts: list[str] = []
    for page_no in page_numbers:
        page = page_by_no.get(page_no)
        if page is None:
            continue
        page_content = (page.markdown_content or page.text_content or "").strip()
        if not page_content:
            block_texts = [
                (block.markdown_content or block.text_content or "").strip()
                for block in sorted(blocks_by_page_id.get(page.id, []), key=lambda item: (item.block_no, item.id))
                if block.markdown_content or block.text_content
            ]
            page_content = "\n".join(block_texts).strip()
        if page_content:
            page_texts.append(f"第{page_no}页\n{page_content}")
    return "\n\n".join(page_texts).strip()


def _build_source_block_refs(
    page_numbers: list[int],
    page_by_no: dict[int, ParsePage],
    blocks_by_page_id: dict[int, list[ParseBlock]],
    page_id_to_no: dict[int, int],
) -> dict[str, Any]:
    """记录语义块对应的 MinerU 原始块引用。"""
    refs: list[dict[str, Any]] = []
    page_number_set = set(page_numbers)
    for page in sorted(page_by_no.values(), key=lambda item: item.page_no):
        if page.page_no not in page_number_set:
            continue
        for block in sorted(blocks_by_page_id.get(page.id, []), key=lambda item: (item.block_no, item.id)):
            refs.append(
                {
                    "parse_page_id": block.parse_page_id,
                    "parse_block_id": block.id,
                    "page_no": page_id_to_no.get(block.parse_page_id),
                    "block_no": block.block_no,
                    "block_type": block.block_type,
                    "bbox_json": block.bbox_json,
                    "asset_file_id": block.asset_file_id,
                }
            )
    return {"blocks": refs}


def _hash_text(text: str) -> str:
    """计算语义块来源文本哈希。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_knowledge_point_vector_records(
    *,
    project_id: int,
    knowledge_version_id: int,
    chapters: list[ChapterNode],
    points: list[KnowledgePoint],
    embeddings: list[list[float]],
    embedding_model: str,
) -> list[VectorRecord]:
    """构造知识点向量写入记录。"""
    chapter_map = {chapter.id: chapter for chapter in chapters}
    records: list[VectorRecord] = []
    for point, embedding in zip(points, embeddings, strict=True):
        chapter = chapter_map.get(point.chapter_node_id) if point.chapter_node_id is not None else None
        records.append(
            VectorRecord(
                id=f"knowledge_point:{point.id}",
                project_id=project_id,
                knowledge_version_id=knowledge_version_id,
                chapter_node_id=point.chapter_node_id,
                importance_level=point.importance_level,
                difficulty_level=point.difficulty_level,
                embedding_model=embedding_model,
                content=build_knowledge_point_embedding_text(point, chapter.title if chapter is not None else None),
                metadata={
                    "chapter_title": chapter.title if chapter is not None else None,
                    "chapter_path": chapter.node_path if chapter is not None else None,
                    "point_code": point.point_code,
                    "tags_json": point.tags_json,
                },
                embedding=embedding,
            )
        )
    return records
