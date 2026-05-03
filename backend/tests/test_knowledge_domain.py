"""
@Date: 2026-04-30
@Author: xisy
@Discription: 知识结构化领域函数测试
"""

import pytest

from app.modules.knowledge.domain import (
    build_chapter_drafts_from_boundaries,
    build_markdown_line_index,
    build_semantic_chunk_drafts_from_markdown_index,
)
from app.modules.knowledge.schemas import KnowledgeChapterBoundaryItem
from app.modules.p0_models import ParseBlock, ParsePage


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
