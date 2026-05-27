# Phase 2：生成过程后端接口对接说明

## 背景

Phase 2 的页面需要向老师展示“EduWeave 正在如何生成备课资源”。这个页面不应该展示后端日志，也不应该暴露 Celery、Redis、Milvus、LLM、内部 `module_code`、队列名或 JSON 明细。

目标是做成类似 Manus 的过程感：用户看到的是“调用 XX 工具做 XX”，而不是“某个后台任务跑到某个内部 stage”。

## 目标

- 后端提供面向前端展示的生成过程数据。
- 每一步使用用户能理解的“工具调用”语言。
- `MinerU` 作为真实教材解析工具名可以直接出现。
- 其他内部能力统一包装成产品化工具名。
- V1 优先复用现有 `TaskRecord` / `TaskStepRecord`，不需要先设计复杂的 Agent 事件系统。

## 非目标

- 不做真正 Agent 调度。
- 不要求实时 token 级日志。
- 不展示原始 Celery 日志。
- 不展示内部队列、worker、数据库、向量库、模型调用细节。
- 不把 `detail_json` 原样透传给前端展示。

## 当前后端基础

当前后端已经有任务中心能力：

- `TaskRecord`
  - `module_code`
  - `task_type`
  - `task_status`
  - `current_stage`
  - `progress_percent`
  - `payload_json`
  - `result_json`
  - `last_error_code`
  - `last_error_message`
- `TaskStepRecord`
  - `step_code`
  - `step_name`
  - `step_order`
  - `step_status`
  - `progress_percent`
  - `detail_json`
  - `started_at`
  - `finished_at`

现有接口：

- `GET /api/v1/tasks`
- `GET /api/v1/tasks/{task_id}`

这些数据足够支撑 V1，但建议后端再包一层“生成过程展示接口”，避免前端自己理解和拼接多个任务。

## 建议新增接口

```http
GET /api/v1/projects/{project_id}/generation-process
```

或如果生成过程严格绑定批次：

```http
GET /api/v1/batches/{batch_id}/generation-process
```

建议优先使用 `project_id` 版本，因为 Phase 2 页面入口是 `/projects/:projectId`，它需要展示从上传材料到生成资源的完整链路。

## 响应结构建议

```json
{
  "project_id": 1,
  "batch_id": 1,
  "status": "running",
  "current_step_code": "lesson_plan_generate",
  "steps": [
    {
      "code": "mineru_parse",
      "display_name": "调用 MinerU 教材解析工具",
      "description": "识别教材章节、页码、图表、题目和知识点。",
      "status": "succeeded",
      "progress_percent": 100,
      "summary": "已识别 12 个课次和 36 个知识点。",
      "started_at": "2026-05-26T10:00:00",
      "finished_at": "2026-05-26T10:02:30",
      "error_message": null
    }
  ]
}
```

## 状态枚举

前端希望只处理以下展示状态：

- `pending`：待开始
- `running`：进行中
- `succeeded`：已完成
- `failed`：失败
- `waiting`：等待用户操作，可选

后端内部如果仍使用 `success`、`processing`、`failure`，请在接口层转换：

| 内部状态 | 展示状态 |
| --- | --- |
| `pending` | `pending` |
| `processing` | `running` |
| `success` | `succeeded` |
| `failure` | `failed` |

## 工具化步骤设计

Phase 2 建议展示 6 个主步骤。

| 展示步骤 code | 展示名称 | 展示说明 | 对应后端任务 |
| --- | --- | --- | --- |
| `mineru_parse` | 调用 MinerU 教材解析工具 | 识别教材章节、页码、图表、题目和知识点。 | `parsing` |
| `learner_profile` | 调用学情理解工具 | 分析学生基础、薄弱点、学习习惯和班级画像。 | `learner_profile` |
| `knowledge_structure` | 调用知识点梳理工具 | 整理课程知识点、能力目标、重点难点和关联关系。 | `knowledge` |
| `curriculum_plan` | 调用课程规划工具 | 生成整套课程课次安排、教学目标和课时规划。 | `curriculum` |
| `lesson_plan_generate` | 调用教案生成工具 | 为每一课生成教学目标、重点难点、教学流程和课后安排。 | `lesson_plan` |
| `coverage_check` | 调用覆盖检查工具 | 检查课程、教案、题目和课件的知识点覆盖情况。 | `coverage` |

