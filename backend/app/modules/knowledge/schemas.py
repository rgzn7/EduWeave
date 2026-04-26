"""
@Date: 2026-04-14
@Author: xisy
@Discription: 知识结构化模块请求与响应模型
"""

from datetime import datetime
from typing import Any

from pydantic import Field, model_validator

from app.schemas.base import BaseSchema

SUPPORTED_KNOWLEDGE_REVISION_OP_TYPES = {
    "update_summary",
    "update_chapter",
    "add_point",
    "update_point",
    "delete_point",
    "merge_points",
}


class KnowledgeTaskCreateRequest(BaseSchema):
    """知识抽取任务创建请求。"""

    force_regenerate: bool = Field(
        default=False,
        description="是否忽略当前可用知识版本并强制重新生成",
        examples=[False],
    )


class KnowledgeManualRevisionEvidenceRequest(BaseSchema):
    """知识点人工修正证据请求。"""

    page_no: int = Field(description="页码", ge=1, examples=[1])
    block_no: int | None = Field(default=None, description="块序号", ge=1, examples=[2])
    evidence_type: str = Field(default="manual", description="证据类型", min_length=1, max_length=32, examples=["manual"])
    excerpt_text: str | None = Field(default=None, description="证据片段", examples=["乘法口诀需要反复练习。"])
    bbox_json: dict[str, Any] | None = Field(
        default=None,
        description="证据坐标",
        examples=[{"x0": 12.5, "y0": 18.0, "x1": 180.0, "y1": 56.0}],
    )
    score_value: float | None = Field(default=None, description="证据分数", ge=0, le=1, examples=[0.91])


class KnowledgeManualRevisionOperationRequest(BaseSchema):
    """知识人工修正操作请求。"""

    op_type: str = Field(description="操作类型", examples=["update_point"])
    summary_json: dict[str, Any] | None = Field(
        default=None,
        description="新的知识摘要 JSON",
        examples=[{"teaching_focus": ["乘法口诀"], "risk_points": ["口诀混淆"]}],
    )
    chapter_node_id: int | None = Field(default=None, description="章节节点主键", examples=[1])
    knowledge_point_id: int | None = Field(default=None, description="知识点主键", examples=[1])
    source_knowledge_point_ids: list[int] | None = Field(default=None, description="待合并知识点主键列表", min_length=2, examples=[[1, 2]])
    title: str | None = Field(default=None, description="章节标题", examples=["第一单元 乘法初步"])
    point_code: str | None = Field(default=None, description="知识点编码", examples=["kp_multiplication_base"])
    point_name: str | None = Field(default=None, description="知识点名称", examples=["乘法口诀"])
    point_type: str | None = Field(default=None, description="知识点类型", examples=["knowledge"])
    importance_level: int | None = Field(default=None, description="重要度", ge=1, le=5, examples=[4])
    difficulty_level: int | None = Field(default=None, description="难度", ge=1, le=5, examples=[3])
    mastery_level_hint: str | None = Field(default=None, description="掌握建议", examples=["understand"])
    tags_json: dict[str, Any] | None = Field(default=None, description="标签 JSON", examples=[{"tags": ["重点", "易错"]}])
    summary_text: str | None = Field(default=None, description="摘要文本", examples=["需要重点训练乘法口诀与基础应用。"])
    sort_order: int | None = Field(default=None, description="排序号", ge=0, examples=[1])
    page_start: int | None = Field(default=None, description="章节起始页", ge=1, examples=[1])
    page_end: int | None = Field(default=None, description="章节结束页", ge=1, examples=[3])
    evidences: list[KnowledgeManualRevisionEvidenceRequest] | None = Field(
        default=None,
        description="替换后的证据列表",
        examples=[
            [
                {
                    "page_no": 1,
                    "block_no": 2,
                    "evidence_type": "manual",
                    "excerpt_text": "乘法口诀需要反复练习。",
                    "bbox_json": {"x0": 12.5, "y0": 18.0, "x1": 180.0, "y1": 56.0},
                    "score_value": 0.95,
                }
            ]
        ],
    )

    @model_validator(mode="after")
    def validate_operation(self) -> "KnowledgeManualRevisionOperationRequest":
        if self.op_type not in SUPPORTED_KNOWLEDGE_REVISION_OP_TYPES:
            raise ValueError("不支持的知识修正操作类型")
        if self.page_start is not None and self.page_end is not None and self.page_start > self.page_end:
            raise ValueError("章节起始页不能大于结束页")

        if self.op_type == "update_summary":
            if self.summary_json is None:
                raise ValueError("update_summary 必须提供 summary_json")
            return self

        if self.op_type == "update_chapter":
            if self.chapter_node_id is None:
                raise ValueError("update_chapter 必须提供 chapter_node_id")
            if all(
                value is None
                for value in (self.title, self.summary_text, self.page_start, self.page_end, self.sort_order)
            ):
                raise ValueError("update_chapter 至少需要修改一个字段")
            return self

        if self.op_type == "add_point":
            if self.chapter_node_id is None or not self.point_name:
                raise ValueError("add_point 必须提供 chapter_node_id 和 point_name")
            if not self.evidences:
                raise ValueError("add_point 必须提供至少一条 evidences")
            return self

        if self.op_type == "update_point":
            if self.knowledge_point_id is None:
                raise ValueError("update_point 必须提供 knowledge_point_id")
            if all(
                value is None
                for value in (
                    self.chapter_node_id,
                    self.point_code,
                    self.point_name,
                    self.point_type,
                    self.importance_level,
                    self.difficulty_level,
                    self.mastery_level_hint,
                    self.tags_json,
                    self.summary_text,
                    self.sort_order,
                    self.evidences,
                )
            ):
                raise ValueError("update_point 至少需要修改一个字段")
            return self

        if self.op_type == "delete_point":
            if self.knowledge_point_id is None:
                raise ValueError("delete_point 必须提供 knowledge_point_id")
            return self

        if self.op_type == "merge_points":
            if not self.source_knowledge_point_ids or len(self.source_knowledge_point_ids) < 2:
                raise ValueError("merge_points 必须提供至少两个 source_knowledge_point_ids")
            if not self.point_name:
                raise ValueError("merge_points 必须提供 point_name")
            return self

        return self


