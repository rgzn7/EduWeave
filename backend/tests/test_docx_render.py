"""
@Date: 2026-05-27
@Author: xisy
@Discription: DOCX 渲染器与文件名工具的单元测试，覆盖字段隐藏、知识点名称替换、标题清洗等行为
"""

from io import BytesIO
from types import SimpleNamespace
from zipfile import ZipFile

from app.shared.document.naming import build_docx_filename, safe_filename_stem, strip_lesson_prefix
from app.shared.document.service import DocxRenderService

# 渲染层不应再泄露给老师的英文键 / 内部字段
_LEAKED_KEYS = (
    "single_choice",
    "fill_blank",
    "short_answer",
    "focus",
    "audience",
    "duration",
    "teaching_style",
    "review",
    "parent_communication",
    "source_trace",
    "question_type_distribution",
    "difficulty_distribution",
    "knowledge_point_refs",
)


def _extract_xml(content: bytes) -> str:
    """从 DOCX 字节中抽取主体 XML 文本。"""
    with ZipFile(BytesIO(content)) as archive:
        return archive.read("word/document.xml").decode("utf-8")


def _assert_no_leaked_keys(xml: str) -> None:
    """断言渲染结果不再出现内部英文字段名。"""
    for key in _LEAKED_KEYS:
        assert key not in xml, f"DOCX 不应出现内部字段 {key}"


def _build_lesson_plan_fixture() -> SimpleNamespace:
    """构造一个完整的教案对象，覆盖 teaching_flow + session_plans + after_class_plan。"""
    return SimpleNamespace(
        lesson_title="第12讲 方向、数据整理与综合思维提升教案",
        summary_text="围绕方向感知与数据整理组织 60 分钟课堂。",
        class_session_no=12,
        content_json={
            "course_overview": {
                "focus": "方向辨别",
                "audience": "三年级学生",
                "duration": "60 分钟",
                "teaching_style": "讲练结合",
                "extra_unknown_field": "应被隐藏",
            },
            "material_list": ["指南针 1 个", "学生练习册"],
            "core_knowledge": ["东南西北辨别", "条形图阅读"],
            "teaching_flow": [
                {
                    "step_no": 1,
                    "stage_name": "导入",
                    "duration_minutes": 10,
                    "teacher_actions": ["用故事引入方向辨别"],
                    "student_activities": ["跟随教师指出方向"],
                    "knowledge_point_refs": [101, 102],
                }
            ],
            "session_plans": [
                {
                    "session_no": 12,
                    "title": "第12讲 方向、数据整理与综合思维提升",
                    "objectives": ["能辨别东南西北", "能读取条形图"],
                    "teaching_focus": ["方向辨别", "条形图阅读"],
                    "teaching_steps": [
                        {
                            "step_no": 1,
                            "stage_name": "讲解",
                            "duration_minutes": 20,
                            "teacher_actions": ["示范辨别方向"],
                            "student_activities": ["跟随练习"],
                            "knowledge_point_refs": [101],
                        }
                    ],
                    "homework": ["完成条形图练习"],
                    "knowledge_point_refs": [101, 102],
                }
            ],
            "after_class_plan": {
                "review": "复习东南西北",
                "homework": ["完成练习册第 12 课"],
                "parent_communication": "家长协助检查练习",
                "internal_note": "应被隐藏",
            },
            "learner_adjustments": ["对基础薄弱学生增加图示练习"],
            "knowledge_point_refs": [101, 102],
        },
    )


def _build_paper_result_fixture() -> tuple[SimpleNamespace, list[SimpleNamespace]]:
    """构造试卷结果对象与题目列表。"""
    paper_result = SimpleNamespace(
        title="第12讲 方向、数据整理与综合思维提升单元测试",
        scene_type="unit_test",
        question_count=2,
        paper_json={
            "question_type_distribution": {"single_choice": 1, "fill_blank": 1},
            "difficulty_distribution": {"2": 1, "3": 1},
        },
    )
    questions = [
        SimpleNamespace(
            question_no=1,
            question_type="single_choice",
            difficulty_level=2,
            score_value=10,
            stem_text="下列哪个方向是太阳升起的方位？",
            options_json={"A": "东", "B": "西", "C": "南", "D": "北"},
            answer_text="A",
            analysis_text="太阳从东方升起。",
            knowledge_point_name="方向辨别",
        ),
        SimpleNamespace(
            question_no=2,
            question_type="fill_blank",
            difficulty_level=3,
            score_value=10,
            stem_text="条形图的横轴通常表示______。",
            options_json=None,
            answer_text="类别",
            analysis_text="条形图横轴通常表示分类。",
            knowledge_point_name=None,
        ),
    ]
    return paper_result, questions


