# Phase 3：题目考查依据后端接口对接说明

## 背景

比赛要求里明确提到：

- 建立测试权重，即提取教材中的知识点矩阵，并根据教学目标设定各章节的考查权重。
- 构建科学的测评蓝图，确保题目生成有据可依。
- 通过对比生成题目与教材原始知识点，可视化展示考点覆盖是否全面、难度分布是否合理。

当前题目详情页只能展示“已关联知识点”。这只能说明题目有 `knowledge_point_id`，但不能说明这道题为什么被生成、对应哪个教学目标、属于什么测评定位，也不能充分体现“题目生成有据可依”。

## 目标

后端在测评题目和课后作业题目接口中补充“题目考查依据”字段，让前端可以把每道题背后的生成依据展示出来。

目标展示效果：

```text
第 1 题 / 单选题 / 基础掌握 / 考查：大月小月判断

考查依据
教材知识点：大月、小月与月份分类
所属课次：第 1 课 年、月、日与日期推算
教学目标：能准确判断 1-12 月中哪些月份是大月、小月
测评定位：基础掌握题，用于检查日期推算前置知识是否牢固
```

## 非目标

- 不要求把后端内部 prompt、模型调用、任务日志暴露给前端。
- 不要求前端解析 `source_trace_json` 原始结构。
- 不要求每道题显示复杂的工程字段，例如 `knowledge_point_id=123`。
- 不要求第一版必须新增数据库字段；可以优先通过接口响应聚合现有数据。

## 当前后端基础

当前后端已经具备以下数据：

- 题目表
  - `question_item.knowledge_point_id`
  - `question_item.question_type`
  - `question_item.difficulty_level`
  - `question_item.source_trace_json`
  - `homework_question.knowledge_point_id`
  - `homework_question.question_type`
  - `homework_question.difficulty_level`
  - `homework_question.source_trace_json`
- 知识点表
  - `knowledge_point.point_name`
  - `knowledge_point.summary_text`
  - `knowledge_point.importance_level`
  - `knowledge_point.difficulty_level`
  - `knowledge_point.mastery_level_hint`
  - `knowledge_point.chapter_node_id`
- 教案和课程大纲
  - `lesson_plan.class_session_no`
  - `lesson_plan.lesson_title`
  - `lesson_plan.content_json`
  - `curriculum_plan.content_json`
- 测评蓝图 / 作业蓝图
  - `assessment_blueprint.content_json.strategy_summary`
  - `assessment_blueprint.content_json.knowledge_weights`
  - `assessment_blueprint.content_json.question_type_distribution`
  - `assessment_blueprint.content_json.difficulty_distribution`
  - `homework_blueprint.content_json`

当前缺口是：这些数据没有被包装成题目级、面向用户展示的“考查依据”。

## 建议新增响应字段

在以下响应中新增字段：

- `QuestionItemResponse`
- `QuestionItemListItemResponse`
- `PaperResultDetailResponse.questions[]`
- `HomeworkQuestionResponse`
- `HomeworkQuestionListItemResponse`
- `HomeworkResultDetailResponse.questions[]`

建议字段：

```python
knowledge_point_name: str | None
question_basis_json: dict[str, Any] | None
```

其中 `knowledge_point_name` 用于替换前端当前的“已关联知识点”标签。

`question_basis_json` 用于展示“考查依据”详情。

## question_basis_json 结构建议

```json
{
  "knowledge_point_id": 123,
  "knowledge_point_name": "大月、小月与月份分类",
  "knowledge_point_summary": "认识 1-12 月中大月、小月和特殊月份二月。",
  "chapter_title": "年、月、日与日期推算",
  "lesson_no": 1,
  "lesson_title": "年、月、日与日期推算",
  "teaching_goal": "能准确判断 1-12 月中哪些月份是大月、小月。",
  "assessment_position": "基础掌握题",
  "basis_summary": "用于检查学生是否掌握日期推算前置知识。",
  "source": {
    "blueprint_type": "homework",
    "blueprint_id": 1,
    "weight_percent": 16.67,
    "suggested_question_count": 1
  }
}
```

字段说明：