class KnowledgeManualRevisionRequest(BaseSchema):
    """知识人工修正请求。"""

    operations: list[KnowledgeManualRevisionOperationRequest] = Field(
        description="修正操作列表",
        min_length=1,
        examples=[
            [
                {
                    "op_type": "update_point",
                    "knowledge_point_id": 1,
                    "point_name": "乘法口诀",
                    "importance_level": 5,
                    "evidences": [
                        {
                            "page_no": 1,
                            "block_no": 2,
                            "evidence_type": "manual",
                            "excerpt_text": "乘法口诀需要反复练习。",
                            "score_value": 0.95,
                        }
                    ],
                }
            ]
        ],
    )


class ChapterNodeResponse(BaseSchema):
    """章节节点响应。"""

    id: int = Field(description="章节节点主键", examples=[1])
    knowledge_version_id: int = Field(description="知识版本主键", examples=[1])
    parent_id: int | None = Field(default=None, description="父节点主键")
    node_path: str = Field(description="路径编码", examples=["1.1"])
    node_no: int = Field(description="节点序号", examples=[1])
    node_level: int = Field(description="节点层级", examples=[2])
    node_type: str = Field(description="节点类型", examples=["section"])
    title: str = Field(description="标题", examples=["乘法口诀"])
    summary_text: str | None = Field(default=None, description="摘要")
    page_start: int | None = Field(default=None, description="起始页")
    page_end: int | None = Field(default=None, description="结束页")
    sort_order: int = Field(description="排序号", examples=[0])
    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="更新时间")


class KnowledgeEvidenceResponse(BaseSchema):
    """知识点证据响应。"""

    id: int = Field(description="证据主键", examples=[1])
    knowledge_point_id: int = Field(description="知识点主键", examples=[1])
    parse_version_id: int = Field(description="解析版本主键", examples=[1])
    parse_page_id: int | None = Field(default=None, description="解析页主键")
    parse_block_id: int | None = Field(default=None, description="解析块主键")
    source_file_id: int | None = Field(default=None, description="来源文件主键")
    evidence_type: str = Field(description="证据类型", examples=["parse_block"])
    page_no: int | None = Field(default=None, description="页码")
    excerpt_text: str | None = Field(default=None, description="证据片段")
    bbox_json: dict[str, Any] | None = Field(default=None, description="坐标框")
    score_value: float | None = Field(default=None, description="证据分数")
    created_at: datetime = Field(description="创建时间")


class KnowledgePointListItemResponse(BaseSchema):
    """知识点列表项响应。"""

    id: int = Field(description="知识点主键", examples=[1])
    knowledge_version_id: int = Field(description="知识版本主键", examples=[1])
    chapter_node_id: int | None = Field(default=None, description="章节节点主键")
    chapter_title: str | None = Field(default=None, description="章节标题")
    point_code: str | None = Field(default=None, description="知识点编码")
    point_name: str = Field(description="知识点名称", examples=["乘法口诀"])
    point_type: str = Field(description="知识点类型", examples=["knowledge"])
    importance_level: int | None = Field(default=None, description="重要度")
    difficulty_level: int | None = Field(default=None, description="难度")
    mastery_level_hint: str | None = Field(default=None, description="掌握建议")
    tags_json: dict[str, Any] | None = Field(default=None, description="标签 JSON")
    summary_text: str | None = Field(default=None, description="摘要")
    sort_order: int = Field(description="排序号", examples=[0])
    evidence_count: int = Field(description="证据数量", examples=[2])
    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="更新时间")


