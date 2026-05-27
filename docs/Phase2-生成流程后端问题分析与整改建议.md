# Phase2 生成流程后端问题分析与整改建议

## 1. 背景

本次走查使用 Project 6 验证语文备课完整流程：

- 教材：人民教育出版社语文三年级下册，解析后共 130 页。
- 学情：学生学情 docx 文件。
- 生成设置：10 节课，每节 40 分钟。
- 页面：`/projects/6` Phase2 生成过程页。

走查过程中出现以下现象：

- Phase2 长时间停留在知识结构抽取阶段，页面显示 35%。
- 后端出现 `TASK_STALE_TIMEOUT`，随后触发任务重试。
- 同一知识抽取任务出现重复 Celery worker 执行风险。
- 原 worker 后续实际完成知识抽取，生成 8 个章节、140 个知识点。
- 页面最终停留在 3 / 6 步：教材解析、学情分析、知识结构完成；课程规划、教案生成、覆盖检查仍为 pending。
- `generation-process` 显示整体仍在 running，但正在处理项为 0。

这说明问题不是单纯的前端展示问题，而是后端长任务进度、任务恢复和流程编排共同暴露出的稳定性问题。

## 2. 结论

### 2.1 35% 卡住的主要原因

知识抽取进入 `invoke_llm_extract` 阶段后，后端将任务进度更新为 35%，随后开始较长的 LLM 抽取过程。该过程包含：

- 章节边界识别 LLM 调用。
- 基于章节和语义块的知识点抽取 LLM 调用。
- LLM 输出校验。
- 知识点草稿构建。

目前该阶段内部没有按语义块持续更新任务进度，也没有定期 heartbeat。因此前端只能看到任务停留在 35%，无法判断真实处理进度。

### 2.2 任务重试的主要原因

后端 reaper 使用 `TaskRecord.updated_at` 判断任务是否 stale。知识抽取长时间执行期间没有更新 `updated_at`，超过 30 分钟阈值后被 reaper 判定为 `TASK_STALE_TIMEOUT` 并重新入队。

但原 Celery worker 实际仍在运行，并且后续成功完成。这说明本次不是 worker 崩溃，而是后端将正常长任务误判为僵尸任务。

### 2.3 重复 worker 的风险

reaper 重排任务时会把任务状态重置为 pending 并重新派发，但没有确认原 worker 是否仍在执行，也没有先 revoke / terminate 原 worker。

因此同一个 task record 可能同时存在旧 worker 和重试 worker，带来以下风险：

- 重复调用外部 LLM。
- 重复写入知识版本、章节、知识点、向量。
- 任务状态被不同 worker 互相覆盖。
- 前端状态出现跳变或停滞。

### 2.4 3 / 6 后不继续的原因

当前后端没有在知识结构抽取成功后自动创建 generation batch。课程规划、教案生成、覆盖检查依赖前端页面 effect 调用 `createGenerationBatch` 继续触发。

Project 6 中知识抽取完成后，`latest_generation_batch_id` 仍为空，因此后续三步没有对应任务，页面只能显示 pending。

这不符合产品预期：用户点击“开始生成”后，Phase2 页面应该是自动流程的可视化，而不应该依赖前端页面状态继续调度后续步骤。

## 3. 代码层证据

### 3.1 知识抽取固定停在 35%

`backend/app/modules/knowledge/tasks.py` 中，任务进入 `invoke_llm_extract` 后更新为 35%：

- step：`invoke_llm_extract`
- task：`current_stage="invoke_llm_extract"`
- task：`progress_percent=35`

之后进入章节边界识别和语义块循环抽取。循环内部没有按语义块更新 task progress，也没有定期提交 heartbeat。

因此对于 130 页教材，若 LLM 调用较多或出现重试，前端会长时间看到 35%。

### 3.2 知识抽取 LLM 调用是串行循环

同一文件中，知识点抽取逻辑会遍历 `semantic_chunk_drafts`，并对每个语义块调用一次：

```text
llm_service.generate_structured_output(...)
```

