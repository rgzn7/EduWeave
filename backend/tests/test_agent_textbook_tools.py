"""
@Date: 2026-05-31
@Author: xisy
@Discription: 智能助手教材检索与语义块精读工具测试
"""

from __future__ import annotations

from typing import Any

import app.modules.agent.tools.textbook as agent_textbook_tools
from app.core.config import get_settings
from app.modules.agent.runtime.executor import AgentRunExecutor
from app.modules.agent.tools.constants import TEXTBOOK_READ_MAX_LENGTH
from app.modules.agent.tools.context import AgentToolContext
from app.modules.agent.tools.registry import AgentToolRegistry
from app.modules.agent.tools.textbook import TextbookAgentTool


class _StubUser:
    """最小用户桩，仅提供 id。"""

    id = 1


class _StubChapter:
    """教材章节桩。"""

    def __init__(self, chapter_id: int, title: str) -> None:
        self.id = chapter_id
        self.title = title


class _StubSemanticChunk:
    """教材语义块桩。"""

    def __init__(
        self,
        *,
        chunk_id: int,
        chunk_text: str,
        project_id: int = 99,
        knowledge_version_id: int = 88,
        chapter_node_id: int | None = 66,
    ) -> None:
        self.id = chunk_id
        self.project_id = project_id
        self.knowledge_version_id = knowledge_version_id
        self.chapter_node_id = chapter_node_id
        self.chunk_no = 3
        self.chunk_title = "名词复数"
        self.page_start = 12
        self.page_end = 13
        self.chunk_text = chunk_text


class _StubVectorHit:
    """Milvus 命中桩。"""

    def __init__(self, semantic_chunk_id: int | None, score: float) -> None:
        self.semantic_chunk_id = semantic_chunk_id
        self.score = score


class _StubKnowledgeRepository:
    """教材工具用知识仓储桩。"""

    def __init__(self, chunks: list[_StubSemanticChunk], chapters: list[_StubChapter] | None = None) -> None:
        self.chunks = {chunk.id: chunk for chunk in chunks}
        self.chapters = {chapter.id: chapter for chapter in chapters or []}
        self.last_chunk_ids: list[int] = []
        self.last_project_id: int | None = None
        self.last_knowledge_version_id: int | None = None

    def list_semantic_chunks_by_ids_for_owner(
        self,
        semantic_chunk_ids: list[int],
        _owner_user_id: int,
        *,
        project_id: int | None = None,
        knowledge_version_id: int | None = None,
    ) -> list[_StubSemanticChunk]:
        self.last_chunk_ids = list(semantic_chunk_ids)
        self.last_project_id = project_id
        self.last_knowledge_version_id = knowledge_version_id
        chunks: list[_StubSemanticChunk] = []
        for chunk_id in semantic_chunk_ids:
            chunk = self.chunks.get(chunk_id)
            if chunk is None:
                continue
            if project_id is not None and chunk.project_id != project_id:
                continue
            if knowledge_version_id is not None and chunk.knowledge_version_id != knowledge_version_id:
                continue
            chunks.append(chunk)
        return chunks

    def get_semantic_chunk_for_owner(
        self,
        semantic_chunk_id: int,
        owner_user_id: int,
        *,
        project_id: int | None = None,
        knowledge_version_id: int | None = None,
    ) -> _StubSemanticChunk | None:
        chunks = self.list_semantic_chunks_by_ids_for_owner(
            [semantic_chunk_id],
            owner_user_id,
            project_id=project_id,
            knowledge_version_id=knowledge_version_id,
        )
        return chunks[0] if chunks else None

    def list_chapter_nodes_by_ids(self, chapter_node_ids: list[int]) -> list[_StubChapter]:
        return [self.chapters[node_id] for node_id in chapter_node_ids if node_id in self.chapters]


def _make_textbook_service(
    repository: _StubKnowledgeRepository,
    *,
    project_id: int | None = 99,
    knowledge_version_id: int | None = 88,
) -> TextbookAgentTool:
    """绕过 __init__ 构造教材工具服务，仅注入本组测试需要的状态。"""
    context = object.__new__(AgentToolContext)
    context.settings = get_settings()
    context.current_user = _StubUser()
    context.project_id = project_id
    context.knowledge_version_id = knowledge_version_id
    context.knowledge_repository = repository
    return TextbookAgentTool(context)


def test_read_textbook_chunk_should_return_mysql_content_window() -> None:
    """read_textbook_chunk 应从 MySQL 语义块事实源读取指定正文窗口。"""
    chunk = _StubSemanticChunk(chunk_id=1, chunk_text="0123456789")
    repository = _StubKnowledgeRepository([chunk], [_StubChapter(66, "第一章")])
    service = _make_textbook_service(repository)

    result = service.read_textbook_chunk({"semantic_chunk_id": 1, "offset": 2, "length": 4})

    assert result["ok"] is True
    assert result["semantic_chunk_id"] == 1
    assert result["chapter_title"] == "第一章"
    assert result["content"] == "2345"
    assert result["returned_chars"] == 4
    assert result["total_chars"] == 10
    assert result["is_truncated"] is True


