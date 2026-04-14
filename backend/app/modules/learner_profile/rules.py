"""
@Date: 2026-04-14
@Author: xisy
@Discription: 学情规则抽取能力
"""

import re
from dataclasses import dataclass


SUBJECT_NAME_TO_CODE = {
    "语文": "chinese",
    "数学": "math",
    "英语": "english",
    "科学": "science",
}
SUBJECT_CODE_TO_NAME = {value: key for key, value in SUBJECT_NAME_TO_CODE.items()}

ADVANTAGE_KEYWORDS = {
    "阅读理解较强": ["阅读理解", "关键信息", "感知力"],
    "表达能力较强": ["表达", "作文思路", "口语表达更加自信", "流畅地进行日常表达"],
    "计算能力较强": ["计算准确率高", "基础计算能力", "加减法掌握较扎实"],
    "逻辑思维较强": ["逻辑思维", "思维活跃", "举一反三", "解题思路灵活"],
    "专注力较强": ["专注力强", "长时间投入", "做事专注"],
}

WEAKNESS_KEYWORDS = {
    "阅读理解待提升": ["阅读理解因", "阅读理解得分率改善", "阅读理解和语法运用能力"],
    "写作表达待提升": ["看图写话", "作文", "表达能力"],
    "计算能力待提升": ["乘法口诀记忆尚不牢固", "计算题上失分", "计算能力"],
    "语法掌握待提升": ["时态混淆", "语法问题", "语法运用"],
    "综合应用待提升": ["逆向思维", "综合性大题", "压轴题", "应用题"],
    "口语表达待提升": ["口语表达", "听说能力", "语感"],
}

ABILITY_KEYWORDS = {
    "阅读能力": ["阅读", "阅读理解"],
    "计算能力": ["计算", "运算"],
    "逻辑能力": ["逻辑", "思维"],
    "表达能力": ["表达", "作文", "口语"],
    "专注能力": ["专注", "注意力"],
}

HABIT_KEYWORDS = {
    "作业完成及时": ["作业完成及时", "作业完成认真"],
    "存在粗心问题": ["粗心大意", "失分"],
    "自主学习意愿较强": ["自主学习意愿"],
    "学习方法待优化": ["缺乏系统性学习方法", "学习方法较为机械"],
}

BEHAVIOR_KEYWORDS = {
    "性格开朗": ["性格开朗"],
    "性格内敛": ["性格内敛沉稳"],
    "乐于交流": ["乐于与老师和同学交流"],
    "存在畏难情绪": ["畏难情绪"],
    "学习态度端正": ["学习态度端正"],
}


@dataclass(slots=True)
class LearnerProfileRecordDraft:
    """学情画像记录草稿。"""

    student_key: str
    student_name: str | None
    is_anonymous: int
    region_name: str | None
    grade_code: str | None
    subject_code: str
    textbook_version_name: str | None
    score_value: float | None
    summary_text: str | None
    evidence_json: dict
    advantage_tags_json: dict
    weakness_tags_json: dict
    ability_tags_json: dict
    habit_tags_json: dict
    behavior_traits_json: dict
    time_plan_json: dict


@dataclass(slots=True)
class LearnerProfileParseResult:
    """学情规则抽取结果。"""

    student_name: str | None
    region_name: str | None
    grade_code: str | None
    subject_scope: str | None
    summary_text: str
    raw_result_json: dict
    source_snapshot_json: dict
    records: list[LearnerProfileRecordDraft]