当前没有并发、没有分批提交进度，也没有将 `已处理 x / n 个片段` 写入任务摘要。

### 3.3 LLM missing text 会放大耗时

`backend/app/shared/llm/service.py` 中，当 LLM 请求成功但没有拿到可解析文本时，会记录 `llm_missing_text_retrying` 并重试。

本次日志中出现过该重试记录。它不是最终失败原因，但会显著放大知识抽取阶段耗时。

### 3.4 Reaper 使用 updated_at 判断 stale

`backend/app/modules/task_center/recovery.py` 中，reaper 查询条件包含：

- `task_status == processing`
- `updated_at < now - threshold`
- 当前阶段不属于外部等待阶段

配置中的 stale 阈值为 1800 秒。知识抽取阶段长时间不更新 `updated_at`，因此会被误判为 stale。

### 3.5 重排不会终止原 worker

`requeue_or_fail_task` 会：

- 增加 `retry_count`
- 将任务改回 pending
- 清空 `worker_task_id`
- 重置 task steps
- 重新 dispatch

但该逻辑没有确保原 Celery worker 已停止，也没有加 task execution lock，导致重复执行风险。

### 3.6 Generation batch 需要前端触发

`backend/app/modules/pipeline/service.py` 中，`create_generation_batch` 会创建 generation batch，并派发课程规划任务。

但该方法当前由前端调用。知识抽取任务成功后，后端不会自动进入课程规划阶段。

因此一旦前端 effect 没有成功触发，流程就会停在 3 / 6。

## 4. 问题拆解

### 4.1 知识抽取耗时长

耗时长本身可以理解，原因包括：

- 教材页数较多，共 130 页。
- 需要先做章节边界识别。
- 章节内容会被切成多个语义块。
- 每个语义块都需要 LLM 结构化抽取。
- LLM missing text 或瞬时错误会触发重试。

但耗时长不应导致页面不可观测，也不应被 reaper 误判为任务死亡。

### 4.2 进度不可观测

当前 `invoke_llm_extract` 是一个大黑盒阶段。前端无法知道：

- 总共有多少语义块。
- 已处理多少语义块。
- 当前正在处理哪个章节。
- LLM 是否正在重试。
- 任务是否仍有 heartbeat。

这会让用户认为系统卡死。

### 4.3 Stale 判定过于粗糙

只依赖 `updated_at` 判断长任务是否 stale，前提是所有长任务都会定期写库更新。但知识抽取阶段没有做到这一点。

所以当前机制会把“正在执行但没有写库”的任务误判为“worker 已崩溃”。

### 4.4 重试缺少互斥保护

任务重试应该保证同一个 task record 同一时间只有一个有效执行者。当前缺少：

- worker 存活确认。
- 原 worker revoke / terminate。
- task execution lock。
- execution attempt id 校验。

因此重试不是安全的。

### 4.5 Phase2 编排权威不清晰

当前 Phase2 的 6 步流程被拆成两段：

- 前半段：教材解析、学情分析、知识抽取，主要由前端页面 effect 接力触发。
- 后半段：课程规划、教案生成、覆盖检查，由 generation batch 触发。

从产品角度，用户点击“开始生成”后，应由后端拥有完整编排权。前端应该只负责轮询 `generation-process` 并展示状态。

## 5. 整改建议

### 5.1 知识抽取增加细粒度进度和 heartbeat

建议在知识抽取任务中：

- 章节边界识别完成后，记录 `semantic_chunk_count`。
- 每处理完一个语义块，更新 `progress_percent`。
- 每处理完一个语义块，更新 `updated_at`。
- 在 task summary 或 step detail 中记录 `已处理 x / n 个片段`。
- LLM missing text retry 时可记录内部 retry 信息，但前端展示应保持产品化文案。

建议进度区间示例：

- 35%：开始 LLM 知识抽取。
- 35% - 60%：按语义块数量线性推进。
- 60%：开始落库。
- 85%：开始向量写入。
- 100%：知识抽取完成。

### 5.2 改造 stale / reaper 机制

建议后端不要只靠 `updated_at` 判断 worker 是否死亡。可以考虑：

