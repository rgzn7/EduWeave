"""
@Date: 2026-05-31
@Author: xisy
@Discription: 智能助手会话工件记忆服务
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.modules.agent.memory.context_pack import AgentContextAssembler, ContextPackEntry
from app.modules.agent.models import AgentRun
from app.modules.agent.repository import AgentRepository
from app.modules.agent.tools.constants import WRITE_SUPERSEDE_RULES
from app.modules.agent.tools.summary import summarize_result

ARTIFACT_TOOLS = frozenset({"read_lesson_plan", "read_outline"})
SEARCH_TEXTBOOK_INDEX_TOOL = "search_textbook_index"
RESOURCE_MEMORY_LIMIT = 5
TEXTBOOK_SEARCH_MEMORY_LIMIT = 3


class AgentArtifactMemoryService:
    """负责 Agent 工具内容落工件、context pack 与跨 run 工件目录渲染。"""

    def __init__(
        self,
        *,
        db: Session,
        settings: Settings,
        repository: AgentRepository,
        run: AgentRun,
        context_assembler: AgentContextAssembler,
        context_pack: dict[int, ContextPackEntry],
    ) -> None:
        self.db = db
        self.settings = settings
        self.repository = repository
        self.run = run
        self.context_assembler = context_assembler
        self.context_pack = context_pack

    def maybe_persist_resource(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        result: dict[str, Any],
        *,
        query_terms: list[str],
        round_index: int,
    ):
        """资源读结果落工件；大内容以描述符替换回灌内容，同步刷新 context pack。"""
        content = result.get("content")
        if not isinstance(content, str):
            return None
        title = summarize_result(tool_name, result)
        preview = content[: self.settings.agent_artifact_preview_chars]
        artifact = self.repository.create_or_reuse_artifact(
            session_id=self.run.session_id,
            source_tool=tool_name,
            content_text=content,
            title=title,
            summary=preview,
        )
        self.db.commit()
        if self.settings.agent_context_pack_enabled:
            entry = self.context_assembler.build_entry(
                artifact_id=artifact.id,
                source_tool=tool_name,
                source_arguments=arguments,
                title=title,
                content=content,
                query_terms=query_terms,
                round_index=round_index,
            )
            self.context_pack[artifact.id] = entry
            self.enforce_context_pack_capacity()
        result["artifact_id"] = artifact.id
        if len(content) >= self.settings.agent_artifact_inline_threshold:
            result["content"] = {
                "artifact_id": artifact.id,
                "total_chars": len(content),
                "preview": preview,
                "tool_hint": "完整内容已落入会话工件库，需要更长片段时调用 read_artifact(artifact_id, offset, length)",
            }
        return artifact

    def persist_search_textbook_index(self, arguments: dict[str, Any], result: dict[str, Any], *, round_index: int):
        """把教材检索命中关系持久化为轻量索引工件，不保存正文或命中窗口。"""
        query = str(result.get("query") or arguments.get("query") or "").strip()
        hits = []
        for hit in result.get("hits") or []:
            if not isinstance(hit, dict):
                continue
            hits.append(
                {
                    "rank": hit.get("rank"),
                    "semantic_chunk_id": hit.get("semantic_chunk_id"),
                    "page_start": hit.get("page_start"),
                    "page_end": hit.get("page_end"),
                    "chapter_node_id": hit.get("chapter_node_id"),
                    "chapter_title": hit.get("chapter_title"),
                    "chunk_no": hit.get("chunk_no"),
                    "chunk_title": hit.get("chunk_title"),
                    "score": hit.get("score"),
                    "content_chars": hit.get("content_chars"),
                    "is_truncated": hit.get("is_truncated"),
                }
            )
        payload = {
            "run_id": self.run.id,
            "round_index": round_index,
            "query": query,
            "count": len(hits),
            "hits": hits,
        }
        content_text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)
        title = f"教材检索：{query or '未命名查询'}（{len(hits)} 条）"
        artifact = self.repository.create_or_reuse_artifact(
            session_id=self.run.session_id,
            source_tool=SEARCH_TEXTBOOK_INDEX_TOOL,
            content_text=content_text,
            title=title,
            summary=content_text[: self.settings.agent_artifact_preview_chars],
        )
        self.db.commit()
        return artifact

    def warm_start_context_pack(self, query_terms: list[str]) -> None:
        """跨运行预热：按当前问题在历史工件中检索关键命中段落。"""
        if not self.settings.agent_context_pack_enabled or not query_terms:
            return
        artifacts = self.repository.list_active_artifacts(self.run.session_id)
        for artifact in artifacts:
            if artifact.source_tool == SEARCH_TEXTBOOK_INDEX_TOOL:
                continue
            entry = self.context_assembler.build_warm_start_entry(
                artifact_id=artifact.id,
                source_tool=artifact.source_tool,
                source_arguments={},
                title=artifact.title or artifact.source_tool,
                content=artifact.content_text or "",
                query_terms=query_terms,
                round_index=0,
            )
            if entry is not None:
                self.context_pack[artifact.id] = entry
        self.enforce_context_pack_capacity()

    def enforce_context_pack_capacity(self) -> None:
        """限制 context pack 条目数，淘汰最久未触达条目。"""
        max_entries = self.settings.agent_context_pack_max_entries
        if len(self.context_pack) <= max_entries:
            return
        ordered = sorted(
            self.context_pack.values(),
            key=lambda item: (item.last_touched_round, item.artifact_id),
        )
        for entry in ordered[: len(self.context_pack) - max_entries]:
            self.context_pack.pop(entry.artifact_id, None)

    def render_context_pack_messages(self) -> list[dict[str, Any]]:
        """渲染运行上下文包为单条 system 消息。"""
        if not self.settings.agent_context_pack_enabled or not self.context_pack:
            return []
        text = self.context_assembler.render(
            list(self.context_pack.values()),
            budget_chars=self.settings.agent_context_pack_budget_chars,
        )
        if not text:
            return []
        return [{"role": "system", "content": text}]

    def render_artifact_memory_messages(self) -> list[dict[str, Any]]:
        """渲染会话历史资源工件目录与教材检索索引，支持跨 run 指代。"""
        resource_artifacts = self.repository.list_recent_active_artifacts_by_source(
            session_id=self.run.session_id,
            source_tools=list(ARTIFACT_TOOLS),
            limit=RESOURCE_MEMORY_LIMIT,
        )
        search_indexes = self.repository.list_recent_active_artifacts_by_source(
            session_id=self.run.session_id,
            source_tools=[SEARCH_TEXTBOOK_INDEX_TOOL],
            limit=TEXTBOOK_SEARCH_MEMORY_LIMIT,
        )
        lines: list[str] = []
        if resource_artifacts:
            lines.append("[会话历史可回读资源]")
            lines.append("用户提到“刚才那个教案/大纲”时，优先参考这些 artifact_id；需要全文可调用 read_artifact。")
            for artifact in resource_artifacts:
                lines.append(
                    f"- artifact_id={artifact.id} | source_tool={artifact.source_tool} | "
                    f"title={artifact.title or artifact.source_tool} | total_chars={len(artifact.content_text or '')} | "
                    f"read_artifact({artifact.id}, offset, length)"
                )
        rendered_indexes = self.render_textbook_search_indexes(search_indexes)
        if rendered_indexes:
            if lines:
                lines.append("")
            lines.extend(rendered_indexes)
        if not lines:
            return []
        return [{"role": "system", "content": "\n".join(lines)}]

    def render_textbook_search_indexes(self, search_indexes: list[Any]) -> list[str]:
        """渲染最近教材检索索引，保留 rank 到 semantic_chunk_id 的映射。"""
        if not search_indexes:
            return []
        lines = [
            "[最近教材检索索引]",
            "用户提到“刚才第 N 条/上次第 N 个结果”时，按最近一次检索的 rank 映射 semantic_chunk_id，"
            "再调用 read_textbook_chunk(semantic_chunk_id, offset, length) 回读正文。",
        ]
        for artifact in search_indexes:
            try:
                payload = json.loads(artifact.content_text or "{}")
            except (TypeError, ValueError):
                continue
            if not isinstance(payload, dict):
                continue
            query = payload.get("query") or "未命名查询"
            hits = payload.get("hits") if isinstance(payload.get("hits"), list) else []
            lines.append(f"- search_index_artifact_id={artifact.id} | query={query} | count={len(hits)}")
            for hit in hits:
                if not isinstance(hit, dict):
                    continue
                title = hit.get("chunk_title") or hit.get("chapter_title") or "未命名片段"
                page_start = hit.get("page_start")
                page_end = hit.get("page_end")
                page_text = f"{page_start}-{page_end}" if page_start != page_end else str(page_start)
                lines.append(
                    f"  rank={hit.get('rank')} -> semantic_chunk_id={hit.get('semantic_chunk_id')} | "
                    f"pages={page_text} | title={title} | score={hit.get('score')} | "
                    f"is_truncated={hit.get('is_truncated')}"
                )
        return lines if len(lines) > 2 else []

    def supersede_artifacts_for_write(self, tool_name: str) -> list[int]:
        """写工具成功后失效同源读工件，并同步清理运行内 context pack。"""
        source_tools = WRITE_SUPERSEDE_RULES.get(tool_name)
        if not source_tools:
            return []
        superseded_ids = self.repository.supersede_artifacts(
            session_id=self.run.session_id,
            source_tools=source_tools,
        )
        self.db.commit()
        for artifact_id in superseded_ids:
            self.context_pack.pop(artifact_id, None)
        return superseded_ids
