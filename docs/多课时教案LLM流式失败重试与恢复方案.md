# 多课时教案 LLM 流式失败重试与恢复方案

## 背景

项目 `12` 的“多课时教案生成”在接入 OpenAI strict schema 后，仍出现过任务失败：

- 并发生成时失败在 `invoke_llm_lesson_plan`，错误为 `LLM_REQUEST_FAILED / LLM 流式调用失败`。
- 将 `LESSON_PLAN_MAX_CONCURRENCY` 临时降为 `1` 后，任务串行跑到第 13 课附近仍失败。
- 单独探针重试第 13 课成功，耗时约 `161.89s`，token 使用约 `26765`，无 schema 校验失败，也不像上下文超限。

因此当前核心问题不是第 13 课内容非法，也不是 strict schema 必然失败，而是上游 Responses SSE 流式调用存在偶发失败；后端当前把真实 SSE error 泛化成了 `LLM 流式调用失败`，并且一个课次失败会导致整个 16 课次任务失败，前面已生成成功的课次也不会落库。

## 当前问题

### 1. SSE 流式错误没有暴露真实原因

当前路径：

```text
HTTP 200 建立流式连接
-> SSE 流内出现 error / response.failed / response.incomplete
-> app/shared/llm/client.py::_raise_for_sse_error 抛 AppException
-> 任务记录只保留 LLM_REQUEST_FAILED / LLM 流式调用失败
```

问题是 `event_type`、上游 `error.code`、`error.message`、`incomplete_details` 等信息没有落到任务 detail 中，排查时无法区分：

- 上游限流
- 模型内部错误
- 输出过长
- context 超限
- schema 约束失败
- 网关或流式中继异常

### 2. 现有 LLM 重试没有覆盖 SSE error

项目里已有 `llm_max_retries=2`，但当前主要覆盖 `httpx.HTTPError`：

- HTTP 429
- HTTP 5xx
- timeout
- transport error

这次失败属于 HTTP 200 后的 SSE 流内错误，抛出的是业务 `AppException`，不会进入现有 HTTP 重试分支。

### 3. 多课时任务缺少课次级容错

当前多课时教案生成会先在内存中生成全部课次，全部成功后再统一落库。结果是：

- 第 13 课偶发失败时，第 1-12 课已成功结果也丢失。
- 手动重试只能重跑整批。
- 任务失败 detail 不知道具体失败课次和可恢复位置。

## 目标

推荐方案目标是让多课时教案生成具备：

- **可观测**：失败时能看到真实上游错误。
- **可重试**：SSE 流内可恢复错误能自动重试。
- **可恢复**：某一课失败时能从失败课次继续，而不是整批重来。
- **可控并发**：保留并发能力，但失败不应被并发放大成整批失败。

## 推荐方案

### 第一阶段：暴露 SSE 原始错误 detail

在 `app/shared/llm/client.py::_raise_for_sse_error` 中保留安全错误字段，并随 `AppException.details` 抛出。

建议 detail 结构：

```json
{
  "api_format": "responses",
  "transport": "stream",
  "event_type": "response.failed",
  "retryable": true,
  "error": {
    "code": "xxx",
    "message": "xxx",
    "type": "xxx",
    "param": "xxx"
  },
  "incomplete_details": {
    "reason": "xxx"
  }
}
```

注意：

- 后端日志可以保留完整 detail。
- 任务 detail 和前端展示建议只保留安全字段，避免泄露 prompt、API key 或过长响应。
- 如果上游 error body 过长，截断到 2-4KB。

任务失败时，将该 detail 写入：

- `task_record.last_error_code`
- `task_record.last_error_message`
- `task_step_record.detail_json.last_error_detail`
- `task_step_record.detail_json.failed_session_no`

### 第二阶段：让 Responses SSE error 进入 LLM 自动重试

扩展 `OpenAICompatibleLlmClient.create_response_stream` 的重试逻辑，不只 catch `httpx.HTTPError`，也 catch 可重试的 `AppException`。

建议判定：

```text
exc.code == LLM_REQUEST_FAILED
AND exc.details.transport == "stream"
AND exc.details.event_type in {"error", "response.failed", "response.incomplete"}
AND exc.details.retryable != false
```

对这类错误走现有 `llm_max_retries` 和 `llm_retry_base_seconds` 退避逻辑。

不可重试场景建议直接失败：

- 明确 `context_length_exceeded`
- 明确 `invalid_request_error`
- 明确 schema 参数错误
- 鉴权失败
- 余额或权限错误

### 第三阶段：增加课次级重试

在 `_generate_single_lesson_plan` 外层增加课次级 retry/backoff。这样即使 LLM client 内部重试耗尽，也可以针对当前课次再做有限重试，并记录课次维度信息。

建议配置：

```env
LESSON_PLAN_SESSION_MAX_RETRIES=2
LESSON_PLAN_SESSION_RETRY_BASE_SECONDS=3
```

建议 detail：

```json
{
  "processed_sessions": 12,
  "total_sessions": 16,
  "parallel_limit": 1,
  "failed_session_no": 13,
  "failed_session_title": "分数比较、加减与实际问题",
  "session_retry_count": 2,
  "last_error_code": "LLM_REQUEST_FAILED",
  "last_error_message": "LLM 流式调用失败",
  "last_error_detail": {
    "event_type": "response.failed",
    "error": {
      "code": "xxx",
      "message": "xxx"
    }
  },
  "retryable": true
}
```

### 第四阶段：支持任务失败后的手动重试