## 内部步骤到展示步骤的聚合建议

### 1. MinerU 教材解析工具

内部步骤示例：

- `prepare_source`
- `submit_mineru`
- `poll_mineru_result`
- `persist_parse_result`

展示为一个主步骤：

```text
调用 MinerU 教材解析工具
识别教材章节、页码、图表、题目和知识点。
```

可选 summary：

```text
已完成教材解析。
```

如果 `result_json` 中有页数、章节数、题目数，可以进一步展示：

```text
已识别 12 个课次、36 个知识点。
```

### 2. 学情理解工具

内部步骤示例：

- `prepare_source`
- `extract_local`
- `build_profile_version`

展示为：

```text
调用学情理解工具
分析学生基础、薄弱点、学习习惯和班级画像。
```

不要展示“本地解析 docx”。

### 3. 知识点梳理工具

内部步骤示例：

- `prepare_parse_source`
- `invoke_llm_extract`
- `persist_knowledge_result`
- `upsert_vectors`

展示为：

```text
调用知识点梳理工具
整理课程知识点、能力目标、重点难点和关联关系。
```

不要展示 `LLM`、`向量索引`、`Milvus`。

### 4. 课程规划工具

内部步骤示例：

- `prepare_generation_baseline`
- `invoke_llm_curriculum`
- `persist_curriculum_plan`
- `finalize_generation_batch`

展示为：

```text
调用课程规划工具
生成整套课程课次安排、教学目标和课时规划。
```

不要展示 `LLM` 和“落库”。

### 5. 教案生成工具

内部步骤示例：

- `prepare_lesson_baseline`
- `invoke_llm_lesson_plan`
- `persist_lesson_plan`
- `finalize_generation_batch`

展示为：

```text
调用教案生成工具
为每一课生成教学目标、重点难点、教学流程和课后安排。
```

### 6. 覆盖检查工具

内部步骤示例：

- `prepare_coverage_baseline`
- `collect_artifact_refs`
- `persist_coverage_report`
- `write_generation_trace`
- `finalize_generation_batch`

展示为：

```text
调用覆盖检查工具
检查课程、教案、题目和课件的知识点覆盖情况。
```

可选 summary：

```text
知识点覆盖 98.18%。
```

## 聚合规则

每个展示步骤可以由一个或多个 `TaskRecord` / `TaskStepRecord` 聚合而来。

建议状态计算：

- 只要任一关键内部任务失败，展示步骤为 `failed`。
- 如果存在内部步骤 `processing`，展示步骤为 `running`。
- 如果所有关键内部步骤都是 `success`，展示步骤为 `succeeded`。
- 如果任务尚未创建，但前置步骤未完成，展示步骤为 `pending`。
- 如果需要用户确认材料或解析结果，可展示为 `waiting`。

建议进度计算：

- V1 可以直接使用内部任务 `progress_percent`。
- 如果一个展示步骤聚合多个内部步骤，可以取平均值或按关键步骤权重计算。
- 前端主要依赖状态，不强依赖精确百分比。

## 错误信息规则

失败时，前端只需要面向用户的 `error_message`。

不要直接返回：

- Python traceback
- SQL 错误
- Celery worker 错误
- 第三方 API 原始响应
- 内部模型提示词或完整 JSON

建议错误文案示例：

```text
教材解析失败，请确认上传文件是否为清晰的 PDF。
```

```text
教案生成失败，请稍后重试；已保留当前教材解析和知识点结果。
```