def parse_learner_profile_text(markdown_text: str, *, fallback_title: str, fallback_filename: str) -> LearnerProfileParseResult:
    """按赛题样例规则抽取学情结构化结果。"""
    normalized_text = _normalize_markdown_text(markdown_text)
    sections = _split_sections(normalized_text)
    basic_info = _parse_basic_info(sections.get("基本信息", ""))
    textbook_map = _parse_textbook_map(sections.get("使用教材", ""))
    score_map = _parse_score_map(sections.get("科目成绩", ""))
    description_text = sections.get("学生基本情况描述", "")
    time_plan_text = sections.get("培训时间规划", "")

    subject_names = _collect_subject_names(
        basic_info.get("学习科目"),
        list(textbook_map.keys()),
        list(score_map.keys()),
    )
    records: list[LearnerProfileRecordDraft] = []
    for sort_order, subject_name in enumerate(subject_names):
        subject_code = SUBJECT_NAME_TO_CODE.get(subject_name)
        if subject_code is None:
            continue
        summary_text = _build_subject_summary(subject_name, description_text, time_plan_text, score_map.get(subject_name))
        records.append(
            LearnerProfileRecordDraft(
                student_key=_build_student_key(basic_info.get("姓名") or fallback_filename, subject_code),
                student_name=basic_info.get("姓名") or fallback_title,
                is_anonymous=1 if "xx" in (basic_info.get("姓名") or "").lower() else 0,
                region_name=basic_info.get("所属地区"),
                grade_code=_normalize_grade_code(basic_info.get("年级")),
                subject_code=subject_code,
                textbook_version_name=textbook_map.get(subject_name),
                score_value=score_map.get(subject_name, {}).get("score"),
                summary_text=summary_text,
                evidence_json={
                    "subject_name": subject_name,
                    "score_line": score_map.get(subject_name, {}).get("raw_text"),
                    "textbook_version_name": textbook_map.get(subject_name),
                    "description_text": description_text,
                    "time_plan_text": time_plan_text,
                    "sort_order": sort_order,
                },
                advantage_tags_json={"items": _extract_tags(summary_text, ADVANTAGE_KEYWORDS)},
                weakness_tags_json={"items": _extract_tags(summary_text, WEAKNESS_KEYWORDS)},
                ability_tags_json={"items": _extract_tags(summary_text, ABILITY_KEYWORDS)},
                habit_tags_json={"items": _extract_tags(summary_text, HABIT_KEYWORDS)},
                behavior_traits_json={"items": _extract_tags(summary_text, BEHAVIOR_KEYWORDS)},
                time_plan_json={"items": _parse_time_plan_items(subject_name, time_plan_text)},
            )
        )

    summary_text = _build_global_summary(basic_info.get("姓名"), description_text, time_plan_text, fallback_title)
    return LearnerProfileParseResult(
        student_name=basic_info.get("姓名"),
        region_name=basic_info.get("所属地区"),
        grade_code=_normalize_grade_code(basic_info.get("年级")),
        subject_scope=",".join(record.subject_code for record in records) if records else None,
        summary_text=summary_text,
        raw_result_json={
            "basic_info": basic_info,
            "textbook_map": textbook_map,
            "score_map": score_map,
            "description_text": description_text,
            "time_plan_text": time_plan_text,
            "record_count": len(records),
        },
        source_snapshot_json={
            "title": fallback_title,
            "filename": fallback_filename,
            "sections": sections,
        },
        records=records,
    )


def _normalize_markdown_text(markdown_text: str) -> str:
    text = markdown_text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"^\s{0,3}#+\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"^[*-]\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def _split_sections(text: str) -> dict[str, str]:
    section_pattern = re.compile(r"([一二三四五六七八九十]+、)(基本信息|使用教材|科目成绩|学生基本情况描述|培训时间规划)")
    sections: dict[str, str] = {}
    current_section = "head"
    buffer: list[str] = []
    for line in text.splitlines():
        stripped_line = line.strip()
        if not stripped_line:
            continue
        matched = section_pattern.search(stripped_line)
        if matched:
            sections[current_section] = "\n".join(buffer).strip()
            current_section = matched.group(2)
            buffer = []
            continue
        buffer.append(stripped_line)
    sections[current_section] = "\n".join(buffer).strip()
    return sections


def _parse_basic_info(section_text: str) -> dict[str, str]:
    lines = [line.strip() for line in section_text.splitlines() if line.strip()]
    info: dict[str, str] = {}
    label_map = {"姓名", "所属地区", "地区", "年级", "学习科目"}
    index = 0
    while index < len(lines):
        current_line = lines[index]
        if current_line in label_map and index + 1 < len(lines):
            normalized_label = "所属地区" if current_line == "地区" else current_line
            info[normalized_label] = lines[index + 1]
            index += 2
            continue
        matched = re.match(r"^(姓名|所属地区|地区|年级|学习科目)[:：]\s*(.+)$", current_line)
        if matched:
            normalized_label = "所属地区" if matched.group(1) == "地区" else matched.group(1)
            info[normalized_label] = matched.group(2).strip()
        index += 1
    return info


def _parse_textbook_map(section_text: str) -> dict[str, str]:
    lines = [line.strip() for line in section_text.splitlines() if line.strip() and line.strip() not in {"科目", "教材版本"}]
    textbook_map: dict[str, str] = {}
    index = 0
    while index + 1 < len(lines):
        subject_name = lines[index]
        textbook_version_name = lines[index + 1]
        if subject_name in SUBJECT_NAME_TO_CODE:
            textbook_map[subject_name] = textbook_version_name
            index += 2
            continue
        index += 1
    return textbook_map


