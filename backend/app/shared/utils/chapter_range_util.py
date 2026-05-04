"""
@Date: 2026-05-04
@Author: xisy
@Discription: 章节范围筛选工具
"""

from dataclasses import dataclass
from typing import Any

from app.core.exceptions import AppException, BusinessErrorCode


@dataclass(frozen=True)
class ChapterRangeSelection:
    """章节范围筛选结果。"""

    is_scoped: bool
    requested_chapter_ids: list[int]
    effective_chapter_ids: list[int]
    chapters: list[Any]


def build_chapter_range_selection(
    *,
    chapters: list[Any],
    chapter_range_json: dict[str, Any] | None,
) -> ChapterRangeSelection:
    """根据章节范围快照筛选章节，选中父章节时自动包含子章节。"""
    requested_chapter_ids = _parse_chapter_node_ids(chapter_range_json)
    if not requested_chapter_ids:
        return ChapterRangeSelection(
            is_scoped=False,
            requested_chapter_ids=[],
            effective_chapter_ids=[int(chapter.id) for chapter in chapters],
            chapters=list(chapters),
        )

    chapter_by_id = {int(chapter.id): chapter for chapter in chapters}
    invalid_chapter_ids = [chapter_id for chapter_id in requested_chapter_ids if chapter_id not in chapter_by_id]
    if invalid_chapter_ids:
        raise AppException(
            BusinessErrorCode.GENERATION_BASELINE_INVALID,
            "章节范围包含不存在的章节",
            {"chapter_node_ids": invalid_chapter_ids},
        )

    selected_paths = [str(chapter_by_id[chapter_id].node_path) for chapter_id in requested_chapter_ids]
    scoped_chapters = [
        chapter
        for chapter in chapters
        if _is_chapter_in_scope(str(chapter.node_path), selected_paths)
    ]
    if not scoped_chapters:
        raise AppException(
            BusinessErrorCode.GENERATION_BASELINE_INVALID,
            "章节范围未匹配到可用章节",
            {"chapter_node_ids": requested_chapter_ids},
        )

    return ChapterRangeSelection(
        is_scoped=True,
        requested_chapter_ids=requested_chapter_ids,
        effective_chapter_ids=[int(chapter.id) for chapter in scoped_chapters],
        chapters=scoped_chapters,
    )


def filter_knowledge_points_by_chapter_selection(
    *,
    knowledge_points: list[Any],
    selection: ChapterRangeSelection,
    raise_when_empty: bool = True,
) -> list[Any]:
    """按章节筛选知识点；全量范围不做过滤。"""
    if not selection.is_scoped:
        return list(knowledge_points)

    effective_chapter_ids = set(selection.effective_chapter_ids)
    scoped_points = [
        point
        for point in knowledge_points
        if point.chapter_node_id is not None and int(point.chapter_node_id) in effective_chapter_ids
    ]
    if raise_when_empty and not scoped_points:
        raise AppException(
            BusinessErrorCode.GENERATION_BASELINE_INVALID,
            "章节范围内缺少知识点",
            {"chapter_node_ids": selection.requested_chapter_ids},
        )
    return scoped_points


def _parse_chapter_node_ids(chapter_range_json: dict[str, Any] | None) -> list[int]:
    """读取章节范围中的 chapter_node_ids，缺省或空列表表示全量。"""
    if not chapter_range_json:
        return []
    if not isinstance(chapter_range_json, dict):
        raise AppException(
            BusinessErrorCode.GENERATION_BASELINE_INVALID,
            "章节范围必须为 JSON 对象",
            {"chapter_range_json": chapter_range_json},
        )
    raw_chapter_ids = chapter_range_json.get("chapter_node_ids")
    if raw_chapter_ids in (None, []):
        return []
    if not isinstance(raw_chapter_ids, list):
        raise AppException(
            BusinessErrorCode.GENERATION_BASELINE_INVALID,
            "章节范围 chapter_node_ids 必须为数组",
            {"chapter_node_ids": raw_chapter_ids},
        )

    chapter_ids: list[int] = []
    for raw_chapter_id in raw_chapter_ids:
        try:
            chapter_id = int(raw_chapter_id)
        except (TypeError, ValueError) as exc:
            raise AppException(
                BusinessErrorCode.GENERATION_BASELINE_INVALID,
                "章节范围包含非法章节主键",
                {"chapter_node_ids": raw_chapter_ids},
            ) from exc
        if chapter_id <= 0:
            raise AppException(
                BusinessErrorCode.GENERATION_BASELINE_INVALID,
                "章节范围包含非法章节主键",
                {"chapter_node_ids": raw_chapter_ids},
            )
        if chapter_id not in chapter_ids:
            chapter_ids.append(chapter_id)
    return chapter_ids


def _is_chapter_in_scope(node_path: str, selected_paths: list[str]) -> bool:
    """判断章节路径是否落在选中章节或其后代范围内。"""
    return any(
        node_path == selected_path or node_path.startswith(f"{selected_path}.")
        for selected_path in selected_paths
    )
