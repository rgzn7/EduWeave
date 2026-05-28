# 生成过程进度与摘要后端改造说明

## 背景

项目页 `/projects/{project_id}` 当前展示 6 个主流程步骤：

1. 教材内容解析
2. 学情信息分析
3. 重组教学内容
4. 整套课程规划
5. 多课时教案生成
6. 校验知识覆盖

现有页面能展示步骤状态和百分比，但用户感知上存在两个问题：

- 进度经常以固定跳点推进，例如 `40 -> 75 -> 100`，长时间卡在某个数字后突然完成。
- 完成态摘要信息偏少，例如只显示“已完成教材结构、页码与内容识别，共 114 页”，没有说明识别了哪些可用于后续生成的关键结果。

本说明基于当前后端代码现状，目标是让后端提供更真实、可复用的进度详情和结果指标，前端负责把这些信息展示得更自然。

## 当前代码现状

### generation-process 聚合接口信息不足

当前 `GenerationProcessStepResponse` 只返回：

- `code`
- `display_name`
- `description`
- `status`
- `status_detail`
- `progress_percent`
- `summary`
- `started_at`
- `finished_at`
- `error_message`

见 `backend/app/modules/generation_process/schemas.py:30`。

`GenerationProcessService._build_step_response()` 目前直接使用 `task.progress_percent`，没有透出 `task.current_stage`，也没有透出 `task_step_record.detail_json`：

- `backend/app/modules/generation_process/service.py:255`
- `backend/app/modules/generation_process/service.py:276`
- `backend/app/modules/generation_process/service.py:282`

但底层其实已经有可用数据：

- `TaskRecord.current_stage`
- `TaskRecord.result_json`
- `TaskStepRecord.detail_json`
- `TaskCenterRepository.list_task_steps(task_record_id)`

相关定义：

- `backend/app/modules/p0_models.py:1454`
- `backend/app/modules/p0_models.py:1473`
- `backend/app/modules/p0_models.py:1518`
- `backend/app/modules/task_center/repository.py:111`

### 当前静态文案仍有“班级画像”

`generation_process` 的学情步骤描述仍是：

```text
分析学生基础、薄弱点、学习习惯和班级画像。
```

位置：`backend/app/modules/generation_process/service.py:67`

赛题和当前上传入口都是单个学生学情文件，建议改为：

```text
分析学生基础、薄弱点、学习习惯和个体学习特征。
```

或：

```text
分析学生画像与时间规划。
```

## 建议一：给 generation-process 增加轻量详情协议

不要让前端凭空猜进度。建议后端在 `GenerationProcessStepResponse` 增加三个字段：

```python
current_stage: str | None
progress_detail: dict[str, Any] | None
result_detail: dict[str, Any] | None
```

字段含义：

| 字段 | 用途 |
| --- | --- |
| `current_stage` | 当前内部阶段，例如 `invoke_llm_lesson_plan` |
| `progress_detail` | 运行中详情，适合展示“已处理 N/M” |
| `result_detail` | 完成后关键指标，适合展示完成态摘要和指标卡 |

建议 `progress_detail` 使用统一结构：

```json
{
  "phase_code": "invoke_llm_lesson_plan",
  "phase_label": "正在生成课时教案",
  "unit": "课时",
  "processed": 2,
  "total": 8,
  "current_label": "第 2 课时",
  "concurrency": 1,
  "metrics": {
    "lesson_session_count": 8
  }
}
```

说明：

- `processed` / `total` 只在可计数任务里返回。
- 单次长 LLM 调用可以只返回 `phase_label`，不必伪造计数。
- `metrics` 用来承载各步骤不同的关键指标。
- 前端可以用该字段展示“正在生成第 2/8 课时”，并在两个后端锚点之间做视觉平滑；但真实状态仍以后端为准。

## 建议二：generation-process 聚合已有 task step detail

`TaskStepRecord.detail_json` 里已有不少信息，但目前项目页接口没有暴露。建议在 `GenerationProcessService._build_step_response()` 中：

1. 根据 `ctx.task.id` 调用 `TaskCenterRepository.list_task_steps(task.id)`。
2. 找到当前 step：
   - 优先匹配 `task.current_stage == step.step_code`
   - 否则取 `step_status=processing` 的最新步骤
   - 完成态可取关键成功步骤或所有 step detail 汇总
3. 从 `step.detail_json` 中抽取白名单字段，构造 `progress_detail` 和 `result_detail`。

