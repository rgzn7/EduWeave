"""
@Date: 2026-05-31
@Author: xisy
@Discription: 智能助手跨轮记忆策略测试：资源工件常驻与教材检索轻量索引
"""

from __future__ import annotations

import json
from typing import Any

from app.core.config import get_settings
from app.modules.agent.memory.artifacts import AgentArtifactMemoryService, SEARCH_TEXTBOOK_INDEX_TOOL
from app.modules.agent.memory.context_pack import AgentContextAssembler


class _FakeArtifact:
    """会话工件桩。"""

    def __init__(
        self,
        *,
        artifact_id: int,
        source_tool: str,
        content_text: str,
        title: str | None = None,
        summary: str | None = None,
    ) -> None:
        self.id = artifact_id
        self.source_tool = source_tool
        self.content_text = content_text
        self.title = title
        self.summary = summary


class _FakeRepository:
    """工件仓储桩。"""

    def __init__(self, artifacts: list[_FakeArtifact] | None = None) -> None:
        self.artifacts = artifacts or []

    def create_or_reuse_artifact(
        self,
        *,
        session_id: int,
        source_tool: str,
        content_text: str,
        title: str | None,
        summary: str | None,
    ) -> _FakeArtifact:
        _ = session_id
        artifact = _FakeArtifact(
            artifact_id=len(self.artifacts) + 1,
            source_tool=source_tool,
            content_text=content_text,
            title=title,
            summary=summary,
        )
        self.artifacts.append(artifact)
        return artifact

    def list_recent_active_artifacts_by_source(
        self,
        *,
        session_id: int,
        source_tools: list[str],
        limit: int,
    ) -> list[_FakeArtifact]:
        _ = session_id
        matched = [artifact for artifact in self.artifacts if artifact.source_tool in source_tools]
        return sorted(matched, key=lambda item: item.id, reverse=True)[:limit]


class _FakeDb:
    """数据库会话桩，仅记录提交次数。"""

    def __init__(self) -> None:
        self.commit_count = 0

    def commit(self) -> None:
        self.commit_count += 1


class _FakeRun:
    """运行桩。"""

    id = 7
    session_id = 99


def _make_memory_service(
    *,
    threshold: int = 2000,
    artifacts: list[_FakeArtifact] | None = None,
) -> AgentArtifactMemoryService:
    """构造工件记忆服务测试所需的最小状态。"""
    settings = get_settings().model_copy(update={"agent_artifact_inline_threshold": threshold})
    context_pack = {}
    return AgentArtifactMemoryService(
        db=_FakeDb(),
        settings=settings,
        repository=_FakeRepository(artifacts),
        run=_FakeRun(),
        context_assembler=AgentContextAssembler(settings),
        context_pack=context_pack,
    )


def test_read_resource_should_always_persist_artifact_but_keep_short_content_inline() -> None:
    """教案/大纲短内容也要落工件，但当前轮仍内联 content。"""
    service = _make_memory_service(threshold=2000)
    result = {"ok": True, "content": '{"lesson_title": "短教案", "teaching_flow": []}'}

    artifact = service.maybe_persist_resource(
        "read_lesson_plan",
        {},
        result,
        query_terms=["导入", "复数"],
        round_index=2,
    )

    assert artifact is not None
    assert result["artifact_id"] == artifact.id
    assert isinstance(result["content"], str)
    assert service.repository.artifacts[0].source_tool == "read_lesson_plan"
    assert service.db.commit_count == 1
    assert artifact.id in service.context_pack


def test_read_resource_should_replace_long_content_with_descriptor() -> None:
    """教案/大纲长内容仍用描述符替换，避免回灌过大的正文。"""
    service = _make_memory_service(threshold=10)
    result = {"ok": True, "content": '{"plan_title": "很长的大纲内容"}'}

    artifact = service.maybe_persist_resource(
        "read_outline",
        {},
        result,
        query_terms=["导入", "复数"],
        round_index=2,
    )

    assert artifact is not None
    assert result["artifact_id"] == artifact.id
    assert isinstance(result["content"], dict)
    assert result["content"]["artifact_id"] == artifact.id
    assert result["content"]["total_chars"] == len('{"plan_title": "很长的大纲内容"}')
    assert "read_artifact" in result["content"]["tool_hint"]


def test_search_textbook_should_persist_lightweight_index_without_snippets() -> None:
    """教材检索只落轻量命中索引，不保存 snippets 或正文。"""
    service = _make_memory_service()
    result = {
        "ok": True,
        "query": "名词复数",
        "hits": [
            {
                "rank": 1,
                "semantic_chunk_id": 123,
                "page_start": 12,
                "page_end": 13,
                "chapter_title": "词法",
                "chunk_title": "名词复数",
                "score": 0.91,
                "content_chars": 900,
                "is_truncated": True,
                "snippets": [{"text": "正文窗口"}],
                "read_hint": "read_textbook_chunk(...)",
            }
        ],
    }

    artifact = service.persist_search_textbook_index({"query": "名词复数"}, result, round_index=2)
    payload = json.loads(artifact.content_text)

    assert artifact.source_tool == SEARCH_TEXTBOOK_INDEX_TOOL
    assert payload["query"] == "名词复数"
    assert payload["hits"][0]["semantic_chunk_id"] == 123
    assert "snippets" not in payload["hits"][0]
    assert "read_hint" not in payload["hits"][0]
    assert "正文窗口" not in artifact.content_text


def test_artifact_memory_messages_should_render_resource_and_search_indexes() -> None:
    """新 run system 上下文应包含可回读资源目录和最近教材检索 rank 映射。"""
    search_payload = {
        "query": "名词复数",
        "count": 1,
        "hits": [
            {
                "rank": 1,
                "semantic_chunk_id": 123,
                "page_start": 12,
                "page_end": 13,
                "chunk_title": "名词复数",
                "score": 0.91,
                "is_truncated": True,
            }
        ],
    }
    artifacts = [
        _FakeArtifact(
            artifact_id=1,
            source_tool="read_lesson_plan",
            content_text='{"lesson_title": "第1课"}',
            title="第 1 课次教案（v1）",
        ),
        _FakeArtifact(
            artifact_id=2,
            source_tool=SEARCH_TEXTBOOK_INDEX_TOOL,
            content_text=json.dumps(search_payload, ensure_ascii=False),
            title="教材检索：名词复数（1 条）",
        ),
    ]
    service = _make_memory_service(artifacts=artifacts)

    messages = service.render_artifact_memory_messages()

    assert len(messages) == 1
    text = messages[0]["content"]
    assert "会话历史可回读资源" in text
    assert "artifact_id=1" in text
    assert "read_artifact(1" in text
    assert "最近教材检索索引" in text
    assert "rank=1 -> semantic_chunk_id=123" in text
    assert "read_textbook_chunk" in text
