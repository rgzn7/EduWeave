"""
@Date: 2026-05-09
@Author: xisy
@Discription: DOCX 渲染与导出归档服务
"""

import hashlib
import json
from io import BytesIO
from typing import Any

from docx import Document
from docx.enum.text import WD_BREAK
from docx.shared import Inches
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import AppException, BusinessErrorCode
from app.modules.file_asset.schemas import FileDownloadUrlResponse
from app.modules.p0_models import FileObject
from app.shared.storage import ObsStorageClient
from app.shared.utils import DateTimeUtil

DOCX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class DocxRenderService:
    """根据结构化结果渲染 DOCX 文档。"""

    def render_curriculum_plan(self, plan) -> bytes:
        """渲染课程大纲 DOCX。"""
        content = _ensure_dict(plan.content_json)
        document = _create_document()
        document.add_heading(_safe_text(plan.plan_title, "课程大纲"), level=0)
        _add_meta_paragraph(document, "课程摘要", plan.summary_text)
        _add_meta_paragraph(document, "总课次", plan.course_count)
        _add_meta_paragraph(document, "单次课时", f"{plan.session_duration_minutes} 分钟")

        _add_mapping_section(document, "课程概览", content.get("course_overview"))
        _add_list_section(document, "阶段目标", content.get("stage_goals"))
        _add_list_section(document, "课程重点", content.get("key_points"))
        _add_list_section(document, "课程难点", content.get("difficult_points"))
        _add_list_section(document, "学情适配策略", content.get("learner_adjustments"))
        _add_lesson_session_table(document, content.get("lesson_sessions"))
        return _dump_document(document)

    def render_lesson_plan(self, lesson_plan) -> bytes:
        """渲染教案 DOCX。"""
        content = _ensure_dict(lesson_plan.content_json)
        document = _create_document()
        document.add_heading(_safe_text(lesson_plan.lesson_title, "教案"), level=0)
        _add_meta_paragraph(document, "教案摘要", lesson_plan.summary_text)
        if lesson_plan.class_session_no is not None:
            _add_meta_paragraph(document, "课次", lesson_plan.class_session_no)

        _add_mapping_section(document, "课程概述", content.get("course_overview"))
        _add_list_section(document, "物料清单", content.get("material_list"))
        _add_list_section(document, "核心知识", content.get("core_knowledge"))
        _add_teaching_flow_table(document, content.get("teaching_flow"))
        _add_lesson_detail_sections(document, content.get("session_plans"))
        _add_mapping_section(document, "课后安排", content.get("after_class_plan"))
        _add_list_section(document, "学情适配策略", content.get("learner_adjustments"))
        return _dump_document(document)

    def render_paper_result(self, paper_result, questions: list) -> bytes:
        """渲染试卷结果 DOCX。"""
        paper_json = _ensure_dict(paper_result.paper_json)
        document = _create_document()
        document.add_heading(_safe_text(paper_result.title or paper_json.get("paper_title"), "试卷"), level=0)
        _add_meta_paragraph(document, "试卷类型", paper_result.scene_type)
        _add_meta_paragraph(document, "题目数量", paper_result.question_count)
        _add_mapping_section(document, "题型分布", paper_json.get("question_type_distribution"))
        _add_mapping_section(document, "难度分布", paper_json.get("difficulty_distribution"))

        document.add_heading("题目明细", level=1)
        if not questions:
            document.add_paragraph("暂无题目。")
            return _dump_document(document)

        for question in questions:
            document.add_heading(f"第 {question.question_no} 题", level=2)
            _add_meta_paragraph(document, "题型", question.question_type)
            _add_meta_paragraph(document, "难度", question.difficulty_level)
            _add_meta_paragraph(document, "分值", question.score_value)
            _add_plain_paragraph(document, "题干", question.stem_text)
            _add_mapping_section(document, "选项", question.options_json, level=3)
            _add_plain_paragraph(document, "答案", question.answer_text)
            _add_plain_paragraph(document, "解析", question.analysis_text)
            _add_mapping_section(document, "来源摘要", question.source_trace_json, level=3)
        return _dump_document(document)


