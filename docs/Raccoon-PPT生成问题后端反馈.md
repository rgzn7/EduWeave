# Raccoon PPT 生成问题后端反馈

## 结论

当前 PPT 生成失败主要不是前端问题，也不像是 token 过期问题；更像是后端接入 Raccoon PPT OpenAPI 时，构造 `prompt` 的方式不符合参考实现预期。

核心问题不只是“输出太长”，而是：

1. 后端传给 Raccoon 的 `prompt` 可能过长。
2. 后端把结构化 slides JSON 整体塞进 `prompt`，要求 Raccoon 严格按 JSON 逐页生成，这与 Raccoon 参考仓库的一句话自然语言生成方式不一致。
3. Raccoon 创建任务阶段因此可能出现解析失败、处理耗时过长、read timeout 或远端 `failed`。

## 现象

项目历史记录中，课件任务曾失败在 `create_raccoon_ppt_job` 阶段：

- 错误码：`COURSEWARE_TASK_FAILED`
- 错误信息：`The read operation timed out`
- 阶段：`create_raccoon_ppt_job`
- 后续 `poll_raccoon_ppt_job`、`archive_courseware_result`、`finalize_generation_batch` 未执行
- 当次没有生成 `courseware_result`，因此无法刷新远程状态或下载 PPTX

同时项目里也有成功任务记录，说明 Raccoon 链路不是完全不可用：

- 成功生成过 `courseware_result_id=1`
- `raccoon_status=succeeded`
- 生成 13 页 PPTX
- 已归档 `export_file_id=1142`

因此更像是特定调用输入导致创建任务失败或超时，而不是全局服务不可用。

## 参考 Raccoon 接入方式

参考仓库：

- https://github.com/SenseTime-Copilot/raccoon-ppt-skill
- https://github.com/SenseTime-Copilot/raccoon-ppt-skill/blob/main/references/API_REFERENCE.md
- https://github.com/SenseTime-Copilot/raccoon-ppt-skill/blob/main/references/CHEATSHEET.md

参考文档中的最小创建任务请求体为：

```json
{
  "prompt": "帮我生成一份介绍 Transformer 发展历程的培训 PPT",
  "role": "研究人员",
  "scene": "培训教学",
  "audience": "大众群体"
}
```

参考脚本中还对 `prompt` 做了长度限制：

- `prompt` 不能为空
- `prompt` 官方建议 1 到 2000 字
- 超过 2000 字会直接报错

当前推荐枚举中，本项目课件场景可使用：

```json
{
  "role": "教师",
  "scene": "培训教学",
  "audience": "学生"
}
```

## 当前项目的问题点

当前后端在 `CoursewareService.build_raccoon_prompt` 中，会把项目、学情摘要和完整课件结构 JSON 拼进 `prompt`。

代码位置：

- `backend/app/modules/courseware/service.py`
- `build_raccoon_prompt`

当前 prompt 形态大致是：

```text
请严格按以下已排好的幻灯片结构逐页生成中文 PPTX 课件：
不要改变页序与每页要点，保持 slides 数组的顺序与内容一一对应；
仅做版式美化与排版，不要新增或删减页面，不要输出解释文字，只生成课件。

{ 项目 + 学情摘要 + 完整 slides JSON }
```

这和 Raccoon 参考实现存在偏差：

| 项目当前实现 | Raccoon 参考实现 |
| --- | --- |
| 把完整 slides JSON 作为 prompt | 使用短自然语言描述 PPT 需求 |
| 要求严格按 JSON 逐页排版 | 由 Raccoon 自己完成规划和生成 |
| prompt 可能远超 2000 字 | prompt 建议 1 到 2000 字 |
| 失败时容易卡在创建任务阶段 | 创建任务应快速返回 job_id 和 queued/running |

## 为什么不像 token 过期

如果 token 未配置，后端会直接报：

```text
RACCOON_API_TOKEN 未配置
```

