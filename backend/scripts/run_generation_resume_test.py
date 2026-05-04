"""
@Date: 2026-05-04
@Author: xisy
@Discription: 复用已有项目的解析与学情，仅重跑知识抽取+大纲教案批次的调试脚本
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import desc
from sqlalchemy.orm import Session

# 与 run_generation_effect_test.py 保持一致：同步执行，跳过 Celery worker
os.environ["TASK_EAGER_MODE"] = "1"
os.environ["LLM_TIMEOUT_SECONDS"] = os.environ.get("LLM_TIMEOUT_SECONDS", "180")

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.exceptions import AppException
from app.core.constants import KNOWLEDGE_EXTRACT_TASK_TYPE, KNOWLEDGE_MODULE_CODE, TASK_STATUS_FAILURE
from app.modules.auth.models import SysUser  # noqa: F401  确保 SQLAlchemy 注册 sys_user 模型
from app.modules.knowledge.repository import KnowledgeRepository
from app.modules.knowledge.schemas import KnowledgeTaskCreateRequest
from app.modules.knowledge.service import KnowledgeService
from app.modules.p0_models import (
    LearnerProfileVersion,
    ParseVersion,
    Project,
    TextbookVersion,
)
from app.modules.pipeline.repository import PipelineRepository
from app.modules.pipeline.schemas import GenerationBatchCreateRequest
from app.modules.pipeline.service import PipelineService
from app.modules.task_center.repository import TaskCenterRepository
from app.shared.llm.client import OpenAICompatibleLlmClient
from app.shared.llm.service import OpenAICompatibleEmbeddingService
from app.shared.vector.service import MilvusVectorService

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = PROJECT_ROOT / "docs"
COURSE_COUNT = 2
SESSION_DURATION_MINUTES = 90


def main() -> None:
    """复用最近一次效果测试项目，按需重跑知识抽取与生成批次。"""
    _patch_embedding_and_vector_noop()
    _patch_llm_gateway_retry()
    _ensure_runtime_ready()

    regenerate_knowledge = "--regenerate-knowledge" in sys.argv
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    session = SessionLocal()
    try:
        project_id = _resolve_project_id_from_argv(session)
        bundle = _load_project_bundle(session, project_id=project_id)
        print(
            f"复用项目 ID={bundle.project.id}，教材版本 ID={bundle.textbook_version.id}，"
            f"解析版本 ID={bundle.parse_version.id}，学情版本 ID={bundle.profile_version.id}",
            flush=True,
        )

        knowledge_repo = KnowledgeRepository(session)
        existing_knowledge = (
            None if regenerate_knowledge else knowledge_repo.get_ready_knowledge_version(bundle.parse_version.id)
        )
        if existing_knowledge is not None:
            knowledge_version_id = existing_knowledge.id
            print(
                f"复用已有知识版本 ID={knowledge_version_id}，跳过 LLM 抽取（如需重抽请加 --regenerate-knowledge）。",
                flush=True,
            )
        else:
            _release_stale_extract_task(session, parse_version_id=bundle.parse_version.id)
            print("开始调用 LLM 抽取知识结构（force_regenerate）。", flush=True)
            knowledge_task = KnowledgeService(session, knowledge_repo).create_extract_task(
                owner_user_id=bundle.project.owner_user_id,
                parse_version_id=bundle.parse_version.id,
                request=KnowledgeTaskCreateRequest(force_regenerate=True),
            )
            knowledge_version_id = int(knowledge_task.result_json["knowledge_version_id"])
            print(f"知识结构已生成，知识版本 ID={knowledge_version_id}。", flush=True)

        print("开始创建大纲教案批次。", flush=True)

        batch = PipelineService(session, PipelineRepository(session)).create_generation_batch(
            owner_user_id=bundle.project.owner_user_id,
            request=GenerationBatchCreateRequest(
                project_id=bundle.project.id,
                knowledge_version_id=knowledge_version_id,
                learner_profile_version_id=bundle.profile_version.id,
                batch_name=f"resume 调试 {timestamp}",
                chapter_range_json={"chapter_node_ids": []},
                course_count=COURSE_COUNT,
                session_duration_minutes=SESSION_DURATION_MINUTES,
            ),
        )
        print(f"批次生成完成，批次 ID={batch.id}，状态={batch.batch_status}，开始写入报告。", flush=True)

        report_path = _write_report(
            session,
            timestamp=timestamp,
            project=bundle.project,
            textbook_version=bundle.textbook_version,
            parse_version=bundle.parse_version,
            profile_version=bundle.profile_version,
            knowledge_version_id=knowledge_version_id,
            generation_batch_id=batch.id,
        )
        print(
            json.dumps(
                {
                    "status": "success",
                    "report_path": str(report_path),
                    "project_id": bundle.project.id,
                    "knowledge_version_id": knowledge_version_id,
                    "generation_batch_id": batch.id,
                },
                ensure_ascii=False,
            )
        )
    finally:
        session.close()


class _ProjectBundle:
    """承载复用项目所需的核心实体。"""

    def __init__(
        self,
        *,
        project: Project,
        textbook_version: TextbookVersion,
        parse_version: ParseVersion,
        profile_version: LearnerProfileVersion,
    ) -> None:
        self.project = project
        self.textbook_version = textbook_version
        self.parse_version = parse_version
        self.profile_version = profile_version


def _resolve_project_id_from_argv(session: Session) -> int:
    """支持命令行传入项目 ID，否则取最近一次 effect_test_* 项目。"""
    if len(sys.argv) >= 2:
        return int(sys.argv[1])
    project = (
        session.query(Project)
        .filter(Project.project_code.like("effect_test_%"))
        .order_by(desc(Project.id))
        .first()
    )
    if project is None:
        raise RuntimeError("未找到 effect_test_* 项目，请先运行 run_generation_effect_test.py 准备数据。")
    return project.id


def _load_project_bundle(session: Session, *, project_id: int) -> _ProjectBundle:
    """加载项目最新的教材、解析和学情版本。"""
    project = session.query(Project).filter(Project.id == project_id).first()
    if project is None:
        raise RuntimeError(f"项目不存在：{project_id}")
    textbook_version = (
        session.query(TextbookVersion)
        .filter(TextbookVersion.project_id == project.id)
        .order_by(desc(TextbookVersion.id))
        .first()
    )
    if textbook_version is None:
        raise RuntimeError(f"项目 {project.id} 缺少教材版本")
    parse_version = (
        session.query(ParseVersion)
        .filter(ParseVersion.textbook_version_id == textbook_version.id)
        .order_by(desc(ParseVersion.id))
        .first()
    )
    if parse_version is None:
        raise RuntimeError(f"教材版本 {textbook_version.id} 缺少解析版本")
    profile_version = (
        session.query(LearnerProfileVersion)
        .filter(LearnerProfileVersion.project_id == project.id)
        .order_by(desc(LearnerProfileVersion.id))
        .first()
    )
    if profile_version is None:
        raise RuntimeError(f"项目 {project.id} 缺少学情版本")
    return _ProjectBundle(
        project=project,
        textbook_version=textbook_version,
        parse_version=parse_version,
        profile_version=profile_version,
    )


def _release_stale_extract_task(session: Session, *, parse_version_id: int) -> None:
    """将先前失败但残留为 processing/pending 的知识抽取任务标记为 failure，避免重复触发时被 TASK_CONFLICT 拦截。"""
    task_repo = TaskCenterRepository(session)
    biz_key = f"parse_version:{parse_version_id}:knowledge"
    stale_task = task_repo.get_active_task_by_biz_key(
        module_code=KNOWLEDGE_MODULE_CODE,
        task_type=KNOWLEDGE_EXTRACT_TASK_TYPE,
        biz_key=biz_key,
    )
    if stale_task is None:
        return
    print(f"检测到残留任务 task_id={stale_task.id}（{stale_task.task_status}），标记为 failure 后继续。", flush=True)
    stale_task.task_status = TASK_STATUS_FAILURE
    stale_task.error_message = "resume 调试脚本主动释放的残留任务"
    task_repo.save(stale_task)
    session.commit()


def _ensure_runtime_ready() -> None:
    """检查运行所需的关键配置。"""
    settings = get_settings()
    missing_items: list[str] = []
    if not settings.llm_api_key:
        missing_items.append("LLM_API_KEY")
    if not settings.llm_model:
        missing_items.append("LLM_MODEL")
    if missing_items:
        raise RuntimeError(f"缺少必要配置：{', '.join(missing_items)}")


def _patch_embedding_and_vector_noop() -> None:
    """跳过本次调试不关心的向量写入。"""

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
    """压缩输出 LLM 错误详情，便于调试定位问题。"""
    if not details:
        return "无错误详情"
    summary = {
        "status_code": details.get("status_code"),
        "payload": details.get("payload"),
    }
    return json.dumps(summary, ensure_ascii=False)[:1200]


def _write_report(
    session: Session,
    *,
    timestamp: str,
    project: Project,
    textbook_version: TextbookVersion,
    parse_version: ParseVersion,
    profile_version: LearnerProfileVersion,
    knowledge_version_id: int,
    generation_batch_id: int,
) -> Path:
    """复用大纲教案产出格式，输出 resume 调试版报告。"""
    from app.modules.lesson_plan.repository import LessonPlanRepository

    lesson_repo = LessonPlanRepository(session)
    batch = lesson_repo.get_generation_batch(generation_batch_id)
    if batch is None:
        raise RuntimeError(f"生成批次不存在：{generation_batch_id}")
    curriculum = lesson_repo.get_curriculum_plan(batch.curriculum_plan_id)
    if curriculum is None:
        raise RuntimeError(f"课程大纲不存在：{batch.curriculum_plan_id}")
    lessons = lesson_repo.list_lesson_plans_by_batch(generation_batch_id)
    knowledge_repo = KnowledgeRepository(session)
    chapters = knowledge_repo.list_chapter_nodes(knowledge_version_id)
    points = knowledge_repo.list_knowledge_points(
        knowledge_version_id,
        chapter_node_id=None,
        keyword=None,
        offset=0,
        limit=20,
    )

    report_path = OUTPUT_DIR / f"generation_resume_test_{timestamp}.md"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    lines = [
        "<!-- @Date: 2026-05-04 @Author: xisy @Discription: 大纲教案 resume 调试报告 -->",
        "",
        "# 大纲与教案 resume 调试报告",
        "",
        "本报告由 `backend/scripts/run_generation_resume_test.py` 自动生成，复用已有项目的教材解析与学情，仅重跑知识抽取与大纲教案生成。",
        "",
        "## 测试输入",
        "",
        f"- 项目 ID：`{project.id}`，code：`{project.project_code}`",
        f"- 教材版本 ID：`{textbook_version.id}`，名称：`{textbook_version.textbook_name}`，页数：`{textbook_version.page_count}`",
        f"- 解析版本 ID：`{parse_version.id}`，模式：`{parse_version.parse_mode}`，范围：`{parse_version.page_range_text}`",
        f"- 知识版本 ID：`{knowledge_version_id}`，章节数：`{len(chapters)}`，知识点数：`{len(points)}`",
        f"- 学情版本 ID：`{profile_version.id}`",
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

    lines.extend(["## 知识点样例", ""])
    for point in points[:12]:
        lines.append(f"- {point.point_name}：{point.summary_text or ''}")

    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


if __name__ == "__main__":
    main()
