"""
@Date: 2026-05-04
@Author: xisy
@Discription: 基于赛题材料运行教材到大纲教案的效果测试脚本
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any
from zipfile import ZipFile

from pypdf import PdfReader, PdfWriter
from sqlalchemy.orm import Session

# 本脚本用于效果验证，任务需要同步执行，避免依赖本地 Celery worker。
os.environ["TASK_EAGER_MODE"] = "1"
os.environ["LLM_TIMEOUT_SECONDS"] = os.environ.get("LLM_TIMEOUT_SECONDS", "180")
os.environ["MINERU_POLL_TIMEOUT_SECONDS"] = os.environ.get("MINERU_POLL_TIMEOUT_SECONDS", "900")

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.exceptions import AppException
from app.core.security import hash_password
from app.modules.auth.models import SysUser
from app.modules.knowledge.repository import KnowledgeRepository
from app.modules.knowledge.schemas import KnowledgeTaskCreateRequest
from app.modules.knowledge.service import KnowledgeService
from app.modules.p0_models import FileObject, ParseVersion, Project, TextbookVersion
from app.modules.parsing.domain import build_page_drafts_from_normalized_document, persist_parse_tree
from app.modules.parsing.repository import ParsingRepository
from app.modules.pipeline.repository import PipelineRepository
from app.modules.pipeline.schemas import GenerationBatchCreateRequest
from app.modules.pipeline.service import PipelineService
from app.modules.textbook.repository import TextbookRepository
from app.shared.llm.client import OpenAICompatibleLlmClient
from app.shared.llm.service import OpenAICompatibleEmbeddingService
from app.shared.mineru import MineruDocumentService
from app.shared.vector.service import MilvusVectorService


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TEXTBOOK_PATH = PROJECT_ROOT / "教育赛题" / "教材文档" / "教材-福建教育出版社-英语-五年级上册.pdf"
PROFILE_PATH = PROJECT_ROOT / "教育赛题" / "学情分析" / "学生4.docx"
OUTPUT_DIR = PROJECT_ROOT / "docs"

TEXTBOOK_NAME = "福建教育出版社英语五年级上册 Unit 1 摘取"
PROFILE_TITLE = "学生4英语学情"
SUBJECT_CODE = "english"
GRADE_CODE = "grade_5"
COURSE_COUNT = 2
SESSION_DURATION_MINUTES = 90
# PDF 第 6-10 页对应 Unit 1 的主体内容，避免一次测试消耗过大。
TEXTBOOK_PAGE_RANGE = range(6, 11)


def main() -> None:
    """执行端到端效果测试。"""
    _patch_embedding_and_vector_noop()
    _patch_llm_gateway_retry()
    settings = get_settings()
    _ensure_runtime_ready(settings)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    session = SessionLocal()
    try:
        print("准备测试账号与项目。", flush=True)
        user = _ensure_demo_user(session)
        project = _create_project(session, owner_user_id=user.id, timestamp=timestamp)
        print("开始调用 MinerU 解析教材页段。", flush=True)
        textbook_version, parse_version = _parse_textbook_with_mineru(
            session,
            project=project,
            operator_user_id=user.id,
            timestamp=timestamp,
        )
        print("教材解析已落库，开始准备学情版本。", flush=True)
        profile_version_id = _upload_profile_with_existing_service(
            session,
            project=project,
            textbook_version_id=textbook_version.id,
            owner_user_id=user.id,
        )
        print("开始调用 LLM 抽取知识结构。", flush=True)
        knowledge_task = KnowledgeService(session, KnowledgeRepository(session)).create_extract_task(
            owner_user_id=user.id,
            parse_version_id=parse_version.id,
            request=KnowledgeTaskCreateRequest(force_regenerate=True),
        )
        knowledge_version_id = int(knowledge_task.result_json["knowledge_version_id"])
        print("知识结构已生成，开始创建大纲教案批次。", flush=True)
        batch = PipelineService(session, PipelineRepository(session)).create_generation_batch(
            owner_user_id=user.id,
            request=GenerationBatchCreateRequest(
                project_id=project.id,
                knowledge_version_id=knowledge_version_id,
                learner_profile_version_id=profile_version_id,
                batch_name=f"赛题材料大纲教案效果测试 {timestamp}",
                chapter_range_json={"chapter_node_ids": []},
                course_count=COURSE_COUNT,
                session_duration_minutes=SESSION_DURATION_MINUTES,
            ),
        )
        print("批次生成完成，开始写入报告。", flush=True)
        report_path = _write_report(
            session,
            timestamp=timestamp,
            project_id=project.id,
            textbook_version_id=textbook_version.id,
            parse_version_id=parse_version.id,
            knowledge_version_id=knowledge_version_id,
            profile_version_id=profile_version_id,
            generation_batch_id=batch.id,
        )
        print(json.dumps({"status": "success", "report_path": str(report_path), "generation_batch_id": batch.id}, ensure_ascii=False))
    finally:
        session.close()


def _ensure_runtime_ready(settings) -> None:
    """检查本次效果测试必须使用的外部配置。"""
    missing_items: list[str] = []
    if not settings.mineru_api_token:
        missing_items.append("MINERU_API_TOKEN")
    if not settings.llm_api_key:
        missing_items.append("LLM_API_KEY")
    if not settings.llm_model:
        missing_items.append("LLM_MODEL")
    if missing_items:
        raise RuntimeError(f"缺少必要配置：{', '.join(missing_items)}")
    if not TEXTBOOK_PATH.exists():
        raise RuntimeError(f"教材不存在：{TEXTBOOK_PATH}")
    if not PROFILE_PATH.exists():
        raise RuntimeError(f"学情文件不存在：{PROFILE_PATH}")


def _ensure_demo_user(session: Session) -> SysUser:
    """确保本地测试教师账号存在。"""
    user = session.query(SysUser).filter(SysUser.username == "teacher_demo").first()
    if user is not None:
        return user
    user = SysUser(
        username="teacher_demo",
        display_name="示例教师",
        password_hash=hash_password("Teacher@123"),
        role_code="teacher",
        status="active",
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def _create_project(session: Session, *, owner_user_id: int, timestamp: str) -> Project:
    """创建本次效果测试项目。"""
    project = Project(
        owner_user_id=owner_user_id,
        project_code=f"effect_test_{timestamp}",
        name=f"赛题材料大纲教案效果测试 {timestamp}",
        subject_code=SUBJECT_CODE,
        grade_code=GRADE_CODE,
        applicable_target="五年级英语基础薄弱学生",
        remark="使用教育赛题材料自动创建，用于验证大纲和教案产出效果。",
        status="active",
    )
    session.add(project)
    session.commit()
    session.refresh(project)
    return project


def _parse_textbook_with_mineru(
    session: Session,
    *,
    project: Project,
    operator_user_id: int,
    timestamp: str,
) -> tuple[TextbookVersion, ParseVersion]:
    """调用 MinerU 解析教材页段并落库为解析版本。"""
    source_content = TEXTBOOK_PATH.read_bytes()
    source_file = _create_file_object(
        session,
        project_id=project.id,
        biz_type="textbook_source",
        original_filename=TEXTBOOK_PATH.name,
        file_ext=".pdf",
        mime_type="application/pdf",
        content=source_content,
        object_key=f"local-effect-test/{timestamp}/source/{TEXTBOOK_PATH.name}",
        uploaded_by=operator_user_id,
    )
    textbook_version = TextbookVersion(
        project_id=project.id,
        source_file_id=source_file.id,
        version_no=TextbookRepository(session).get_next_version_no(project.id),
        textbook_name=TEXTBOOK_NAME,
        publisher="福建教育出版社",
        subject_code=SUBJECT_CODE,
        grade_code=GRADE_CODE,
        volume_code="上册",
        edition_label="三年级起点",
        isbn=None,
        file_hash=hashlib.sha256(source_content).hexdigest(),
        page_count=len(PdfReader(str(TEXTBOOK_PATH)).pages),
        parse_status="processing",
        version_status="ready",
        auto_identify_json={"source": "education_competition_material", "selected_pages": list(TEXTBOOK_PAGE_RANGE)},
        remark="效果测试使用 Unit 1 页段进行 MinerU 解析。",
        uploaded_by=operator_user_id,
    )
    session.add(textbook_version)
    session.flush()
    project.current_textbook_version_id = textbook_version.id
    session.add(project)
    session.commit()
    session.refresh(textbook_version)

    subset_content = _extract_pdf_pages(TEXTBOOK_PATH, TEXTBOOK_PAGE_RANGE)
    normalized_document = MineruDocumentService().parse_document(
        file_name=f"{TEXTBOOK_PATH.stem}_pages_{TEXTBOOK_PAGE_RANGE.start}_{TEXTBOOK_PAGE_RANGE.stop - 1}.pdf",
        content=subset_content,
        strategy_code="mineru_vlm_default",
        data_id=f"effect_test_textbook_{textbook_version.id}_{timestamp}",
    )
    markdown_file = _create_file_object(
        session,
        project_id=project.id,
        biz_type="parse_markdown",
        original_filename="full.md",
        file_ext=".md",
        mime_type="text/markdown",
        content=normalized_document.markdown_text.encode("utf-8"),
        object_key=f"local-effect-test/{timestamp}/parse/full.md",
        uploaded_by=operator_user_id,
    )
    json_file = _create_file_object(
        session,
        project_id=project.id,
        biz_type="parse_json",
        original_filename="content_list.json",
        file_ext=".json",
        mime_type="application/json",
        content=json.dumps(normalized_document.content_list_json, ensure_ascii=False).encode("utf-8"),
        object_key=f"local-effect-test/{timestamp}/parse/content_list.json",
        uploaded_by=operator_user_id,
    )
    parse_version = ParseVersion(
        project_id=project.id,
        textbook_version_id=textbook_version.id,
        parent_parse_version_id=None,
        version_no=1,
        parse_mode="partial",
        page_range_text=f"{TEXTBOOK_PAGE_RANGE.start}-{TEXTBOOK_PAGE_RANGE.stop - 1}",
        strategy_code="mineru_vlm_default",
        mineru_model=normalized_document.model_version,
        parse_status="success",
        review_status="confirmed",
        version_status="ready",
        page_count=len(normalized_document.pages),
        source_markdown_file_id=markdown_file.id,
        source_json_file_id=json_file.id,
        asset_manifest_json={
            "batch_id": normalized_document.batch_id,
            "data_id": normalized_document.data_id,
            "source_pages": list(TEXTBOOK_PAGE_RANGE),
            "asset_count": len(normalized_document.asset_files),
        },
    )
    session.add(parse_version)
    session.flush()
    page_drafts, issue_drafts = build_page_drafts_from_normalized_document(
        normalized_document,
        asset_file_id_map={},
        page_image_file_id_map={},
        page_no_mapping=list(TEXTBOOK_PAGE_RANGE),
    )
    persist_parse_tree(
        repository=ParsingRepository(session),
        parse_version_id=parse_version.id,
        pages=page_drafts,
        issues=issue_drafts,
    )
    textbook_version.parse_status = "success"
    session.add(textbook_version)
    session.commit()
    session.refresh(parse_version)
    return textbook_version, parse_version


def _upload_profile_with_existing_service(
    session: Session,
    *,
    project: Project,
    textbook_version_id: int,
    owner_user_id: int,
) -> int:
    """使用现有学情服务上传并同步抽取学情。"""
    from app.modules.learner_profile.repository import LearnerProfileRepository
    from app.modules.learner_profile.service import LearnerProfileService
    from app.shared.storage import ObsStorageClient

    _patch_storage_to_local_noop()
    detail = LearnerProfileService(
        session,
        LearnerProfileRepository(session),
        ObsStorageClient(),
    ).upload_profile_file(
        owner_user_id=owner_user_id,
        project_id=project.id,
        filename=PROFILE_PATH.name,
        content=PROFILE_PATH.read_bytes(),
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        title=PROFILE_TITLE,
        grade_code=GRADE_CODE,
        subject_scope=SUBJECT_CODE,
        textbook_version_hint_id=textbook_version_id,
        auto_extract=False,
        set_as_current=True,
    )
    profile_file_id = detail.id
    profile_version_id = _create_profile_version_from_docx(
        session,
        project=project,
        profile_file_id=profile_file_id,
        textbook_version_id=textbook_version_id,
        owner_user_id=owner_user_id,
    )
    project.current_learner_profile_version_id = profile_version_id
    session.add(project)
    session.commit()
    return profile_version_id


def _create_profile_version_from_docx(
    session: Session,
    *,
    project: Project,
    profile_file_id: int,
    textbook_version_id: int,
    owner_user_id: int,
) -> int:
    """根据学情 docx 文本构造可用学情版本。"""
    from app.modules.p0_models import LearnerProfileRecord, LearnerProfileVersion

    text = _extract_docx_text(PROFILE_PATH)
    score = _extract_subject_score(text, "英语")
    version = LearnerProfileVersion(
        project_id=project.id,
        profile_file_id=profile_file_id,
        parent_version_id=None,
        version_no=1,
        textbook_version_hint_id=textbook_version_id,
        grade_code=GRADE_CODE,
        subject_scope=SUBJECT_CODE,
        extract_status="success",
        review_status="confirmed",
        version_status="ready",
        summary_text="英语基础偏弱，词汇量约 200，语法知识零散，阅读理解失分明显；自律性较好，但主动提问和独立思考不足。",
        raw_result_json={"source": "docx_local_parse", "text_excerpt": text[:1000]},
        source_snapshot_json={"profile_path": str(PROFILE_PATH)},
        created_by=owner_user_id,
    )
    session.add(version)
    session.flush()
    record = LearnerProfileRecord(
        project_id=project.id,
        profile_version_id=version.id,
        student_key="student_4_english",
        student_name="刘xx",
        is_anonymous=1,
        region_name="深圳",
        grade_code=GRADE_CODE,
        subject_code=SUBJECT_CODE,
        textbook_version_hint_id=textbook_version_id,
        score_value=score,
        advantage_tags_json={"tags": ["自律性较好", "做事有条理", "能完成预习和作业"]},
        weakness_tags_json={"tags": ["词汇量偏少", "语法知识零散", "阅读理解失分明显", "主动提问不足"]},
        ability_tags_json={"tags": ["基础跟随能力尚可", "需要建立英语学习信心"]},
        habit_tags_json={"tags": ["课堂跟随型", "预习作业完成度较好"]},
        behavior_traits_json={"tags": ["家长期望较高", "辅导精力有限"]},
        time_plan_json={"plan": "英语每周 2 次课，每次 1.5 课时，重点提升词汇积累和基础语法运用。"},
        summary_text=text,
        evidence_json={"source_text": text},
        sort_order=1,
    )
    session.add(record)
    session.commit()
    return version.id


def _create_file_object(
    session: Session,
    *,
    project_id: int,
    biz_type: str,
    original_filename: str,
    file_ext: str,
    mime_type: str,
    content: bytes,
    object_key: str,
    uploaded_by: int,
) -> FileObject:
    """创建本地测试文件对象记录。"""
    settings = get_settings()
    file_object = FileObject(
        project_id=project_id,
        biz_type=biz_type,
        storage_provider="local",
        bucket_name=settings.obs_bucket,
        object_key=object_key,
        original_filename=original_filename,
        file_ext=file_ext,
        mime_type=mime_type,
        file_size=len(content),
        content_hash=hashlib.sha256(content).hexdigest(),
        source_type="local_effect_test",
        upload_status="uploaded",
        uploaded_by=uploaded_by,
        metadata_json={"local_effect_test": True},
    )
    session.add(file_object)
    session.flush()
    return file_object


def _extract_pdf_pages(path: Path, page_numbers: range) -> bytes:
    """按 1 基页码提取 PDF 页段。"""
    reader = PdfReader(str(path))
    writer = PdfWriter()
    for page_no in page_numbers:
        writer.add_page(reader.pages[page_no - 1])
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def _extract_docx_text(path: Path) -> str:
    """轻量提取 docx 正文文本。"""
    with ZipFile(path) as archive:
        xml_text = archive.read("word/document.xml").decode("utf-8", errors="ignore")
    text = re.sub(r"<[^>]+>", "", xml_text)
    return re.sub(r"\s+", " ", text).strip()


def _extract_subject_score(text: str, subject_name: str) -> float | None:
    """从学情文本中提取指定学科分数。"""
    match = re.search(rf"{subject_name}：(\d+(?:\.\d+)?)分", text)
    return float(match.group(1)) if match else None


def _patch_embedding_and_vector_noop() -> None:
    """跳过本次效果测试不关心的向量写入。"""

    def fake_embed_texts(self, texts: list[str]) -> list[list[float]]:  # noqa: ANN001
        dimension = get_settings().milvus_embedding_dim
        return [[float(index + 1)] * dimension for index, _ in enumerate(texts)]

    def fake_upsert_vectors(self, collection_name: str, records: list[Any]) -> dict[str, int]:  # noqa: ANN001
        _ = (self, collection_name)
        return {"upsert_count": len(records)}

    OpenAICompatibleEmbeddingService.embed_texts = fake_embed_texts
    MilvusVectorService.upsert_vectors = fake_upsert_vectors


def _patch_llm_gateway_retry() -> None:
    """为真实效果验证增加 LLM 网关错误重试。"""
    original_create_chat_completion = OpenAICompatibleLlmClient.create_chat_completion
    original_create_response = OpenAICompatibleLlmClient.create_response

    def retrying_create_chat_completion(self, payload: dict[str, Any]) -> dict[str, Any]:  # noqa: ANN001
        return _retry_llm_call(
            call_name="Chat Completions",
            call_func=lambda: original_create_chat_completion(self, payload),
        )

    def retrying_create_response(self, payload: dict[str, Any]) -> dict[str, Any]:  # noqa: ANN001
        return _retry_llm_call(
            call_name="Responses",
            call_func=lambda: original_create_response(self, payload),
        )

    OpenAICompatibleLlmClient.create_chat_completion = retrying_create_chat_completion
    OpenAICompatibleLlmClient.create_response = retrying_create_response


def _retry_llm_call(*, call_name: str, call_func) -> dict[str, Any]:  # noqa: ANN001
    """重试 LLM 网关可恢复错误。"""
    last_exception: AppException | None = None
    for attempt in range(1, 4):
        try:
            return call_func()
        except AppException as exc:
            last_exception = exc
            details = exc.details if isinstance(exc.details, dict) else {}
            response_payload = details.get("payload") if isinstance(details.get("payload"), dict) else {}
            status_code = int(details.get("status_code") or response_payload.get("status") or 0)
            retryable = bool(response_payload.get("retryable")) or status_code in {429, 502, 503, 504}
            if not retryable or attempt >= 3:
                print(
                    f"LLM {call_name} 第 {attempt} 次调用失败，不再重试：{_summarize_llm_error(details)}",
                    flush=True,
                )
                raise
            retry_after = int(response_payload.get("retry_after") or 30)
            wait_seconds = max(10, min(retry_after, 90))
            print(f"LLM {call_name} 第 {attempt} 次调用返回可重试错误 {status_code}，等待 {wait_seconds} 秒后重试。", flush=True)
            time.sleep(wait_seconds)
    raise last_exception or RuntimeError(f"LLM {call_name} 调用失败")


def _summarize_llm_error(details: dict[str, Any]) -> str:
    """压缩输出 LLM 错误详情，便于效果测试定位问题。"""
    if not details:
        return "无错误详情"
    summary = {
        "status_code": details.get("status_code"),
        "payload": details.get("payload"),
    }
    return json.dumps(summary, ensure_ascii=False)[:1200]


def _patch_storage_to_local_noop() -> None:
    """避免学情上传阶段依赖 OBS 网络，仅保留文件对象记录。"""
    from app.shared.storage import ObsStorageClient

    def fake_upload_bytes(self, object_key: str, content: bytes, content_type=None, metadata=None):  # noqa: ANN001
        _ = (self, content_type, metadata)
        return {
            "bucket_name": get_settings().obs_bucket,
            "object_key": object_key,
            "etag": hashlib.sha256(content).hexdigest(),
            "request_id": "local-effect-test",
        }

    def fake_delete_object(self, object_key: str) -> bool:  # noqa: ANN001
        _ = (self, object_key)
        return True

    ObsStorageClient.upload_bytes = fake_upload_bytes
    ObsStorageClient.delete_object = fake_delete_object


def _write_report(
    session: Session,
    *,
    timestamp: str,
    project_id: int,
    textbook_version_id: int,
    parse_version_id: int,
    knowledge_version_id: int,
    profile_version_id: int,
    generation_batch_id: int,
) -> Path:
    """将本次生成结果写为 Markdown 报告。"""
    from app.modules.lesson_plan.repository import LessonPlanRepository

    lesson_repo = LessonPlanRepository(session)
    batch = lesson_repo.get_generation_batch(generation_batch_id)
    if batch is None:
        raise RuntimeError(f"生成批次不存在：{generation_batch_id}")
    curriculum = lesson_repo.get_curriculum_plan(batch.curriculum_plan_id)
    if curriculum is None:
        raise RuntimeError(f"课程大纲不存在：{batch.curriculum_plan_id}")
    lessons = lesson_repo.list_lesson_plans_by_batch(generation_batch_id)
    chapters = KnowledgeRepository(session).list_chapter_nodes(knowledge_version_id)
    points = KnowledgeRepository(session).list_knowledge_points(knowledge_version_id)

    report_path = OUTPUT_DIR / f"generation_effect_test_{timestamp}.md"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    lines = [
        "<!-- @Date: 2026-05-04 @Author: xisy @Discription: 大纲教案效果测试报告 -->",
        "",
        "# 大纲与教案效果测试报告",
        "",
        "本报告由 `backend/scripts/run_generation_effect_test.py` 自动生成，使用教育赛题目录下的真实教材与学情材料完成一次大纲、教案产出验证。",
        "",
        "## 测试输入",
        "",
        f"- 项目 ID：`{project_id}`",
        f"- 教材版本 ID：`{textbook_version_id}`，教材：`{TEXTBOOK_PATH.name}`，页段：`{TEXTBOOK_PAGE_RANGE.start}-{TEXTBOOK_PAGE_RANGE.stop - 1}`",
        f"- 解析版本 ID：`{parse_version_id}`",
        f"- 知识版本 ID：`{knowledge_version_id}`，章节数：`{len(chapters)}`，知识点数：`{len(points)}`",
        f"- 学情版本 ID：`{profile_version_id}`，学情：`{PROFILE_PATH.name}`",
        f"- 生成批次 ID：`{generation_batch_id}`，状态：`{batch.batch_status}`",
        "",
        "## 课程大纲",
        "",
        f"标题：{curriculum.plan_title}",
        "",
        curriculum.summary_text or "",
        "",
        "### 课次安排",
        "",
    ]
    for session_item in curriculum.content_json.get("lesson_sessions", []):
        lines.extend(
            [
                f"- 第 {session_item.get('session_no')} 讲：{session_item.get('title')}",
                f"  目标：{'；'.join(session_item.get('objectives') or [])}",
                f"  活动：{'；'.join(session_item.get('activities') or [])}",
                f"  作业：{'；'.join(session_item.get('homework') or [])}",
            ]
        )

    lines.extend(["", "## 教案摘要", ""])
    for lesson in lessons:
        content = lesson.content_json or {}
        lines.extend(
            [
                f"### 第 {lesson.class_session_no} 讲：{lesson.lesson_title}",
                "",
                lesson.summary_text or "",
                "",
                "- 核心知识：" + "；".join(content.get("core_knowledge") or []),
                "- 学情适配：" + "；".join(content.get("learner_adjustments") or []),
                "",
                "教学流程：",
            ]
        )
        for step in content.get("teaching_flow") or []:
            lines.append(
                f"- {step.get('stage_name')}（{step.get('duration_minutes')} 分钟）：教师动作：{'；'.join(step.get('teacher_actions') or [])}；学生活动：{'；'.join(step.get('student_activities') or [])}"
            )
        lines.append("")

    lines.extend(
        [
            "## 知识点样例",
            "",
        ]
    )
    for point in points[:12]:
        lines.append(f"- {point.point_name}：{point.summary_text or ''}")

    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


if __name__ == "__main__":
    main()
