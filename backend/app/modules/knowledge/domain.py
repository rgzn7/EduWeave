"""
@Date: 2026-04-14
@Author: xisy
@Discription: 知识结构化模块领域辅助函数
"""

from dataclasses import dataclass, field
from typing import Any

from app.modules.knowledge.repository import KnowledgeRepository
from app.modules.knowledge.schemas import (
    KnowledgeExtractionChapterDraft,
    KnowledgeExtractionEvidenceDraft,
    KnowledgeExtractionPointDraft,
)
from app.modules.p0_models import ChapterNode, KnowledgeEvidence, KnowledgePoint, KnowledgeVersion, ParseBlock, ParsePage, ParseVersion
from app.shared.vector import VectorRecord


@dataclass(slots=True)
class KnowledgeEvidenceDraft:
    """待持久化的知识证据草稿。"""

    parse_version_id: int
    parse_page_id: int | None
    parse_block_id: int | None
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
    sort_order: int = 0


@dataclass(slots=True)
class PersistedKnowledgeSnapshot:
    """知识版本持久化结果。"""

    chapters: list[ChapterNode]
    points: list[KnowledgePoint]
    evidences_by_point_id: dict[int, list[KnowledgeEvidence]]


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


def persist_knowledge_snapshot(
    repository: KnowledgeRepository,
    *,
    knowledge_version: KnowledgeVersion,
    chapter_drafts: list[ChapterDraft],
    point_drafts: list[KnowledgePointDraft],
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
            sort_order=chapter_draft.sort_order,
        )
        repository.create_chapter_node(chapter_node)
        created_chapters.append(chapter_node)
        draft_id_to_chapter_id[chapter_draft.draft_id] = chapter_node.id

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
            knowledge_evidence = KnowledgeEvidence(
                knowledge_point_id=knowledge_point.id,
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


def build_textbook_chunk_embedding_text(block: ParseBlock) -> str:
    """构造教材块向量文本。"""
    content = (block.markdown_content or block.text_content or "").strip()
    return f"块类型：{block.block_type}\n内容：{content}".strip()


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


def build_textbook_chunk_vector_records(
    *,
    project_id: int,
    textbook_version_id: int,
    parse_version: ParseVersion,
    parse_pages: list[ParsePage],
    parse_blocks: list[ParseBlock],
    chapters: list[ChapterNode],
    embeddings: list[list[float]],
    embedding_model: str,
) -> list[VectorRecord]:
    """构造教材块向量写入记录。"""
    page_id_to_page = {page.id: page for page in parse_pages}
    valid_blocks = [
        block
        for block in parse_blocks
        if block.is_deleted == 0 and (block.markdown_content or block.text_content)
    ]
    records: list[VectorRecord] = []
    for block, embedding in zip(valid_blocks, embeddings, strict=True):
        parse_page = page_id_to_page.get(block.parse_page_id)
        chapter = resolve_chapter_for_page(parse_page.page_no if parse_page is not None else None, chapters)
        records.append(
            VectorRecord(
                id=f"parse_block:{block.id}",
                project_id=project_id,
                textbook_version_id=textbook_version_id,
                parse_version_id=parse_version.id,
                chapter_node_id=chapter.id if chapter is not None else None,
                page_no=parse_page.page_no if parse_page is not None else None,
                block_type=block.block_type,
                embedding_model=embedding_model,
                content=(block.markdown_content or block.text_content or "").strip(),
                metadata={
                    "knowledge_version_parse_version_id": parse_version.id,
                    "chapter_title": chapter.title if chapter is not None else None,
                    "chapter_path": chapter.node_path if chapter is not None else None,
                    "parse_page_id": block.parse_page_id,
                    "parse_block_id": block.id,
                },
                embedding=embedding,
            )
        )
    return records


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
