"""
@Date: 2026-05-26
@Author: xisy
@Discription: 题目考查依据装配工具：把"题目 -> 知识点 -> 课次 -> 教学目标 -> 测评定位 -> 蓝图依据"链路聚合为接口可消费的字典
"""

from typing import Any, Literal

from app.modules.p0_models import ChapterNode, KnowledgePoint, LessonPlan

# 难度等级到测评定位的固定映射
DIFFICULTY_TO_ASSESSMENT_POSITION: dict[int, str] = {
    1: "基础掌握题",
    2: "基础掌握题",
    3: "典型应用题",
    4: "综合提升题",
    5: "综合提升题",
}

# difficulty_level 为空时的兜底定位
DEFAULT_ASSESSMENT_POSITION = "基础掌握题"

SceneType = Literal["assessment", "homework"]


def build_assessment_position(difficulty_level: int | None) -> str:
    """根据题目难度生成测评定位标签。"""
    if difficulty_level is None:
        return DEFAULT_ASSESSMENT_POSITION
    return DIFFICULTY_TO_ASSESSMENT_POSITION.get(int(difficulty_level), DEFAULT_ASSESSMENT_POSITION)


def build_basis_summary(
    *,
    scene: SceneType,
    knowledge_point_name: str,
    teaching_goal: str | None,
    assessment_position: str,
) -> str:
    """根据场景与可用上下文拼接 basis_summary。"""
    if scene == "homework":
        if teaching_goal:
            return f"围绕「{teaching_goal}」设计，用于巩固学生对「{knowledge_point_name}」的掌握情况。"
        return f"围绕本课教学目标设计，用于巩固学生对「{knowledge_point_name}」的掌握情况。"
    return f"作为{assessment_position}，用于检查学生对「{knowledge_point_name}」的掌握情况。"


def extract_first_teaching_goal(lesson_plan_content_json: dict[str, Any] | None) -> str | None:
    """从教案 content_json 中提取首个课次的首条教学目标。"""
    if not isinstance(lesson_plan_content_json, dict):
        return None
    session_plans = lesson_plan_content_json.get("session_plans")
    if not isinstance(session_plans, list) or not session_plans:
        return None
    first_session = session_plans[0]
    if not isinstance(first_session, dict):
        return None
    objectives = first_session.get("objectives")
    if not isinstance(objectives, list) or not objectives:
        return None
    first_objective = objectives[0]
    if not isinstance(first_objective, str) or not first_objective.strip():
        return None
    return first_objective.strip()


def find_lesson_plan_for_knowledge_point(
    lesson_plans: list[LessonPlan],
    knowledge_point_id: int,
) -> LessonPlan | None:
    """在一组教案中查找首个覆盖该知识点的教案。

    依次匹配两个位置：
      - content_json.knowledge_point_refs（教案整体引用）
      - content_json.session_plans[*].knowledge_point_refs（课次引用）
    """
    for lesson_plan in lesson_plans:
        content_json = lesson_plan.content_json
        if not isinstance(content_json, dict):
            continue
        top_refs = content_json.get("knowledge_point_refs")
        if isinstance(top_refs, list) and knowledge_point_id in top_refs:
            return lesson_plan
        session_plans = content_json.get("session_plans")
        if not isinstance(session_plans, list):
            continue
        for session in session_plans:
            if not isinstance(session, dict):
                continue
            refs = session.get("knowledge_point_refs")
            if isinstance(refs, list) and knowledge_point_id in refs:
                return lesson_plan
    return None


def index_blueprint_kp_weights(content_json: dict[str, Any] | None) -> dict[int, dict[str, Any]]:
    """把蓝图 content_json.knowledge_weights 转为 {kp_id: {weight_percent, suggested_question_count}}。"""
    if not isinstance(content_json, dict):
        return {}
    weights = content_json.get("knowledge_weights")
    if not isinstance(weights, list):
        return {}
    index: dict[int, dict[str, Any]] = {}
    for item in weights:
        if not isinstance(item, dict):
            continue
        kp_id = item.get("knowledge_point_id")
        if not isinstance(kp_id, int):
            continue
        index[kp_id] = {
            "weight_percent": item.get("weight_percent"),
            "suggested_question_count": item.get("suggested_question_count"),
        }
    return index


