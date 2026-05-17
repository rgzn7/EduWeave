"""
@Date: 2026-05-17
@Author: xisy
@Discription: 知识结构化领域函数测试
"""

import pytest

from app.modules.knowledge.domain import (
    ChapterDraft,
    build_chapter_drafts_from_boundaries,
    build_markdown_line_index,
    build_semantic_chunk_drafts_from_markdown_index,
    build_semantic_chunk_vector_records,
    build_semantic_chunk_vector_segments,
    SemanticChunkVectorSegment,
)
from app.modules.knowledge.schemas import KnowledgeChapterBoundaryItem
from app.modules.p0_models import ParseBlock, ParsePage, ParseVersion, SemanticChunk


def _build_parse_pages() -> list[ParsePage]:
    """构造带封面目录和两章正文的解析页。"""
    return [
        ParsePage(id=1, parse_version_id=1, page_no=1, markdown_content="封面\n目录"),
        ParsePage(id=2, parse_version_id=1, page_no=2, markdown_content="# 第一章 集合\n集合的基本概念"),
        ParsePage(id=3, parse_version_id=1, page_no=3, markdown_content="# 第二章 函数\n函数的基本概念"),
    ]


def _build_parse_blocks() -> list[ParseBlock]:
    """构造解析块用于来源引用。"""
    return [
        ParseBlock(id=101, parse_version_id=1, parse_page_id=1, block_no=1, block_type="paragraph", markdown_content="封面", is_deleted=0),
        ParseBlock(id=201, parse_version_id=1, parse_page_id=2, block_no=1, block_type="heading", markdown_content="# 第一章 集合", is_deleted=0),
        ParseBlock(id=202, parse_version_id=1, parse_page_id=2, block_no=2, block_type="paragraph", markdown_content="集合的基本概念", is_deleted=0),
        ParseBlock(id=301, parse_version_id=1, parse_page_id=3, block_no=1, block_type="heading", markdown_content="# 第二章 函数", is_deleted=0),
        ParseBlock(id=302, parse_version_id=1, parse_page_id=3, block_no=2, block_type="paragraph", markdown_content="函数的基本概念", is_deleted=0),
    ]


def test_markdown_line_boundary_should_build_chapter_chunks() -> None:
    """章节边界应能纠偏行号并切出不含封面目录的语义块。"""
    parse_pages = _build_parse_pages()
    line_index = build_markdown_line_index(parse_pages)

    chapter_drafts = build_chapter_drafts_from_boundaries(
        [
            KnowledgeChapterBoundaryItem(title="第一章 集合", start_line=6, line_text="# 第一章 集合", confidence=0.9),
            KnowledgeChapterBoundaryItem(title="第二章 函数", start_line=8, line_text="# 第二章 函数", confidence=0.9),
        ],
        line_index,
    )
    semantic_chunks = build_semantic_chunk_drafts_from_markdown_index(
        parse_pages=parse_pages,
        parse_blocks=_build_parse_blocks(),
        chapter_drafts=chapter_drafts,
        line_index=line_index,
    )

    assert chapter_drafts[0].line_start == 5
    assert chapter_drafts[0].line_end == 7
    assert chapter_drafts[0].page_start == 2
    assert chapter_drafts[0].page_end == 2
    assert semantic_chunks[0].chunk_text == "# 第一章 集合\n集合的基本概念"
    assert "封面" not in semantic_chunks[0].chunk_text
    assert semantic_chunks[1].line_start == 8
    assert semantic_chunks[1].page_start == 3
    assert semantic_chunks[1].source_block_refs_json["blocks"][0]["parse_block_id"] == 301


