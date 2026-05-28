"""
@Date: 2026-05-28
@Author: xisy
@Discription: 生成过程展示模块请求与响应模型
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from app.schemas.base import BaseSchema

# 保持 4 值枚举不动，避免前端 switch 缺少分支导致解析失败；
# 新语义通过 status_detail 表达，前端可按需消费
GenerationProcessStatus = Literal["pending", "running", "succeeded", "failed"]

# 细化状态：表达「整体仍在 running，但当前没有 worker 在干活」等语义
GenerationProcessStatusDetail = Literal[
    "waiting_dispatch",
    "waiting_user_confirm",
    "retrying",
    "blocked",
]

# 步骤级细化状态：仅表达 retrying / waiting_dispatch 两种
GenerationProcessStepStatusDetail = Literal["retrying", "waiting_dispatch"]


class GenerationProcessStepResponse(BaseSchema):
    """生成过程展示步骤响应。"""

    code: str = Field(description="展示步骤编码", examples=["mineru_parse"])
    display_name: str = Field(description="展示步骤名称", examples=["调用 MinerU 教材解析工具"])
    description: str = Field(
        description="展示步骤说明",
        examples=["识别教材章节、页码、图表、题目和知识点。"],
    )
    status: GenerationProcessStatus = Field(description="展示状态", examples=["running"])
    status_detail: GenerationProcessStepStatusDetail | None = Field(
        default=None,
        description="细化状态：retrying 表示被 reaper 重排后等待新 worker；waiting_dispatch 表示等待后端调度下一步",
        examples=["retrying"],
    )
    progress_percent: int = Field(description="进度百分比", examples=[60])
    current_stage: str | None = Field(
        default=None,
        description="当前内部阶段编码，仅用于前端展示当前阶段与调试定位",
        examples=["invoke_llm_lesson_plan"],
    )
    progress_detail: dict[str, Any] | None = Field(
        default=None,
        description=(
            "公开进度指标，例如 processed/total/parallel_limit/last_completed；"
            "教案失败时可包含 failed_session_no、failed_session_title、session_retry_count，"
            "不包含原始 LLM 错误、prompt、traceback 或内部任务字段"
        ),
        examples=[
            {
                "processed_sessions": 3,
                "total_sessions": 10,
                "parallel_limit": 4,
                "failed_session_no": 4,
                "failed_session_title": "小数乘法练习",
                "session_retry_count": 2,
            }
        ],
    )
    result_detail: dict[str, Any] | None = Field(
        default=None,
        description="公开结果指标，例如页数、画像记录数、课程课次数、覆盖统计等",
        examples=[{"covered_count": 23, "total_count": 24, "coverage_rate": 95.83}],
    )
    summary: str | None = Field(default=None, description="面向用户的步骤摘要", examples=["已识别 12 页教材内容。"])
    started_at: datetime | None = Field(default=None, description="开始时间")
    finished_at: datetime | None = Field(default=None, description="结束时间")
    error_message: str | None = Field(
        default=None,
        description="面向用户的错误文案，仅失败时返回",
        examples=["教材解析失败，请确认上传文件是否为清晰的 PDF。"],
    )


class GenerationProcessResponse(BaseSchema):
    """生成过程展示响应。"""

    project_id: int = Field(description="项目主键", examples=[1])
    batch_id: int | None = Field(
        default=None,
        description=(
            "当前展示批次主键：活跃 run 已创建批次时为 run 批次；"
            "活跃 run 未创建批次时为 null；无活跃 run 时为项目最近生成批次"
        ),
        examples=[1],
    )
    generation_run_id: int | None = Field(
        default=None,
        description="当前活跃一键生成 run 主键；无 run 则为 null",
        examples=[1],
    )
    status: GenerationProcessStatus = Field(description="整体展示状态", examples=["running"])
    status_detail: GenerationProcessStatusDetail | None = Field(
        default=None,
        description=(
            "整体细化状态：waiting_dispatch=等待后端调度下一步；"
            "waiting_user_confirm=等待用户确认教材解析；"
            "retrying=任务被 reaper 重排重试中；blocked=前置缺失，无法继续"
        ),
        examples=["waiting_dispatch"],
    )
    blocked_reason: str | None = Field(
        default=None,
        description="status_detail=blocked 时的原因编码，例如 LEARNER_PROFILE_NOT_READY",
        examples=["LEARNER_PROFILE_NOT_READY"],
    )
    current_step_code: str | None = Field(
        default=None,
        description="当前正在进行的展示步骤编码",
        examples=["lesson_plan_generate"],
    )
    steps: list[GenerationProcessStepResponse] = Field(description="展示步骤列表，固定 6 步")