def build_question_basis_from_context(
    *,
    scene: SceneType,
    knowledge_point_id: int | None,
    knowledge_points_by_id: dict[int, KnowledgePoint],
    chapter_nodes_by_id: dict[int, ChapterNode],
    lesson_plans: list[LessonPlan],
    fixed_lesson_plan: LessonPlan | None,
    difficulty_level: int | None,
    blueprint_kp_weights: dict[int, dict[str, Any]],
    blueprint_type: str,
    blueprint_id: int | None,
) -> dict[str, Any] | None:
    """高阶装配入口：消费预取好的索引/列表，自行解析章节、课次、教学目标。

    - 课后作业：`fixed_lesson_plan` 传当前作业所属教案；本课只有一份教案，所有题目共用。
    - 测评：`fixed_lesson_plan` 传 None，由 `lesson_plans` 内查找首个引用该知识点的课次。
    """
    if knowledge_point_id is None:
        return None
    knowledge_point = knowledge_points_by_id.get(knowledge_point_id)
    if knowledge_point is None:
        return None
    chapter_node = (
        chapter_nodes_by_id.get(knowledge_point.chapter_node_id)
        if knowledge_point.chapter_node_id is not None
        else None
    )
    if fixed_lesson_plan is not None:
        lesson_plan = fixed_lesson_plan
    else:
        lesson_plan = find_lesson_plan_for_knowledge_point(lesson_plans, knowledge_point.id)
    teaching_goal = extract_first_teaching_goal(lesson_plan.content_json if lesson_plan else None)
    return build_question_basis(
        scene=scene,
        knowledge_point=knowledge_point,
        chapter_node=chapter_node,
        lesson_plan=lesson_plan,
        teaching_goal=teaching_goal,
        difficulty_level=difficulty_level,
        blueprint_kp_weights=blueprint_kp_weights,
        blueprint_type=blueprint_type,
        blueprint_id=blueprint_id,
    )


def build_question_basis(
    *,
    scene: SceneType,
    knowledge_point: KnowledgePoint | None,
    chapter_node: ChapterNode | None,
    lesson_plan: LessonPlan | None,
    teaching_goal: str | None,
    difficulty_level: int | None,
    blueprint_kp_weights: dict[int, dict[str, Any]],
    blueprint_type: str,
    blueprint_id: int | None,
) -> dict[str, Any] | None:
    """装配单题考查依据字典；缺失关联知识点时返回 None。"""
    if knowledge_point is None:
        return None

    assessment_position = build_assessment_position(difficulty_level)
    basis_summary = build_basis_summary(
        scene=scene,
        knowledge_point_name=knowledge_point.point_name,
        teaching_goal=teaching_goal,
        assessment_position=assessment_position,
    )

    basis: dict[str, Any] = {
        "knowledge_point_id": knowledge_point.id,
        "knowledge_point_name": knowledge_point.point_name,
        "knowledge_point_summary": knowledge_point.summary_text,
        "chapter_title": chapter_node.title if chapter_node is not None else None,
        "lesson_no": lesson_plan.class_session_no if lesson_plan is not None else None,
        "lesson_title": lesson_plan.lesson_title if lesson_plan is not None else None,
        "teaching_goal": teaching_goal,
        "assessment_position": assessment_position,
        "basis_summary": basis_summary,
    }

    source: dict[str, Any] = {"blueprint_type": blueprint_type}
    if blueprint_id is not None:
        source["blueprint_id"] = blueprint_id
    weight_entry = blueprint_kp_weights.get(knowledge_point.id)
    if weight_entry is not None:
        weight_percent = weight_entry.get("weight_percent")
        suggested_question_count = weight_entry.get("suggested_question_count")
        if weight_percent is not None:
            source["weight_percent"] = weight_percent
        if suggested_question_count is not None:
            source["suggested_question_count"] = suggested_question_count
    basis["source"] = source
    return basis
