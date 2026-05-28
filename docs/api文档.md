# EduWeave

**版本**: 0.1.0

## 目录

- [系统](#系统)
- [认证](#认证)
- [文件](#文件)
- [项目](#项目)
- [生成过程](#生成过程)
- [教材](#教材)
- [学情](#学情)
- [解析](#解析)
- [知识结构化](#知识结构化)
- [生成编排](#生成编排)
- [一键生成](#一键生成)
- [课程大纲](#课程大纲)
- [教案](#教案)
- [测评](#测评)
- [课后作业](#课后作业)
- [课件](#课件)
- [覆盖率](#覆盖率)
- [任务中心](#任务中心)

## 系统

### GET `/health`

**应用存活检查**

返回应用进程存活状态，不校验外部依赖连通性。

**响应**

`200` Successful Response

```json
{
  success: boolean  # 请求是否成功
  code: integer  # 业务响应状态码
  message: string  # 响应消息
  data?: {
    status: string  # 应用状态
    app_name: string  # 应用名称
    version: string  # 应用版本
    timestamp: string  # 当前时间
  }
  timestamp: string  # 响应时间，UTC ISO8601 格式
  request_id: string  # 请求追踪 ID
  errors?: array[{
    code: string  # 错误码
    message: string  # 错误描述
    details?: object  # 补充信息
    field?: object  # 字段名
  }]
}
```

---

### GET `/ready`

**应用就绪检查**

返回应用对 MySQL、Redis、Milvus 等核心依赖的就绪检查结果。

**响应**

`200` Successful Response

```json
{
  success: boolean  # 请求是否成功
  code: integer  # 业务响应状态码
  message: string  # 响应消息
  data?: {
    status: string  # 系统就绪状态
    checks: object  # 依赖检查结果
  }
  timestamp: string  # 响应时间，UTC ISO8601 格式
  request_id: string  # 请求追踪 ID
  errors?: array[{
    code: string  # 错误码
    message: string  # 错误描述
    details?: object  # 补充信息
    field?: object  # 字段名
  }]
}
```

---

## 认证

### POST `/api/v1/auth/login`

**教师账号登录**

教师使用账号密码登录系统，返回访问令牌和当前教师基础信息。

**请求体**

```json
{
  username: string  # 登录账号
  password: string  # 登录密码
}
```

**响应**

`200` Successful Response

```json
{
  success: boolean  # 请求是否成功
  code: integer  # 业务响应状态码
  message: string  # 响应消息
  data?: {
    access_token: string  # 访问令牌
    token_type?: string  # 令牌类型
    expires_in: integer  # 过期秒数
    user: object  # 当前教师信息
  }
  timestamp: string  # 响应时间，UTC ISO8601 格式
  request_id: string  # 请求追踪 ID
  errors?: array[{
    code: string  # 错误码
    message: string  # 错误描述
    details?: object  # 补充信息
    field?: object  # 字段名
  }]
}
```

---

### GET `/api/v1/auth/me`

**获取当前教师信息**

根据当前访问令牌获取已登录教师的基础账号信息。

**响应**

`200` Successful Response

```json
{
  success: boolean  # 请求是否成功
  code: integer  # 业务响应状态码
  message: string  # 响应消息
  data?: {
    id: integer  # 教师账号主键
    username: string  # 教师登录账号
    display_name: string  # 教师显示名称
    role_code: string  # 角色编码，当前阶段固定为 teacher
    status: string  # 账号状态
  }
  timestamp: string  # 响应时间，UTC ISO8601 格式
  request_id: string  # 请求追踪 ID
  errors?: array[{
    code: string  # 错误码
    message: string  # 错误描述
    details?: object  # 补充信息
    field?: object  # 字段名
  }]
}
```

---

## 文件

### GET `/api/v1/files/{file_object_id}/download-url`

**获取文件下载地址**

为当前教师可见的文件对象生成临时签名下载地址。

**参数**

| 位置 | 名称 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| path | `file_object_id` | integer | 是 | 文件对象主键 |

**响应**

`200` Successful Response

```json
{
  success: boolean  # 请求是否成功
  code: integer  # 业务响应状态码
  message: string  # 响应消息
  data?: {
    file_object_id: integer  # 文件对象主键
    bucket_name: string  # 存储桶名称
    object_key: string  # 对象路径
    signed_url: object  # 签名下载地址
    expires_in_seconds: integer  # 有效期秒数
    generated_at: object  # 生成时间
  }
  timestamp: string  # 响应时间，UTC ISO8601 格式
  request_id: string  # 请求追踪 ID
  errors?: array[{
    code: string  # 错误码
    message: string  # 错误描述
    details?: object  # 补充信息
    field?: object  # 字段名
  }]
}
```

---

## 项目

### POST `/api/v1/projects`

**创建项目**

创建新的教学项目，作为教材、学情、任务与结果的统一上下文容器。

**请求体**

```json
{
  name: string  # 项目名称
  subject_code: string  # 学科编码
  grade_code: string  # 年级编码
  applicable_target?: string | null  # 适用对象
  remark?: string | null  # 备注
  project_code?: string | null  # 项目编码
}
```

**响应**

`201` Successful Response

```json
{
  success: boolean  # 请求是否成功
  code: integer  # 业务响应状态码
  message: string  # 响应消息
  data?: {
    id: integer  # 项目主键
    project_code?: object  # 项目编码
    name: string  # 项目名称
    subject_code: string  # 学科编码
    grade_code: string  # 年级编码
    applicable_target?: object  # 适用对象
    remark?: object  # 备注
    status: string  # 项目状态
    current_textbook_version_id?: object  # 当前教材版本主键
    current_learner_profile_version_id?: object  # 当前学情版本主键
    latest_generation_batch_id?: object  # 最近生成批次主键
    last_activity_at?: object  # 最近活动时间
    created_at: object  # 创建时间
    updated_at: object  # 更新时间
    owner_user_id: integer  # 负责人主键
    current_textbook?: object  # 当前教材引用
    current_learner_profile?: object  # 当前学情引用
  }
  timestamp: string  # 响应时间，UTC ISO8601 格式
  request_id: string  # 请求追踪 ID
  errors?: array[{
    code: string  # 错误码
    message: string  # 错误描述
    details?: object  # 补充信息
    field?: object  # 字段名
  }]
}
```

---

### GET `/api/v1/projects`

**获取项目列表**

分页获取当前教师创建的项目列表，支持按项目状态和学科筛选。

**参数**

| 位置 | 名称 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| query | `status` | string | 否 | 项目状态 |
| query | `subject_code` | string | 否 | 学科编码 |
| query | `page` | integer | 否 | 页码 |
| query | `page_size` | integer | 否 | 每页大小 |

**响应**

`200` Successful Response

```json
{
  success: boolean  # 请求是否成功
  code: integer  # 业务响应状态码
  message: string  # 响应消息
  data?: {
    items: array[{
      id: integer  # 项目主键
      project_code?: object  # 项目编码
      name: string  # 项目名称
      subject_code: string  # 学科编码
      grade_code: string  # 年级编码
      applicable_target?: object  # 适用对象
      remark?: object  # 备注
      status: string  # 项目状态
      current_textbook_version_id?: object  # 当前教材版本主键
      current_learner_profile_version_id?: object  # 当前学情版本主键
      latest_generation_batch_id?: object  # 最近生成批次主键
      last_activity_at?: object  # 最近活动时间
      created_at: object  # 创建时间
      updated_at: object  # 更新时间
    }]
    pagination: {
      total_count: integer  # 总记录数
      page: integer  # 当前页码
      page_size: integer  # 每页大小
      total_pages: integer  # 总页数
      has_previous: boolean  # 是否存在上一页
      has_next: boolean  # 是否存在下一页
    }
  }
  timestamp: string  # 响应时间，UTC ISO8601 格式
  request_id: string  # 请求追踪 ID
  errors?: array[{
    code: string  # 错误码
    message: string  # 错误描述
    details?: object  # 补充信息
    field?: object  # 字段名
  }]
}
```

---

### GET `/api/v1/projects/{project_id}`

**获取项目详情**

获取当前教师拥有的项目详情及当前教材、学情引用信息。

**参数**

| 位置 | 名称 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| path | `project_id` | integer | 是 | 项目主键 |

**响应**

`200` Successful Response

```json
{
  success: boolean  # 请求是否成功
  code: integer  # 业务响应状态码
  message: string  # 响应消息
  data?: {
    id: integer  # 项目主键
    project_code?: object  # 项目编码
    name: string  # 项目名称
    subject_code: string  # 学科编码
    grade_code: string  # 年级编码
    applicable_target?: object  # 适用对象
    remark?: object  # 备注
    status: string  # 项目状态
    current_textbook_version_id?: object  # 当前教材版本主键
    current_learner_profile_version_id?: object  # 当前学情版本主键
    latest_generation_batch_id?: object  # 最近生成批次主键
    last_activity_at?: object  # 最近活动时间
    created_at: object  # 创建时间
    updated_at: object  # 更新时间
    owner_user_id: integer  # 负责人主键
    current_textbook?: object  # 当前教材引用
    current_learner_profile?: object  # 当前学情引用
  }
  timestamp: string  # 响应时间，UTC ISO8601 格式
  request_id: string  # 请求追踪 ID
  errors?: array[{
    code: string  # 错误码
    message: string  # 错误描述
    details?: object  # 补充信息
    field?: object  # 字段名
  }]
}
```

---

### GET `/api/v1/projects/{project_id}/dashboard`

**获取项目工作台**

获取项目工作台聚合数据，包括当前引用、输入链路统计和最近任务列表。

**参数**

| 位置 | 名称 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| path | `project_id` | integer | 是 | 项目主键 |

**响应**

`200` Successful Response

```json
{
  success: boolean  # 请求是否成功
  code: integer  # 业务响应状态码
  message: string  # 响应消息
  data?: {
    project: object  # 项目详情
    stats: object  # 工作台统计
    recent_tasks: object  # 最近任务列表
  }
  timestamp: string  # 响应时间，UTC ISO8601 格式
  request_id: string  # 请求追踪 ID
  errors?: array[{
    code: string  # 错误码
    message: string  # 错误描述
    details?: object  # 补充信息
    field?: object  # 字段名
  }]
}
```

---

### PATCH `/api/v1/projects/{project_id}/active-refs`

**切换项目当前引用**

切换项目当前默认教材版本和学情版本，版本必须属于当前项目。

**参数**

| 位置 | 名称 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| path | `project_id` | integer | 是 | 项目主键 |

**请求体**

```json
{
  current_textbook_version_id?: integer | null  # 当前教材版本主键
  current_learner_profile_version_id?: integer | null  # 当前学情版本主键
}
```

**响应**

`200` Successful Response

```json
{
  success: boolean  # 请求是否成功
  code: integer  # 业务响应状态码
  message: string  # 响应消息
  data?: {
    id: integer  # 项目主键
    project_code?: object  # 项目编码
    name: string  # 项目名称
    subject_code: string  # 学科编码
    grade_code: string  # 年级编码
    applicable_target?: object  # 适用对象
    remark?: object  # 备注
    status: string  # 项目状态
    current_textbook_version_id?: object  # 当前教材版本主键
    current_learner_profile_version_id?: object  # 当前学情版本主键
    latest_generation_batch_id?: object  # 最近生成批次主键
    last_activity_at?: object  # 最近活动时间
    created_at: object  # 创建时间
    updated_at: object  # 更新时间
    owner_user_id: integer  # 负责人主键
    current_textbook?: object  # 当前教材引用
    current_learner_profile?: object  # 当前学情引用
  }
  timestamp: string  # 响应时间，UTC ISO8601 格式
  request_id: string  # 请求追踪 ID
  errors?: array[{
    code: string  # 错误码
    message: string  # 错误描述
    details?: object  # 补充信息
    field?: object  # 字段名
  }]
}
```

---

## 生成过程

### GET `/api/v1/projects/{project_id}/generation-process`

**获取项目生成过程**

将项目当前的内部任务聚合成 6 个产品化展示步骤（MinerU 教材解析、学情理解、知识点梳理、课程规划、教案生成、覆盖检查），用于 Phase 2 页面展示。响应包含面向用户的文案、状态、当前阶段、公开进度指标与公开结果指标，不暴露内部任务 ID、队列名、worker 信息等实现细节。

**参数**

| 位置 | 名称 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| path | `project_id` | integer | 是 | 项目主键 |

**响应**

`200` Successful Response

```json
{
  success: boolean  # 请求是否成功
  code: integer  # 业务响应状态码
  message: string  # 响应消息
  data?: {
    project_id: integer  # 项目主键
    batch_id?: integer  # 当前展示批次主键：活跃 run 已创建批次时为 run 批次；活跃 run 未创建批次时为 null；无活跃 run 时为项目最近生成批次
    generation_run_id?: integer  # 当前活跃一键生成 run 主键；无 run 则为 null
    status: string  # 整体展示状态
    status_detail?: string  # 整体细化状态：waiting_dispatch=等待后端调度下一步；waiting_user_confirm=等待用户确认教材解析；retrying=任务被 reaper 重排重试中；blocked=前置缺失，无法继续
    blocked_reason?: string  # status_detail=blocked 时的原因编码，例如 LEARNER_PROFILE_NOT_READY
    current_step_code?: string  # 当前正在进行的展示步骤编码
    steps: object  # 展示步骤列表，固定 6 步
  }
  timestamp: string  # 响应时间，UTC ISO8601 格式
  request_id: string  # 请求追踪 ID
  errors?: array[{
    code: string  # 错误码
    message: string  # 错误描述
    details?: object  # 补充信息
    field?: object  # 字段名
  }]
}
```

---

## 教材

### POST `/api/v1/projects/{project_id}/textbooks`

**上传教材文件**

向指定项目上传 PDF 教材文件，并创建新的教材版本记录。

**参数**

| 位置 | 名称 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| path | `project_id` | integer | 是 | 项目主键 |

**请求体**

```json
{
  file: string  # 教材 PDF 文件
  textbook_name?: string | null  # 教材名称
  publisher?: string | null  # 出版社
  subject_code?: string | null  # 学科编码
  grade_code?: string | null  # 年级编码
  volume_code?: string | null  # 册别
  edition_label?: string | null  # 版本标签
  isbn?: string | null  # ISBN
  remark?: string | null  # 备注
  set_as_current?: boolean  # 是否设为当前版本
}
```

**响应**

`201` Successful Response

```json
{
  success: boolean  # 请求是否成功
  code: integer  # 业务响应状态码
  message: string  # 响应消息
  data?: {
    id: integer  # 教材版本主键
    project_id: integer  # 所属项目主键
    version_no: integer  # 项目内版本号
    textbook_name: string  # 教材名称
    publisher?: object  # 出版社
    subject_code: string  # 学科编码
    grade_code: string  # 年级编码
    volume_code?: object  # 册别
    edition_label?: object  # 版本标签
    isbn?: object  # ISBN
    page_count?: object  # 页数
    parse_status: string  # 解析状态
    version_status: string  # 版本状态
    remark?: object  # 备注
    is_current: boolean  # 是否为当前项目引用的教材版本
    source_file: object  # 源文件摘要
    created_at: object  # 创建时间
    updated_at: object  # 更新时间
    auto_identify_json?: object  # 自动识别结果
  }
  timestamp: string  # 响应时间，UTC ISO8601 格式
  request_id: string  # 请求追踪 ID
  errors?: array[{
    code: string  # 错误码
    message: string  # 错误描述
    details?: object  # 补充信息
    field?: object  # 字段名
  }]
}
```

---

### GET `/api/v1/projects/{project_id}/textbooks`

**获取教材版本列表**

分页获取指定项目下的教材版本列表。

**参数**

| 位置 | 名称 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| path | `project_id` | integer | 是 | 项目主键 |
| query | `page` | integer | 否 | 页码 |
| query | `page_size` | integer | 否 | 每页大小 |

**响应**

`200` Successful Response

```json
{
  success: boolean  # 请求是否成功
  code: integer  # 业务响应状态码
  message: string  # 响应消息
  data?: {
    items: array[{
      id: integer  # 教材版本主键
      project_id: integer  # 所属项目主键
      version_no: integer  # 项目内版本号
      textbook_name: string  # 教材名称
      publisher?: object  # 出版社
      subject_code: string  # 学科编码
      grade_code: string  # 年级编码
      volume_code?: object  # 册别
      edition_label?: object  # 版本标签
      isbn?: object  # ISBN
      page_count?: object  # 页数
      parse_status: string  # 解析状态
      version_status: string  # 版本状态
      remark?: object  # 备注
      is_current: boolean  # 是否为当前项目引用的教材版本
      source_file: object  # 源文件摘要
      created_at: object  # 创建时间
      updated_at: object  # 更新时间
    }]
    pagination: {
      total_count: integer  # 总记录数
      page: integer  # 当前页码
      page_size: integer  # 每页大小
      total_pages: integer  # 总页数
      has_previous: boolean  # 是否存在上一页
      has_next: boolean  # 是否存在下一页
    }
  }
  timestamp: string  # 响应时间，UTC ISO8601 格式
  request_id: string  # 请求追踪 ID
  errors?: array[{
    code: string  # 错误码
    message: string  # 错误描述
    details?: object  # 补充信息
    field?: object  # 字段名
  }]
}
```

---

### GET `/api/v1/projects/{project_id}/textbooks/{textbook_version_id}`

**获取教材版本详情**

获取指定项目下单个教材版本的详细信息。

**参数**

| 位置 | 名称 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| path | `project_id` | integer | 是 | 项目主键 |
| path | `textbook_version_id` | integer | 是 | 教材版本主键 |

**响应**

`200` Successful Response

```json
{
  success: boolean  # 请求是否成功
  code: integer  # 业务响应状态码
  message: string  # 响应消息
  data?: {
    id: integer  # 教材版本主键
    project_id: integer  # 所属项目主键
    version_no: integer  # 项目内版本号
    textbook_name: string  # 教材名称
    publisher?: object  # 出版社
    subject_code: string  # 学科编码
    grade_code: string  # 年级编码
    volume_code?: object  # 册别
    edition_label?: object  # 版本标签
    isbn?: object  # ISBN
    page_count?: object  # 页数
    parse_status: string  # 解析状态
    version_status: string  # 版本状态
    remark?: object  # 备注
    is_current: boolean  # 是否为当前项目引用的教材版本
    source_file: object  # 源文件摘要
    created_at: object  # 创建时间
    updated_at: object  # 更新时间
    auto_identify_json?: object  # 自动识别结果
  }
  timestamp: string  # 响应时间，UTC ISO8601 格式
  request_id: string  # 请求追踪 ID
  errors?: array[{
    code: string  # 错误码
    message: string  # 错误描述
    details?: object  # 补充信息
    field?: object  # 字段名
  }]
}
```

---

## 学情

### POST `/api/v1/projects/{project_id}/learner-profiles`

**上传班级学情文件**

向指定项目上传一个班级的多份 docx 学情文件（每份对应一个学生），系统建立单个班级学情文件，并按配置创建真实学情抽取任务：逐份本地 python-docx 同步解析出各学生画像后，再用 LLM 聚合出班级画像。title 字段在此语义下表示班级名称。

**参数**

| 位置 | 名称 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| path | `project_id` | integer | 是 | 项目主键 |

**请求体**

```json
{
  files: array[string]  # 班级学生学情 docx 文件列表（每份一个学生）
  title?: string | null  # 班级名称
  grade_code?: string | null  # 年级编码
  subject_scope?: string | null  # 学科范围
  textbook_version_hint_id?: integer | null  # 教材提示版本主键
  auto_extract?: boolean  # 是否立即创建抽取任务
  set_as_current?: boolean  # 是否在成功后设为当前学情版本
}
```

**响应**

`201` Successful Response

```json
{
  success: boolean  # 请求是否成功
  code: integer  # 业务响应状态码
  message: string  # 响应消息
  data?: {
    id: integer  # 学情文件主键
    project_id: integer  # 所属项目主键
    source_file_id: integer  # 源文件主键
    title: string  # 学情文档标题
    file_status: string  # 文件状态
    source_file: object  # 源文件摘要
    latest_version?: object  # 最新学情版本
    created_at: object  # 创建时间
    updated_at: object  # 更新时间
  }
  timestamp: string  # 响应时间，UTC ISO8601 格式
  request_id: string  # 请求追踪 ID
  errors?: array[{
    code: string  # 错误码
    message: string  # 错误描述
    details?: object  # 补充信息
    field?: object  # 字段名
  }]
}
```

---

### GET `/api/v1/projects/{project_id}/learner-profiles`

**获取学情文件列表**

分页获取指定项目下的学情文件及其最新抽取结果摘要。

**参数**

| 位置 | 名称 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| path | `project_id` | integer | 是 | 项目主键 |
| query | `page` | integer | 否 | 页码 |
| query | `page_size` | integer | 否 | 每页大小 |

**响应**

`200` Successful Response

```json
{
  success: boolean  # 请求是否成功
  code: integer  # 业务响应状态码
  message: string  # 响应消息
  data?: {
    items: array[{
      id: integer  # 学情文件主键
      project_id: integer  # 所属项目主键
      source_file_id: integer  # 源文件主键
      title: string  # 学情文档标题
      file_status: string  # 文件状态
      source_file: object  # 源文件摘要
      latest_version?: object  # 最新学情版本
      created_at: object  # 创建时间
      updated_at: object  # 更新时间
    }]
    pagination: {
      total_count: integer  # 总记录数
      page: integer  # 当前页码
      page_size: integer  # 每页大小
      total_pages: integer  # 总页数
      has_previous: boolean  # 是否存在上一页
      has_next: boolean  # 是否存在下一页
    }
  }
  timestamp: string  # 响应时间，UTC ISO8601 格式
  request_id: string  # 请求追踪 ID
  errors?: array[{
    code: string  # 错误码
    message: string  # 错误描述
    details?: object  # 补充信息
    field?: object  # 字段名
  }]
}
```

---

### GET `/api/v1/projects/{project_id}/learner-profiles/{profile_file_id}`

**获取学情文件详情**

获取指定项目下学情文件详情及其最新学情版本内容。

**参数**

| 位置 | 名称 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| path | `project_id` | integer | 是 | 项目主键 |
| path | `profile_file_id` | integer | 是 | 学情文件主键 |

**响应**

`200` Successful Response

```json
{
  success: boolean  # 请求是否成功
  code: integer  # 业务响应状态码
  message: string  # 响应消息
  data?: {
    id: integer  # 学情文件主键
    project_id: integer  # 所属项目主键
    source_file_id: integer  # 源文件主键
    title: string  # 学情文档标题
    file_status: string  # 文件状态
    source_file: object  # 源文件摘要
    latest_version?: object  # 最新学情版本
    created_at: object  # 创建时间
    updated_at: object  # 更新时间
  }
  timestamp: string  # 响应时间，UTC ISO8601 格式
  request_id: string  # 请求追踪 ID
  errors?: array[{
    code: string  # 错误码
    message: string  # 错误描述
    details?: object  # 补充信息
    field?: object  # 字段名
  }]
}
```

---

### GET `/api/v1/projects/{project_id}/learner-profiles/{profile_file_id}/versions`

**获取学情版本列表**

分页获取指定学情文件下的学情版本列表。

**参数**

| 位置 | 名称 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| path | `project_id` | integer | 是 | 项目主键 |
| path | `profile_file_id` | integer | 是 | 学情文件主键 |
| query | `page` | integer | 否 | 页码 |
| query | `page_size` | integer | 否 | 每页大小 |

**响应**

`200` Successful Response

```json
{
  success: boolean  # 请求是否成功
  code: integer  # 业务响应状态码
  message: string  # 响应消息
  data?: {
    items: array[{
      id: integer  # 学情版本主键
      project_id: integer  # 所属项目主键
      profile_file_id: integer  # 学情文件主键
      parent_version_id?: object  # 父版本主键
      version_no: integer  # 版本号
      textbook_version_hint_id?: object  # 教材提示版本主键
      grade_code?: object  # 年级编码
      subject_scope?: object  # 学科范围
      extract_status: string  # 抽取状态
      review_status: string  # 审核状态
      version_status: string  # 版本状态
      summary_text?: object  # 摘要文本（班级整体学情摘要）
      class_profile?: object  # 班级画像聚合结果（学科概览、共性强弱、分层建议等）
      raw_result_json?: object  # 抽取结果 JSON
      source_snapshot_json?: object  # 输入快照
      created_by?: object  # 创建人
      created_at: object  # 创建时间
      updated_at: object  # 更新时间
    }]
    pagination: {
      total_count: integer  # 总记录数
      page: integer  # 当前页码
      page_size: integer  # 每页大小
      total_pages: integer  # 总页数
      has_previous: boolean  # 是否存在上一页
      has_next: boolean  # 是否存在下一页
    }
  }
  timestamp: string  # 响应时间，UTC ISO8601 格式
  request_id: string  # 请求追踪 ID
  errors?: array[{
    code: string  # 错误码
    message: string  # 错误描述
    details?: object  # 补充信息
    field?: object  # 字段名
  }]
}
```

---

### GET `/api/v1/learner-profile-versions/{profile_version_id}`

**获取学情版本详情**

获取单个学情版本详情及其结构化画像记录。

**参数**

| 位置 | 名称 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| path | `profile_version_id` | integer | 是 | 学情版本主键 |

**响应**

`200` Successful Response

```json
{
  success: boolean  # 请求是否成功
  code: integer  # 业务响应状态码
  message: string  # 响应消息
  data?: {
    id: integer  # 学情版本主键
    project_id: integer  # 所属项目主键
    profile_file_id: integer  # 学情文件主键
    parent_version_id?: object  # 父版本主键
    version_no: integer  # 版本号
    textbook_version_hint_id?: object  # 教材提示版本主键
    grade_code?: object  # 年级编码
    subject_scope?: object  # 学科范围
    extract_status: string  # 抽取状态
    review_status: string  # 审核状态
    version_status: string  # 版本状态
    summary_text?: object  # 摘要文本（班级整体学情摘要）
    class_profile?: object  # 班级画像聚合结果（学科概览、共性强弱、分层建议等）
    raw_result_json?: object  # 抽取结果 JSON
    source_snapshot_json?: object  # 输入快照
    created_by?: object  # 创建人
    created_at: object  # 创建时间
    updated_at: object  # 更新时间
    records: object  # 画像记录列表
  }
  timestamp: string  # 响应时间，UTC ISO8601 格式
  request_id: string  # 请求追踪 ID
  errors?: array[{
    code: string  # 错误码
    message: string  # 错误描述
    details?: object  # 补充信息
    field?: object  # 字段名
  }]
}
```

---

### POST `/api/v1/learner-profile-versions/{profile_version_id}/manual-revisions`

**保存学情人工修正版本**

提交完整的学情画像记录并生成新的学情版本，可按需切换为项目当前学情版本。

**参数**

| 位置 | 名称 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| path | `profile_version_id` | integer | 是 | 学情版本主键 |

**请求体**

```json
{
  summary_text?: string | null  # 版本摘要
  grade_code?: string | null  # 年级编码
  subject_scope?: string | null  # 学科范围
  records: array[{
    student_key: string  # 学生标识
    student_name?: string | null  # 学生姓名
    is_anonymous?: boolean  # 是否匿名
    region_name?: string | null  # 地区名称
    grade_code?: string | null  # 年级编码
    subject_code: string  # 学科编码
    textbook_version_hint_id?: integer | null  # 教材提示版本主键
    score_value?: number | null  # 分数
    advantage_tags_json?: object | null  # 优势标签
    weakness_tags_json?: object | null  # 薄弱标签
    ability_tags_json?: object | null  # 能力标签
    habit_tags_json?: object | null  # 学习习惯标签
    behavior_traits_json?: object | null  # 行为特征标签
    time_plan_json?: object | null  # 时间规划标签
    summary_text?: string | null  # 摘要文本
    evidence_json?: object | null  # 证据 JSON
    sort_order?: integer  # 排序号
  }]  # 完整画像记录列表
  set_as_current?: boolean  # 是否设为项目当前学情版本
}
```

**响应**

`201` Successful Response

```json
{
  success: boolean  # 请求是否成功
  code: integer  # 业务响应状态码
  message: string  # 响应消息
  data?: {
    id: integer  # 学情版本主键
    project_id: integer  # 所属项目主键
    profile_file_id: integer  # 学情文件主键
    parent_version_id?: object  # 父版本主键
    version_no: integer  # 版本号
    textbook_version_hint_id?: object  # 教材提示版本主键
    grade_code?: object  # 年级编码
    subject_scope?: object  # 学科范围
    extract_status: string  # 抽取状态
    review_status: string  # 审核状态
    version_status: string  # 版本状态
    summary_text?: object  # 摘要文本（班级整体学情摘要）
    class_profile?: object  # 班级画像聚合结果（学科概览、共性强弱、分层建议等）
    raw_result_json?: object  # 抽取结果 JSON
    source_snapshot_json?: object  # 输入快照
    created_by?: object  # 创建人
    created_at: object  # 创建时间
    updated_at: object  # 更新时间
    records: object  # 画像记录列表
  }
  timestamp: string  # 响应时间，UTC ISO8601 格式
  request_id: string  # 请求追踪 ID
  errors?: array[{
    code: string  # 错误码
    message: string  # 错误描述
    details?: object  # 补充信息
    field?: object  # 字段名
  }]
}
```

---

## 解析

### POST `/api/v1/textbook-versions/{textbook_version_id}/parse-tasks`

**创建教材解析任务**

为指定教材版本创建全量解析任务，并由 Worker 对接 MinerU 执行真实解析。

**参数**

| 位置 | 名称 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| path | `textbook_version_id` | integer | 是 | 教材版本主键 |

**请求体**

```json
{
  strategy_code?: string  # 解析策略编码
  set_as_current_on_success?: boolean  # 是否在成功后设为当前可用解析版本
}
```

**响应**

`201` Successful Response

```json
{
  success: boolean  # 请求是否成功
  code: integer  # 业务响应状态码
  message: string  # 响应消息
  data?: {
    id: integer  # 任务主键
    project_id: integer  # 所属项目主键
    generation_batch_id?: object  # 生成批次主键
    module_code: string  # 模块编码
    task_type: string  # 任务类型
    biz_key?: string  # 业务键
    task_status: string  # 任务状态
    queue_name?: string  # 队列名称
    current_stage?: string  # 当前阶段
    progress_percent: integer  # 任务进度
    retry_count: integer  # 重试次数
    max_retry_count: integer  # 最大重试次数
    worker_task_id?: object  # Worker 任务ID
    last_error_code?: object  # 最近错误码
    last_error_message?: object  # 最近错误信息
    payload_json?: object  # 任务载荷
    result_json?: object  # 任务结果
    started_at?: object  # 开始时间
    finished_at?: object  # 结束时间
    created_at: object  # 创建时间
    updated_at: object  # 更新时间
  }
  timestamp: string  # 响应时间，UTC ISO8601 格式
  request_id: string  # 请求追踪 ID
  errors?: array[{
    code: string  # 错误码
    message: string  # 错误描述
    details?: object  # 补充信息
    field?: object  # 字段名
  }]
}
```

---

### POST `/api/v1/parse-versions/{parse_version_id}/reparse-tasks`

**创建页级重解析任务**

针对指定解析版本的页码范围创建重解析任务，并生成新的解析版本。

**参数**

| 位置 | 名称 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| path | `parse_version_id` | integer | 是 | 解析版本主键 |

**请求体**

```json
{
  page_range_text: string  # 页码范围文本
  strategy_code?: string  # 解析策略编码
  set_as_current_on_success?: boolean  # 是否在成功后设为当前可用解析版本
}
```

**响应**

`201` Successful Response

```json
{
  success: boolean  # 请求是否成功
  code: integer  # 业务响应状态码
  message: string  # 响应消息
  data?: {
    id: integer  # 任务主键
    project_id: integer  # 所属项目主键
    generation_batch_id?: object  # 生成批次主键
    module_code: string  # 模块编码
    task_type: string  # 任务类型
    biz_key?: string  # 业务键
    task_status: string  # 任务状态
    queue_name?: string  # 队列名称
    current_stage?: string  # 当前阶段
    progress_percent: integer  # 任务进度
    retry_count: integer  # 重试次数
    max_retry_count: integer  # 最大重试次数
    worker_task_id?: object  # Worker 任务ID
    last_error_code?: object  # 最近错误码
    last_error_message?: object  # 最近错误信息
    payload_json?: object  # 任务载荷
    result_json?: object  # 任务结果
    started_at?: object  # 开始时间
    finished_at?: object  # 结束时间
    created_at: object  # 创建时间
    updated_at: object  # 更新时间
  }
  timestamp: string  # 响应时间，UTC ISO8601 格式
  request_id: string  # 请求追踪 ID
  errors?: array[{
    code: string  # 错误码
    message: string  # 错误描述
    details?: object  # 补充信息
    field?: object  # 字段名
  }]
}
```

---

### GET `/api/v1/textbook-versions/{textbook_version_id}/parse-versions`

**获取解析版本列表**

分页获取指定教材版本下的解析版本列表。

**参数**

| 位置 | 名称 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| path | `textbook_version_id` | integer | 是 | 教材版本主键 |
| query | `page` | integer | 否 | 页码 |
| query | `page_size` | integer | 否 | 每页大小 |

**响应**

`200` Successful Response

```json
{
  success: boolean  # 请求是否成功
  code: integer  # 业务响应状态码
  message: string  # 响应消息
  data?: {
    items: array[{
      id: integer  # 解析版本主键
      project_id: integer  # 所属项目主键
      textbook_version_id: integer  # 教材版本主键
      parent_parse_version_id?: object  # 父解析版本主键
      version_no: integer  # 版本号
      parse_mode: string  # 解析模式
      page_range_text?: object  # 页范围文本
      strategy_code: string  # 解析策略编码
      mineru_model?: object  # MinerU 模型名称
      parse_status: string  # 解析状态
      review_status: string  # 审核状态
      version_status: string  # 版本状态
      page_count?: object  # 页数
      issue_count: integer  # 异常数量
      source_markdown_file_id?: object  # 解析 Markdown 文件主键
      source_json_file_id?: object  # 解析 JSON 文件主键
      asset_manifest_json?: object  # 资源清单
      diff_json?: object  # 差异摘要
      error_summary?: object  # 错误摘要
      started_at?: object  # 开始时间
      finished_at?: object  # 结束时间
      created_at: object  # 创建时间
      updated_at: object  # 更新时间
    }]
    pagination: {
      total_count: integer  # 总记录数
      page: integer  # 当前页码
      page_size: integer  # 每页大小
      total_pages: integer  # 总页数
      has_previous: boolean  # 是否存在上一页
      has_next: boolean  # 是否存在下一页
    }
  }
  timestamp: string  # 响应时间，UTC ISO8601 格式
  request_id: string  # 请求追踪 ID
  errors?: array[{
    code: string  # 错误码
    message: string  # 错误描述
    details?: object  # 补充信息
    field?: object  # 字段名
  }]
}
```

---

### GET `/api/v1/parse-versions/{parse_version_id}`

**获取解析版本详情**

获取单个解析版本的基础信息、状态和异常统计。

**参数**

| 位置 | 名称 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| path | `parse_version_id` | integer | 是 | 解析版本主键 |

**响应**

`200` Successful Response

```json
{
  success: boolean  # 请求是否成功
  code: integer  # 业务响应状态码
  message: string  # 响应消息
  data?: {
    id: integer  # 解析版本主键
    project_id: integer  # 所属项目主键
    textbook_version_id: integer  # 教材版本主键
    parent_parse_version_id?: object  # 父解析版本主键
    version_no: integer  # 版本号
    parse_mode: string  # 解析模式
    page_range_text?: object  # 页范围文本
    strategy_code: string  # 解析策略编码
    mineru_model?: object  # MinerU 模型名称
    parse_status: string  # 解析状态
    review_status: string  # 审核状态
    version_status: string  # 版本状态
    page_count?: object  # 页数
    issue_count: integer  # 异常数量
    source_markdown_file_id?: object  # 解析 Markdown 文件主键
    source_json_file_id?: object  # 解析 JSON 文件主键
    asset_manifest_json?: object  # 资源清单
    diff_json?: object  # 差异摘要
    error_summary?: object  # 错误摘要
    started_at?: object  # 开始时间
    finished_at?: object  # 结束时间
    created_at: object  # 创建时间
    updated_at: object  # 更新时间
  }
  timestamp: string  # 响应时间，UTC ISO8601 格式
  request_id: string  # 请求追踪 ID
  errors?: array[{
    code: string  # 错误码
    message: string  # 错误描述
    details?: object  # 补充信息
    field?: object  # 字段名
  }]
}
```

---

### POST `/api/v1/parse-versions/{parse_version_id}/confirm`

**确认解析版本**

将解析成功的版本显式标记为已确认，使其可作为后续知识抽取的合法输入基线。

**参数**

| 位置 | 名称 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| path | `parse_version_id` | integer | 是 | 解析版本主键 |

**响应**

`200` Successful Response

```json
{
  success: boolean  # 请求是否成功
  code: integer  # 业务响应状态码
  message: string  # 响应消息
  data?: {
    id: integer  # 解析版本主键
    project_id: integer  # 所属项目主键
    textbook_version_id: integer  # 教材版本主键
    parent_parse_version_id?: object  # 父解析版本主键
    version_no: integer  # 版本号
    parse_mode: string  # 解析模式
    page_range_text?: object  # 页范围文本
    strategy_code: string  # 解析策略编码
    mineru_model?: object  # MinerU 模型名称
    parse_status: string  # 解析状态
    review_status: string  # 审核状态
    version_status: string  # 版本状态
    page_count?: object  # 页数
    issue_count: integer  # 异常数量
    source_markdown_file_id?: object  # 解析 Markdown 文件主键
    source_json_file_id?: object  # 解析 JSON 文件主键
    asset_manifest_json?: object  # 资源清单
    diff_json?: object  # 差异摘要
    error_summary?: object  # 错误摘要
    started_at?: object  # 开始时间
    finished_at?: object  # 结束时间
    created_at: object  # 创建时间
    updated_at: object  # 更新时间
  }
  timestamp: string  # 响应时间，UTC ISO8601 格式
  request_id: string  # 请求追踪 ID
  errors?: array[{
    code: string  # 错误码
    message: string  # 错误描述
    details?: object  # 补充信息
    field?: object  # 字段名
  }]
}
```

---

### GET `/api/v1/parse-versions/{parse_version_id}/evidence-summary`

**获取解析证据摘要**

聚合解析版本的页数、block 统计、类型分布、MinerU 参数与示例 block，证明教材 PDF 已被结构化拆解。

**参数**

| 位置 | 名称 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| path | `parse_version_id` | integer | 是 | 解析版本主键 |
| query | `sample_size` | integer | 否 | 示例证据 block 数量，限制在 3-10 之间 |

**响应**

`200` Successful Response

```json
{
  success: boolean  # 请求是否成功
  code: integer  # 业务响应状态码
  message: string  # 响应消息
  data?: {
    parse_version_id: integer  # 解析版本主键
    textbook_version_id: integer  # 教材版本主键
    strategy_code: string  # 解析策略编码
    mineru_model?: string  # MinerU 模型名称
    parse_status: string  # 解析状态
    review_status: string  # 审核状态
    version_status: string  # 版本状态
    volume: object  # 规模统计
    block_type_counts: object  # block 类型分布，按数量倒序
    mineru_parameters: object  # MinerU 参数摘要
    sample_blocks: object  # 示例证据 block 列表
  }
  timestamp: string  # 响应时间，UTC ISO8601 格式
  request_id: string  # 请求追踪 ID
  errors?: array[{
    code: string  # 错误码
    message: string  # 错误描述
    details?: object  # 补充信息
    field?: object  # 字段名
  }]
}
```

---

### GET `/api/v1/parse-versions/{parse_version_id}/pages`

**获取解析页列表**

分页获取解析页及其文本级块预览数据。

**参数**

| 位置 | 名称 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| path | `parse_version_id` | integer | 是 | 解析版本主键 |
| query | `page` | integer | 否 | 页码 |
| query | `page_size` | integer | 否 | 每页大小 |

**响应**

`200` Successful Response

```json
{
  success: boolean  # 请求是否成功
  code: integer  # 业务响应状态码
  message: string  # 响应消息
  data?: {
    items: array[{
      id: integer  # 解析页主键
      parse_version_id: integer  # 解析版本主键
      page_no: integer  # 页码
      source_page_image_file_id?: object  # 页图文件主键
      page_status: string  # 页状态
      has_issue: boolean  # 是否存在异常
      text_content?: object  # 页文本内容
      markdown_content?: object  # 页 Markdown 内容
      layout_json?: object  # 布局数据
      blocks: object  # 块列表
      created_at: object  # 创建时间
      updated_at: object  # 更新时间
    }]
    pagination: {
      total_count: integer  # 总记录数
      page: integer  # 当前页码
      page_size: integer  # 每页大小
      total_pages: integer  # 总页数
      has_previous: boolean  # 是否存在上一页
      has_next: boolean  # 是否存在下一页
    }
  }
  timestamp: string  # 响应时间，UTC ISO8601 格式
  request_id: string  # 请求追踪 ID
  errors?: array[{
    code: string  # 错误码
    message: string  # 错误描述
    details?: object  # 补充信息
    field?: object  # 字段名
  }]
}
```

---

### GET `/api/v1/parse-versions/{parse_version_id}/issues`

**获取解析异常列表**

分页获取解析版本下的异常记录。

**参数**

| 位置 | 名称 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| path | `parse_version_id` | integer | 是 | 解析版本主键 |
| query | `page` | integer | 否 | 页码 |
| query | `page_size` | integer | 否 | 每页大小 |

**响应**

`200` Successful Response

```json
{
  success: boolean  # 请求是否成功
  code: integer  # 业务响应状态码
  message: string  # 响应消息
  data?: {
    items: array[{
      id: integer  # 解析异常主键
      parse_version_id: integer  # 解析版本主键
      parse_page_id?: object  # 解析页主键
      parse_block_id?: object  # 解析块主键
      related_reparse_version_id?: object  # 关联重解析版本主键
      issue_type: string  # 异常类型
      severity: string  # 严重级别
      issue_status: string  # 异常状态
      detected_by: string  # 发现来源
      description?: object  # 异常描述
      resolution_note?: object  # 处理说明
      created_by?: object  # 创建人
      resolved_by?: object  # 处理人
      created_at: object  # 创建时间
      updated_at: object  # 更新时间
    }]
    pagination: {
      total_count: integer  # 总记录数
      page: integer  # 当前页码
      page_size: integer  # 每页大小
      total_pages: integer  # 总页数
      has_previous: boolean  # 是否存在上一页
      has_next: boolean  # 是否存在下一页
    }
  }
  timestamp: string  # 响应时间，UTC ISO8601 格式
  request_id: string  # 请求追踪 ID
  errors?: array[{
    code: string  # 错误码
    message: string  # 错误描述
    details?: object  # 补充信息
    field?: object  # 字段名
  }]
}
```

---

### POST `/api/v1/parse-versions/{parse_version_id}/manual-revisions`

**保存解析人工修正版本**

提交指定页的人工修正结果，后端生成新的解析版本并可按需切换为当前有效版本。

**参数**

| 位置 | 名称 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| path | `parse_version_id` | integer | 是 | 解析版本主键 |

**请求体**

```json
{
  pages: array[{
    page_no: integer  # 页码
    page_status?: string  # 页状态
    text_content?: string | null  # 页文本内容
    markdown_content?: string | null  # 页 Markdown 内容
    layout_json?: object | null  # 页布局 JSON
    blocks: array[{
      block_no: integer  # 块序号
      block_type: string  # 块类型
      heading_level?: integer | null  # 标题级别
      bbox_json?: object | null  # 坐标框
      text_content?: string | null  # 文本内容
      markdown_content?: string | null  # Markdown 内容
      asset_file_id?: integer | null  # 关联资源文件主键
      origin_ref_json?: object | null  # 原始来源引用
      is_deleted?: boolean  # 是否逻辑删除
    }]  # 块列表
  }]  # 需要替换的页列表
  set_as_current_on_success?: boolean  # 是否在成功后设为当前可用解析版本
}
```

**响应**

`201` Successful Response

```json
{
  success: boolean  # 请求是否成功
  code: integer  # 业务响应状态码
  message: string  # 响应消息
  data?: {
    id: integer  # 解析版本主键
    project_id: integer  # 所属项目主键
    textbook_version_id: integer  # 教材版本主键
    parent_parse_version_id?: object  # 父解析版本主键
    version_no: integer  # 版本号
    parse_mode: string  # 解析模式
    page_range_text?: object  # 页范围文本
    strategy_code: string  # 解析策略编码
    mineru_model?: object  # MinerU 模型名称
    parse_status: string  # 解析状态
    review_status: string  # 审核状态
    version_status: string  # 版本状态
    page_count?: object  # 页数
    issue_count: integer  # 异常数量
    source_markdown_file_id?: object  # 解析 Markdown 文件主键
    source_json_file_id?: object  # 解析 JSON 文件主键
    asset_manifest_json?: object  # 资源清单
    diff_json?: object  # 差异摘要
    error_summary?: object  # 错误摘要
    started_at?: object  # 开始时间
    finished_at?: object  # 结束时间
    created_at: object  # 创建时间
    updated_at: object  # 更新时间
  }
  timestamp: string  # 响应时间，UTC ISO8601 格式
  request_id: string  # 请求追踪 ID
  errors?: array[{
    code: string  # 错误码
    message: string  # 错误描述
    details?: object  # 补充信息
    field?: object  # 字段名
  }]
}
```

---

## 知识结构化

### POST `/api/v1/parse-versions/{parse_version_id}/knowledge-tasks`

**创建知识抽取任务**

为已确认的解析版本创建知识结构化任务，抽取章节树、知识点和证据映射。

**参数**

| 位置 | 名称 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| path | `parse_version_id` | integer | 是 | 解析版本主键 |

**请求体**

```json
{
  force_regenerate?: boolean  # 是否忽略当前可用知识版本并强制重新生成
}
```

**响应**

`201` Successful Response

```json
{
  success: boolean  # 请求是否成功
  code: integer  # 业务响应状态码
  message: string  # 响应消息
  data?: {
    id: integer  # 任务主键
    project_id: integer  # 所属项目主键
    generation_batch_id?: object  # 生成批次主键
    module_code: string  # 模块编码
    task_type: string  # 任务类型
    biz_key?: string  # 业务键
    task_status: string  # 任务状态
    queue_name?: string  # 队列名称
    current_stage?: string  # 当前阶段
    progress_percent: integer  # 任务进度
    retry_count: integer  # 重试次数
    max_retry_count: integer  # 最大重试次数
    worker_task_id?: object  # Worker 任务ID
    last_error_code?: object  # 最近错误码
    last_error_message?: object  # 最近错误信息
    payload_json?: object  # 任务载荷
    result_json?: object  # 任务结果
    started_at?: object  # 开始时间
    finished_at?: object  # 结束时间
    created_at: object  # 创建时间
    updated_at: object  # 更新时间
  }
  timestamp: string  # 响应时间，UTC ISO8601 格式
  request_id: string  # 请求追踪 ID
  errors?: array[{
    code: string  # 错误码
    message: string  # 错误描述
    details?: object  # 补充信息
    field?: object  # 字段名
  }]
}
```

---

### GET `/api/v1/parse-versions/{parse_version_id}/knowledge-versions`

**获取知识版本列表**

分页获取指定解析版本下的知识结构版本列表。

**参数**

| 位置 | 名称 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| path | `parse_version_id` | integer | 是 | 解析版本主键 |
| query | `page` | integer | 否 | 页码 |
| query | `page_size` | integer | 否 | 每页大小 |

**响应**

`200` Successful Response

```json
{
  success: boolean  # 请求是否成功
  code: integer  # 业务响应状态码
  message: string  # 响应消息
  data?: {
    items: array[{
      id: integer  # 知识版本主键
      project_id: integer  # 所属项目主键
      parse_version_id: integer  # 解析版本主键
      parent_knowledge_version_id?: object  # 父知识版本主键
      version_no: integer  # 版本号
      version_status: string  # 版本状态
      summary_json?: object  # 知识摘要
      chapter_count: integer  # 章节数量
      point_count: integer  # 知识点数量
      created_by?: object  # 创建人主键
      created_at: object  # 创建时间
      updated_at: object  # 更新时间
    }]
    pagination: {
      total_count: integer  # 总记录数
      page: integer  # 当前页码
      page_size: integer  # 每页大小
      total_pages: integer  # 总页数
      has_previous: boolean  # 是否存在上一页
      has_next: boolean  # 是否存在下一页
    }
  }
  timestamp: string  # 响应时间，UTC ISO8601 格式
  request_id: string  # 请求追踪 ID
  errors?: array[{
    code: string  # 错误码
    message: string  # 错误描述
    details?: object  # 补充信息
    field?: object  # 字段名
  }]
}
```

---

### GET `/api/v1/knowledge-versions/{knowledge_version_id}`

**获取知识版本详情**

获取单个知识版本的基础信息和摘要统计。

**参数**

| 位置 | 名称 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| path | `knowledge_version_id` | integer | 是 | 知识版本主键 |

**响应**

`200` Successful Response

```json
{
  success: boolean  # 请求是否成功
  code: integer  # 业务响应状态码
  message: string  # 响应消息
  data?: {
    id: integer  # 知识版本主键
    project_id: integer  # 所属项目主键
    parse_version_id: integer  # 解析版本主键
    parent_knowledge_version_id?: object  # 父知识版本主键
    version_no: integer  # 版本号
    version_status: string  # 版本状态
    summary_json?: object  # 知识摘要
    chapter_count: integer  # 章节数量
    point_count: integer  # 知识点数量
    created_by?: object  # 创建人主键
    created_at: object  # 创建时间
    updated_at: object  # 更新时间
  }
  timestamp: string  # 响应时间，UTC ISO8601 格式
  request_id: string  # 请求追踪 ID
  errors?: array[{
    code: string  # 错误码
    message: string  # 错误描述
    details?: object  # 补充信息
    field?: object  # 字段名
  }]
}
```

---

### GET `/api/v1/knowledge-versions/{knowledge_version_id}/chapters`

**获取知识章节树**

获取知识版本下的平铺章节节点列表，前端可自行转换为树结构。

**参数**

| 位置 | 名称 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| path | `knowledge_version_id` | integer | 是 | 知识版本主键 |

**响应**

`200` Successful Response

```json
{
  success: boolean  # 请求是否成功
  code: integer  # 业务响应状态码
  message: string  # 响应消息
  data?: object  # 业务数据
  timestamp: string  # 响应时间，UTC ISO8601 格式
  request_id: string  # 请求追踪 ID
  errors?: array[{
    code: string  # 错误码
    message: string  # 错误描述
    details?: object  # 补充信息
    field?: object  # 字段名
  }]
}
```

---

### GET `/api/v1/knowledge-versions/{knowledge_version_id}/points`

**获取知识点列表**

分页获取知识版本下的知识点列表，支持按章节和关键词筛选。

**参数**

| 位置 | 名称 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| path | `knowledge_version_id` | integer | 是 | 知识版本主键 |
| query | `chapter_node_id` | string | 否 | 章节节点主键 |
| query | `keyword` | string | 否 | 关键字 |
| query | `page` | integer | 否 | 页码 |
| query | `page_size` | integer | 否 | 每页大小 |

**响应**

`200` Successful Response

```json
{
  success: boolean  # 请求是否成功
  code: integer  # 业务响应状态码
  message: string  # 响应消息
  data?: {
    items: array[{
      id: integer  # 知识点主键
      knowledge_version_id: integer  # 知识版本主键
      chapter_node_id?: object  # 章节节点主键
      chapter_title?: object  # 章节标题
      point_code?: object  # 知识点编码
      point_name: string  # 知识点名称
      point_type: string  # 知识点类型
      importance_level?: object  # 重要度
      difficulty_level?: object  # 难度
      mastery_level_hint?: object  # 掌握建议
      tags_json?: object  # 标签 JSON
      summary_text?: object  # 摘要
      sort_order: integer  # 排序号
      evidence_count: integer  # 证据数量
      created_at: object  # 创建时间
      updated_at: object  # 更新时间
    }]
    pagination: {
      total_count: integer  # 总记录数
      page: integer  # 当前页码
      page_size: integer  # 每页大小
      total_pages: integer  # 总页数
      has_previous: boolean  # 是否存在上一页
      has_next: boolean  # 是否存在下一页
    }
  }
  timestamp: string  # 响应时间，UTC ISO8601 格式
  request_id: string  # 请求追踪 ID
  errors?: array[{
    code: string  # 错误码
    message: string  # 错误描述
    details?: object  # 补充信息
    field?: object  # 字段名
  }]
}
```

---

### GET `/api/v1/knowledge-points/{knowledge_point_id}`

**获取知识点详情**

获取单个知识点详情及其完整证据映射。

**参数**

| 位置 | 名称 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| path | `knowledge_point_id` | integer | 是 | 知识点主键 |

**响应**

`200` Successful Response

```json
{
  success: boolean  # 请求是否成功
  code: integer  # 业务响应状态码
  message: string  # 响应消息
  data?: {
    id: integer  # 知识点主键
    knowledge_version_id: integer  # 知识版本主键
    chapter_node_id?: object  # 章节节点主键
    chapter_title?: object  # 章节标题
    point_code?: object  # 知识点编码
    point_name: string  # 知识点名称
    point_type: string  # 知识点类型
    importance_level?: object  # 重要度
    difficulty_level?: object  # 难度
    mastery_level_hint?: object  # 掌握建议
    tags_json?: object  # 标签 JSON
    summary_text?: object  # 摘要
    sort_order: integer  # 排序号
    evidence_count: integer  # 证据数量
    created_at: object  # 创建时间
    updated_at: object  # 更新时间
    evidences: object  # 证据列表
  }
  timestamp: string  # 响应时间，UTC ISO8601 格式
  request_id: string  # 请求追踪 ID
  errors?: array[{
    code: string  # 错误码
    message: string  # 错误描述
    details?: object  # 补充信息
    field?: object  # 字段名
  }]
}
```

---

### POST `/api/v1/knowledge-versions/{knowledge_version_id}/manual-revisions`

**保存知识人工修正版本**

按操作补丁提交知识修正内容，生成新的知识版本并替换当前可用版本。

**参数**

| 位置 | 名称 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| path | `knowledge_version_id` | integer | 是 | 知识版本主键 |

**请求体**

```json
{
  operations: array[{
    op_type: string  # 操作类型
    summary_json?: object | null  # 新的知识摘要 JSON
    chapter_node_id?: integer | null  # 章节节点主键
    knowledge_point_id?: integer | null  # 知识点主键
    source_knowledge_point_ids?: array[integer] | null  # 待合并知识点主键列表
    title?: string | null  # 章节标题
    point_code?: string | null  # 知识点编码
    point_name?: string | null  # 知识点名称
    point_type?: string | null  # 知识点类型
    importance_level?: integer | null  # 重要度
    difficulty_level?: integer | null  # 难度
    mastery_level_hint?: string | null  # 掌握建议
    tags_json?: object | null  # 标签 JSON
    summary_text?: string | null  # 摘要文本
    sort_order?: integer | null  # 排序号
    page_start?: integer | null  # 章节起始页
    page_end?: integer | null  # 章节结束页
    evidences?: array[{
      page_no: integer  # 页码
      block_no?: integer | null  # 块序号
      evidence_type?: string  # 证据类型
      excerpt_text?: string | null  # 证据片段
      bbox_json?: object | null  # 证据坐标
      score_value?: number | null  # 证据分数
    }] | null  # 替换后的证据列表
  }]  # 修正操作列表
}
```

**响应**

`201` Successful Response

```json
{
  success: boolean  # 请求是否成功
  code: integer  # 业务响应状态码
  message: string  # 响应消息
  data?: {
    id: integer  # 知识版本主键
    project_id: integer  # 所属项目主键
    parse_version_id: integer  # 解析版本主键
    parent_knowledge_version_id?: object  # 父知识版本主键
    version_no: integer  # 版本号
    version_status: string  # 版本状态
    summary_json?: object  # 知识摘要
    chapter_count: integer  # 章节数量
    point_count: integer  # 知识点数量
    created_by?: object  # 创建人主键
    created_at: object  # 创建时间
    updated_at: object  # 更新时间
  }
  timestamp: string  # 响应时间，UTC ISO8601 格式
  request_id: string  # 请求追踪 ID
  errors?: array[{
    code: string  # 错误码
    message: string  # 错误描述
    details?: object  # 补充信息
    field?: object  # 字段名
  }]
}
```

---

## 生成编排

### POST `/api/v1/generation-batches`

**创建生成批次**

冻结知识版本与学情版本基线，创建生成批次并自动发起课程大纲与教案生成任务。chapter_range_json 缺省或 chapter_node_ids 为空表示全量，非空时仅围绕选中章节及其子章节生成。

**请求体**

```json
{
  project_id: integer  # 项目主键
  knowledge_version_id: integer  # 知识版本主键
  learner_profile_version_id: integer  # 学情版本主键
  batch_name?: string | null  # 批次名称
  chapter_range_json?: object | null  # 章节范围快照；缺省或 chapter_node_ids 为空表示全量，非空 chapter_node_ids 表示选中章节及其子章节
  course_count: integer  # 总课次
  session_duration_minutes: integer  # 单次课时分钟数
}
```

**响应**

`201` Successful Response

```json
{
  success: boolean  # 请求是否成功
  code: integer  # 业务响应状态码
  message: string  # 响应消息
  data?: {
    id: integer  # 生成批次主键
    project_id: integer  # 所属项目主键
    batch_no: integer  # 项目内批次号
    batch_name?: object  # 批次名称
    trigger_mode: string  # 触发模式
    batch_status: string  # 批次状态
    knowledge_version_id: integer  # 知识版本主键
    learner_profile_version_id: integer  # 学情版本主键
    chapter_range_json?: object  # 章节范围快照
    course_count?: object  # 总课次快照
    session_duration_minutes?: object  # 单次课时分钟数快照
    template_snapshot_json?: object  # 模板快照
    assessment_strategy_json?: object  # 测评策略快照
    pipeline_options_json?: object  # 编排选项
    curriculum_plan_id?: object  # 课程大纲版本主键
    lesson_plan_id?: object  # 教案版本主键
    started_at?: object  # 开始时间
    finished_at?: object  # 结束时间
    created_by?: object  # 创建人
    created_at: object  # 创建时间
    updated_at: object  # 更新时间
    lesson_plan_ids?: object  # 批次下全部教案主键列表
    tasks?: object  # 批次关联任务列表
  }
  timestamp: string  # 响应时间，UTC ISO8601 格式
  request_id: string  # 请求追踪 ID
  errors?: array[{
    code: string  # 错误码
    message: string  # 错误描述
    details?: object  # 补充信息
    field?: object  # 字段名
  }]
}
```

---

### GET `/api/v1/generation-batches`

**获取生成批次列表**

分页获取指定项目下的生成批次列表。

**参数**

| 位置 | 名称 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| query | `project_id` | integer | 是 | 项目主键 |
| query | `page` | integer | 否 | 页码 |
| query | `page_size` | integer | 否 | 每页大小 |

**响应**

`200` Successful Response

```json
{
  success: boolean  # 请求是否成功
  code: integer  # 业务响应状态码
  message: string  # 响应消息
  data?: {
    items: array[{
      id: integer  # 生成批次主键
      project_id: integer  # 所属项目主键
      batch_no: integer  # 项目内批次号
      batch_name?: object  # 批次名称
      trigger_mode: string  # 触发模式
      batch_status: string  # 批次状态
      knowledge_version_id: integer  # 知识版本主键
      learner_profile_version_id: integer  # 学情版本主键
      chapter_range_json?: object  # 章节范围快照
      course_count?: object  # 总课次快照
      session_duration_minutes?: object  # 单次课时分钟数快照
      template_snapshot_json?: object  # 模板快照
      assessment_strategy_json?: object  # 测评策略快照
      pipeline_options_json?: object  # 编排选项
      curriculum_plan_id?: object  # 课程大纲版本主键
      lesson_plan_id?: object  # 教案版本主键
      started_at?: object  # 开始时间
      finished_at?: object  # 结束时间
      created_by?: object  # 创建人
      created_at: object  # 创建时间
      updated_at: object  # 更新时间
    }]
    pagination: {
      total_count: integer  # 总记录数
      page: integer  # 当前页码
      page_size: integer  # 每页大小
      total_pages: integer  # 总页数
      has_previous: boolean  # 是否存在上一页
      has_next: boolean  # 是否存在下一页
    }
  }
  timestamp: string  # 响应时间，UTC ISO8601 格式
  request_id: string  # 请求追踪 ID
  errors?: array[{
    code: string  # 错误码
    message: string  # 错误描述
    details?: object  # 补充信息
    field?: object  # 字段名
  }]
}
```

---

### GET `/api/v1/generation-batches/{generation_batch_id}`

**获取生成批次详情**

获取生成批次的基线快照、状态和关联任务列表。

**参数**

| 位置 | 名称 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| path | `generation_batch_id` | integer | 是 | 生成批次主键 |

**响应**

`200` Successful Response

```json
{
  success: boolean  # 请求是否成功
  code: integer  # 业务响应状态码
  message: string  # 响应消息
  data?: {
    id: integer  # 生成批次主键
    project_id: integer  # 所属项目主键
    batch_no: integer  # 项目内批次号
    batch_name?: object  # 批次名称
    trigger_mode: string  # 触发模式
    batch_status: string  # 批次状态
    knowledge_version_id: integer  # 知识版本主键
    learner_profile_version_id: integer  # 学情版本主键
    chapter_range_json?: object  # 章节范围快照
    course_count?: object  # 总课次快照
    session_duration_minutes?: object  # 单次课时分钟数快照
    template_snapshot_json?: object  # 模板快照
    assessment_strategy_json?: object  # 测评策略快照
    pipeline_options_json?: object  # 编排选项
    curriculum_plan_id?: object  # 课程大纲版本主键
    lesson_plan_id?: object  # 教案版本主键
    started_at?: object  # 开始时间
    finished_at?: object  # 结束时间
    created_by?: object  # 创建人
    created_at: object  # 创建时间
    updated_at: object  # 更新时间
    lesson_plan_ids?: object  # 批次下全部教案主键列表
    tasks?: object  # 批次关联任务列表
  }
  timestamp: string  # 响应时间，UTC ISO8601 格式
  request_id: string  # 请求追踪 ID
  errors?: array[{
    code: string  # 错误码
    message: string  # 错误描述
    details?: object  # 补充信息
    field?: object  # 字段名
  }]
}
```

---

## 一键生成

### POST `/api/v1/projects/{project_id}/generation-runs`

**启动一键生成**

为指定项目启动一次完整的 Phase2 生成运行（教材解析 → 学情分析 → 知识结构 → 课程规划 → 教案 → 覆盖检查）。后端持有完整编排权：前端只需点一次本接口，无需再单独触发 parse、knowledge、generation-batch。同一项目同时只允许一个活跃 run，重复调用本接口将返回当前活跃 run 详情（幂等）。auto_confirm_parse 默认开启；若关闭，解析成功后 run 将停在 waiting_user_confirm，等用户在解析页确认后自动续跑。

**参数**

| 位置 | 名称 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| path | `project_id` | integer | 是 | 项目主键 |

**请求体**

```json
{
  course_count: integer  # 课次数
  session_duration_minutes: integer  # 单次时长（分钟）
  chapter_range_json?: object | null  # 章节范围；省略表示全量
  auto_confirm_parse?: boolean  # 教材解析成功后是否自动 confirm。默认开启，符合「一键生成」预期；若希望解析后人工校对后再继续下游，可显式传 false，此时 run 将进入 waiting_user_confirm 状态，用户在解析页确认后自动续跑。
}
```

**响应**

`201` Successful Response

```json
{
  success: boolean  # 请求是否成功
  code: integer  # 业务响应状态码
  message: string  # 响应消息
  data?: {
    id: integer  # 运行主键
    project_id: integer  # 项目主键
    run_status: string  # 运行状态
    course_count: integer  # 课次数
    session_duration_minutes: integer  # 单次时长（分钟）
    chapter_range_json?: object  # 章节范围
    auto_confirm_parse: boolean  # 解析自动确认开关
    parse_version_id?: integer  # 使用的解析版本
    knowledge_version_id?: integer  # 使用的知识版本
    generation_batch_id?: integer  # 生成批次
    blocked_reason?: object  # 阻塞原因编码
    last_error_code?: object  # 错误码
    last_error_message?: object  # 错误信息
    started_at?: object  # 开始时间
    finished_at?: object  # 结束时间
    created_at: object  # 创建时间
    updated_at: object  # 更新时间
  }
  timestamp: string  # 响应时间，UTC ISO8601 格式
  request_id: string  # 请求追踪 ID
  errors?: array[{
    code: string  # 错误码
    message: string  # 错误描述
    details?: object  # 补充信息
    field?: object  # 字段名
  }]
}
```

---

### GET `/api/v1/projects/{project_id}/generation-runs/active`

**获取当前活跃一键生成运行**

返回项目当前活跃（运行中或等待用户确认）的一键生成 run；无活跃 run 时返回 null。

**参数**

| 位置 | 名称 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| path | `project_id` | integer | 是 | 项目主键 |

**响应**

`200` Successful Response

```json
{
  success: boolean  # 请求是否成功
  code: integer  # 业务响应状态码
  message: string  # 响应消息
  data?: object  # 业务数据
  timestamp: string  # 响应时间，UTC ISO8601 格式
  request_id: string  # 请求追踪 ID
  errors?: array[{
    code: string  # 错误码
    message: string  # 错误描述
    details?: object  # 补充信息
    field?: object  # 字段名
  }]
}
```

---

## 课程大纲

### GET `/api/v1/curriculum-plans`

**获取课程大纲列表**

分页获取指定项目下的课程大纲版本列表，可按知识版本筛选。

**参数**

| 位置 | 名称 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| query | `project_id` | integer | 是 | 项目主键 |
| query | `knowledge_version_id` | string | 否 | 知识版本主键 |
| query | `page` | integer | 否 | 页码 |
| query | `page_size` | integer | 否 | 每页大小 |

**响应**

`200` Successful Response

```json
{
  success: boolean  # 请求是否成功
  code: integer  # 业务响应状态码
  message: string  # 响应消息
  data?: {
    items: array[{
      id: integer  # 课程大纲主键
      project_id: integer  # 所属项目主键
      knowledge_version_id: integer  # 知识版本主键
      learner_profile_version_id: integer  # 学情版本主键
      parent_plan_id?: object  # 父课程大纲主键
      version_no: integer  # 版本号
      plan_title: string  # 课程大纲标题
      target_subject_code: string  # 目标学科编码
      target_grade_code?: object  # 目标年级编码
      chapter_range_json?: object  # 章节范围
      course_count: integer  # 总课次
      session_duration_minutes: integer  # 单次课时分钟数
      generation_mode: string  # 生成模式
      version_status: string  # 版本状态
      summary_text?: object  # 摘要
      content_json: object  # 课程大纲结构化内容
      export_file_id?: object  # 导出文件主键
      created_by?: object  # 创建人
      created_at: object  # 创建时间
      updated_at: object  # 更新时间
    }]
    pagination: {
      total_count: integer  # 总记录数
      page: integer  # 当前页码
      page_size: integer  # 每页大小
      total_pages: integer  # 总页数
      has_previous: boolean  # 是否存在上一页
      has_next: boolean  # 是否存在下一页
    }
  }
  timestamp: string  # 响应时间，UTC ISO8601 格式
  request_id: string  # 请求追踪 ID
  errors?: array[{
    code: string  # 错误码
    message: string  # 错误描述
    details?: object  # 补充信息
    field?: object  # 字段名
  }]
}
```

---

### GET `/api/v1/curriculum-plans/{curriculum_plan_id}`

**获取课程大纲详情**

获取单个课程大纲版本的结构化内容。

**参数**

| 位置 | 名称 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| path | `curriculum_plan_id` | integer | 是 | 课程大纲主键 |

**响应**

`200` Successful Response

```json
{
  success: boolean  # 请求是否成功
  code: integer  # 业务响应状态码
  message: string  # 响应消息
  data?: {
    id: integer  # 课程大纲主键
    project_id: integer  # 所属项目主键
    knowledge_version_id: integer  # 知识版本主键
    learner_profile_version_id: integer  # 学情版本主键
    parent_plan_id?: object  # 父课程大纲主键
    version_no: integer  # 版本号
    plan_title: string  # 课程大纲标题
    target_subject_code: string  # 目标学科编码
    target_grade_code?: object  # 目标年级编码
    chapter_range_json?: object  # 章节范围
    course_count: integer  # 总课次
    session_duration_minutes: integer  # 单次课时分钟数
    generation_mode: string  # 生成模式
    version_status: string  # 版本状态
    summary_text?: object  # 摘要
    content_json: object  # 课程大纲结构化内容
    export_file_id?: object  # 导出文件主键
    created_by?: object  # 创建人
    created_at: object  # 创建时间
    updated_at: object  # 更新时间
  }
  timestamp: string  # 响应时间，UTC ISO8601 格式
  request_id: string  # 请求追踪 ID
  errors?: array[{
    code: string  # 错误码
    message: string  # 错误描述
    details?: object  # 补充信息
    field?: object  # 字段名
  }]
}
```

---

### POST `/api/v1/curriculum-plans/{curriculum_plan_id}/export-docx`

**导出课程大纲 DOCX**

将当前教师可见的课程大纲结构化内容同步导出为 DOCX 文件，并返回签名下载地址。

DOCX 模板 v2（2026-05-27 起生效）共用以下约定：
- 文件名面向教师可读：`{plan_title}-课程大纲.docx`；
- `object_key` 嵌入模板版本号段（如 `.../tv2/…`），模板升级时旧 `export_file_id` 由迁移脚本统一清空；
- 渲染层不再展示英文枚举与数据库内部追溯字段（`single_choice / fill_blank / focus / audience / source_trace` 等）。

**参数**

| 位置 | 名称 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| path | `curriculum_plan_id` | integer | 是 | 课程大纲主键 |

**响应**

`200` Successful Response

```json
{
  success: boolean  # 请求是否成功
  code: integer  # 业务响应状态码
  message: string  # 响应消息
  data?: {
    file_object_id: integer  # 文件对象主键
    bucket_name: string  # 存储桶名称
    object_key: string  # 对象路径
    signed_url: object  # 签名下载地址
    expires_in_seconds: integer  # 有效期秒数
    generated_at: object  # 生成时间
  }
  timestamp: string  # 响应时间，UTC ISO8601 格式
  request_id: string  # 请求追踪 ID
  errors?: array[{
    code: string  # 错误码
    message: string  # 错误描述
    details?: object  # 补充信息
    field?: object  # 字段名
  }]
}
```

---

## 教案

### GET `/api/v1/lesson-plans`

**获取教案列表**

分页获取指定课程大纲下的教案版本列表。

**参数**

| 位置 | 名称 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| query | `curriculum_plan_id` | integer | 是 | 课程大纲主键 |
| query | `page` | integer | 否 | 页码 |
| query | `page_size` | integer | 否 | 每页大小 |

**响应**

`200` Successful Response

```json
{
  success: boolean  # 请求是否成功
  code: integer  # 业务响应状态码
  message: string  # 响应消息
  data?: {
    items: array[{
      id: integer  # 教案主键
      curriculum_plan_id: integer  # 课程大纲主键
      generation_batch_id?: object  # 生成批次主键
      class_session_no?: integer  # 批次内课次序号
      version_no: integer  # 版本号
      lesson_title: string  # 教案标题
      style_code?: string  # 教案风格编码
      version_status: string  # 版本状态
      summary_text?: object  # 教案摘要
      content_json: object  # 教案结构化内容
      export_file_id?: object  # 导出文件主键
      created_by?: object  # 创建人
      created_at: object  # 创建时间
      updated_at: object  # 更新时间
    }]
    pagination: {
      total_count: integer  # 总记录数
      page: integer  # 当前页码
      page_size: integer  # 每页大小
      total_pages: integer  # 总页数
      has_previous: boolean  # 是否存在上一页
      has_next: boolean  # 是否存在下一页
    }
  }
  timestamp: string  # 响应时间，UTC ISO8601 格式
  request_id: string  # 请求追踪 ID
  errors?: array[{
    code: string  # 错误码
    message: string  # 错误描述
    details?: object  # 补充信息
    field?: object  # 字段名
  }]
}
```

---

### GET `/api/v1/lesson-plans/{lesson_plan_id}`

**获取教案详情**

获取单个教案版本的结构化内容。

**参数**

| 位置 | 名称 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| path | `lesson_plan_id` | integer | 是 | 教案主键 |

**响应**

`200` Successful Response

```json
{
  success: boolean  # 请求是否成功
  code: integer  # 业务响应状态码
  message: string  # 响应消息
  data?: {
    id: integer  # 教案主键
    curriculum_plan_id: integer  # 课程大纲主键
    generation_batch_id?: object  # 生成批次主键
    class_session_no?: integer  # 批次内课次序号
    version_no: integer  # 版本号
    lesson_title: string  # 教案标题
    style_code?: string  # 教案风格编码
    version_status: string  # 版本状态
    summary_text?: object  # 教案摘要
    content_json: object  # 教案结构化内容
    export_file_id?: object  # 导出文件主键
    created_by?: object  # 创建人
    created_at: object  # 创建时间
    updated_at: object  # 更新时间
  }
  timestamp: string  # 响应时间，UTC ISO8601 格式
  request_id: string  # 请求追踪 ID
  errors?: array[{
    code: string  # 错误码
    message: string  # 错误描述
    details?: object  # 补充信息
    field?: object  # 字段名
  }]
}
```

---

### POST `/api/v1/lesson-plans/{lesson_plan_id}/export-docx`

**导出教案 DOCX**

将当前教师可见的教案结构化内容同步导出为 DOCX 文件，并返回签名下载地址。

DOCX 模板 v2（2026-05-27 起生效）共用以下约定：
- 文件名面向教师可读：`{lesson_title}-第{N}讲-教案.docx`，无课次序号时省略 `-第{N}讲`；
- `object_key` 嵌入模板版本号段（如 `.../tv2/…`），模板升级时旧 `export_file_id` 由迁移脚本统一清空；
- 渲染层不再展示英文枚举与数据库内部追溯字段，教学流程「知识点」列改用名称替代 ID。

**参数**

| 位置 | 名称 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| path | `lesson_plan_id` | integer | 是 | 教案主键 |

**响应**

`200` Successful Response

```json
{
  success: boolean  # 请求是否成功
  code: integer  # 业务响应状态码
  message: string  # 响应消息
  data?: {
    file_object_id: integer  # 文件对象主键
    bucket_name: string  # 存储桶名称
    object_key: string  # 对象路径
    signed_url: object  # 签名下载地址
    expires_in_seconds: integer  # 有效期秒数
    generated_at: object  # 生成时间
  }
  timestamp: string  # 响应时间，UTC ISO8601 格式
  request_id: string  # 请求追踪 ID
  errors?: array[{
    code: string  # 错误码
    message: string  # 错误描述
    details?: object  # 补充信息
    field?: object  # 字段名
  }]
}
```

---

## 测评

### POST `/api/v1/curriculum-plans/{curriculum_plan_id}/assessment-tasks`

**创建按需测评生成任务**

为当前教师可见的课程大纲创建测评生成任务，按 scene_type 自动套用测练场景预设，生成测评蓝图、试卷和题目；同一批次同一场景不可重复生成。

**参数**

| 位置 | 名称 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| path | `curriculum_plan_id` | integer | 是 | 课程大纲主键 |

**请求体**

```json
{
  scene_type?: 'homework' | 'unit_test' | 'final_exam'  # 测练场景类型，后端按场景自动套用预设策略：unit_test=单元测试，final_exam=期末综合测；课后作业（homework）已迁移至 /lesson-plans/{lesson_plan_id}/homework-tasks 课次维度接口，本接口不再接受 homework 场景。
}
```

**响应**

`201` Successful Response

```json
{
  success: boolean  # 请求是否成功
  code: integer  # 业务响应状态码
  message: string  # 响应消息
  data?: {
    id: integer  # 任务主键
    project_id: integer  # 所属项目主键
    generation_batch_id?: object  # 生成批次主键
    module_code: string  # 模块编码
    task_type: string  # 任务类型
    biz_key?: string  # 业务键
    task_status: string  # 任务状态
    queue_name?: string  # 队列名称
    current_stage?: string  # 当前阶段
    progress_percent: integer  # 任务进度
    retry_count: integer  # 重试次数
    max_retry_count: integer  # 最大重试次数
    worker_task_id?: object  # Worker 任务ID
    last_error_code?: object  # 最近错误码
    last_error_message?: object  # 最近错误信息
    payload_json?: object  # 任务载荷
    result_json?: object  # 任务结果
    started_at?: object  # 开始时间
    finished_at?: object  # 结束时间
    created_at: object  # 创建时间
    updated_at: object  # 更新时间
  }
  timestamp: string  # 响应时间，UTC ISO8601 格式
  request_id: string  # 请求追踪 ID
  errors?: array[{
    code: string  # 错误码
    message: string  # 错误描述
    details?: object  # 补充信息
    field?: object  # 字段名
  }]
}
```

---

### GET `/api/v1/assessment-blueprints`

**获取测评蓝图列表**

分页获取指定课程大纲下的测评蓝图版本列表，可按测评场景筛选。

**参数**

| 位置 | 名称 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| query | `curriculum_plan_id` | integer | 是 | 课程大纲主键 |
| query | `scenario_type` | string | 否 | 测练场景类型：homework=课后作业，unit_test=单元测试，final_exam=期末综合测 |
| query | `page` | integer | 否 | 页码 |
| query | `page_size` | integer | 否 | 每页大小 |

**响应**

`200` Successful Response

```json
{
  success: boolean  # 请求是否成功
  code: integer  # 业务响应状态码
  message: string  # 响应消息
  data?: {
    items: array[{
      id: integer  # 测评蓝图主键
      curriculum_plan_id: integer  # 课程大纲主键
      version_no: integer  # 版本号
      scenario_type: string  # 测评场景类型
      blueprint_name: string  # 测评蓝图名称
      version_status: string  # 版本状态
      strategy_json?: object  # 测评策略配置
      content_json: object  # 测评蓝图结构化内容
      export_file_id?: object  # 导出文件主键
      created_by?: object  # 创建人
      created_at: object  # 创建时间
      updated_at: object  # 更新时间
    }]
    pagination: {
      total_count: integer  # 总记录数
      page: integer  # 当前页码
      page_size: integer  # 每页大小
      total_pages: integer  # 总页数
      has_previous: boolean  # 是否存在上一页
      has_next: boolean  # 是否存在下一页
    }
  }
  timestamp: string  # 响应时间，UTC ISO8601 格式
  request_id: string  # 请求追踪 ID
  errors?: array[{
    code: string  # 错误码
    message: string  # 错误描述
    details?: object  # 补充信息
    field?: object  # 字段名
  }]
}
```

---

### GET `/api/v1/assessment-blueprints/{assessment_blueprint_id}`

**获取测评蓝图详情**

获取单个测评蓝图版本的结构化内容。

**参数**

| 位置 | 名称 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| path | `assessment_blueprint_id` | integer | 是 | 测评蓝图主键 |

**响应**

`200` Successful Response

```json
{
  success: boolean  # 请求是否成功
  code: integer  # 业务响应状态码
  message: string  # 响应消息
  data?: {
    id: integer  # 测评蓝图主键
    curriculum_plan_id: integer  # 课程大纲主键
    version_no: integer  # 版本号
    scenario_type: string  # 测评场景类型
    blueprint_name: string  # 测评蓝图名称
    version_status: string  # 版本状态
    strategy_json?: object  # 测评策略配置
    content_json: object  # 测评蓝图结构化内容
    export_file_id?: object  # 导出文件主键
    created_by?: object  # 创建人
    created_at: object  # 创建时间
    updated_at: object  # 更新时间
  }
  timestamp: string  # 响应时间，UTC ISO8601 格式
  request_id: string  # 请求追踪 ID
  errors?: array[{
    code: string  # 错误码
    message: string  # 错误描述
    details?: object  # 补充信息
    field?: object  # 字段名
  }]
}
```

---

### GET `/api/v1/paper-results`

**获取试卷结果列表**

分页获取指定生成批次下的作业或试卷结果列表，可按场景类型筛选。

**参数**

| 位置 | 名称 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| query | `generation_batch_id` | integer | 是 | 生成批次主键 |
| query | `scene_type` | string | 否 | 测练场景类型：homework=课后作业，unit_test=单元测试，final_exam=期末综合测 |
| query | `page` | integer | 否 | 页码 |
| query | `page_size` | integer | 否 | 每页大小 |

**响应**

`200` Successful Response

```json
{
  success: boolean  # 请求是否成功
  code: integer  # 业务响应状态码
  message: string  # 响应消息
  data?: {
    items: array[{
      id: integer  # 试卷结果主键
      generation_batch_id: integer  # 生成批次主键
      assessment_blueprint_id: integer  # 测评蓝图主键
      scene_type: string  # 试卷场景类型
      title: string  # 试卷标题
      result_status: string  # 结果状态
      question_count: integer  # 题目数量
      difficulty_stats_json?: object  # 难度统计
      paper_json: object  # 试卷结构化内容
      export_file_id?: object  # 导出文件主键
      created_at: object  # 创建时间
      updated_at: object  # 更新时间
    }]
    pagination: {
      total_count: integer  # 总记录数
      page: integer  # 当前页码
      page_size: integer  # 每页大小
      total_pages: integer  # 总页数
      has_previous: boolean  # 是否存在上一页
      has_next: boolean  # 是否存在下一页
    }
  }
  timestamp: string  # 响应时间，UTC ISO8601 格式
  request_id: string  # 请求追踪 ID
  errors?: array[{
    code: string  # 错误码
    message: string  # 错误描述
    details?: object  # 补充信息
    field?: object  # 字段名
  }]
}
```

---

### GET `/api/v1/paper-results/{paper_result_id}`

**获取试卷结果详情**

获取单个作业或试卷结果的结构化内容与题目明细。

**参数**

| 位置 | 名称 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| path | `paper_result_id` | integer | 是 | 试卷结果主键 |

**响应**

`200` Successful Response

```json
{
  success: boolean  # 请求是否成功
  code: integer  # 业务响应状态码
  message: string  # 响应消息
  data?: {
    id: integer  # 试卷结果主键
    generation_batch_id: integer  # 生成批次主键
    assessment_blueprint_id: integer  # 测评蓝图主键
    scene_type: string  # 试卷场景类型
    title: string  # 试卷标题
    result_status: string  # 结果状态
    question_count: integer  # 题目数量
    difficulty_stats_json?: object  # 难度统计
    paper_json: object  # 试卷结构化内容
    export_file_id?: object  # 导出文件主键
    created_at: object  # 创建时间
    updated_at: object  # 更新时间
    questions?: object  # 题目明细列表
  }
  timestamp: string  # 响应时间，UTC ISO8601 格式
  request_id: string  # 请求追踪 ID
  errors?: array[{
    code: string  # 错误码
    message: string  # 错误描述
    details?: object  # 补充信息
    field?: object  # 字段名
  }]
}
```

---

### GET `/api/v1/question-items`

**获取题库题目列表**

按批次、试卷、知识点、题型、难度、测练场景筛选当前教师可见的题目，支持分页。

**参数**

| 位置 | 名称 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| query | `generation_batch_id` | string | 否 | 生成批次主键 |
| query | `paper_result_id` | string | 否 | 试卷结果主键 |
| query | `knowledge_point_id` | string | 否 | 知识点主键 |
| query | `question_type` | string | 否 | 题型：single_choice=单选题，fill_blank=填空题，short_answer=简答题 |
| query | `difficulty_level` | string | 否 | 难度等级（1-5） |
| query | `scene_type` | string | 否 | 测练场景类型：homework=课后作业，unit_test=单元测试，final_exam=期末综合测 |
| query | `page` | integer | 否 | 页码 |
| query | `page_size` | integer | 否 | 每页大小 |

**响应**

`200` Successful Response

```json
{
  success: boolean  # 请求是否成功
  code: integer  # 业务响应状态码
  message: string  # 响应消息
  data?: {
    items: array[{
      id: integer  # 题目主键
      generation_batch_id: integer  # 生成批次主键
      paper_result_id: integer  # 试卷结果主键
      knowledge_point_id?: object  # 知识点主键
      knowledge_point_name?: object  # 知识点名称，前端考查标签使用
      question_no: integer  # 题号
      question_type: string  # 题型
      difficulty_level?: object  # 难度等级
      score_value?: object  # 分值
      stem_text: object  # 题干
      options_json?: object  # 选项
      answer_text?: object  # 答案
      analysis_text?: object  # 解析
      source_trace_json?: object  # 来源摘要
      question_basis_json?: object  # 题目考查依据：包含知识点、章节、课次、教学目标、测评定位、依据说明与蓝图来源
      created_at: object  # 创建时间
      updated_at: object  # 更新时间
      paper_title: string  # 所属试卷标题
      scene_type: string  # 所属测练场景
    }]
    pagination: {
      total_count: integer  # 总记录数
      page: integer  # 当前页码
      page_size: integer  # 每页大小
      total_pages: integer  # 总页数
      has_previous: boolean  # 是否存在上一页
      has_next: boolean  # 是否存在下一页
    }
  }
  timestamp: string  # 响应时间，UTC ISO8601 格式
  request_id: string  # 请求追踪 ID
  errors?: array[{
    code: string  # 错误码
    message: string  # 错误描述
    details?: object  # 补充信息
    field?: object  # 字段名
  }]
}
```

---

### POST `/api/v1/paper-results/{paper_result_id}/export-docx`

**导出试卷结果 DOCX**

将当前教师可见的试卷结构化内容和题目明细同步导出为 DOCX 文件，并返回签名下载地址。

DOCX 模板 v2（2026-05-27 起生效）共用以下约定：
- 文件名面向教师可读：`{paper_title}-{场景中文名}.docx`（场景如「单元测试 / 期末综合测」）；
- `object_key` 嵌入模板版本号段（如 `.../tv2/…`），模板升级时旧 `export_file_id` 由迁移脚本统一清空；
- 渲染层不再展示英文枚举、内部追溯字段，题型/难度统一中文，选项以 `A. 内容` 形式呈现。

**参数**

| 位置 | 名称 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| path | `paper_result_id` | integer | 是 | 试卷结果主键 |

**响应**

`200` Successful Response

```json
{
  success: boolean  # 请求是否成功
  code: integer  # 业务响应状态码
  message: string  # 响应消息
  data?: {
    file_object_id: integer  # 文件对象主键
    bucket_name: string  # 存储桶名称
    object_key: string  # 对象路径
    signed_url: object  # 签名下载地址
    expires_in_seconds: integer  # 有效期秒数
    generated_at: object  # 生成时间
  }
  timestamp: string  # 响应时间，UTC ISO8601 格式
  request_id: string  # 请求追踪 ID
  errors?: array[{
    code: string  # 错误码
    message: string  # 错误描述
    details?: object  # 补充信息
    field?: object  # 字段名
  }]
}
```

---

## 课后作业

> 前端接入提示：课后作业不在自动 pipeline 中批量生成，需要在教案生成完成后，按 `lesson_plan_id` 单独触发。推荐在教案详情页提供“生成课后作业”按钮，在课程/批次维度提供“作业总览”页。

- 触发生成：调用 `POST /api/v1/lesson-plans/{lesson_plan_id}/homework-tasks`，成功返回 `TaskListItem`。本地同步任务模式下 `result_json` 可能立即包含 `homework_result_id`；异步模式下前端应按任务中心接口轮询任务状态。
- 查询详情：调用 `GET /api/v1/lesson-plans/{lesson_plan_id}/homework-result` 获取本课唯一作业，响应内 `questions` 可直接用于渲染题目列表。
- 作业总览：调用 `GET /api/v1/homework-results?curriculum_plan_id={id}` 或 `generation_batch_id={id}`，列表按 `class_session_no` 升序返回。
- 题库筛选：调用 `GET /api/v1/homework-questions`，支持按 `lesson_plan_id`、`homework_result_id`、`knowledge_point_id`、`question_type`、`difficulty_level` 过滤。
- 常见错误：重复生成返回 `409 TASK_CONFLICT`；未生成详情返回 `404 HOMEWORK_RESULT_NOT_FOUND`；继续走批次级测评接口传 `scene_type=homework` 返回 `422 ASSESSMENT_SCENE_INVALID`。

### POST `/api/v1/lesson-plans/{lesson_plan_id}/homework-tasks`

**创建课后作业生成任务**

为当前教师可见的教案创建课后作业生成任务，按教案知识点与教学内容生成 6 题练习；同一教案不可重复生成。

**参数**

| 位置 | 名称 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| path | `lesson_plan_id` | integer | 是 | 教案主键 |

**响应**

`201` Successful Response

```json
{
  success: boolean  # 请求是否成功
  code: integer  # 业务响应状态码
  message: string  # 响应消息
  data?: {
    id: integer  # 任务主键
    project_id: integer  # 所属项目主键
    generation_batch_id?: object  # 生成批次主键
    module_code: string  # 模块编码
    task_type: string  # 任务类型
    biz_key?: string  # 业务键
    task_status: string  # 任务状态
    queue_name?: string  # 队列名称
    current_stage?: string  # 当前阶段
    progress_percent: integer  # 任务进度
    retry_count: integer  # 重试次数
    max_retry_count: integer  # 最大重试次数
    worker_task_id?: object  # Worker 任务ID
    last_error_code?: object  # 最近错误码
    last_error_message?: object  # 最近错误信息
    payload_json?: object  # 任务载荷
    result_json?: object  # 任务结果
    started_at?: object  # 开始时间
    finished_at?: object  # 结束时间
    created_at: object  # 创建时间
    updated_at: object  # 更新时间
  }
  timestamp: string  # 响应时间，UTC ISO8601 格式
  request_id: string  # 请求追踪 ID
  errors?: array[{
    code: string  # 错误码
    message: string  # 错误描述
    details?: object  # 补充信息
    field?: object  # 字段名
  }]
}
```

---

### GET `/api/v1/lesson-plans/{lesson_plan_id}/homework-result`

**按教案获取课后作业详情**

按教案主键查询其唯一的课后作业结构化内容与题目明细，未生成时返回 404。

**参数**

| 位置 | 名称 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| path | `lesson_plan_id` | integer | 是 | 教案主键 |

**响应**

`200` Successful Response

```json
{
  success: boolean  # 请求是否成功
  code: integer  # 业务响应状态码
  message: string  # 响应消息
  data?: {
    id: integer  # 作业结果主键
    generation_batch_id: integer  # 生成批次主键
    lesson_plan_id: integer  # 所属教案主键
    homework_blueprint_id: integer  # 作业蓝图主键
    title: string  # 作业标题
    result_status: string  # 结果状态
    question_count: integer  # 题目数量
    difficulty_stats_json?: object  # 难度统计
    content_json: object  # 作业结构化内容
    export_file_id?: object  # 导出文件主键
    class_session_no?: integer  # 所属课次序号
    lesson_title?: string  # 所属教案标题
    created_at: object  # 创建时间
    updated_at: object  # 更新时间
    questions?: object  # 题目明细列表
  }
  timestamp: string  # 响应时间，UTC ISO8601 格式
  request_id: string  # 请求追踪 ID
  errors?: array[{
    code: string  # 错误码
    message: string  # 错误描述
    details?: object  # 补充信息
    field?: object  # 字段名
  }]
}
```

---

### GET `/api/v1/homework-results`

**获取课后作业列表**

按课程大纲或生成批次分页获取当前教师可见的课后作业，按课次序号升序排列。

**参数**

| 位置 | 名称 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| query | `curriculum_plan_id` | string | 否 | 课程大纲主键 |
| query | `generation_batch_id` | string | 否 | 生成批次主键 |
| query | `page` | integer | 否 | 页码 |
| query | `page_size` | integer | 否 | 每页大小 |

**响应**

`200` Successful Response

```json
{
  success: boolean  # 请求是否成功
  code: integer  # 业务响应状态码
  message: string  # 响应消息
  data?: {
    items: array[{
      id: integer  # 作业结果主键
      generation_batch_id: integer  # 生成批次主键
      lesson_plan_id: integer  # 所属教案主键
      homework_blueprint_id: integer  # 作业蓝图主键
      title: string  # 作业标题
      result_status: string  # 结果状态
      question_count: integer  # 题目数量
      difficulty_stats_json?: object  # 难度统计
      content_json: object  # 作业结构化内容
      export_file_id?: object  # 导出文件主键
      class_session_no?: integer  # 所属课次序号
      lesson_title?: string  # 所属教案标题
      created_at: object  # 创建时间
      updated_at: object  # 更新时间
    }]
    pagination: {
      total_count: integer  # 总记录数
      page: integer  # 当前页码
      page_size: integer  # 每页大小
      total_pages: integer  # 总页数
      has_previous: boolean  # 是否存在上一页
      has_next: boolean  # 是否存在下一页
    }
  }
  timestamp: string  # 响应时间，UTC ISO8601 格式
  request_id: string  # 请求追踪 ID
  errors?: array[{
    code: string  # 错误码
    message: string  # 错误描述
    details?: object  # 补充信息
    field?: object  # 字段名
  }]
}
```

---

### GET `/api/v1/homework-results/{homework_result_id}`

**获取课后作业详情**

按主键查询单份课后作业的结构化内容与题目明细。

**参数**

| 位置 | 名称 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| path | `homework_result_id` | integer | 是 | 课后作业主键 |

**响应**

`200` Successful Response

```json
{
  success: boolean  # 请求是否成功
  code: integer  # 业务响应状态码
  message: string  # 响应消息
  data?: {
    id: integer  # 作业结果主键
    generation_batch_id: integer  # 生成批次主键
    lesson_plan_id: integer  # 所属教案主键
    homework_blueprint_id: integer  # 作业蓝图主键
    title: string  # 作业标题
    result_status: string  # 结果状态
    question_count: integer  # 题目数量
    difficulty_stats_json?: object  # 难度统计
    content_json: object  # 作业结构化内容
    export_file_id?: object  # 导出文件主键
    class_session_no?: integer  # 所属课次序号
    lesson_title?: string  # 所属教案标题
    created_at: object  # 创建时间
    updated_at: object  # 更新时间
    questions?: object  # 题目明细列表
  }
  timestamp: string  # 响应时间，UTC ISO8601 格式
  request_id: string  # 请求追踪 ID
  errors?: array[{
    code: string  # 错误码
    message: string  # 错误描述
    details?: object  # 补充信息
    field?: object  # 字段名
  }]
}
```

---

### POST `/api/v1/homework-results/{homework_result_id}/export-docx`

**导出课后作业 DOCX**

将当前教师可见的课后作业结构化内容和题目明细同步导出为 DOCX 文件，并返回签名下载地址。

DOCX 模板 v2（2026-05-27 起生效）共用以下约定：
- 文件名面向教师可读：`{lesson_title}-第{N}讲-课后作业.docx`，无课次序号时省略 `-第{N}讲`；
- `object_key` 嵌入模板版本号段（如 `.../tv2/…`），模板升级时旧 `export_file_id` 由迁移脚本统一清空；
- 渲染层不再展示英文枚举、内部追溯字段，题型/难度统一中文，选项以 `A. 内容` 形式呈现。

**参数**

| 位置 | 名称 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| path | `homework_result_id` | integer | 是 | 课后作业主键 |

**响应**

`200` Successful Response

```json
{
  success: boolean  # 请求是否成功
  code: integer  # 业务响应状态码
  message: string  # 响应消息
  data?: {
    file_object_id: integer  # 文件对象主键
    bucket_name: string  # 存储桶名称
    object_key: string  # 对象路径
    signed_url: object  # 签名下载地址
    expires_in_seconds: integer  # 有效期秒数
    generated_at: object  # 生成时间
  }
  timestamp: string  # 响应时间，UTC ISO8601 格式
  request_id: string  # 请求追踪 ID
  errors?: array[{
    code: string  # 错误码
    message: string  # 错误描述
    details?: object  # 补充信息
    field?: object  # 字段名
  }]
}
```

---

### GET `/api/v1/homework-blueprints/{homework_blueprint_id}`

**获取课后作业蓝图详情**

按主键查询单份课后作业蓝图，包含策略与考查权重。

**参数**

| 位置 | 名称 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| path | `homework_blueprint_id` | integer | 是 | 课后作业蓝图主键 |

**响应**

`200` Successful Response

```json
{
  success: boolean  # 请求是否成功
  code: integer  # 业务响应状态码
  message: string  # 响应消息
  data?: {
    id: integer  # 作业蓝图主键
    lesson_plan_id: integer  # 所属教案主键
    generation_batch_id: integer  # 生成批次主键
    version_no: integer  # 版本号
    blueprint_name: string  # 作业蓝图名称
    version_status: string  # 版本状态
    strategy_json?: object  # 策略配置
    content_json: object  # 蓝图结构化内容
    export_file_id?: object  # 导出文件主键
    created_by?: object  # 创建人
    created_at: object  # 创建时间
    updated_at: object  # 更新时间
  }
  timestamp: string  # 响应时间，UTC ISO8601 格式
  request_id: string  # 请求追踪 ID
  errors?: array[{
    code: string  # 错误码
    message: string  # 错误描述
    details?: object  # 补充信息
    field?: object  # 字段名
  }]
}
```

---

### GET `/api/v1/homework-questions`

**获取课后作业题目列表**

按教案、作业、知识点、题型、难度筛选当前教师可见的作业题目，支持分页。

**参数**

| 位置 | 名称 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| query | `lesson_plan_id` | string | 否 | 教案主键 |
| query | `homework_result_id` | string | 否 | 课后作业主键 |
| query | `knowledge_point_id` | string | 否 | 知识点主键 |
| query | `question_type` | string | 否 | 题型：single_choice=单选题，fill_blank=填空题，short_answer=简答题 |
| query | `difficulty_level` | string | 否 | 难度等级（1-5） |
| query | `page` | integer | 否 | 页码 |
| query | `page_size` | integer | 否 | 每页大小 |

**响应**

`200` Successful Response

```json
{
  success: boolean  # 请求是否成功
  code: integer  # 业务响应状态码
  message: string  # 响应消息
  data?: {
    items: array[{
      id: integer  # 作业题目主键
      generation_batch_id: integer  # 生成批次主键
      homework_result_id: integer  # 作业结果主键
      lesson_plan_id: integer  # 所属教案主键
      knowledge_point_id?: object  # 知识点主键
      knowledge_point_name?: object  # 知识点名称，前端考查标签使用
      question_no: integer  # 题号
      question_type: string  # 题型
      difficulty_level?: object  # 难度等级
      score_value?: object  # 分值
      stem_text: object  # 题干
      options_json?: object  # 选项
      answer_text?: object  # 答案
      analysis_text?: object  # 解析
      source_trace_json?: object  # 来源摘要
      question_basis_json?: object  # 题目考查依据：包含知识点、章节、课次、教学目标、测评定位、依据说明与蓝图来源
      created_at: object  # 创建时间
      updated_at: object  # 更新时间
      homework_title: string  # 所属作业标题
      class_session_no?: integer  # 所属课次序号
    }]
    pagination: {
      total_count: integer  # 总记录数
      page: integer  # 当前页码
      page_size: integer  # 每页大小
      total_pages: integer  # 总页数
      has_previous: boolean  # 是否存在上一页
      has_next: boolean  # 是否存在下一页
    }
  }
  timestamp: string  # 响应时间，UTC ISO8601 格式
  request_id: string  # 请求追踪 ID
  errors?: array[{
    code: string  # 错误码
    message: string  # 错误描述
    details?: object  # 补充信息
    field?: object  # 字段名
  }]
}
```

---

## 课件

### POST `/api/v1/lesson-plans/{lesson_plan_id}/courseware-tasks`

**创建按需课件生成任务**

为当前教师可见的教案创建 Raccoon PPT 课件生成任务并归档 PPTX。

**参数**

| 位置 | 名称 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| path | `lesson_plan_id` | integer | 是 | 教案主键 |

**响应**

`201` Successful Response

```json
{
  success: boolean  # 请求是否成功
  code: integer  # 业务响应状态码
  message: string  # 响应消息
  data?: {
    id: integer  # 任务主键
    project_id: integer  # 所属项目主键
    generation_batch_id?: object  # 生成批次主键
    module_code: string  # 模块编码
    task_type: string  # 任务类型
    biz_key?: string  # 业务键
    task_status: string  # 任务状态
    queue_name?: string  # 队列名称
    current_stage?: string  # 当前阶段
    progress_percent: integer  # 任务进度
    retry_count: integer  # 重试次数
    max_retry_count: integer  # 最大重试次数
    worker_task_id?: object  # Worker 任务ID
    last_error_code?: object  # 最近错误码
    last_error_message?: object  # 最近错误信息
    payload_json?: object  # 任务载荷
    result_json?: object  # 任务结果
    started_at?: object  # 开始时间
    finished_at?: object  # 结束时间
    created_at: object  # 创建时间
    updated_at: object  # 更新时间
  }
  timestamp: string  # 响应时间，UTC ISO8601 格式
  request_id: string  # 请求追踪 ID
  errors?: array[{
    code: string  # 错误码
    message: string  # 错误描述
    details?: object  # 补充信息
    field?: object  # 字段名
  }]
}
```

---

### GET `/api/v1/courseware-results`

**获取课件结果列表**

分页获取指定生成批次下的课件结果列表。

**参数**

| 位置 | 名称 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| query | `generation_batch_id` | integer | 是 | 生成批次主键 |
| query | `page` | integer | 否 | 页码 |
| query | `page_size` | integer | 否 | 每页大小 |

**响应**

`200` Successful Response

```json
{
  success: boolean  # 请求是否成功
  code: integer  # 业务响应状态码
  message: string  # 响应消息
  data?: {
    items: array[{
      id: integer  # 课件结果主键
      generation_batch_id: integer  # 生成批次主键
      lesson_plan_id: integer  # 教案版本主键
      template_code?: object  # 模板编码
      template_version?: object  # 模板版本
      result_status: string  # 课件结果状态
      page_count?: object  # 页数
      page_type_stats_json?: object  # 页面类型统计
      structure_json: object  # 课件结构与生成摘要
      preview_json?: object  # 远程任务预览状态
      export_file_id?: object  # 导出文件主键
      created_at: object  # 创建时间
      updated_at: object  # 更新时间
    }]
    pagination: {
      total_count: integer  # 总记录数
      page: integer  # 当前页码
      page_size: integer  # 每页大小
      total_pages: integer  # 总页数
      has_previous: boolean  # 是否存在上一页
      has_next: boolean  # 是否存在下一页
    }
  }
  timestamp: string  # 响应时间，UTC ISO8601 格式
  request_id: string  # 请求追踪 ID
  errors?: array[{
    code: string  # 错误码
    message: string  # 错误描述
    details?: object  # 补充信息
    field?: object  # 字段名
  }]
}
```

---

### GET `/api/v1/courseware-results/{courseware_result_id}`

**获取课件结果详情**

获取单个课件结果的结构化内容、远程任务状态与导出文件引用。

**参数**

| 位置 | 名称 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| path | `courseware_result_id` | integer | 是 | 课件结果主键 |

**响应**

`200` Successful Response

```json
{
  success: boolean  # 请求是否成功
  code: integer  # 业务响应状态码
  message: string  # 响应消息
  data?: {
    id: integer  # 课件结果主键
    generation_batch_id: integer  # 生成批次主键
    lesson_plan_id: integer  # 教案版本主键
    template_code?: object  # 模板编码
    template_version?: object  # 模板版本
    result_status: string  # 课件结果状态
    page_count?: object  # 页数
    page_type_stats_json?: object  # 页面类型统计
    structure_json: object  # 课件结构与生成摘要
    preview_json?: object  # 远程任务预览状态
    export_file_id?: object  # 导出文件主键
    created_at: object  # 创建时间
    updated_at: object  # 更新时间
  }
  timestamp: string  # 响应时间，UTC ISO8601 格式
  request_id: string  # 请求追踪 ID
  errors?: array[{
    code: string  # 错误码
    message: string  # 错误描述
    details?: object  # 补充信息
    field?: object  # 字段名
  }]
}
```

---

### POST `/api/v1/courseware-results/{courseware_result_id}/refresh`

**刷新课件生成状态**

继续查询 Raccoon PPT 远程任务，成功后归档 PPTX 并收口生成批次。

**参数**

| 位置 | 名称 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| path | `courseware_result_id` | integer | 是 | 课件结果主键 |

**响应**

`200` Successful Response

```json
{
  success: boolean  # 请求是否成功
  code: integer  # 业务响应状态码
  message: string  # 响应消息
  data?: {
    id: integer  # 课件结果主键
    generation_batch_id: integer  # 生成批次主键
    lesson_plan_id: integer  # 教案版本主键
    template_code?: object  # 模板编码
    template_version?: object  # 模板版本
    result_status: string  # 课件结果状态
    page_count?: object  # 页数
    page_type_stats_json?: object  # 页面类型统计
    structure_json: object  # 课件结构与生成摘要
    preview_json?: object  # 远程任务预览状态
    export_file_id?: object  # 导出文件主键
    created_at: object  # 创建时间
    updated_at: object  # 更新时间
  }
  timestamp: string  # 响应时间，UTC ISO8601 格式
  request_id: string  # 请求追踪 ID
  errors?: array[{
    code: string  # 错误码
    message: string  # 错误描述
    details?: object  # 补充信息
    field?: object  # 字段名
  }]
}
```

---

### POST `/api/v1/courseware-results/{courseware_result_id}/reply`

**回复课件生成补充问题**

当 Raccoon PPT 任务需要补充信息时，提交回答并继续短轮询课件状态。

**参数**

| 位置 | 名称 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| path | `courseware_result_id` | integer | 是 | 课件结果主键 |

**请求体**

```json
{
  answer: string  # 补充回答内容
}
```

**响应**

`200` Successful Response

```json
{
  success: boolean  # 请求是否成功
  code: integer  # 业务响应状态码
  message: string  # 响应消息
  data?: {
    id: integer  # 课件结果主键
    generation_batch_id: integer  # 生成批次主键
    lesson_plan_id: integer  # 教案版本主键
    template_code?: object  # 模板编码
    template_version?: object  # 模板版本
    result_status: string  # 课件结果状态
    page_count?: object  # 页数
    page_type_stats_json?: object  # 页面类型统计
    structure_json: object  # 课件结构与生成摘要
    preview_json?: object  # 远程任务预览状态
    export_file_id?: object  # 导出文件主键
    created_at: object  # 创建时间
    updated_at: object  # 更新时间
  }
  timestamp: string  # 响应时间，UTC ISO8601 格式
  request_id: string  # 请求追踪 ID
  errors?: array[{
    code: string  # 错误码
    message: string  # 错误描述
    details?: object  # 补充信息
    field?: object  # 字段名
  }]
}
```

---

### PUT `/api/v1/courseware-results/{courseware_result_id}/slides`

**更新课件结构化内容**

保存教师编辑后的结构化幻灯片内容，记录编辑留痕并标记需重新排版。

**参数**

| 位置 | 名称 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| path | `courseware_result_id` | integer | 是 | 课件结果主键 |

**请求体**

```json
{
  deck_title?: string | null  # 课件标题
  slides: array[{
    slide_no: integer  # 页序号
    slide_type: 'cover' | 'toc' | 'knowledge' | 'example' | 'interaction' | 'summary' | 'homework'  # 页型：cover/toc/knowledge/example/interaction/summary/homework
    title: string  # 页标题
    bullet_points?: array[string]  # 页面要点
    speaker_notes?: string | null  # 讲解备注
    knowledge_point_refs?: array[integer]  # 关联知识点主键列表
    example_block?: {
      stem_text: string  # 例题题干
      answer_text?: string | null  # 例题答案
      analysis_text?: string | null  # 例题解析
    } | null  # 例题块（例题页使用）
  }]  # 编辑后的幻灯片列表
}
```

**响应**

`200` Successful Response

```json
{
  success: boolean  # 请求是否成功
  code: integer  # 业务响应状态码
  message: string  # 响应消息
  data?: {
    id: integer  # 课件结果主键
    generation_batch_id: integer  # 生成批次主键
    lesson_plan_id: integer  # 教案版本主键
    template_code?: object  # 模板编码
    template_version?: object  # 模板版本
    result_status: string  # 课件结果状态
    page_count?: object  # 页数
    page_type_stats_json?: object  # 页面类型统计
    structure_json: object  # 课件结构与生成摘要
    preview_json?: object  # 远程任务预览状态
    export_file_id?: object  # 导出文件主键
    created_at: object  # 创建时间
    updated_at: object  # 更新时间
  }
  timestamp: string  # 响应时间，UTC ISO8601 格式
  request_id: string  # 请求追踪 ID
  errors?: array[{
    code: string  # 错误码
    message: string  # 错误描述
    details?: object  # 补充信息
    field?: object  # 字段名
  }]
}
```

---

### POST `/api/v1/courseware-results/{courseware_result_id}/regenerate`

**重新排版生成课件**

基于当前（含教师编辑）的结构化课件内容，重新调用 Raccoon 排版生成 PPTX。

**参数**

| 位置 | 名称 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| path | `courseware_result_id` | integer | 是 | 课件结果主键 |

**响应**

`200` Successful Response

```json
{
  success: boolean  # 请求是否成功
  code: integer  # 业务响应状态码
  message: string  # 响应消息
  data?: {
    id: integer  # 课件结果主键
    generation_batch_id: integer  # 生成批次主键
    lesson_plan_id: integer  # 教案版本主键
    template_code?: object  # 模板编码
    template_version?: object  # 模板版本
    result_status: string  # 课件结果状态
    page_count?: object  # 页数
    page_type_stats_json?: object  # 页面类型统计
    structure_json: object  # 课件结构与生成摘要
    preview_json?: object  # 远程任务预览状态
    export_file_id?: object  # 导出文件主键
    created_at: object  # 创建时间
    updated_at: object  # 更新时间
  }
  timestamp: string  # 响应时间，UTC ISO8601 格式
  request_id: string  # 请求追踪 ID
  errors?: array[{
    code: string  # 错误码
    message: string  # 错误描述
    details?: object  # 补充信息
    field?: object  # 字段名
  }]
}
```

---

## 覆盖率

### GET `/api/v1/coverage-reports`

**获取覆盖率报告列表**

分页获取指定生成批次下的覆盖率分析报告，报告会展示课程大纲、教案、课件页面、试卷题目与作业题目的知识点覆盖矩阵，并返回质量评审字段。

**参数**

| 位置 | 名称 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| query | `generation_batch_id` | integer | 是 | 生成批次主键 |
| query | `page` | integer | 否 | 页码 |
| query | `page_size` | integer | 否 | 每页大小 |

**响应**

`200` Successful Response

```json
{
  success: boolean  # 请求是否成功
  code: integer  # 业务响应状态码
  message: string  # 响应消息
  data?: {
    items: array[{
      id: integer  # 覆盖率报告主键
      generation_batch_id: integer  # 生成批次主键
      report_status: string  # 报告状态
      coverage_rate?: number  # 覆盖率百分比
      warning_count: integer  # 告警数量
      coverage_summary_json?: object  # 覆盖摘要
      report_json: object  # 覆盖率报告内容，包含覆盖矩阵、质量评审、学情适配和补救建议
      export_file_id?: object  # 导出文件主键
      created_at: object  # 创建时间
      updated_at: object  # 更新时间
    }]
    pagination: {
      total_count: integer  # 总记录数
      page: integer  # 当前页码
      page_size: integer  # 每页大小
      total_pages: integer  # 总页数
      has_previous: boolean  # 是否存在上一页
      has_next: boolean  # 是否存在下一页
    }
  }
  timestamp: string  # 响应时间，UTC ISO8601 格式
  request_id: string  # 请求追踪 ID
  errors?: array[{
    code: string  # 错误码
    message: string  # 错误描述
    details?: object  # 补充信息
    field?: object  # 字段名
  }]
}
```

---

### GET `/api/v1/coverage-reports/{coverage_report_id}`

**获取覆盖率报告详情**

获取单个覆盖率分析报告的结构化内容。

**参数**

| 位置 | 名称 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| path | `coverage_report_id` | integer | 是 | 覆盖率报告主键 |

**响应**

`200` Successful Response

```json
{
  success: boolean  # 请求是否成功
  code: integer  # 业务响应状态码
  message: string  # 响应消息
  data?: {
    id: integer  # 覆盖率报告主键
    generation_batch_id: integer  # 生成批次主键
    report_status: string  # 报告状态
    coverage_rate?: number  # 覆盖率百分比
    warning_count: integer  # 告警数量
    coverage_summary_json?: object  # 覆盖摘要
    report_json: object  # 覆盖率报告内容，包含覆盖矩阵、质量评审、学情适配和补救建议
    export_file_id?: object  # 导出文件主键
    created_at: object  # 创建时间
    updated_at: object  # 更新时间
  }
  timestamp: string  # 响应时间，UTC ISO8601 格式
  request_id: string  # 请求追踪 ID
  errors?: array[{
    code: string  # 错误码
    message: string  # 错误描述
    details?: object  # 补充信息
    field?: object  # 字段名
  }]
}
```

---

### POST `/api/v1/generation-batches/{generation_batch_id}/coverage-reports/refresh`

**重新分析覆盖率报告**

重新汇总指定生成批次下课程大纲、教案、课件页面、试卷题目与作业题目的知识点引用，并刷新覆盖率报告、质量评审字段和可读告警。

**参数**

| 位置 | 名称 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| path | `generation_batch_id` | integer | 是 | 生成批次主键 |

**响应**

`200` Successful Response

```json
{
  success: boolean  # 请求是否成功
  code: integer  # 业务响应状态码
  message: string  # 响应消息
  data?: {
    id: integer  # 覆盖率报告主键
    generation_batch_id: integer  # 生成批次主键
    report_status: string  # 报告状态
    coverage_rate?: number  # 覆盖率百分比
    warning_count: integer  # 告警数量
    coverage_summary_json?: object  # 覆盖摘要
    report_json: object  # 覆盖率报告内容，包含覆盖矩阵、质量评审、学情适配和补救建议
    export_file_id?: object  # 导出文件主键
    created_at: object  # 创建时间
    updated_at: object  # 更新时间
  }
  timestamp: string  # 响应时间，UTC ISO8601 格式
  request_id: string  # 请求追踪 ID
  errors?: array[{
    code: string  # 错误码
    message: string  # 错误描述
    details?: object  # 补充信息
    field?: object  # 字段名
  }]
}
```

---

## 任务中心

### GET `/api/v1/tasks`

**获取任务列表**

按项目、模块、任务类型和任务状态筛选当前教师可见的任务列表。

**参数**

| 位置 | 名称 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| query | `project_id` | string | 否 | 项目主键 |
| query | `module_code` | string | 否 | 模块编码 |
| query | `task_type` | string | 否 | 任务类型 |
| query | `task_status` | string | 否 | 任务状态 |
| query | `page` | integer | 否 | 页码 |
| query | `page_size` | integer | 否 | 每页大小 |

**响应**

`200` Successful Response

```json
{
  success: boolean  # 请求是否成功
  code: integer  # 业务响应状态码
  message: string  # 响应消息
  data?: {
    items: array[{
      id: integer  # 任务主键
      project_id: integer  # 所属项目主键
      generation_batch_id?: object  # 生成批次主键
      module_code: string  # 模块编码
      task_type: string  # 任务类型
      biz_key?: string  # 业务键
      task_status: string  # 任务状态
      queue_name?: string  # 队列名称
      current_stage?: string  # 当前阶段
      progress_percent: integer  # 任务进度
      retry_count: integer  # 重试次数
      max_retry_count: integer  # 最大重试次数
      worker_task_id?: object  # Worker 任务ID
      last_error_code?: object  # 最近错误码
      last_error_message?: object  # 最近错误信息
      payload_json?: object  # 任务载荷
      result_json?: object  # 任务结果
      started_at?: object  # 开始时间
      finished_at?: object  # 结束时间
      created_at: object  # 创建时间
      updated_at: object  # 更新时间
    }]
    pagination: {
      total_count: integer  # 总记录数
      page: integer  # 当前页码
      page_size: integer  # 每页大小
      total_pages: integer  # 总页数
      has_previous: boolean  # 是否存在上一页
      has_next: boolean  # 是否存在下一页
    }
  }
  timestamp: string  # 响应时间，UTC ISO8601 格式
  request_id: string  # 请求追踪 ID
  errors?: array[{
    code: string  # 错误码
    message: string  # 错误描述
    details?: object  # 补充信息
    field?: object  # 字段名
  }]
}
```

---

### GET `/api/v1/tasks/{task_id}`

**获取任务详情**

获取当前教师可见的单个任务详情及其步骤信息。

**参数**

| 位置 | 名称 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| path | `task_id` | integer | 是 | 任务主键 |

**响应**

`200` Successful Response

```json
{
  success: boolean  # 请求是否成功
  code: integer  # 业务响应状态码
  message: string  # 响应消息
  data?: {
    id: integer  # 任务主键
    project_id: integer  # 所属项目主键
    generation_batch_id?: object  # 生成批次主键
    module_code: string  # 模块编码
    task_type: string  # 任务类型
    biz_key?: string  # 业务键
    task_status: string  # 任务状态
    queue_name?: string  # 队列名称
    current_stage?: string  # 当前阶段
    progress_percent: integer  # 任务进度
    retry_count: integer  # 重试次数
    max_retry_count: integer  # 最大重试次数
    worker_task_id?: object  # Worker 任务ID
    last_error_code?: object  # 最近错误码
    last_error_message?: object  # 最近错误信息
    payload_json?: object  # 任务载荷
    result_json?: object  # 任务结果
    started_at?: object  # 开始时间
    finished_at?: object  # 结束时间
    created_at: object  # 创建时间
    updated_at: object  # 更新时间
    steps: object  # 任务步骤列表
  }
  timestamp: string  # 响应时间，UTC ISO8601 格式
  request_id: string  # 请求追踪 ID
  errors?: array[{
    code: string  # 错误码
    message: string  # 错误描述
    details?: object  # 补充信息
    field?: object  # 字段名
  }]
}
```

---

### POST `/api/v1/tasks/{task_id}/retry`

**重试失败任务**

重试当前教师可见的失败任务。当前版本仅支持 task_status=failure 且 task_type=lesson_plan_generate 的多课时教案生成任务；无请求体。成功后返回 202，任务会回到 pending、retry_count 归零、错误字段清空、步骤重置，并复用原任务、生成批次和任务载荷重新派发。非本人任务返回 404，非失败态或非教案任务返回 409。

**参数**

| 位置 | 名称 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| path | `task_id` | integer | 是 | 任务主键 |

**响应**

`202` Successful Response

```json
{
  success: boolean  # 请求是否成功
  code: integer  # 业务响应状态码
  message: string  # 响应消息
  data?: {
    id: integer  # 任务主键
    project_id: integer  # 所属项目主键
    generation_batch_id?: object  # 生成批次主键
    module_code: string  # 模块编码
    task_type: string  # 任务类型
    biz_key?: string  # 业务键
    task_status: string  # 任务状态
    queue_name?: string  # 队列名称
    current_stage?: string  # 当前阶段
    progress_percent: integer  # 任务进度
    retry_count: integer  # 重试次数
    max_retry_count: integer  # 最大重试次数
    worker_task_id?: object  # Worker 任务ID
    last_error_code?: object  # 最近错误码
    last_error_message?: object  # 最近错误信息
    payload_json?: object  # 任务载荷
    result_json?: object  # 任务结果
    started_at?: object  # 开始时间
    finished_at?: object  # 结束时间
    created_at: object  # 创建时间
    updated_at: object  # 更新时间
    steps: object  # 任务步骤列表
  }
  timestamp: string  # 响应时间，UTC ISO8601 格式
  request_id: string  # 请求追踪 ID
  errors?: array[{
    code: string  # 错误码
    message: string  # 错误描述
    details?: object  # 补充信息
    field?: object  # 字段名
  }]
}
```

---
