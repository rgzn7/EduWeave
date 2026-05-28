# EduWeave 提示词缓存实测结论

## 测试环境

- base_url：`https://www.packyapi.com/v1`
- model：`gpt-5.5`
- api_format：`response`（OpenAI Responses）
- reasoning_effort：`low`（仅为压低 output token 成本，命中规律与 `high` 一致）
- 稳定前缀：2 段 system（约 1.2K 字符）+ 1 段 user（含 30 知识点 + 10 学情画像 JSON，约 8.4K 字符）→ **`input_tokens = 4315`**，远超 OpenAI 自动缓存的 1024 tokens 阈值
- 实测脚本：[`backend/scripts/test_lesson_plan_prompt_cache.py`](../scripts/test_lesson_plan_prompt_cache.py)
- 测试日期：2026-05-25

## 关键结论

packy 上的前缀缓存可用，但必须显式带 `prompt_cache_key`；Anthropic 风格的 `cache_control:ephemeral` 仍会 400；本次实测 `user` 字段已不再触发 400（与 thesis-viva 2026-05-25 旧记录不一致，详见下文校正）。

| 测试条件 | 第 1 次 cached_tokens / input_tokens | 第 2 次 cached_tokens / input_tokens | 命中率 |
| --- | --- | --- | --- |
| 仅同前缀，不带 `prompt_cache_key` | 0 / 4315 | 0 / 4315 | 0% |
| 同前缀 + `prompt_cache_key`（推荐） | 0 / 4315 | 3840 / 4315 | 89.0% |
| 同上 + `user` 字段 | 0 / 4315 | 3840 / 4315 | 89.0% |
| Anthropic 风格 `cache_control:ephemeral` | HTTP 400 `unknown_parameter: input[2].content[0].cache_control` | — | — |

机理：packy 会把请求分散路由到多个上游 OpenAI 账号，纯靠 prompt 哈希自动缓存会落到不同账号的分片，命中率为 0；OpenAI 原生的 `prompt_cache_key` 显式指定缓存分片，相同 key 的请求强制落同一分片，立即命中。

EduWeave 教案场景命中比例约 89%（剩 11% 是变量段 `target_lesson_session`、padding 和 reasoning context），与 OpenAI 文档给出的典型上限一致，**比 thesis-viva 实测的 86% 略高**，主要因为教案稳定前缀里的知识点 + 学情列表占比更大。

## 项目集成现状

`prompt_cache_key` 注入与 `cache_control` 标记下沉到 [`app/shared/llm/prompt_cache.py`](../app/shared/llm/prompt_cache.py)，由 `OpenAICompatibleLlmService._build_chat_completion_payload / _build_response_payload` 自动调用。`OpenAICompatibleLlmService.generate_structured_output` 新增 4 个可选 kwargs：

- `cache_biz_key: str | None`：业务键，派生 `prompt_cache_key`。
- `stable_prefix_message_count: int`：稳定前缀消息数量，给 Anthropic `cache_control` 锚点定位用。
- `cache_user_id: int | None`：可选用户标识；仅在 `llm_prompt_cache_user_enabled` 开启时注入 `user` 字段。
- `on_usage: Callable[[LlmUsage], None] | None`：每次成功调用后回调一次（含缺文本重试与 JSON 修复重试），用于聚合 `cached_tokens`。

当前接入的模块为**教案生成**（[`app/modules/lesson_plan/tasks.py`](../app/modules/lesson_plan/tasks.py)），按 `cache_biz_key = f"lesson-batch-{generation_batch_id}"` 派生缓存键，让同一批次跨课次共享同一上游缓存分片。教案的 4 条消息布局：

- `system` —— 角色与字段 schema 定义（稳定，模块级常量 `_LESSON_PLAN_ROLE_AND_SCHEMA_PROMPT`）。
- `system` —— 硬性输出规则（稳定，模块级常量 `_LESSON_PLAN_OUTPUT_RULES_PROMPT`）。
- `user` —— 稳定上下文 JSON（`project / generation_batch / curriculum_plan / knowledge_points / learner_profile_version` + 同批次共享的 evidence images），循环外构造一次。
- `user` —— 变量段（仅 `target_lesson_session`），循环内每课次重新构造，包含"JSON 对象"字样以避免 Chat 端追加兜底消息。

教案任务会把单课次 `cached_tokens / prompt_tokens / completion_tokens / total_tokens / call_count` 写入 `lesson_plan_generation_item.llm_usage_json`，全部课次成功后再聚合到任务步骤记录的 `task_step_records.detail_json.llm_usage`，便于在前端任务详情页观测命中率。

其他 6 个 LLM 调用点（课程大纲、测评、课件、知识抽取、作业、修复路径）保持原状未接入，新参数全部默认值确保零破坏。后续接入按以下顺序优先级最高：

- 知识抽取（[`app/modules/knowledge/tasks.py`](../app/modules/knowledge/tasks.py)）按章节循环，可复用同一基础设施零代码改动。
- 课件（[`app/modules/courseware/service.py`](../app/modules/courseware/service.py)）单次调用，前缀复用率取决于跨教案命中情况。

### 相关配置

新增 4 个 Settings 字段（[`app/core/config.py`](../app/core/config.py)）：

