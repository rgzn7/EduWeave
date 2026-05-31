"""
@Date: 2026-05-31
@Author: xisy
@Discription: 智能助手教材语义块检索与精读工具
"""

from __future__ import annotations

from typing import Any

from app.core.exceptions import AppException, BusinessErrorCode
from app.modules.agent.memory import AgentContextAssembler
from app.modules.agent.tools.constants import (
    TEXTBOOK_READ_DEFAULT_LENGTH,
    TEXTBOOK_SNIPPET_MAX_PASSAGES,
)
from app.modules.agent.tools.context import AgentToolContext
from app.shared.llm.service import OpenAICompatibleEmbeddingService
from app.shared.vector import MilvusVectorService


class TextbookAgentTool:
    """教材语义块相关工具：混合检索与按块回读。"""

    def __init__(self, context: AgentToolContext) -> None:
        self.context = context

    def search_textbook(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """教材语义块混合检索：Milvus 召回，MySQL 回源构造命中窗口。"""
        query = str(arguments.get("query") or "").strip()
        if not query:
            raise AppException(BusinessErrorCode.LLM_RESULT_INVALID, "检索问题不能为空")
        project_id, knowledge_version_id = self.context.ensure_textbook_context()
        top_k = int(arguments.get("top_k") or self.context.settings.agent_textbook_top_k)
        top_k = max(1, min(top_k, 20))

        if knowledge_version_id is not None:
            filter_expression = f"knowledge_version_id == {knowledge_version_id}"
        else:
            filter_expression = f"project_id == {project_id}"

        embedding_service = OpenAICompatibleEmbeddingService(settings=self.context.settings)
        query_vector = embedding_service.embed_texts([query])[0]
        vector_service = MilvusVectorService(settings=self.context.settings)
        vector_hits = vector_service.hybrid_search_vectors(
            "semantic_chunk_vector",
            query_vector=query_vector,
            query_text=query,
            limit=top_k,
            filter_expression=filter_expression,
        )

        hit_by_chunk_id: dict[int, Any] = {}
        ordered_chunk_ids: list[int] = []
        for hit in vector_hits:
            semantic_chunk_id = hit.semantic_chunk_id
            if semantic_chunk_id is None:
                continue
            chunk_id = int(semantic_chunk_id)
            if chunk_id in hit_by_chunk_id:
                continue
            hit_by_chunk_id[chunk_id] = hit
            ordered_chunk_ids.append(chunk_id)

        chunks = self.context.knowledge_repository.list_semantic_chunks_by_ids_for_owner(
            ordered_chunk_ids,
            self.context.current_user.id,
            project_id=project_id,
            knowledge_version_id=knowledge_version_id,
        )
        chunk_by_id = {int(chunk.id): chunk for chunk in chunks}
        chapter_ids = [
            int(chunk.chapter_node_id)
            for chunk in chunks
            if getattr(chunk, "chapter_node_id", None) is not None
        ]
        chapters = self.context.knowledge_repository.list_chapter_nodes_by_ids(chapter_ids)
        chapter_by_id = {int(chapter.id): chapter for chapter in chapters}

        hit_items: list[dict[str, Any]] = []
        for chunk_id in ordered_chunk_ids:
            chunk = chunk_by_id.get(chunk_id)
            if chunk is None:
                continue
            content = chunk.chunk_text or ""
            snippets = self._build_textbook_snippets(content, query)
            chapter = chapter_by_id.get(int(chunk.chapter_node_id)) if chunk.chapter_node_id is not None else None
            hit_items.append(
                {
                    "rank": len(hit_items) + 1,
                    "semantic_chunk_id": chunk.id,
                    "score": round(hit_by_chunk_id[chunk_id].score, 4),
                    "page_start": chunk.page_start,
                    "page_end": chunk.page_end,
                    "chapter_node_id": chunk.chapter_node_id,
                    "chapter_title": chapter.title if chapter is not None else None,
                    "chunk_no": chunk.chunk_no,
                    "chunk_title": chunk.chunk_title,
                    "content_chars": len(content),
                    "is_truncated": self._is_textbook_hit_truncated(snippets, len(content)),
                    "snippets": snippets,
                    "read_hint": (
                        "需要完整语义块时调用 "
                        f"read_textbook_chunk(semantic_chunk_id={chunk.id}, offset=0, length={TEXTBOOK_READ_DEFAULT_LENGTH})"
                    ),
                }
            )

        return {"ok": True, "query": query, "count": len(hit_items), "hits": hit_items}

    def read_textbook_chunk(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """按 semantic_chunk_id 从 MySQL 回读教材语义块正文片段。"""
        semantic_chunk_id = self.context.require_positive_int_argument(arguments, "semantic_chunk_id", "semantic_chunk_id")
        project_id, knowledge_version_id = self.context.ensure_textbook_context()
        chunk = self.context.knowledge_repository.get_semantic_chunk_for_owner(
            semantic_chunk_id,
            self.context.current_user.id,
            project_id=project_id,
            knowledge_version_id=knowledge_version_id,
        )
        if chunk is None:
            raise AppException(BusinessErrorCode.KNOWLEDGE_VERSION_NOT_FOUND, "教材语义块不存在或无权访问")

        content = chunk.chunk_text or ""
        if not content:
            raise AppException(BusinessErrorCode.LLM_RESULT_INVALID, "教材语义块正文为空")
        offset, length = self.context.resolve_read_window(arguments)
        chunk_text = content[offset : offset + length]
        chapter = None
        if chunk.chapter_node_id is not None:
            chapters = self.context.knowledge_repository.list_chapter_nodes_by_ids([int(chunk.chapter_node_id)])
            chapter = chapters[0] if chapters else None
        return {
            "ok": True,
            "semantic_chunk_id": chunk.id,
            "page_start": chunk.page_start,
            "page_end": chunk.page_end,
            "chapter_node_id": chunk.chapter_node_id,
            "chapter_title": chapter.title if chapter is not None else None,
            "chunk_no": chunk.chunk_no,
            "chunk_title": chunk.chunk_title,
            "offset": offset,
            "returned_chars": len(chunk_text),
            "total_chars": len(content),
            "is_truncated": offset + length < len(content),
            "content": chunk_text,
        }

    def _build_textbook_snippets(self, content: str, query: str) -> list[dict[str, Any]]:
        """按检索词从教材正文中抽取 1-3 个自然边界窗口。"""
        normalized_content = content or ""
        if not normalized_content:
            return []
        assembler = AgentContextAssembler(self.context.settings)
        terms = assembler.extract_query_terms(query)
        snippets = assembler.find_key_passages(
            normalized_content,
            terms,
            max_passages=TEXTBOOK_SNIPPET_MAX_PASSAGES,
            passage_chars=self.context.settings.agent_context_pack_passage_chars,
        )
        if not snippets:
            head_len = min(len(normalized_content), self.context.settings.agent_context_pack_passage_chars)
            snippets = [{"offset": 0, "length": head_len, "text": normalized_content[:head_len], "score": 0.0}]
        return [
            {
                "offset": int(snippet["offset"]),
                "length": int(snippet["length"]),
                "text": str(snippet["text"]),
                "score": float(snippet.get("score") or 0.0),
            }
            for snippet in snippets
        ]

    @staticmethod
    def _is_textbook_hit_truncated(snippets: list[dict[str, Any]], total_chars: int) -> bool:
        """判断检索命中窗口是否只是正文的部分视图。"""
        return not (
            len(snippets) == 1
            and int(snippets[0].get("offset") or 0) == 0
            and int(snippets[0].get("length") or 0) >= total_chars
        )