如果需要排查，可以额外返回后端内部字段，但不要给前端默认展示：

```json
{
  "error_message": "教材解析失败，请确认上传文件是否为清晰的 PDF。",
  "debug": {
    "task_id": 123,
    "internal_error_code": "MINERU_TIMEOUT"
  }
}
```

`debug` 字段仅用于开发环境或管理员视图，不进入普通老师页面。

## 推荐接口 Schema

```python
class GenerationProcessStepResponse(BaseModel):
    code: str
    display_name: str
    description: str
    status: Literal["pending", "running", "succeeded", "failed", "waiting"]
    progress_percent: int = 0
    summary: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_message: str | None = None


class GenerationProcessResponse(BaseModel):
    project_id: int
    batch_id: int | None = None
    status: Literal["pending", "running", "succeeded", "failed", "waiting"]
    current_step_code: str | None = None
    steps: list[GenerationProcessStepResponse]
```

## 返回示例

### 进行中

```json
{
  "project_id": 1,
  "batch_id": 1,
  "status": "running",
  "current_step_code": "lesson_plan_generate",
  "steps": [
    {
      "code": "mineru_parse",
      "display_name": "调用 MinerU 教材解析工具",
      "description": "识别教材章节、页码、图表、题目和知识点。",
      "status": "succeeded",
      "progress_percent": 100,
      "summary": "教材解析已完成。",
      "started_at": "2026-05-26T10:00:00",
      "finished_at": "2026-05-26T10:02:30",
      "error_message": null
    },
    {
      "code": "learner_profile",
      "display_name": "调用学情理解工具",
      "description": "分析学生基础、薄弱点、学习习惯和班级画像。",
      "status": "succeeded",
      "progress_percent": 100,
      "summary": "学情分析已完成。",
      "started_at": "2026-05-26T10:02:31",
      "finished_at": "2026-05-26T10:03:12",
      "error_message": null
    },
    {
      "code": "knowledge_structure",
      "display_name": "调用知识点梳理工具",
      "description": "整理课程知识点、能力目标、重点难点和关联关系。",
      "status": "succeeded",
      "progress_percent": 100,
      "summary": "知识点结构已生成。",
      "started_at": "2026-05-26T10:03:13",
      "finished_at": "2026-05-26T10:04:20",
      "error_message": null
    },
    {
      "code": "curriculum_plan",
      "display_name": "调用课程规划工具",
      "description": "生成整套课程课次安排、教学目标和课时规划。",
      "status": "succeeded",
      "progress_percent": 100,
      "summary": "课程总纲已生成。",
      "started_at": "2026-05-26T10:04:21",
      "finished_at": "2026-05-26T10:05:45",
      "error_message": null
    },
    {
      "code": "lesson_plan_generate",
      "display_name": "调用教案生成工具",
      "description": "为每一课生成教学目标、重点难点、教学流程和课后安排。",
      "status": "running",
      "progress_percent": 60,
      "summary": "正在生成多课教案。",
      "started_at": "2026-05-26T10:05:46",
      "finished_at": null,
      "error_message": null
    },
    {
      "code": "coverage_check",
      "display_name": "调用覆盖检查工具",
      "description": "检查课程、教案、题目和课件的知识点覆盖情况。",
      "status": "pending",
      "progress_percent": 0,
      "summary": null,
      "started_at": null,
      "finished_at": null,
      "error_message": null
    }
  ]
}
```

### 已完成