def test_read_textbook_chunk_should_limit_length_and_return_structured_errors() -> None:
    """read_textbook_chunk 应限制读取长度，并将参数/范围问题转为结构化工具错误。"""
    long_chunk = _StubSemanticChunk(chunk_id=1, chunk_text="甲" * (TEXTBOOK_READ_MAX_LENGTH + 10))
    empty_chunk = _StubSemanticChunk(chunk_id=2, chunk_text="")
    other_version_chunk = _StubSemanticChunk(chunk_id=3, chunk_text="正文", knowledge_version_id=999)
    repository = _StubKnowledgeRepository([long_chunk, empty_chunk, other_version_chunk])
    service = _make_textbook_service(repository)

    result = service.read_textbook_chunk({"semantic_chunk_id": 1, "length": TEXTBOOK_READ_MAX_LENGTH + 500})
    assert result["returned_chars"] == TEXTBOOK_READ_MAX_LENGTH
    assert result["is_truncated"] is True

    registry = AgentToolRegistry(tool_context=service.context)
    missing_id = registry.execute_tool("read_textbook_chunk", {})
    assert missing_id["ok"] is False
    assert missing_id["error_code"] == "LLM_RESULT_INVALID"

    empty_body = registry.execute_tool("read_textbook_chunk", {"semantic_chunk_id": 2})
    assert empty_body["ok"] is False
    assert empty_body["error_code"] == "LLM_RESULT_INVALID"

    version_mismatch = registry.execute_tool("read_textbook_chunk", {"semantic_chunk_id": 3})
    assert version_mismatch["ok"] is False
    assert version_mismatch["error_code"] == "KNOWLEDGE_VERSION_NOT_FOUND"


def test_search_textbook_should_recall_then_return_mysql_snippets(monkeypatch) -> None:
    """search_textbook 应用 Milvus 召回、MySQL 回源，并返回围绕 query 的命中窗口。"""
    prefix = "铺垫" * 450
    content = f"{prefix}关键定义：名词复数通常在词尾加 s 或 es。后续例题说明如何判断。"
    chunk = _StubSemanticChunk(chunk_id=1, chunk_text=content)
    repository = _StubKnowledgeRepository([chunk], [_StubChapter(66, "词法章节")])
    service = _make_textbook_service(repository)

    class _FakeEmbeddingService:
        """Embedding 服务桩。"""

        def __init__(self, **_kwargs: Any) -> None:
            pass

        def embed_texts(self, texts: list[str]) -> list[list[float]]:
            assert texts == ["关键定义"]
            return [[0.1, 0.2, 0.3, 0.4]]

    class _FakeVectorService:
        """向量服务桩。"""

        def __init__(self, **_kwargs: Any) -> None:
            pass

        def hybrid_search_vectors(self, *_args: Any, **kwargs: Any) -> list[_StubVectorHit]:
            assert kwargs["filter_expression"] == "knowledge_version_id == 88"
            return [_StubVectorHit(1, 0.91), _StubVectorHit(999, 0.6), _StubVectorHit(1, 0.5)]

    monkeypatch.setattr(agent_textbook_tools, "OpenAICompatibleEmbeddingService", _FakeEmbeddingService)
    monkeypatch.setattr(agent_textbook_tools, "MilvusVectorService", _FakeVectorService)

    result = service.search_textbook({"query": "关键定义", "top_k": 4})

    assert result["ok"] is True
    assert result["count"] == 1
    assert "content" not in result
    hit = result["hits"][0]
    assert hit["semantic_chunk_id"] == 1
    assert hit["chapter_title"] == "词法章节"
    assert hit["content_chars"] == len(content)
    assert hit["is_truncated"] is True
    assert "content" not in hit
    assert "关键定义" not in content[:800]
    assert any("关键定义" in snippet["text"] for snippet in hit["snippets"])
    assert "read_textbook_chunk" in hit["read_hint"]
    assert repository.last_chunk_ids == [1, 999]
    assert repository.last_project_id == 99
    assert repository.last_knowledge_version_id == 88


def test_model_tool_result_should_not_trim_search_snippets() -> None:
    """执行器回灌 search_textbook 时不再对命中正文做固定 800 字裁切。"""
    executor = object.__new__(AgentRunExecutor)
    long_snippet = "x" * 900
    result = {
        "ok": True,
        "content": "兼容旧结构的大字段应被移除",
        "hits": [{"snippets": [{"text": long_snippet}]}],
    }

    compact = executor._build_model_tool_result("search_textbook", result)

    assert "content" not in compact
    assert compact["hits"][0]["snippets"][0]["text"] == long_snippet