不建议直接把所有 `detail_json` 原样返回给前端。建议按步骤做白名单，避免泄露内部 ID、上游 batch id、错误诊断等不适合产品页展示的信息。

## 各主流程步骤建议

### 1. 教材内容解析

当前跳点：

- 全量解析：`5 -> 20 -> 55 -> 100`
- 重解析：`5 -> 25 -> 60 -> 100`

相关代码：

- `backend/app/modules/parsing/tasks.py:67`
- `backend/app/modules/parsing/tasks.py:89`
- `backend/app/modules/parsing/tasks.py:113`
- `backend/app/modules/parsing/tasks.py:233`
- `backend/app/modules/parsing/tasks.py:291`
- `backend/app/modules/parsing/tasks.py:314`
- `backend/app/modules/parsing/tasks.py:337`
- `backend/app/modules/parsing/tasks.py:454`

已有数据：

- `prepare_source.detail_json.page_image_count`
- `result_json.page_count`
- `result_json.issue_count`
- `persist_parse_result.detail_json.parse_version_id`

建议 `result_detail`：

```json
{
  "page_count": 114,
  "page_image_count": 114,
  "issue_count": 0
}
```

建议完成摘要：

```text
已解析 114 页教材，完成页码、版面图片与结构内容归档。
```

如果后续能在解析结果中统计章节数、图表数、题目数，可升级为：

```text
已解析 114 页教材，识别 5 个章节、X 个图表/题目，页码与版面图片已归档。
```

### 2. 学情信息分析

当前跳点：

- `5 -> 25 -> 55 -> 100`

相关代码：

- `backend/app/modules/learner_profile/tasks.py:55`
- `backend/app/modules/learner_profile/tasks.py:80`
- `backend/app/modules/learner_profile/tasks.py:104`
- `backend/app/modules/learner_profile/tasks.py:240`

已有数据：

- `payload_json.profile_file_id`
- `prepare_source.detail_json.source_file_id`
- `build_profile_version.detail_json.record_count`
- `result_json.record_count`

当前问题：

- `record_count` 是学科画像/记录数，不等于用户上传的学情文件数。
- 单个学情文件可能解析出多个学科画像，例如 1 份文件识别出数学、英语两个画像。

建议 `result_detail`：

```json
{
  "profile_file_count": 1,
  "profile_record_count": 2,
  "target_subject_code": "math"
}
```

建议完成摘要：

```text
已分析 1 份学情文件，识别 2 个学科画像。
```

如果能确定当前项目只使用其中一个学科画像，可返回：

```text
已分析 1 份学情文件，识别 2 个学科画像；当前教学适配数学画像。
```

同时修改展示步骤描述，不再使用“班级画像”。

### 3. 重组教学内容

当前跳点：

- `10 -> 35 -> 35~60 -> 85 -> 100`

相关代码：

- `backend/app/modules/knowledge/tasks.py:99`
- `backend/app/modules/knowledge/tasks.py:127`
- `backend/app/modules/knowledge/tasks.py:139`
- `backend/app/modules/knowledge/tasks.py:178`
- `backend/app/modules/knowledge/tasks.py:194`
- `backend/app/modules/knowledge/tasks.py:334`

已有数据：

- `processed_chunks`
- `total_chunks`
- `chapter_count`
- `current_chapter_path`
- `parallel_limit`
- `point_count`
- `semantic_chunk_vector_count`
- `knowledge_point_vector_count`

建议 `progress_detail`：

```json
{
  "phase_code": "invoke_llm_extract",
  "phase_label": "正在抽取语义块知识点",
  "unit": "语义块",
  "processed": 23,
  "total": 24,
  "current_label": "第 5 章",
  "concurrency": 10,
  "metrics": {
    "chapter_count": 5
  }
}
```

建议 `result_detail`：

```json
{
  "chapter_count": 5,
  "knowledge_point_count": 228,
  "semantic_chunk_count": 24,
  "parallel_limit": 10
}
```

建议进度权重：

- `prepare_parse_source`: `0 -> 10`
- 章节边界识别：`10 -> 25`
- 语义块知识抽取：`25 -> 85`
- 结果落库：`85 -> 92`
- 向量入库：`92 -> 98`
- 完成：`100`

当前 LLM chunk 阶段只占 `35 -> 60`，但它是真正耗时最长的部分，建议拉大权重。

### 4. 整套课程规划

当前跳点：

- `10 -> 40 -> 75 -> 90 -> 100`

相关代码：