```json
{
  "project_id": 1,
  "batch_id": 1,
  "status": "succeeded",
  "current_step_code": null,
  "steps": [
    {
      "code": "mineru_parse",
      "display_name": "调用 MinerU 教材解析工具",
      "description": "识别教材章节、页码、图表、题目和知识点。",
      "status": "succeeded",
      "progress_percent": 100,
      "summary": "教材解析已完成。",
      "started_at": "2026-05-26T10:00:00",
      "finished_at": "2026-05-26T10:02:30",
      "error_message": null
    },
    {
      "code": "coverage_check",
      "display_name": "调用覆盖检查工具",
      "description": "检查课程、教案、题目和课件的知识点覆盖情况。",
      "status": "succeeded",
      "progress_percent": 100,
      "summary": "知识点覆盖 98.18%。",
      "started_at": "2026-05-26T10:08:10",
      "finished_at": "2026-05-26T10:08:35",
      "error_message": null
    }
  ]
}
```

已完成时可以返回完整 6 步。上面示例为了说明结构只截取了部分步骤。

## 前端展示原则

前端只展示：

- `display_name`
- `description`
- `status`
- `summary`
- 必要的 `error_message`

前端不展示：

- `task_id`
- `worker_task_id`
- `queue_name`
- `module_code`
- `task_type`
- `step_code` 的原始内部含义
- `detail_json`

## 后端实现建议

### V1 推荐做法

1. 新增一个 service，例如 `GenerationProcessService`。
2. 根据 `project_id` 找到当前项目相关的教材解析、学情、知识、最近生成批次和批次任务。
3. 从现有 `TaskRecord` / `TaskStepRecord` 聚合为 6 个展示步骤。
4. 在 service 层维护一张展示映射表。
5. 接口只返回产品化字段。

展示映射表示例：

```python
GENERATION_PROCESS_STEPS = [
    {
        "code": "mineru_parse",
        "display_name": "调用 MinerU 教材解析工具",
        "description": "识别教材章节、页码、图表、题目和知识点。",
        "module_codes": ["parsing"],
    },
    {
        "code": "learner_profile",
        "display_name": "调用学情理解工具",
        "description": "分析学生基础、薄弱点、学习习惯和班级画像。",
        "module_codes": ["learner_profile"],
    },
    {
        "code": "knowledge_structure",
        "display_name": "调用知识点梳理工具",
        "description": "整理课程知识点、能力目标、重点难点和关联关系。",
        "module_codes": ["knowledge"],
    },
    {
        "code": "curriculum_plan",
        "display_name": "调用课程规划工具",
        "description": "生成整套课程课次安排、教学目标和课时规划。",
        "module_codes": ["curriculum"],
    },
    {
        "code": "lesson_plan_generate",
        "display_name": "调用教案生成工具",
        "description": "为每一课生成教学目标、重点难点、教学流程和课后安排。",
        "module_codes": ["lesson_plan"],
    },
    {
        "code": "coverage_check",
        "display_name": "调用覆盖检查工具",
        "description": "检查课程、教案、题目和课件的知识点覆盖情况。",
        "module_codes": ["coverage"],
    },
]
```

### V2 可选增强

如果后续希望更像 Manus，可以新增 `task_event` 或 `generation_process_event` 表，记录更细粒度的事件：

- `event_type`
- `tool_name`
- `action`
- `status`
- `summary`
- `metadata_json`
- `created_at`

但 Phase 2 V1 不建议先做这件事。当前任务表足够支撑可用体验。

## 验收标准

- 接口能基于真实任务返回 6 个展示步骤。
- 页面不需要解析后端内部 `step_name` 才能展示用户文案。
- 返回数据不包含给普通用户展示的 Celery、Redis、Milvus、LLM、worker、queue 文案。
- `MinerU` 出现在教材解析步骤中。
- 失败时能返回用户可理解的错误信息。
- 已完成项目返回 `status = succeeded`，并且 6 个步骤全部 `succeeded` 或能解释部分跳过原因。
- 进行中项目能正确标出当前运行步骤。
- 不要求前端读取原始日志文件。

## 给后端的一句话

Phase 2 需要的是“产品化的生成过程步骤接口”，不是后台日志接口；请把现有任务和步骤聚合成类似 Manus 的“调用 XX 工具做 XX”的展示数据。