def _parse_score_map(section_text: str) -> dict[str, dict]:
    score_pattern = re.compile(
        r"(?P<subject>语文|数学|英语|科学)[:：]\s*(?P<score>\d+(?:\.\d+)?)分(?:（(?P<exam>[^）]+)）)?"
    )
    score_map: dict[str, dict] = {}
    for line in section_text.splitlines():
        matched = score_pattern.search(line.strip())
        if matched is None:
            continue
        score_map[matched.group("subject")] = {
            "score": float(matched.group("score")),
            "exam": matched.group("exam"),
            "raw_text": line.strip(),
        }
    return score_map


def _collect_subject_names(*subject_name_groups) -> list[str]:
    ordered_subjects: list[str] = []
    seen = set()
    for subject_group in subject_name_groups:
        if subject_group is None:
            continue
        if isinstance(subject_group, str):
            candidates = [item.strip() for item in re.split(r"[、,，/]", subject_group) if item.strip()]
        else:
            candidates = list(subject_group)
        for subject_name in candidates:
            if subject_name in SUBJECT_NAME_TO_CODE and subject_name not in seen:
                ordered_subjects.append(subject_name)
                seen.add(subject_name)
    return ordered_subjects


def _build_subject_summary(subject_name: str, description_text: str, time_plan_text: str, score_info: dict | None) -> str:
    sentences = _split_sentences(description_text)
    subject_sentences = [sentence for sentence in sentences if subject_name in sentence]
    if not subject_sentences:
        subject_sentences = sentences[:2]
    summary_parts: list[str] = []
    if score_info and score_info.get("raw_text"):
        summary_parts.append(score_info["raw_text"])
    summary_parts.extend(subject_sentences[:3])
    time_plan_sentences = [sentence for sentence in _split_sentences(time_plan_text) if subject_name in sentence]
    summary_parts.extend(time_plan_sentences[:2])
    return " ".join(item for item in summary_parts if item).strip()


def _build_global_summary(student_name: str | None, description_text: str, time_plan_text: str, fallback_title: str) -> str:
    summary_prefix = student_name or fallback_title
    summary_sentences = _split_sentences(description_text)[:3] + _split_sentences(time_plan_text)[:2]
    return f"{summary_prefix}学情摘要：" + " ".join(summary_sentences).strip()


def _extract_tags(text: str, mapping: dict[str, list[str]]) -> list[str]:
    tags: list[str] = []
    for tag_name, keywords in mapping.items():
        if any(keyword in text for keyword in keywords):
            tags.append(tag_name)
    return tags


def _parse_time_plan_items(subject_name: str, time_plan_text: str) -> list[dict]:
    items: list[dict] = []
    patterns = [
        re.compile(rf"每周安排(?P<count>\d+)次{subject_name}课（每次(?P<hours>[\d.]+)课时）"),
        re.compile(rf"{subject_name}每周(?P<count>\d+)次课（每次(?P<hours>[\d.]+)课时）"),
        re.compile(rf"{subject_name}每周(?P<count>\d+)次课"),
    ]
    expected_total_session_pattern = re.compile(r"预计(?:在接下来的)?(?P<count>\d+)次课程后|预计(?P<count_simple>\d+)次课后")
    for sentence in _split_sentences(time_plan_text):
        if subject_name not in sentence:
            continue
        item = {"subject_name": subject_name, "raw_text": sentence}
        for pattern in patterns:
            matched = pattern.search(sentence)
            if matched is None:
                continue
            if matched.groupdict().get("count"):
                item["lessons_per_week"] = int(matched.group("count"))
            if matched.groupdict().get("hours"):
                item["class_hours_per_session"] = float(matched.group("hours"))
            break
        expected_match = expected_total_session_pattern.search(sentence)
        if expected_match is not None:
            total_sessions = expected_match.group("count") or expected_match.group("count_simple")
            if total_sessions is not None:
                item["expected_total_sessions"] = int(total_sessions)
        items.append(item)
    return items


def _split_sentences(text: str) -> list[str]:
    raw_sentences = re.split(r"[。；!！?？\n]+", text)
    return [sentence.strip() for sentence in raw_sentences if sentence.strip()]


def _build_student_key(student_name: str, subject_code: str) -> str:
    normalized_name = re.sub(r"\W+", "_", student_name, flags=re.UNICODE).strip("_")
    return f"{normalized_name or 'student'}_{subject_code}"


def _normalize_grade_code(grade_text: str | None) -> str | None:
    if grade_text is None:
        return None
    grade_pattern = re.search(r"([一二三四五六])年级", grade_text)
    if grade_pattern is None:
        return grade_text.strip() or None
    grade_number_map = {"一": "1", "二": "2", "三": "3", "四": "4", "五": "5", "六": "6"}
    return f"grade_{grade_number_map[grade_pattern.group(1)]}"