- `backend/app/modules/curriculum/tasks.py:127`
- `backend/app/modules/curriculum/tasks.py:149`
- `backend/app/modules/curriculum/tasks.py:160`
- `backend/app/modules/curriculum/tasks.py:168`
- `backend/app/modules/curriculum/tasks.py:210`
- `backend/app/modules/curriculum/tasks.py:238`

已有数据：

- `prepare_generation_baseline.detail_json.chapter_count`
- `prepare_generation_baseline.detail_json.knowledge_point_count`
- `prepare_generation_baseline.detail_json.profile_record_count`
- `invoke_llm_curriculum.detail_json.session_count`
- `generation_batch.course_count`
- `generation_batch.session_duration_minutes`

当前 `result_json` 只有：

- `generation_batch_id`
- `curriculum_plan_id`
- `lesson_plan_task_id`

建议补充 `result_json` 或在 `generation-process` 聚合时读取 `CurriculumPlan`：

```json
{
  "curriculum_plan_id": 3,
  "session_count": 8,
  "session_duration_minutes": 90,
  "chapter_count": 5,
  "knowledge_point_count": 228
}
```

建议完成摘要：

```text
已生成 8 课时课程规划，覆盖 5 个章节、228 个知识点。
```

单次 LLM 生成期间无法知道内部百分比，建议返回：

```json
{
  "phase_code": "invoke_llm_curriculum",
  "phase_label": "正在生成整套课程规划",
  "metrics": {
    "requested_session_count": 8,
    "knowledge_point_count": 228
  }
}
```

前端可以基于该 phase 展示“不确定进度/已用时”，不要假装有精确 `processed/total`。

### 5. 多课时教案生成

当前跳点：

- 进入 LLM 阶段时直接到 `40`
- 每课完成后使用 `30 + int(45 * index / total_sessions)`
- 保存到 `75`
- 收尾到 `90`
- 完成 `100`

相关代码：

- `backend/app/modules/lesson_plan/tasks.py:172`
- `backend/app/modules/lesson_plan/tasks.py:196`
- `backend/app/modules/lesson_plan/tasks.py:197`
- `backend/app/modules/lesson_plan/tasks.py:205`
- `backend/app/modules/lesson_plan/tasks.py:219`
- `backend/app/modules/lesson_plan/tasks.py:221`
- `backend/app/modules/lesson_plan/tasks.py:263`
- `backend/app/modules/lesson_plan/tasks.py:278`
- `backend/app/modules/lesson_plan/tasks.py:304`

当前问题：

- 教案是逐课时串行 LLM 调用，当前内部并发是 1。
- 先把 task 进度设为 `40`，随后按 `30 + 45 * index / total` 计算；当课时数较多时，第一课完成后的计算值可能低于 40，存在进度回退风险。
- `processed_sessions` / `total_sessions` 已写入 `invoke_llm_lesson_plan.detail_json`，但 `generation-process` 没有透出。

建议 `progress_detail`：

```json
{
  "phase_code": "invoke_llm_lesson_plan",
  "phase_label": "正在生成课时教案",
  "unit": "课时",
  "processed": 2,
  "total": 8,
  "current_label": "第 2 课时",
  "concurrency": 1
}
```

建议进度权重：

- 准备上下文：`0 -> 15`
- 逐课时 LLM 生成：`15 -> 85`
- 教案落库：`85 -> 92`
- 创建覆盖检查任务：`92 -> 98`
- 完成：`100`

进度计算示例：

```python
base = 15
span = 70
progress = base + int(span * processed_sessions / total_sessions)
```

并确保 `progress` 不小于当前 task 进度，避免回退。

建议完成摘要：

```text
已生成 8 课时教案，包含教学目标、重点难点、课堂流程与课后安排。
```

### 多课时教案是否建议并发

建议支持有限并发，但不要直接开到 10。

当前知识抽取已经支持 `KNOWLEDGE_EXTRACT_MAX_CONCURRENCY`，范围 1-10。教案生成比知识点 chunk 输出更长、单次请求更重，更容易遇到网关排队、空文本、超时或限流。

建议：

- 新增配置：`LESSON_PLAN_MAX_CONCURRENCY`
- 默认值：`2` 或 `3`
- 允许范围：`1-5`
- `1` 表示保持当前串行行为

实现建议：

- LLM 调用可以使用 `ThreadPoolExecutor` 并发。
- 数据库落库仍由主线程按 `class_session_no` 顺序写入。
- 每个 future 返回 `class_session_no`、`lesson_session`、`generation_result`、`usage`。
- 主线程按完成数量更新 `processed_sessions / total_sessions`。
- 最终按课时顺序创建 lesson plan，避免展示顺序混乱。

