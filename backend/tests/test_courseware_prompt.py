"""
@Date: 2026-05-28
@Author: xisy
@Discription: 课件模块 Raccoon prompt 构造单元测试
"""

from types import SimpleNamespace

from app.modules.courseware.schemas import (
    SlideDeckGenerationResult,
    SlideDraft,
    SlideExampleBlock,
)
from app.modules.courseware.service import (
    RACCOON_PROMPT_MAX_CHARS,
    CoursewareService,
)


def _build_context(
    *,
    deck_title: str = "乘法分配律",
    lesson_summary: str = "本课围绕乘法分配律的含义与应用展开。",
) -> dict:
    """构造 build_raccoon_prompt 所需的最小上下文。"""
    project = SimpleNamespace(
        name="人教版三年级数学",
        subject_code="数学",
        grade_code="三年级",
        applicable_target="三年级学生",
    )
    generation_batch = SimpleNamespace(
        id=10,
        session_duration_minutes=40,
    )
    lesson_plan = SimpleNamespace(
        id=20,
        class_session_no=1,
        lesson_title=deck_title,
        summary_text=lesson_summary,
    )
    return {
        "project": project,
        "generation_batch": generation_batch,
        "lesson_plan": lesson_plan,
    }


def _build_deck(slide_count: int = 5, with_example: bool = True) -> SlideDeckGenerationResult:
    """构造覆盖封面+若干知识/例题/总结页的样例 deck。"""
    slides: list[SlideDraft] = [
        SlideDraft(slide_no=1, slide_type="cover", title="乘法分配律", bullet_points=[]),
    ]
    for index in range(2, slide_count):
        slides.append(
            SlideDraft(
                slide_no=index,
                slide_type="knowledge",
                title=f"知识点{index - 1}",
                bullet_points=[f"要点 A{index}", f"要点 B{index}", f"要点 C{index}"],
            )
        )
    if with_example:
        slides.append(
            SlideDraft(
                slide_no=slide_count,
                slide_type="example",
                title="例题",
                bullet_points=["按公式拆分", "代入计算"],
                example_block=SlideExampleBlock(
                    stem_text="计算 25 × 12 = 25 × (10 + 2)",
                    answer_text="300",
                    analysis_text="使用乘法分配律",
                ),
            )
        )
    else:
        slides.append(
            SlideDraft(
                slide_no=slide_count,
                slide_type="summary",
                title="本节小结",
                bullet_points=["回顾核心方法"],
            )
        )
    return SlideDeckGenerationResult(deck_title="乘法分配律", slides=slides)


def test_build_raccoon_prompt_emits_natural_language_summary() -> None:
    """新版 prompt 应输出自然语言需求摘要而非完整 JSON。"""
    deck = _build_deck()
    context = _build_context()

    prompt = CoursewareService.build_raccoon_prompt(context, deck)

    assert prompt.startswith("请生成一份中文课堂教学 PPT。")
    assert "主题：乘法分配律" in prompt
    assert "学科年级：数学 三年级" in prompt
    assert "适用对象：三年级学生" in prompt
    assert "课时：第 1 课时，约 40 分钟" in prompt
    assert f"页数：约 {len(deck.slides)} 页" in prompt
    assert "页面结构建议：" in prompt
    assert "1. [cover] 乘法分配律" in prompt
    assert "关键例题：" in prompt
    # 不应再包含完整 deck JSON 标志性字段
    assert "knowledge_point_refs" not in prompt
    assert "speaker_notes" not in prompt


def test_build_raccoon_prompt_respects_max_chars() -> None:
    """超长上下文应被压缩到 ≤2000 字。"""
    long_summary = "学情说明" * 800  # 远超 2000 字
    long_bullet = "教学重点要点扩展叙述" * 30
    slides = [SlideDraft(slide_no=1, slide_type="cover", title="封面页", bullet_points=[])]
    for idx in range(2, 22):
        slides.append(
            SlideDraft(
                slide_no=idx,
                slide_type="knowledge",
                title=f"知识点{idx}",
                bullet_points=[long_bullet, long_bullet, long_bullet],
            )
        )
    deck = SlideDeckGenerationResult(deck_title="长课件", slides=slides)
    context = _build_context(deck_title="长课件", lesson_summary=long_summary)

    prompt = CoursewareService.build_raccoon_prompt(context, deck)

    assert len(prompt) <= RACCOON_PROMPT_MAX_CHARS
    assert "请生成一份中文课堂教学 PPT。" in prompt
