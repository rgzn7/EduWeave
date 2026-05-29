"""
@Date: 2026-05-29
@Author: xisy
@Discription: 智能助手系统提示词与上下文消息构建
"""

from __future__ import annotations

from typing import Any

AGENT_SYSTEM_PROMPT = """你是 EduWeave 的项目级备课智能助手，服务于教师的备课工作。你的能力：
1. 修改教学资源：列出本项目课程大纲（list_curricula），按课次读写教案（read_lesson_plan / write_lesson_plan），读写课程大纲（read_outline / write_outline）。
2. 教材知识问答：通过 search_textbook 在本项目教材中做混合检索，回答与教材知识相关的问题，并为修改提供依据。
3. 项目问答：基于大纲、教案与教材内容回答教师关于本项目备课的问题。

工作准则：
- 默认对象：当用户说「这个教案」「当前课次」等且未指明课次时，默认指「当前所在课次教案」（见下方上下文）。需要操作其他课次时显式传 class_session_no。
- 定位大纲：若下方没有「当前所在位置上下文」（如独立小助手单项目模式，仅锁定了项目范围），在读写教案/大纲前先调用 list_curricula 列出本项目课程大纲，结合用户意图选定一个，并把 curriculum_plan_id 传给后续工具；课次序号只在某个大纲内有意义，未定位大纲前不要凭课次序号直接读写。
- 先读后写：修改前务必先 read 取得完整结构化内容，在其基础上做局部修改，再以「完整 content_json」整体写回；不要凭空构造或省略字段。写入采用「新建版本」，会保留历史版本。
- 联动更新：当教案修改影响到大纲（如课次目标、知识点覆盖发生变化）时，主动同步更新大纲。
- 教材依据：涉及教材知识点、例题、定义等问题时，先 search_textbook 检索，引用时标注页码区间。
- 写入校验：content_json 必须符合资源结构规范；若写入返回校验错误，请依据错误信息修正后重试。
- 输出规范：用简体中文、Markdown 作答；完成修改后用简明语言向教师说明改了什么、为什么改。不要编造教材中不存在的内容。
"""


def build_location_context_text(
    *,
    project_title: str | None,
    project_id: int | None,
    curriculum_title: str | None,
    curriculum_plan_id: int | None,
    class_session_no: int | None,
    lesson_title: str | None,
) -> str | None:
    """构建「所在位置」上下文描述：课次/大纲上下文优先；仅项目范围时给出项目级提示。"""
    # 单项目模式：无课次/大纲上下文，仅锁定项目范围
    if curriculum_plan_id is None and class_session_no is None:
        if project_id is None:
            return None
        lines = ["[当前所在位置上下文]"]
        if project_title:
            lines.append(f"项目：{project_title}(project_id={project_id})")
        else:
            lines.append(f"项目 project_id={project_id}")
        lines.append(
            "当前仅锁定项目范围，未锁定具体课程大纲与课次。"
            "读写教案/大纲前请先调用 list_curricula 列出本项目大纲并选定 curriculum_plan_id。"
        )
        return "\n".join(lines)
    lines: list[str] = ["[当前所在位置上下文]"]
    if project_title:
        lines.append(f"项目：{project_title}")
    if curriculum_title:
        lines.append(f"课程大纲：《{curriculum_title}》(curriculum_plan_id={curriculum_plan_id})")
    if class_session_no is not None:
        session_desc = f"当前所在课次：第 {class_session_no} 课次"
        if lesson_title:
            session_desc += f"《{lesson_title}》"
        lines.append(session_desc)
        lines.append("未指明课次的「教案」操作默认指向以上当前课次。")
    else:
        lines.append("当前为大纲/项目视图，未锁定具体课次教案。")
    return "\n".join(lines)


def build_static_system_messages(location_context_text: str | None) -> list[dict[str, Any]]:
    """构建稳定前缀 system 消息（系统提示词 + 所在位置上下文）。"""
    messages: list[dict[str, Any]] = [{"role": "system", "content": AGENT_SYSTEM_PROMPT}]
    if location_context_text:
        messages.append({"role": "system", "content": location_context_text})
    return messages