注意：

- 当前教案生成使用稳定前缀和 prompt cache。并发后首批请求可能无法充分利用“前一次调用先暖缓存”的收益，因此默认并发不宜太大。
- 若某一课失败，应在错误详情中保留 `class_session_no`，方便后续支持单课重试。

### 6. 校验知识覆盖

当前跳点：

- `10 -> 35 -> 65 -> 80 -> 95 -> 100`

相关代码：

- `backend/app/modules/coverage/tasks.py:52`
- `backend/app/modules/coverage/tasks.py:74`
- `backend/app/modules/coverage/tasks.py:88`
- `backend/app/modules/coverage/tasks.py:94`
- `backend/app/modules/coverage/tasks.py:109`
- `backend/app/modules/coverage/tasks.py:124`
- `backend/app/modules/coverage/tasks.py:140`

已有数据：

- `coverage_rate`
- `warning_count`
- `lesson_plan_count`
- `trace_count`
- `coverage_report_id`

建议 `result_detail`：

```json
{
  "coverage_rate": 82.35,
  "warning_count": 3,
  "lesson_plan_count": 8,
  "trace_count": 120
}
```

建议完成摘要：

```text
已完成覆盖校验，知识点覆盖率 82.35%，发现 3 条待优化建议。
```

覆盖检查多为本地计算和落库，固定阶段跳点可以接受，但建议把指标透给前端。

## 后续任务：课件、作业、测练

这些不在 `/projects/{project_id}/generation-process` 的 6 步主流程内，但在批次详情页和任务详情页也会出现类似跳点。

### 作业生成

当前跳点：

- `10 -> 40 -> 75 -> 90 -> 100`

相关代码：

- `backend/app/modules/homework/tasks.py:129`
- `backend/app/modules/homework/tasks.py:143`
- `backend/app/modules/homework/tasks.py:159`
- `backend/app/modules/homework/tasks.py:163`
- `backend/app/modules/homework/tasks.py:252`
- `backend/app/modules/homework/tasks.py:266`

已有结果：

- `question_count`
- `homework_blueprint_id`
- `homework_result_id`

建议完成摘要：

```text
已生成课后作业，共 X 道题。
```

### 测练生成

当前跳点：

- `10 -> 40 -> 75 -> 90 -> 100`

相关代码：

- `backend/app/modules/assessment/tasks.py:120`
- `backend/app/modules/assessment/tasks.py:134`
- `backend/app/modules/assessment/tasks.py:150`
- `backend/app/modules/assessment/tasks.py:154`
- `backend/app/modules/assessment/tasks.py:242`
- `backend/app/modules/assessment/tasks.py:256`

已有结果：

- `question_count`
- `assessment_blueprint_id`
- `paper_result_id`

建议完成摘要：

```text
已生成配套测练，共 X 道题。
```

### PPT 课件生成

当前跳点：

- `10 -> 30 -> 45 -> 80/100`

相关代码：

- `backend/app/modules/courseware/tasks.py:76`
- `backend/app/modules/courseware/tasks.py:87`
- `backend/app/modules/courseware/tasks.py:95`
- `backend/app/modules/courseware/tasks.py:112`
- `backend/app/modules/courseware/tasks.py:180`
- `backend/app/modules/courseware/tasks.py:188`

已有数据：

- `slide_count`
- `raccoon_job_id`
- `raccoon_status`
- `required_user_input`
- `export_file_id`

建议：

- 等待远程 PPT 结果时保持 `progress_percent=80` 可以接受。
- 但需返回 `progress_detail.phase_label = "等待远程课件生成结果"`。
- 如 `required_user_input` 为 true，返回明确 `phase_label = "等待补充课件生成信息"`。

## 进度责任边界

前端可以做：

- 在后端两个锚点之间做视觉平滑。
- 对长时间运行状态显示“已用时”。
- 用 `processed/total` 展示可计数进度。
- 对不可计数 LLM 阶段展示不确定进度，而不是伪造百分比。

后端必须做：

- `100%` 只能在结果真正落库、版本状态更新完成后返回。
- 返回真实 `current_stage`。
- 返回可计数任务的 `processed/total`。
- 保证 `progress_percent` 单调递增。
- 失败、重试、reaper 重排时保持状态权威。

不建议前端完全自控进度，因为刷新页面、多端打开、任务重试、worker 抢占后，前端无法保证一致性。

## 建议实现步骤

### 第一阶段：低风险接口增强