class KnowledgePointDetailResponse(KnowledgePointListItemResponse):
    """知识点详情响应。"""

    evidences: list[KnowledgeEvidenceResponse] = Field(description="证据列表")


class KnowledgeVersionListItemResponse(BaseSchema):
    """知识版本列表项响应。"""

    id: int = Field(description="知识版本主键", examples=[1])
    project_id: int = Field(description="所属项目主键", examples=[1])
    parse_version_id: int = Field(description="解析版本主键", examples=[1])
    parent_knowledge_version_id: int | None = Field(default=None, description="父知识版本主键")
    version_no: int = Field(description="版本号", examples=[1])
    version_status: str = Field(description="版本状态", examples=["ready"])
    summary_json: dict[str, Any] | None = Field(default=None, description="知识摘要")
    chapter_count: int = Field(description="章节数量", examples=[3])
    point_count: int = Field(description="知识点数量", examples=[8])
    created_by: int | None = Field(default=None, description="创建人主键")
    created_at: datetime = Field(description="创建时间")
    updated_at: datetime = Field(description="更新时间")


class KnowledgeVersionDetailResponse(KnowledgeVersionListItemResponse):
    """知识版本详情响应。"""


class KnowledgeExtractionEvidenceDraft(BaseSchema):
    """LLM 知识抽取证据草稿。"""

    page_no: int = Field(description="页码", ge=1)
    block_no: int | None = Field(default=None, description="块序号", ge=1)
    evidence_type: str = Field(default="parse_block", description="证据类型", min_length=1, max_length=32)
    excerpt_text: str | None = Field(default=None, description="证据片段")
    bbox_json: dict[str, Any] | None = Field(default=None, description="坐标框")
    score_value: float | None = Field(default=None, description="证据分数", ge=0, le=1)


class KnowledgeExtractionChapterDraft(BaseSchema):
    """LLM 章节草稿。"""

    node_path: str = Field(description="路径编码", min_length=1, max_length=255)
    node_no: int = Field(description="节点序号", ge=1)
    node_level: int = Field(description="节点层级", ge=1)
    node_type: str = Field(description="节点类型", min_length=1, max_length=32)
    title: str = Field(description="标题", min_length=1, max_length=255)
    summary_text: str | None = Field(default=None, description="摘要")
    page_start: int | None = Field(default=None, description="起始页", ge=1)
    page_end: int | None = Field(default=None, description="结束页", ge=1)
    sort_order: int = Field(default=0, description="排序号", ge=0)

    @model_validator(mode="after")
    def validate_page_range(self) -> "KnowledgeExtractionChapterDraft":
        if self.page_start is not None and self.page_end is not None and self.page_start > self.page_end:
            raise ValueError("章节起始页不能大于结束页")
        return self


class KnowledgeExtractionPointDraft(BaseSchema):
    """LLM 知识点草稿。"""

    chapter_path: str | None = Field(default=None, description="所属章节路径编码")
    point_code: str | None = Field(default=None, description="知识点编码")
    point_name: str = Field(description="知识点名称", min_length=1, max_length=255)
    point_type: str = Field(default="knowledge", description="知识点类型", min_length=1, max_length=32)
    importance_level: int | None = Field(default=None, description="重要度", ge=1, le=5)
    difficulty_level: int | None = Field(default=None, description="难度", ge=1, le=5)
    mastery_level_hint: str | None = Field(default=None, description="掌握建议")
    tags_json: dict[str, Any] | None = Field(default=None, description="标签 JSON")
    summary_text: str | None = Field(default=None, description="摘要")
    sort_order: int = Field(default=0, description="排序号", ge=0)
    evidences: list[KnowledgeExtractionEvidenceDraft] = Field(default_factory=list, description="证据列表")


class KnowledgeExtractionResult(BaseSchema):
    """LLM 知识抽取结果。"""

    summary_json: dict[str, Any] | None = Field(default=None, description="知识摘要 JSON")
    chapters: list[KnowledgeExtractionChapterDraft] = Field(description="章节列表", min_length=1)
    knowledge_points: list[KnowledgeExtractionPointDraft] = Field(description="知识点列表", min_length=1)