后端提供一个任务重试能力，复用原 `generation_batch` 和 `task_record`，不要创建新批次。

建议接口之一：

```http
POST /api/v1/tasks/{task_id}/retry
```

或针对项目生成链路：

```http
POST /api/v1/projects/{project_id}/generation/tasks/{task_id}/retry
```

重试时做这些事：

- 校验任务属于当前用户和项目。
- 只允许失败状态任务重试。
- 判断 `task_type == lesson_plan_generate`。
- 清空任务错误、worker id、开始结束时间、heartbeat。
- 轮换 `execution_attempt_id`。
- 重置失败步骤及其后续步骤。
- 复用原 payload。
- 重新 dispatch 到 `generation_queue`。

前端展示：

- “多课时教案生成失败”
- 展示简短错误原因
- 展示失败课次
- 提供“重试”按钮

### 第五阶段：支持断点续跑和部分落库

这是最终形态，能彻底避免“第 13 课失败导致前 12 课白跑”。

推荐实现方式有两种。

#### 方案 A：成功一课落库一课

每个课次成功后立即创建或 upsert `lesson_plan`：

- 唯一键建议为 `(generation_batch_id, class_session_no)`。
- 第一次写入时 `version_status=ready` 或 `draft`。
- 重试时如果课次已存在且内容有效，跳过该课次。
- 整批成功后再设置 `generation_batch.lesson_plan_id` 为第 1 课教案 id。

优点：

- 实现直观。
- 查询和恢复简单。
- 失败后前端也可以展示已生成课次。

注意：

- 需要处理失败批次下已有部分教案的展示语义。
- 覆盖率任务只能在全部课次 ready 后触发。

#### 方案 B：新增中间结果表

新增 `lesson_plan_generation_item` 保存每课次生成状态：

```text
id
generation_batch_id
task_record_id
class_session_no
lesson_title
item_status
content_json
llm_usage_json
last_error_code
last_error_message
last_error_detail_json
retry_count
created_at
updated_at
```

全部课次成功后，再批量写入正式 `lesson_plan`。

优点：

- 正式 `lesson_plan` 仍保持“完整成功后可见”。
- 中间状态和重试状态清晰。

缺点：

- 多一张表和迁移成本。

推荐优先选择 **方案 A**，除非产品明确要求失败批次不能出现任何正式 lesson_plan 记录。

## 并发策略

不建议把最终方案固定成串行。串行只是诊断手段，稳定但太慢。

推荐策略：

- 保留 `LESSON_PLAN_MAX_CONCURRENCY`。
- 默认并发可以先从 `3` 或 `5` 起步，而不是直接 `10`。
- 对同一个批次内的课次，每个课次都有独立 retry。
- 如果上游出现 429 或明确限流，自动降级并发或退避重试。
- 失败时只失败当前课次，不让并发批量结果全部丢失。

## 代码改造点

主要涉及：

- `backend/app/shared/llm/client.py`
  - 暴露 SSE error detail。
  - 将可重试 SSE error 纳入 `llm_max_retries`。

- `backend/app/shared/llm/service.py`
  - 保持 strict schema 逻辑不变。
  - 必要时透传更完整的 `AppException.details`。

- `backend/app/modules/lesson_plan/tasks.py`
  - `_generate_single_lesson_plan` 增加课次级 retry。
  - `_generate_remaining_lesson_plans_in_parallel` 记录失败课次。
  - 成功课次及时落库或写入中间结果。
  - 失败时写 `failed_session_no`、`last_error_detail`、`retryable`。

- `backend/app/modules/task_center`
  - 增加失败任务手动 retry 能力。
  - 复用原 task payload 和 generation batch。

- 前端生成过程页
  - 失败时展示真实简短错误和失败课次。
  - 提供“重试”按钮。

## 测试计划

### 单元测试

- SSE `response.failed` 会携带 detail 抛出。
- 可重试 SSE error 会触发 `llm_max_retries`。
- 不可重试错误不会重试。
- 课次级 retry 能在第一次失败、第二次成功时返回成功。
- 课次级 retry 耗尽后 detail 包含 `failed_session_no`。

### 集成测试

- 模拟 16 课次，第 13 课第一次 SSE error，第二次成功，整批最终成功。
- 模拟第 13 课持续失败，任务失败但已成功课次不丢失。
- 手动 retry 失败任务，从失败课次继续。
- 全部课次成功后正常触发覆盖率任务。

### 回归测试

- strict schema 仍然开启。
- `course_overview`、`after_class_plan` 固定结构不回退。
- `LESSON_PLAN_MAX_CONCURRENCY` 配置仍生效。
- 并发大于 1 时不会因为单个 future 失败丢失已完成课次。

## 推荐落地顺序

1. 先做 SSE error detail 暴露，解决“看不见真实错误”的问题。
2. 再做 SSE error 自动重试，复用已有 `llm_max_retries` 配置。
3. 增加课次级 retry 和失败课次 detail。
4. 增加手动 retry 接口。
5. 做成功课次持久化和断点续跑。
6. 最后恢复合理并发，并按真实稳定性调默认值。

## 结论

当前最需要修的不是 prompt，也不是第 13 课内容，而是后端任务可靠性：

- SSE 流式错误要可见。
- SSE 流式错误要能重试。
- 多课时任务要按课次容错。
- 失败任务要能手动恢复。
- 已成功课次不要因为后续单课失败而白跑。

这套改完以后，多课时教案生成可以继续使用 strict schema 和合理并发，而不是依赖永久串行来规避上游偶发不稳定。