| 字段 | 默认值 | 说明 |
| --- | --- | --- |
| `llm_prompt_cache_identity_enabled` | `True` | 总开关；换到不识别该字段的供应商时关闭 |
| `llm_prompt_cache_key_prefix` | `"eduweave"` | cache_key 前缀；最终下发为 `f"{prefix}-{biz_key}"` |
| `llm_prompt_cache_user_enabled` | `False` | 是否额外注入 `user`；2026-05-25 packy 实测可用但保守保持 False |
| `llm_prompt_cache_explicit_markers` | `False` | Anthropic 兼容的 `cache_control:ephemeral`；**packy 必须保持 False**，否则 400 |

注意：后端配置由 `get_settings()` 用 `@lru_cache(maxsize=1)` 缓存（[`app/core/config.py:308`](../app/core/config.py)），修改环境变量后需要重启进程或清理 lru_cache 才会生效。

`LlmUsage` 同步新增 `cached_tokens: int = Field(default=0)` 字段（[`app/shared/llm/schemas.py`](../app/shared/llm/schemas.py)），`build_usage` 支持三协议读取：

- OpenAI Responses：`usage.input_tokens_details.cached_tokens`
- OpenAI Chat：`usage.prompt_tokens_details.cached_tokens`
- Anthropic 兼容：`usage.cache_read_input_tokens`

## 实测脚本用法

脚本读取 `backend/.env` 中已配置的 `LLM_API_BASE_URL / LLM_API_KEY / LLM_MODEL / LLM_API_FORMAT`，无须额外环境变量：

```bash
cd backend

# 基线：带 prompt_cache_key（默认），期望第 2 次 cached_tokens ≈ 3840
.venv/bin/python scripts/test_lesson_plan_prompt_cache.py --reasoning low

# 对照 A：不带 prompt_cache_key，期望两次都为 0
.venv/bin/python scripts/test_lesson_plan_prompt_cache.py --reasoning low --prompt-cache-key none

# 对照 B：Anthropic 风格标记，packy 上必定 400
.venv/bin/python scripts/test_lesson_plan_prompt_cache.py --reasoning low --explicit-cache

# 对照 C：带 user 字段（2026-05-25 packy 实测可用）
.venv/bin/python scripts/test_lesson_plan_prompt_cache.py --reasoning low --user eduweave-cache-probe

# 切到 Chat Completions 协议测试
.venv/bin/python scripts/test_lesson_plan_prompt_cache.py --reasoning low --api-format chat

# 增大稳定前缀规模到 ~25K 字符（应进一步提升命中比例）
.venv/bin/python scripts/test_lesson_plan_prompt_cache.py --reasoning low --scale 3
```

## 与 thesis-viva 文档的校正

| 项 | thesis-viva 文档（2026-05-25） | EduWeave 本次实测（2026-05-25） |
| --- | --- | --- |
| 不带 `prompt_cache_key` 时第 2 次 cached_tokens | 0（命中率 0） | 0（一致） |
| `cache_control:ephemeral` 在 packy Responses 上 | HTTP 400 `unknown_parameter` | HTTP 400 `Unknown parameter: 'input[2].content[0].cache_control'`（一致） |
| `user` 字段在 packy `gpt-5.5` Responses 上 | HTTP 400 `openai_error/bad_response_status_code` | **正常返回 200 且命中 89%**（不一致；packy 疑似已修复） |
| 项目稳定前缀实际命中比例 | ~86% | ~89%（更高，因教案稳定块比例更大） |

由于 `user` 字段在 packy 上的行为存在历史抖动，`llm_prompt_cache_user_enabled` 保守保持默认 `False`；如确认上游稳定可用且确有按用户分片需求，再单独开启。

## 经验提炼

- 多账号代理上拿前缀缓存不能只靠"消息排序稳定"，必须显式带 `prompt_cache_key`。EduWeave 实测对照（不带 key 命中率 0 vs 带 key 89%）与 thesis-viva 结论完全一致。
- cache_key 粒度选择按"批次"派生（`lesson-batch-{generation_batch_id}`）而非项目级（`curriculum_plan_id`），因为同一课程大纲跨批次的 `learner_profile_version_id / chapter_range_json / knowledge_points` 子集可能变化，按批次分片可确保稳定前缀字面一致，避免上游因 hash 不匹配命中率掉为 0。
- 稳定前缀里禁止掺天然动态字段（时间戳、签名 URL、`signed_url`、随机种子等）。EduWeave 教案稳定 JSON 仅包含 `project / generation_batch / curriculum_plan / knowledge_points / learner_profile_version` 的稳定元数据 + 同批次共享的 evidence images base64。
- system prompt 拆为模块级常量（`_LESSON_PLAN_ROLE_AND_SCHEMA_PROMPT` / `_LESSON_PLAN_OUTPUT_RULES_PROMPT`），避免循环内字符串拼接造成的不可见差异击穿缓存。
- 变量段 user 消息显式包含"JSON 对象"字样，避免 Chat Completions 端为 `response_format=json_object` 兜底追加额外消息击穿稳定前缀。
- JSON 修复路径不传 `cache_biz_key`，让修复请求独立分片，避免污染教案稳定块的缓存命中。