def test_markdown_line_boundary_should_split_oversized_chapter_chunks() -> None:
    """过长章节语义块应按 UTF-8 字节上限继续拆分。"""
    parse_pages = [
        ParsePage(
            id=10,
            parse_version_id=1,
            page_no=1,
            markdown_content="\n".join(
                [
                    "# 第一章 长章节",
                    "第一段内容" * 8,
                    "第二段内容" * 8,
                    "第三段内容" * 8,
                ]
            ),
        )
    ]
    parse_blocks = [
        ParseBlock(
            id=1001,
            parse_version_id=1,
            parse_page_id=10,
            block_no=1,
            block_type="paragraph",
            markdown_content="第一段内容",
            is_deleted=0,
        )
    ]
    line_index = build_markdown_line_index(parse_pages)
    chapter_drafts = [
        ChapterDraft(
            draft_id=1,
            parent_ref_id=None,
            node_path="1",
            node_no=1,
            node_level=1,
            node_type="chapter",
            title="第一章 长章节",
            line_start=2,
            line_end=5,
            sort_order=1,
        )
    ]

    semantic_chunks = build_semantic_chunk_drafts_from_markdown_index(
        parse_pages=parse_pages,
        parse_blocks=parse_blocks,
        chapter_drafts=chapter_drafts,
        line_index=line_index,
        max_chunk_utf8_bytes=120,
    )

    assert len(semantic_chunks) > 1
    assert [chunk.chunk_no for chunk in semantic_chunks] == list(range(1, len(semantic_chunks) + 1))
    assert {chunk.chapter_ref_id for chunk in semantic_chunks} == {1}
    assert all(len(chunk.chunk_text.encode("utf-8")) <= 120 for chunk in semantic_chunks)
    assert semantic_chunks[0].metadata_json["is_split"] is True
    assert semantic_chunks[0].metadata_json["segment_count"] == len(semantic_chunks)


def test_semantic_chunk_vector_segments_should_keep_full_content() -> None:
    """向量写入片段拆分不能丢失语义块正文。"""
    chunk = SemanticChunk(
        id=1,
        project_id=1,
        parse_version_id=1,
        knowledge_version_id=1,
        chunk_no=1,
        chunk_title="长文本",
        chunk_text="汉" * 3000,
    )

    segments = build_semantic_chunk_vector_segments([chunk], max_content_utf8_bytes=4096)

    assert len(segments) == 3
    assert "".join(segment.content for segment in segments) == chunk.chunk_text
    assert all(segment.chunk is chunk for segment in segments)
    assert [segment.segment_index for segment in segments] == [1, 2, 3]
    assert {segment.segment_count for segment in segments} == {3}
    assert all(len(segment.content.encode("utf-8")) <= 4096 for segment in segments)


def test_semantic_chunk_vector_metadata_should_not_embed_full_source_refs() -> None:
    """Milvus metadata 不应重复携带完整来源块引用。"""
    chunk = SemanticChunk(
        id=1,
        project_id=1,
        parse_version_id=1,
        knowledge_version_id=1,
        chunk_no=1,
        chunk_title="长引用",
        chunk_text="正文",
        source_block_refs_json={
            "blocks": [
                {"parse_block_id": index, "bbox_json": {"x": index, "y": index}, "text": "来源" * 20}
                for index in range(300)
            ]
        },
    )

    records = build_semantic_chunk_vector_records(
        project_id=1,
        textbook_version_id=1,
        parse_version=ParseVersion(id=1),
        semantic_chunk_segments=[
            SemanticChunkVectorSegment(chunk=chunk, content=chunk.chunk_text, segment_index=1, segment_count=1)
        ],
        chapters=[],
        embeddings=[[0.1, 0.2, 0.3, 0.4]],
        embedding_model="test-embedding",
    )

    metadata = records[0].metadata
    assert metadata["source_block_ref_count"] == 300
    assert "source_block_refs_json" not in metadata


def test_chapter_boundary_should_reject_duplicate_lines() -> None:
    """重复章节起始行应被拒绝。"""
    line_index = build_markdown_line_index(_build_parse_pages())

    with pytest.raises(ValueError, match="重复"):
        build_chapter_drafts_from_boundaries(
            [
                KnowledgeChapterBoundaryItem(title="第一章 集合", start_line=5, line_text="# 第一章 集合", confidence=0.9),
                KnowledgeChapterBoundaryItem(title="第一章 集合", start_line=5, line_text="# 第一章 集合", confidence=0.9),
            ],
            line_index,
        )


def test_chapter_boundary_should_reject_empty_markdown() -> None:
    """缺少页级 Markdown 时应拒绝章节切分。"""
    line_index = build_markdown_line_index([ParsePage(id=1, parse_version_id=1, page_no=1, markdown_content=None)])

    with pytest.raises(ValueError, match="缺少可用页级 Markdown"):
        build_chapter_drafts_from_boundaries(
            [KnowledgeChapterBoundaryItem(title="第一章", start_line=1, line_text="第一章", confidence=0.8)],
            line_index,
        )