class DocumentExportService:
    """负责 DOCX 文件上传、文件对象落库与下载地址生成。"""

    def __init__(
        self,
        session: Session,
        storage_client: ObsStorageClient | None = None,
        render_service: DocxRenderService | None = None,
    ) -> None:
        self.session = session
        self.storage_client = storage_client or ObsStorageClient()
        self.render_service = render_service or DocxRenderService()
        self.settings = get_settings()

    def archive_docx(
        self,
        *,
        project_id: int,
        owner_user_id: int,
        biz_type: str,
        object_segments: tuple[str, ...],
        filename: str,
        content: bytes,
        metadata_json: dict[str, Any] | None,
        target,
    ) -> FileDownloadUrlResponse:
        """归档 DOCX 并回填业务对象导出文件。"""
        object_key = self.storage_client.build_object_key(*object_segments, filename=filename)
        try:
            self.storage_client.upload_bytes(object_key, content, content_type=DOCX_MIME_TYPE)
        except Exception as exc:  # noqa: BLE001
            raise AppException(BusinessErrorCode.FILE_UPLOAD_FAILED, "DOCX 文件上传失败", {"error": str(exc)}) from exc

        file_object = self._upsert_file_object(
            project_id=project_id,
            owner_user_id=owner_user_id,
            biz_type=biz_type,
            object_key=object_key,
            filename=filename,
            content=content,
            metadata_json=metadata_json,
        )
        target.export_file_id = file_object.id
        self.session.add(target)
        self.session.commit()

        try:
            signed_url = self.storage_client.create_download_signed_url(file_object.object_key)
        except Exception as exc:  # noqa: BLE001
            raise AppException(
                BusinessErrorCode.EXTERNAL_SERVICE_ERROR,
                "生成 DOCX 下载地址失败",
                {"file_object_id": file_object.id, "error": str(exc)},
            ) from exc

        return FileDownloadUrlResponse(
            file_object_id=file_object.id,
            bucket_name=file_object.bucket_name,
            object_key=file_object.object_key,
            signed_url=signed_url,
            expires_in_seconds=self.settings.obs_signed_url_expire_seconds,
            generated_at=DateTimeUtil.now_utc(),
        )

    def _upsert_file_object(
        self,
        *,
        project_id: int,
        owner_user_id: int,
        biz_type: str,
        object_key: str,
        filename: str,
        content: bytes,
        metadata_json: dict[str, Any] | None,
    ) -> FileObject:
        """按桶和对象路径复用或创建文件对象。"""
        bucket_name = self.storage_client.settings.obs_bucket
        statement = select(FileObject).where(FileObject.bucket_name == bucket_name, FileObject.object_key == object_key)
        file_object = self.session.scalar(statement)
        if file_object is None:
            file_object = FileObject(
                project_id=project_id,
                biz_type=biz_type,
                bucket_name=bucket_name,
                object_key=object_key,
                original_filename=filename,
                file_ext=".docx",
                mime_type=DOCX_MIME_TYPE,
                file_size=len(content),
                content_hash=hashlib.sha256(content).hexdigest(),
                source_type="system_export",
                upload_status="uploaded",
                uploaded_by=owner_user_id,
                metadata_json=metadata_json,
            )
        else:
            file_object.project_id = project_id
            file_object.biz_type = biz_type
            file_object.original_filename = filename
            file_object.file_ext = ".docx"
            file_object.mime_type = DOCX_MIME_TYPE
            file_object.file_size = len(content)
            file_object.content_hash = hashlib.sha256(content).hexdigest()
            file_object.source_type = "system_export"
            file_object.upload_status = "uploaded"
            file_object.uploaded_by = owner_user_id
            file_object.metadata_json = metadata_json
        self.session.add(file_object)
        self.session.flush()
        return file_object


def _create_document() -> Document:
    """创建基础 DOCX 文档。"""
    document = Document()
    section = document.sections[0]
    section.top_margin = Inches(0.7)
    section.bottom_margin = Inches(0.7)
    section.left_margin = Inches(0.8)
    section.right_margin = Inches(0.8)
    return document


def _dump_document(document: Document) -> bytes:
    """导出 DOCX 二进制内容。"""
    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _ensure_dict(value: Any) -> dict[str, Any]:
    """确保结构化字段为字典。"""
    return value if isinstance(value, dict) else {}


def _safe_text(value: Any, fallback: str = "暂无") -> str:
    """转换安全展示文本。"""
    if value is None:
        return fallback
    if isinstance(value, str):
        return value.strip() or fallback
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _join_list(value: Any) -> str:
    """把列表或对象转换为多行文本。"""
    if isinstance(value, list):
        if not value:
            return "暂无"
        return "\n".join(_safe_text(item) for item in value)
    return _safe_text(value)


def _add_meta_paragraph(document: Document, label: str, value: Any) -> None:
    """追加键值段落。"""
    paragraph = document.add_paragraph()
    paragraph.add_run(f"{label}：").bold = True
    paragraph.add_run(_safe_text(value))


def _add_plain_paragraph(document: Document, label: str, value: Any) -> None:
    """追加普通文本段落。"""
    paragraph = document.add_paragraph()
    paragraph.add_run(f"{label}：").bold = True
    paragraph.add_run(_safe_text(value))


