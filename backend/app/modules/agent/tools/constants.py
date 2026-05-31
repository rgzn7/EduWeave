"""
@Date: 2026-05-31
@Author: xisy
@Discription: 智能助手工具常量
"""

LARGE_RESULT_FIELD = "content"
ARTIFACT_SOURCE_TOOLS = frozenset({"read_lesson_plan", "read_outline"})
WRITE_SUPERSEDE_RULES: dict[str, list[str]] = {
    "write_lesson_plan": ["read_lesson_plan", "list_lessons"],
    "write_outline": ["read_outline"],
}
TEXTBOOK_SNIPPET_MAX_PASSAGES = 3
TEXTBOOK_READ_DEFAULT_LENGTH = 4000
TEXTBOOK_READ_MAX_LENGTH = 20000