1. 修改 `GenerationProcessStepResponse`，增加：
   - `current_stage`
   - `progress_detail`
   - `result_detail`
2. 在 `GenerationProcessService._build_step_response()` 中读取 `TaskStepRecord`。
3. 对 6 个主流程步骤做白名单映射。
4. 修正学情步骤“班级画像”文案。
5. 优化 `_build_summary()`：
   - 学情：区分文件数和画像数。
   - 教材：保留页数，补充归档/识别结果。
   - 课程：补充课时数、章节数、知识点数。
   - 教案：补充课时数。
   - 覆盖：补充覆盖率和建议数。

这一阶段不需要改任务执行逻辑。

### 第二阶段：进度权重修正

1. 调整知识抽取权重，让语义块抽取占主要区间。
2. 调整教案生成权重，修复可能回退的问题。
3. 课程规划、作业、测练这类单次 LLM 阶段保持后端锚点，前端展示不确定进度。
4. 所有更新都应保证 `progress_percent` 单调递增。

### 第三阶段：教案有限并发

1. 增加 `LESSON_PLAN_MAX_CONCURRENCY` 配置。
2. 默认 2 或 3，最大 5。
3. 并发 LLM，主线程按课时顺序落库。
4. 记录每课失败信息，后续可支持单课重试。

## 示例响应

运行中的知识抽取：

```json
{
  "code": "knowledge_structure",
  "status": "running",
  "current_stage": "invoke_llm_extract",
  "progress_percent": 78,
  "summary": "正在抽取章节知识点，请稍候。",
  "progress_detail": {
    "phase_code": "invoke_llm_extract",
    "phase_label": "正在抽取语义块知识点",
    "unit": "语义块",
    "processed": 23,
    "total": 24,
    "current_label": "第 5 章",
    "concurrency": 10,
    "metrics": {
      "chapter_count": 5
    }
  },
  "result_detail": null
}
```

完成后的学情分析：

```json
{
  "code": "learner_profile",
  "status": "succeeded",
  "current_stage": "build_profile_version",
  "progress_percent": 100,
  "summary": "已分析 1 份学情文件，识别 2 个学科画像。",
  "progress_detail": null,
  "result_detail": {
    "profile_file_count": 1,
    "profile_record_count": 2,
    "target_subject_code": "math"
  }
}
```

运行中的多课时教案：

```json
{
  "code": "lesson_plan_generate",
  "status": "running",
  "current_stage": "invoke_llm_lesson_plan",
  "progress_percent": 48,
  "summary": "正在生成多课时教案，请稍候。",
  "progress_detail": {
    "phase_code": "invoke_llm_lesson_plan",
    "phase_label": "正在生成课时教案",
    "unit": "课时",
    "processed": 2,
    "total": 8,
    "current_label": "第 2 课时",
    "concurrency": 1
  },
  "result_detail": null
}
```

完成后的覆盖检查：

```json
{
  "code": "coverage_check",
  "status": "succeeded",
  "current_stage": "finalize_generation_batch",
  "progress_percent": 100,
  "summary": "已完成覆盖校验，知识点覆盖率 82.35%，发现 3 条待优化建议。",
  "progress_detail": null,
  "result_detail": {
    "coverage_rate": 82.35,
    "warning_count": 3,
    "lesson_plan_count": 8,
    "trace_count": 120
  }
}
```

## 测试建议

新增或调整测试：

1. `generation-process` 返回 `current_stage`。
2. 知识抽取运行中返回 `processed_chunks / total_chunks / parallel_limit`。
3. 教案生成运行中返回 `processed_sessions / total_sessions`。
4. 学情完成摘要显示“1 份学情文件，2 个学科画像”，不再把画像数当作文件数。
5. 学情步骤描述不包含“班级画像”。
6. 覆盖完成摘要包含覆盖率和 warning 数。
7. 教案生成进度不回退。
8. 课程规划完成态能返回课时数。
9. 老前端不消费新增字段时仍兼容。

## 验收标准

- `/api/v1/projects/{project_id}/generation-process` 保持原字段兼容，同时新增详情字段。
- 项目页刷新后仍能看到一致的真实进度，不依赖前端本地状态。
- 可计数任务显示 `已处理 N/M`。
- 单次长 LLM 阶段不伪造计数，但有明确阶段文案。
- 所有主流程步骤完成态都至少包含一个关键结果指标。
- 学情流程不再出现“班级画像”。
- `progress_percent` 不出现回退。
- `100%` 只在最终结果落库并状态更新完成后出现。