def _add_list_section(document: Document, title: str, values: Any) -> None:
    """追加列表章节。"""
    document.add_heading(title, level=1)
    if isinstance(values, list) and values:
        for item in values:
            document.add_paragraph(_safe_text(item), style="List Bullet")
        return
    document.add_paragraph(_safe_text(values))


def _add_mapping_section(document: Document, title: str, mapping: Any, *, level: int = 1) -> None:
    """追加字典章节。"""
    if mapping is None:
        return
    document.add_heading(title, level=level)
    if isinstance(mapping, dict) and mapping:
        table = document.add_table(rows=1, cols=2)
        table.style = "Table Grid"
        table.rows[0].cells[0].text = "字段"
        table.rows[0].cells[1].text = "内容"
        for key, value in mapping.items():
            cells = table.add_row().cells
            cells[0].text = _safe_text(key)
            cells[1].text = _join_list(value)
        return
    if isinstance(mapping, list):
        for item in mapping:
            document.add_paragraph(_safe_text(item), style="List Bullet")
        return
    document.add_paragraph(_safe_text(mapping))


def _add_lesson_session_table(document: Document, sessions: Any) -> None:
    """追加课次安排表。"""
    document.add_heading("课次安排", level=1)
    if not isinstance(sessions, list) or not sessions:
        document.add_paragraph("暂无课次安排。")
        return
    table = document.add_table(rows=1, cols=7)
    table.style = "Table Grid"
    headers = ["课次", "标题", "时长", "目标", "重点", "活动", "课后任务"]
    for index, header in enumerate(headers):
        table.rows[0].cells[index].text = header
    for session in sessions:
        item = _ensure_dict(session)
        cells = table.add_row().cells
        cells[0].text = _safe_text(item.get("session_no"))
        cells[1].text = _safe_text(item.get("title"))
        cells[2].text = _safe_text(item.get("duration_minutes"))
        cells[3].text = _join_list(item.get("objectives"))
        cells[4].text = _join_list(item.get("key_points"))
        cells[5].text = _join_list(item.get("activities"))
        cells[6].text = _join_list(item.get("homework"))


def _add_teaching_flow_table(document: Document, steps: Any) -> None:
    """追加教学流程表。"""
    document.add_heading("教学流程", level=1)
    if not isinstance(steps, list) or not steps:
        document.add_paragraph("暂无教学流程。")
        return
    table = document.add_table(rows=1, cols=6)
    table.style = "Table Grid"
    headers = ["序号", "环节", "时长", "教师动作", "学生活动", "知识点"]
    for index, header in enumerate(headers):
        table.rows[0].cells[index].text = header
    for step in steps:
        item = _ensure_dict(step)
        cells = table.add_row().cells
        cells[0].text = _safe_text(item.get("step_no"))
        cells[1].text = _safe_text(item.get("stage_name"))
        cells[2].text = _safe_text(item.get("duration_minutes"))
        cells[3].text = _join_list(item.get("teacher_actions"))
        cells[4].text = _join_list(item.get("student_activities"))
        cells[5].text = _join_list(item.get("knowledge_point_refs"))


def _add_lesson_detail_sections(document: Document, session_plans: Any) -> None:
    """追加课次讲解安排。"""
    document.add_heading("课次讲解安排", level=1)
    if not isinstance(session_plans, list) or not session_plans:
        document.add_paragraph("暂无课次讲解安排。")
        return
    for session_plan in session_plans:
        item = _ensure_dict(session_plan)
        document.add_heading(_safe_text(item.get("title"), "课次安排"), level=2)
        _add_list_like_paragraph(document, "课次目标", item.get("objectives"))
        _add_list_like_paragraph(document, "教学重点", item.get("teaching_focus"))
        _add_list_like_paragraph(document, "课后任务", item.get("homework"))
        _add_teaching_step_list(document, item.get("teaching_steps"))


def _add_list_like_paragraph(document: Document, label: str, values: Any) -> None:
    """追加带换行的列表型段落。"""
    paragraph = document.add_paragraph()
    paragraph.add_run(f"{label}：").bold = True
    text = _join_list(values)
    lines = text.splitlines() or ["暂无"]
    paragraph.add_run(lines[0])
    for line in lines[1:]:
        paragraph.add_run().add_break(WD_BREAK.LINE)
        paragraph.add_run(line)


def _add_teaching_step_list(document: Document, steps: Any) -> None:
    """追加课次内教学步骤。"""
    if not isinstance(steps, list) or not steps:
        return
    for step in steps:
        item = _ensure_dict(step)
        text = (
            f"{_safe_text(item.get('step_no'))}. {_safe_text(item.get('stage_name'))}："
            f"教师动作 {_join_list(item.get('teacher_actions'))}；"
            f"学生活动 {_join_list(item.get('student_activities'))}"
        )
        document.add_paragraph(text, style="List Number")
