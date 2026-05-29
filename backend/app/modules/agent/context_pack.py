"""
@Date: 2026-05-29
@Author: xisy
@Discription: 运行内长上下文装配器：把大段工件结构化为可继续推理的 run-local context pack
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

# 关键词检索停用词：高频虚词与指令词，命中无区分度
_QUERY_STOPWORDS = frozenset(
    {
        "的", "了", "是", "在", "和", "与", "及", "或", "我", "你", "他", "她", "它",
        "请", "帮", "把", "给", "要", "想", "这", "那", "个", "些", "一下", "一个",
        "什么", "怎么", "如何", "为什么", "可以", "需要", "应该", "进行", "通过",
        "对于", "关于", "以及", "等等", "一些", "这个", "那个", "现在", "然后",
        "the", "a", "an", "of", "to", "in", "on", "for", "and", "or", "is", "are",
        "be", "with", "as", "at", "by", "it", "this", "that", "please", "help",
    }
)

# 句子边界字符：把关键段落窗口吸附到自然边界
_SENTENCE_BOUNDARY_CHARS = "。！？!?\n；;"
_SENTENCE_SNAP_RANGE = 60
_EN_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9]+")
_CJK_RUN_RE = re.compile("[一-鿿]+")


@dataclass
class ContextPackEntry:
    """单个工件在 run-local context pack 中的结构化摘要。

    context pack 是 Run 内存态、不落库；事实记忆仍由 agent_artifact 工件库承担。
    本条目把工件全文压缩成「便于继续推理」的结构化视图。
    """

    artifact_id: int
    source_tool: str
    title: str
    total_chars: int
    digest_kind: str  # lesson_plan | outline | textbook | generic
    source_arguments: dict = field(default_factory=dict)
    key_passages: list[dict] = field(default_factory=list)
    structure_lines: list[str] = field(default_factory=list)
    passage_only: bool = False
    last_touched_round: int = 0


class AgentContextAssembler:
    """长上下文装配器：把工件全文构造成适合继续推理的结构化 context pack 条目。

    纯关键词检索，零外部依赖；所有方法对输入是确定性的。
    """

    def __init__(self, settings: Any) -> None:
        self.settings = settings

    # ------------------------------------------------------------------ #
    # 关键词检索
    # ------------------------------------------------------------------ #
    def extract_query_terms(self, prompt: str) -> list[str]:
        """从用户问题抽取检索关键词：英文单词 + 中文整串/3-gram/2-gram，去停用词。"""
        text = (prompt or "").strip()
        if not text:
            return []
        terms: list[str] = []
        seen: set[str] = set()

        def add(term: str) -> None:
            cleaned = term.strip().lower()
            if len(cleaned) < 2 or cleaned in _QUERY_STOPWORDS or cleaned in seen:
                return
            seen.add(cleaned)
            terms.append(cleaned)

        for match in _EN_WORD_RE.finditer(text):
            add(match.group(0))
        cjk_runs = _CJK_RUN_RE.findall(text)
        for run in cjk_runs:
            if 2 <= len(run) <= 8:
                add(run)
        for size in (3, 2):
            for run in cjk_runs:
                for index in range(len(run) - size + 1):
                    add(run[index : index + size])
        return terms[:24]

    def find_key_passages(
        self,
        content: str,
        terms: list[str],
        *,
        max_passages: int,
        passage_chars: int,
    ) -> list[dict]:
        """滑动窗口按关键词命中打分，返回 top-K 非重叠关键段落（含 offset）。"""
        if not content or not terms or max_passages <= 0:
            return []
        lowered = content.lower()
        content_len = len(content)
        window = max(passage_chars, 100)
        stride = max(window // 2, 1)
        scored: list[tuple[float, int]] = []
        position = 0
        while position < content_len:
            window_text = lowered[position : position + window]
            score = 0.0
            for term in terms:
                occurrences = window_text.count(term)
                if occurrences:
                    score += occurrences * len(term)
            if score > 0:
                scored.append((score, position))
            position += stride
        if not scored:
            return []
        scored.sort(key=lambda item: (-item[0], item[1]))
        passages: list[dict] = []
        used: list[tuple[int, int]] = []
        for score, start in scored:
            end = min(start + window, content_len)
            if any(not (end <= used_start or start >= used_end) for used_start, used_end in used):
                continue
            snapped_start, snapped_end = self._snap_to_sentence(content, start, end)
            passages.append(
                {
                    "offset": snapped_start,
                    "length": snapped_end - snapped_start,
                    "text": content[snapped_start:snapped_end],
                    "score": round(score, 2),
                }
            )
            used.append((start, end))
            if len(passages) >= max_passages:
                break
        passages.sort(key=lambda item: item["offset"])
        return passages

    @staticmethod
    def _snap_to_sentence(content: str, start: int, end: int) -> tuple[int, int]:
        """把窗口起止吸附到最近的句子边界，避免段落从句中截断。"""
        snapped_start = start
        lookback_limit = max(0, start - _SENTENCE_SNAP_RANGE)
        for index in range(start - 1, lookback_limit - 1, -1):
            if content[index] in _SENTENCE_BOUNDARY_CHARS:
                snapped_start = index + 1
                break
        snapped_end = end
        lookahead_limit = min(len(content), end + _SENTENCE_SNAP_RANGE)
        for index in range(end, lookahead_limit):
            if content[index] in _SENTENCE_BOUNDARY_CHARS:
                snapped_end = index + 1
                break
        if snapped_end <= snapped_start:
            return start, end
        return snapped_start, snapped_end

    # ------------------------------------------------------------------ #
    # 条目装配
    # ------------------------------------------------------------------ #
    def build_entry(
        self,
        *,
        artifact_id: int,
        source_tool: str,
        source_arguments: dict,
        title: str,
        content: str,
        query_terms: list[str],
        round_index: int,
    ) -> ContextPackEntry:
        """构造大段工件条目：教案/大纲给结构概览，其余给关键命中段落。"""
        structure_lines: list[str] = []
        digest_kind = "generic"
        if source_tool == "read_lesson_plan":
            digest_kind = "lesson_plan"
            structure_lines = self._lesson_plan_structure_lines(content)
        elif source_tool == "read_outline":
            digest_kind = "outline"
            structure_lines = self._outline_structure_lines(content)
        elif source_tool == "search_textbook":
            digest_kind = "textbook"

        key_passages = self.find_key_passages(
            content,
            query_terms,
            max_passages=self.settings.agent_context_pack_max_passages,
            passage_chars=self.settings.agent_context_pack_passage_chars,
        )
        if not structure_lines and not key_passages and content:
            head_len = min(len(content), self.settings.agent_context_pack_passage_chars)
            key_passages = [{"offset": 0, "length": head_len, "text": content[:head_len], "score": 0.0}]
        return ContextPackEntry(
            artifact_id=artifact_id,
            source_tool=source_tool,
            source_arguments=source_arguments or {},
            title=title,
            total_chars=len(content),
            digest_kind=digest_kind,
            structure_lines=structure_lines,
            key_passages=key_passages,
            last_touched_round=round_index,
        )

    def build_warm_start_entry(
        self,
        *,
        artifact_id: int,
        source_tool: str,
        source_arguments: dict,
        title: str,
        content: str,
        query_terms: list[str],
        round_index: int,
    ) -> ContextPackEntry | None:
        """跨 Run 预热：仅按新问题检索关键命中段落，无命中返回 None。"""
        passages = self.find_key_passages(
            content,
            query_terms,
            max_passages=self.settings.agent_context_pack_max_passages,
            passage_chars=self.settings.agent_context_pack_passage_chars,
        )
        if not passages:
            return None
        return ContextPackEntry(
            artifact_id=artifact_id,
            source_tool=source_tool,
            source_arguments=source_arguments or {},
            title=title,
            total_chars=len(content),
            digest_kind="generic",
            key_passages=passages,
            passage_only=True,
            last_touched_round=round_index,
        )

    @staticmethod
    def _lesson_plan_structure_lines(content: str) -> list[str]:
        """从教案工件 JSON 提取课次/教学环节概览。"""
        try:
            payload = json.loads(content)
        except (ValueError, TypeError):
            return []
        if not isinstance(payload, dict):
            return []
        lines: list[str] = []
        if payload.get("lesson_title"):
            lines.append(f"教案标题：{payload.get('lesson_title')}")
        for step in payload.get("teaching_flow") or []:
            if isinstance(step, dict):
                lines.append(f"行课环节 {step.get('step_no')}：{step.get('stage_name')}")
        for session in payload.get("session_plans") or []:
            if isinstance(session, dict):
                lines.append(f"课次 {session.get('session_no')}：{session.get('title')}")
        return lines

    @staticmethod
    def _outline_structure_lines(content: str) -> list[str]:
        """从大纲工件 JSON 提取课次安排概览。"""
        try:
            payload = json.loads(content)
        except (ValueError, TypeError):
            return []
        if not isinstance(payload, dict):
            return []
        lines: list[str] = []
        if payload.get("plan_title"):
            lines.append(f"大纲标题：{payload.get('plan_title')}")
        for session in payload.get("lesson_sessions") or []:
            if isinstance(session, dict):
                lines.append(f"课次 {session.get('session_no')}：{session.get('title')}")
        return lines

    # ------------------------------------------------------------------ #
    # 渲染
    # ------------------------------------------------------------------ #
    def render(self, entries: list[ContextPackEntry], *, budget_chars: int) -> str:
        """把 context pack 条目渲染为单条 system 消息文本，超预算逐级降级。"""
        if not entries:
            return ""
        ordered = sorted(
            entries,
            key=lambda item: (item.last_touched_round, item.artifact_id),
            reverse=True,
        )
        header = (
            "[运行上下文包]\n"
            "本会话本轮已读取以下大段内容的结构化摘要，可直接用于推理；\n"
            "需要逐字精确内容时调用 read_artifact(artifact_id, offset, length)。\n\n"
        )
        body = ""
        for level in ("full", "no_passages", "structure_only"):
            body = "\n\n".join(self._render_entry(entry, level) for entry in ordered)
            text = header + body
            if len(text) <= budget_chars:
                return text
        return (header + body)[: max(budget_chars - 24, 200)] + "\n…(运行上下文包已截断)"

    def _render_entry(self, entry: ContextPackEntry, level: str) -> str:
        """渲染单个 context pack 条目。level 控制降级粒度。"""
        tag = "（来自历史工件检索）" if entry.passage_only else ""
        parts: list[str] = [
            f"# artifact_id={entry.artifact_id} | {entry.title} | total_chars={entry.total_chars}{tag}"
        ]
        if entry.structure_lines and level in ("full", "no_passages", "structure_only"):
            parts.append("结构概览：")
            parts.extend(f"  {line}" for line in entry.structure_lines)
        if entry.key_passages and level == "full":
            parts.append("关键命中段落（与当前问题相关）：")
            for passage in entry.key_passages:
                passage_text = str(passage.get("text") or "").replace("\n", " ").strip()
                parts.append(
                    f"  [offset={passage.get('offset')} length={passage.get('length')}] {passage_text}"
                )
        parts.append(f"继续读取：read_artifact({entry.artifact_id}, <offset>, <length>)")
        return "\n".join(parts)