| 字段 | 说明 | 是否必需 |
| --- | --- | --- |
| `knowledge_point_id` | 题目关联知识点 ID | 是 |
| `knowledge_point_name` | 知识点名称 | 是 |
| `knowledge_point_summary` | 知识点摘要 | 否 |
| `chapter_title` | 所属章节 / 教材单元 | 否 |
| `lesson_no` | 所属课次 | 否 |
| `lesson_title` | 所属课题 | 否 |
| `teaching_goal` | 对应教学目标 | 否 |
| `assessment_position` | 测评定位，如基础掌握、典型应用、综合提升 | 是 |
| `basis_summary` | 给老师看的自然语言依据说明 | 是 |
| `source` | 蓝图来源信息，用于开发和可选展示 | 否 |

## 字段生成建议

### 1. knowledge_point_name

由 `knowledge_point_id` join `knowledge_point` 得到。

如果没有关联知识点，返回 `null`。

### 2. knowledge_point_summary

优先使用：

```text
knowledge_point.summary_text
```

如果为空，可以回退为空，不需要强行生成。

### 3. chapter_title

优先从知识点关联的章节节点获取。

如果 V1 获取章节标题成本较高，可以先不返回。

### 4. lesson_no / lesson_title

课后作业题目：

- 直接使用 `homework_question.lesson_plan_id` 找到 `lesson_plan`
- 返回 `lesson_plan.class_session_no`
- 返回 `lesson_plan.lesson_title`

测评题目：

- 如果能根据知识点引用反查到覆盖该知识点的课次，则返回对应课次。
- 如果一个知识点被多课覆盖，可以返回最相关课次，或暂时不返回。
- V1 可优先只返回 `knowledge_point_name` 和 `basis_summary`。

### 5. teaching_goal

优先从对应 `lesson_plan.content_json` 中提取教学目标。

如果没有课次映射，可以从 `curriculum_plan.content_json` 中提取课程目标或阶段目标。

如果结构不稳定，V1 可以先返回 `null`。

### 6. assessment_position

可根据 `difficulty_level` 做稳定映射：

| difficulty_level | assessment_position |
| --- | --- |
| 1 | 基础掌握题 |
| 2 | 基础掌握题 |
| 3 | 典型应用题 |
| 4 | 综合提升题 |
| 5 | 综合提升题 |

后续如果蓝图中已有更准确的定位字段，可以优先使用蓝图字段。

### 7. basis_summary

V1 可以先用模板拼接，不必重新调用模型。

模板示例：

```text
用于检查学生对「{knowledge_point_name}」的掌握情况。
```

如果有教学目标：

```text
围绕「{teaching_goal}」设计，检查学生对「{knowledge_point_name}」的掌握情况。
```

如果有测评定位：

```text
作为{assessment_position}，用于检查学生对「{knowledge_point_name}」的掌握情况。
```

## 示例响应

### 测评题目

```json
{
  "id": 1,
  "paper_result_id": 1,
  "knowledge_point_id": 123,
  "knowledge_point_name": "大月、小月与月份分类",
  "question_no": 1,
  "question_type": "single_choice",
  "difficulty_level": 1,
  "stem_text": "课后制作“大月小月记忆卡”时，下面哪一组月份都是大月？",
  "options_json": {
    "A": "1月、3月、5月",
    "B": "4月、6月、9月",
    "C": "2月、6月、11月",
    "D": "9月、10月、12月"
  },
  "answer_text": "A",
  "analysis_text": "大月每月有31天，包括1月、3月、5月、7月、8月、10月、12月。A组中的1月、3月、5月都是大月。",
  "question_basis_json": {
    "knowledge_point_id": 123,
    "knowledge_point_name": "大月、小月与月份分类",
    "knowledge_point_summary": "认识 1-12 月中大月、小月和特殊月份二月。",
    "chapter_title": "年、月、日与日期推算",
    "lesson_no": 1,
    "lesson_title": "年、月、日与日期推算",
    "teaching_goal": "能准确判断 1-12 月中哪些月份是大月、小月。",
    "assessment_position": "基础掌握题",
    "basis_summary": "作为基础掌握题，用于检查学生对「大月、小月与月份分类」的掌握情况。",
    "source": {
      "blueprint_type": "assessment",
      "blueprint_id": 1,
      "weight_percent": 10,
      "suggested_question_count": 1
    }
  }
}
```