- 为长任务增加独立 heartbeat 字段，例如 `last_heartbeat_at`。
- worker 定期写 heartbeat，不必每次都更新业务进度。
- reaper 判定 stale 前检查 Celery active/reserved 状态。
- 对已知长阶段设置更长阈值或阶段级阈值。
- LLM 调用阶段支持显式 heartbeat。

### 5.3 重试前确保原执行者失效

建议 reaper 重排前必须满足至少一种条件：

- 原 `worker_task_id` 已确认不在 active/reserved/scheduled。
- 已成功 revoke / terminate 原 worker。
- 获取到同一 task record 的执行锁。
- 新 worker 启动时校验 execution attempt id，旧 attempt 不允许继续写库。

否则不应重新派发同一任务。

### 5.4 后端全权编排 Phase2

建议新增后端启动能力：前端上传教材和学情后，调用一个 start 接口，后端创建并持久化一次生成运行记录，然后自动编排 6 步：

1. 教材解析。
2. 学情分析。
3. 知识结构抽取。
4. 课程规划。
5. 多课时教案生成。
6. 覆盖检查。

后端应在前置任务成功后自动调度后续任务。前端不再依赖 localStorage marker 或页面 effect 来决定是否继续生成。

### 5.5 generation-process 增加明确状态

建议 `generation-process` 避免出现整体 running 但没有任何 running step 的状态。

如果确实处于异常等待，应返回明确状态，例如：

- `waiting_dispatch`：等待后端调度下一步。
- `blocked`：前置条件缺失，无法继续。
- `retrying`：任务重试中。
- `failed`：流程失败。

前端据此展示产品化提示，而不是显示“正在处理 0 项”。

## 6. 前端配合建议

后端完成上述改造后，前端建议调整为：

- 点击开始生成后，上传材料完成即调用后端 start 接口。
- Phase2 页面只轮询 `GET /api/v1/projects/{project_id}/generation-process`。
- 不再由页面 effect 接力触发 parse、knowledge、generation batch。
- `/tasks` 仅用于开发诊断或按钮禁用，不作为主流程展示来源。
- 若 `generation-process` 返回 blocked / failed，展示后端提供的产品化中文文案。

## 7. 验收建议

建议后端至少覆盖以下场景：

- 130 页教材知识抽取期间，页面能看到语义块级进度变化。
- 知识抽取运行超过 30 分钟时，不会被 reaper 误判为 stale。
- 手动模拟 worker 崩溃后，reaper 可以安全重试，且不会产生重复 worker 写库。
- 知识抽取成功后，后端自动创建 generation batch 并进入课程规划。
- 前端刷新、关闭、重新打开 Phase2 页面，不影响后端继续生成。
- `generation-process` 不出现整体 running 但正在处理 0 项且后续全 pending 的状态。
- 生成完成后，课程总纲、多课时教案、覆盖报告均可见。
- 多课时教案数量与启动参数一致，例如 10 节课、每节 40 分钟。

## 8. 优先级建议

建议按以下顺序处理：

1. 知识抽取增加 heartbeat 和语义块级进度。
2. reaper 重试前增加 worker 存活确认或 execution lock。
3. 后端接管 Phase2 完整编排。
4. `generation-process` 增加 blocked / waiting_dispatch / retrying 等明确状态。
5. 前端移除 Phase2 页面中的自动接力触发逻辑，只保留状态展示。

## 9. 总结

Project 6 暴露的问题本质上不是“前端没有显示 loading”，而是后端流程还没有形成真正稳定的一键生成编排。

当前后端可以执行各个任务，但缺少完整运行态、长任务 heartbeat、安全重试和阶段自动续跑能力。只要这些能力没有补齐，Phase2 页面就可能继续出现：

- 长时间卡在某个固定进度。
- 误判 stale 后重复执行。
- 某一步成功但后续不启动。
- 页面整体 running 但没有任何实际任务运行。

因此建议后端将 Phase2 定义为一个完整自动化 pipeline，由后端作为权威控制者；前端只负责启动、轮询和展示。