def test_render_lesson_plan_should_hide_internal_keys_and_resolve_knowledge_points() -> None:
    """教案 DOCX 不应暴露英文字段或裸 ID，知识点列应使用名称。"""
    lesson_plan = _build_lesson_plan_fixture()
    kp_names = {101: "方向辨别", 102: "数据整理"}
    content = DocxRenderService().render_lesson_plan(lesson_plan, knowledge_point_names=kp_names)
    xml = _extract_xml(content)

    _assert_no_leaked_keys(xml)
    # 标题应去除「第N讲」前缀
    assert "方向、数据整理与综合思维提升教案" in xml
    assert "第12讲 方向、数据整理与综合思维提升教案" not in xml
    # 课次以人类可读形式呈现
    assert "第 12 讲" in xml
    # 课程概述按中文标签输出，未知键被丢弃
    assert "教学重点" in xml
    assert "适用学情" in xml
    assert "应被隐藏" not in xml
    # 课后安排按中文标签输出
    assert "复习巩固" in xml
    assert "家校沟通" in xml
    # 教学流程「知识点」列使用名称替代 ID，不应出现纯数字 ID
    assert "方向辨别" in xml
    assert "数据整理" in xml
    assert ">101<" not in xml
    assert ">102<" not in xml


def test_render_paper_result_should_translate_enums_and_drop_source_trace() -> None:
    """试卷 DOCX 题型/难度应转中文，选项以 A./B. 渲染，且不再展示来源摘要。"""
    paper_result, questions = _build_paper_result_fixture()
    content = DocxRenderService().render_paper_result(paper_result, questions)
    xml = _extract_xml(content)

    _assert_no_leaked_keys(xml)
    # 标题剥离前缀
    assert "方向、数据整理与综合思维提升单元测试" in xml
    assert "第12讲 方向、数据整理与综合思维提升单元测试" not in xml
    # 场景与题型走中文枚举
    assert "单元测试" in xml
    assert "单选题" in xml
    assert "填空题" in xml
    # 难度走星级
    assert "★★" in xml
    # 选项以 A./B. 渲染
    assert "A. 东" in xml
    assert "D. 北" in xml
    # 知识点名称在题目段中出现
    assert "方向辨别" in xml
    # 来源摘要不应输出
    assert "来源摘要" not in xml


def test_render_homework_result_should_use_chinese_labels_and_strip_prefix() -> None:
    """作业 DOCX 应去掉课次前缀、题型走中文、并展示所属教案名。"""
    homework_result = SimpleNamespace(
        title="第12讲 方向、数据整理与综合思维提升课后作业",
        question_count=1,
        content_json={
            "scene_type": "homework",
            "question_type_distribution": {"single_choice": 1},
            "difficulty_distribution": {"1": 1},
        },
    )
    lesson_plan = SimpleNamespace(class_session_no=12, lesson_title="第12讲 方向、数据整理与综合思维提升教案")
    questions = [
        SimpleNamespace(
            question_no=1,
            question_type="single_choice",
            difficulty_level=1,
            score_value=5,
            stem_text="下列哪个图属于条形图？",
            options_json={"A": "条形图", "B": "饼图"},
            answer_text="A",
            analysis_text="条形图以矩形长度表示数量。",
            knowledge_point_name="数据整理",
        )
    ]
    content = DocxRenderService().render_homework_result(homework_result, questions, lesson_plan=lesson_plan)
    xml = _extract_xml(content)

    _assert_no_leaked_keys(xml)
    assert "方向、数据整理与综合思维提升课后作业" in xml
    assert "第12讲 方向、数据整理与综合思维提升课后作业" not in xml
    assert "课后作业" in xml
    assert "单选题" in xml
    assert "A. 条形图" in xml
    # 所属教案也需剥离前缀
    assert "方向、数据整理与综合思维提升教案" in xml
    assert "数据整理" in xml


def test_strip_lesson_prefix_should_handle_common_patterns() -> None:
    """剥离前缀工具应覆盖中文/阿拉伯数字、带破折号或冒号的形态。"""
    assert strip_lesson_prefix("第12讲 方向感知") == "方向感知"
    assert strip_lesson_prefix("第十二讲：方向感知") == "方向感知"
    assert strip_lesson_prefix("第1课 - 方向感知") == "方向感知"
    assert strip_lesson_prefix("方向感知") == "方向感知"
    assert strip_lesson_prefix("") == ""
    assert strip_lesson_prefix(None) == ""


def test_safe_filename_stem_should_drop_invalid_chars_and_fallback() -> None:
    """文件名清洗：剔除非法字符，空内容回退默认值。"""
    assert safe_filename_stem("方向/数据*整理") == "方向数据整理"
    assert safe_filename_stem("   ") == "导出"
    assert safe_filename_stem("方向?<>|:\"\\感知") == "方向感知"
    assert safe_filename_stem(None, fallback="兜底") == "兜底"


def test_build_docx_filename_should_join_segments_and_drop_empty() -> None:
    """文件名构造应按 `-` 拼接、跳过空段，并加 .docx 后缀。"""
    assert (
        build_docx_filename("方向、数据整理与综合思维提升", "第12讲", "教案")
        == "方向、数据整理与综合思维提升-第12讲-教案.docx"
    )
    assert (
        build_docx_filename("方向、数据整理与综合思维提升", None, "课后作业")
        == "方向、数据整理与综合思维提升-课后作业.docx"
    )
    assert build_docx_filename("", None, fallback="导出") == "导出.docx"