### 课后作业题目

```json
{
  "id": 1,
  "homework_result_id": 1,
  "lesson_plan_id": 1,
  "knowledge_point_id": 123,
  "knowledge_point_name": "大月、小月与月份分类",
  "question_no": 1,
  "question_type": "single_choice",
  "difficulty_level": 1,
  "question_basis_json": {
    "knowledge_point_id": 123,
    "knowledge_point_name": "大月、小月与月份分类",
    "lesson_no": 1,
    "lesson_title": "年、月、日与日期推算",
    "teaching_goal": "能准确判断 1-12 月中哪些月份是大月、小月。",
    "assessment_position": "基础掌握题",
    "basis_summary": "围绕本课教学目标设计，用于巩固学生对「大月、小月与月份分类」的掌握情况。",
    "source": {
      "blueprint_type": "homework",
      "blueprint_id": 1
    }
  }
}
```

## 前端展示建议

前端拿到字段后：

1. 顶部标签从“已关联知识点”改为：

```text
考查：大月、小月与月份分类
```

2. 题目卡片中增加“考查依据”区域：

```text
考查依据
教材知识点：大月、小月与月份分类
所属课次：第 1 课 年、月、日与日期推算
教学目标：能准确判断 1-12 月中哪些月份是大月、小月
测评定位：基础掌握题，用于检查日期推算前置知识是否牢固
```

3. 不展示原始 ID，除非开发调试模式。

## V1 实现建议

V1 不建议新增表字段，优先做接口聚合：

1. 在题目查询时根据 `knowledge_point_id` 批量查询知识点。
2. 课后作业题目根据 `lesson_plan_id` 查询课次和教案标题。
3. 测评题目根据 `paper_result.assessment_blueprint_id` 找到测评蓝图。
4. 从蓝图 `content_json.knowledge_weights` 中找到当前知识点对应的权重信息。
5. 组装 `knowledge_point_name` 和 `question_basis_json` 后返回。

V1 最低可交付字段：

```json
{
  "knowledge_point_name": "大月、小月与月份分类",
  "question_basis_json": {
    "knowledge_point_id": 123,
    "knowledge_point_name": "大月、小月与月份分类",
    "assessment_position": "基础掌握题",
    "basis_summary": "作为基础掌握题，用于检查学生对「大月、小月与月份分类」的掌握情况。"
  }
}
```

这样前端就可以先把“已关联知识点”替换掉。

## V2 实现建议

如果希望后续导出、回放、审计都复用同一份依据，可以考虑新增持久化字段：

- `question_item.question_basis_json`
- `homework_question.question_basis_json`

或者复用并规范化现有字段：

- `question_item.source_trace_json`
- `homework_question.source_trace_json`

如果复用 `source_trace_json`，建议明确结构，不要继续让它成为任意 JSON：

```json
{
  "knowledge_point": {
    "id": 123,
    "name": "大月、小月与月份分类",
    "summary": "认识 1-12 月中大月、小月和特殊月份二月。"
  },
  "lesson": {
    "no": 1,
    "title": "年、月、日与日期推算"
  },
  "teaching_goal": "能准确判断 1-12 月中哪些月份是大月、小月。",
  "assessment_position": "基础掌握题",
  "basis_summary": "作为基础掌握题，用于检查学生对「大月、小月与月份分类」的掌握情况。"
}
```

## 验收标准

- 题目详情接口不再只返回 `knowledge_point_id`。
- 至少返回 `knowledge_point_name`，前端不再显示“已关联知识点”。
- 至少返回 `question_basis_json.assessment_position` 和 `question_basis_json.basis_summary`。
- 课后作业题目能返回所属课次和课题。
- 测评题目能返回蓝图来源或知识点权重信息。
- 前端能展示“考查依据”区域，体现题目与教材知识点、教学目标、测评蓝图之间的关系。
- 普通用户页面不展示后端内部 ID、JSON 原文或模型调用细节。

## 给后端的一句话

请把“题目 -> 知识点 -> 课次 / 教学目标 -> 测评定位 -> 蓝图依据”的链路包装成 `question_basis_json`，让前端能把现在的“已关联知识点”升级为可解释的“考查依据”。