如果 token 过期或无效，正常情况下 Raccoon 会快速返回 HTTP 401/403 或业务错误 JSON。

而当前主要现象是：

```text
The read operation timed out
```

这是请求发出后，在读取响应时超时，更像是远端处理过慢、输入导致解析卡住，或网络/服务波动。

另外，用同一套环境发起过极小 prompt 测试，可以拿到 Raccoon `job_id`，说明 token 至少不是“完全不可用”状态。

## 建议后端调整

### 1. 改造 Raccoon prompt

不要把完整 slides JSON 直接塞给 Raccoon。建议改成 1000 到 2000 字以内的自然语言需求摘要。

建议 prompt 结构：

```text
请生成一份中文课堂教学 PPT。

主题：小学数学《乘法分配律》
对象：三年级学生
课时：1 课时，约 40 分钟
页数：约 12 页
教学目标：
1. 理解乘法分配律的含义
2. 能用乘法分配律进行简便计算
3. 能结合生活情境解释算式

页面结构建议：
1. 封面
2. 情境导入
3. 学习目标
4. 核心知识讲解
5. 例题讲解
6. 课堂互动
7. 分层练习
8. 总结
9. 课后作业

请使用清晰、适合小学生课堂展示的风格。
```

可保留的信息：

- 课件标题
- 学科、年级、适用对象
- 课时和页数
- 核心知识点名称
- 教学目标
- 页面结构摘要
- 关键例题摘要

建议去掉或压缩的信息：

- 完整 `slides` JSON
- 过长 `speaker_notes`
- 大段学情画像明细
- 大段课程大纲和教案原始 JSON

### 2. 增加 prompt 长度保护

在调用 Raccoon 前增加长度检查：

- 如果 prompt 超过 2000 字，先自动压缩摘要。
- 记录压缩前后字符数。
- 不要直接把超长 prompt 发给 Raccoon。

### 3. 改善异常归类

当前 read timeout 没有被包装成明确的 Raccoon 业务错误，最后会兜底成：

```text
COURSEWARE_TASK_FAILED
```

建议在 `RaccoonPptClient` 中捕获：

- `httpx.TimeoutException`
- `httpx.TransportError`

并转成：

```text
RACCOON_REQUEST_FAILED
```

用户可读文案建议：

```text
Raccoon PPT 创建任务超时，未获得远程 job_id，请稍后重试。
```

### 4. 拆分超时配置

当前使用单一 `RACCOON_REQUEST_TIMEOUT_SECONDS`。建议拆分：

- connect timeout：10 秒
- read timeout：180 秒
- write timeout：30 秒
- pool timeout：10 秒

参考仓库脚本里默认请求超时为 180 秒。

### 5. 创建任务成功后再异步轮询

参考文档建议：

- 创建或回复后，前台观察约 2 分钟。
- 如果仍是 `queued/running`，保留 job_id，后续继续查。
- 不建议一次请求阻塞 30 分钟到 2 小时。

当前项目已有 `waiting_raccoon_result` 和后台复查机制，可以继续沿用。

## 推荐优先级

1. 先改 `build_raccoon_prompt`，从完整 JSON 改为自然语言摘要，并控制在 2000 字以内。
2. 再补充 `httpx.TimeoutException` / `TransportError` 包装，避免裸露 `The read operation timed out`。
3. 再调整 Raccoon timeout 为接近参考脚本的 180 秒。
4. 最后增加日志诊断字段：prompt 字符数、slide 数、lesson_plan_id、Raccoon 状态、耗时、异常类型。

## 一句话反馈

这次 PPT 生成问题主要是后端 Raccoon 接入方式不匹配：不是简单 token 过期，也不只是输出太长，而是后端把完整结构化课件 JSON 作为超长 prompt 发给 Raccoon，偏离了 Raccoon “短自然语言需求创建 PPT 任务”的参考方式，导致创建任务阶段解析失败或超时。
