"""
@Date: 2026-05-03
@Author: xisy
@Discription: 课件模块业务服务
"""

import hashlib
import json
from typing import Any

from sqlalchemy.orm import Session

from app.core.constants import (
    COURSEWARE_EXPORT_BIZ_TYPE,
    COURSEWARE_GENERATE_TASK_TYPE,
    COURSEWARE_MODULE_CODE,
    TASK_STATUS_FAILURE,
    TASK_STATUS_PROCESSING,
    TASK_STATUS_SUCCESS,
    VERSION_STATUS_READY,
)
from app.core.exceptions import AppException, BusinessErrorCode
from app.modules.courseware.repository import CoursewareRepository
from app.modules.courseware.schemas import CoursewareResultDetailResponse, CoursewareResultListItemResponse
from app.modules.p0_models import CoursewareResult, FileObject
from app.shared.ppt import RaccoonPptJobState, RaccoonPptService
from app.shared.storage import ObsStorageClient
from app.shared.utils import DateTimeUtil

PPTX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
RACCOON_TEMPLATE_CODE = "raccoon_default"
RACCOON_TEMPLATE_VERSION = "openapi_v2"
RACCOON_ROLE = "教师"
RACCOON_SCENE = "培训教学"
RACCOON_AUDIENCE = "学生"


class CoursewareService:
    """课件模块服务。"""

    def __init__(
        self,
        session: Session,
        repository: CoursewareRepository | None = None,
        ppt_service: RaccoonPptService | None = None,
        storage_client: ObsStorageClient | None = None,
    ) -> None:
        self.session = session
        self.repository = repository or CoursewareRepository(session)
        self.ppt_service = ppt_service or RaccoonPptService()
        self.storage_client = storage_client or ObsStorageClient()

    def list_courseware_results(
        self,
        *,
        owner_user_id: int,
        generation_batch_id: int,
        page: int,
        page_size: int,
    ) -> tuple[list[CoursewareResultListItemResponse], int]:
        """分页查询课件结果。"""
        generation_batch = self.repository.get_generation_batch_for_owner(generation_batch_id, owner_user_id)
        if generation_batch is None:
            raise AppException(BusinessErrorCode.GENERATION_BATCH_NOT_FOUND, "生成批次不存在")
        offset = (page - 1) * page_size
        items = self.repository.list_courseware_results_for_owner(
            owner_user_id,
            generation_batch_id=generation_batch_id,
            offset=offset,
            limit=page_size,
        )
        total_count = self.repository.count_courseware_results_for_owner(
            owner_user_id,
            generation_batch_id=generation_batch_id,
        )
        return [self.build_courseware_response(item) for item in items], total_count

    def get_courseware_result_detail(
        self,
        *,
        owner_user_id: int,
        courseware_result_id: int,
    ) -> CoursewareResultDetailResponse:
        """查询课件结果详情。"""
        courseware_result = self.repository.get_courseware_result_for_owner(courseware_result_id, owner_user_id)
        if courseware_result is None:
            raise AppException(BusinessErrorCode.COURSEWARE_RESULT_NOT_FOUND, "课件结果不存在")
        return CoursewareResultDetailResponse(**self.build_courseware_response(courseware_result).model_dump())

    def refresh_courseware_result(
        self,
        *,
        owner_user_id: int,
        courseware_result_id: int,
    ) -> CoursewareResultDetailResponse:
        """刷新 Raccoon PPT 远程任务状态。"""
        courseware_result = self.repository.get_courseware_result_for_owner(courseware_result_id, owner_user_id)
        if courseware_result is None:
            raise AppException(BusinessErrorCode.COURSEWARE_RESULT_NOT_FOUND, "课件结果不存在")
        self.refresh_remote_state(courseware_result)
        self.session.commit()
        self.session.refresh(courseware_result)
        return CoursewareResultDetailResponse(**self.build_courseware_response(courseware_result).model_dump())

    def reply_courseware_result(
        self,
        *,
        owner_user_id: int,
        courseware_result_id: int,
        answer: str,
    ) -> CoursewareResultDetailResponse:
        """回复 Raccoon PPT 补充问题并刷新状态。"""
        courseware_result = self.repository.get_courseware_result_for_owner(courseware_result_id, owner_user_id)
        if courseware_result is None:
            raise AppException(BusinessErrorCode.COURSEWARE_RESULT_NOT_FOUND, "课件结果不存在")
        job_id = self._get_raccoon_job_id(courseware_result)
        state = self.ppt_service.reply_and_short_poll(job_id=job_id, answer=answer)
        self.apply_remote_state(courseware_result, state)
        self.session.commit()
        self.session.refresh(courseware_result)
        return CoursewareResultDetailResponse(**self.build_courseware_response(courseware_result).model_dump())

    def create_remote_courseware_result(
        self,
        *,
        generation_batch_id: int,
        operator_user_id: int | None,
    ) -> tuple[CoursewareResult, RaccoonPptJobState]:
        """基于生成批次创建 Raccoon PPT 课件任务。"""
        context = self.build_generation_context(generation_batch_id)
        prompt = self.build_raccoon_prompt(context)
        state = self.ppt_service.create_job_and_short_poll(
            prompt=prompt,
            role=RACCOON_ROLE,
            scene=RACCOON_SCENE,
            audience=RACCOON_AUDIENCE,
        )
        generation_batch = context["generation_batch"]
        lesson_plan = context["lesson_plan"]
        courseware_result = self.repository.create_courseware_result(
            CoursewareResult(
                generation_batch_id=generation_batch.id,
                lesson_plan_id=lesson_plan.id,
                template_code=RACCOON_TEMPLATE_CODE,
                template_version=RACCOON_TEMPLATE_VERSION,
                result_status=TASK_STATUS_PROCESSING,
                page_count=None,
                page_type_stats_json={},
                structure_json=self.build_structure_json(context, prompt, state, operator_user_id),
                preview_json=self.build_preview_json(state),
                export_file_id=None,
            )
        )
        self.apply_remote_state(courseware_result, state)
        return courseware_result, state

    def refresh_remote_state(self, courseware_result: CoursewareResult) -> RaccoonPptJobState:
        """短轮询并应用远程状态。"""
        job_id = self._get_raccoon_job_id(courseware_result)
        state = self.ppt_service.short_poll_job(job_id)
        self.apply_remote_state(courseware_result, state)
        return state

    def apply_remote_state(self, courseware_result: CoursewareResult, state: RaccoonPptJobState) -> None:
        """将远程任务状态落到课件结果、批次和任务。"""
        normalized_status = state.status.lower()
        courseware_result.preview_json = self.build_preview_json(state)
        courseware_result.structure_json = {
            **(courseware_result.structure_json or {}),
            "raccoon_job": state.model_dump(mode="json"),
        }
        generation_batch = self.repository.get_generation_batch(courseware_result.generation_batch_id)
        task = self.repository.get_courseware_task_by_batch(courseware_result.generation_batch_id)

        if normalized_status == "succeeded":
            if courseware_result.export_file_id is None:
                self.archive_pptx(courseware_result, state)
            courseware_result.result_status = TASK_STATUS_SUCCESS
            if generation_batch is not None:
                generation_batch.batch_status = TASK_STATUS_SUCCESS
                generation_batch.finished_at = DateTimeUtil.now_utc()
                self.repository.save(generation_batch)
            if task is not None:
                task.task_status = TASK_STATUS_SUCCESS
                task.current_stage = "finalize_courseware_result"
                task.progress_percent = 100
                task.result_json = {
                    "generation_batch_id": courseware_result.generation_batch_id,
                    "courseware_result_id": courseware_result.id,
                    "export_file_id": courseware_result.export_file_id,
                    "raccoon_job_id": state.job_id,
                }
                task.finished_at = DateTimeUtil.now_utc()
                self.repository.save(task)
                self._sync_task_steps(
                    task.id,
                    state=state,
                    step_status=TASK_STATUS_SUCCESS,
                    export_file_id=courseware_result.export_file_id,
                )
        elif normalized_status in {"failed", "canceled"}:
            courseware_result.result_status = TASK_STATUS_FAILURE
            if generation_batch is not None:
                generation_batch.batch_status = TASK_STATUS_FAILURE
                generation_batch.finished_at = DateTimeUtil.now_utc()
                self.repository.save(generation_batch)
            if task is not None:
                task.task_status = TASK_STATUS_FAILURE
                task.current_stage = "raccoon_task_failed"
                task.progress_percent = 100
                task.last_error_code = BusinessErrorCode.RACCOON_RESULT_INVALID.value
                task.last_error_message = state.error_message or f"Raccoon PPT 任务状态为 {state.status}"
                task.finished_at = DateTimeUtil.now_utc()
                self.repository.save(task)
                self._sync_task_steps(task.id, state=state, step_status=TASK_STATUS_FAILURE)
        else:
            courseware_result.result_status = TASK_STATUS_PROCESSING
            if generation_batch is not None:
                generation_batch.batch_status = TASK_STATUS_PROCESSING
                self.repository.save(generation_batch)
            if task is not None:
                task.task_status = TASK_STATUS_PROCESSING
                task.current_stage = "waiting_raccoon_result" if normalized_status != "waiting_user_input" else "waiting_user_input"
                task.progress_percent = 80
                task.result_json = {
                    "generation_batch_id": courseware_result.generation_batch_id,
                    "courseware_result_id": courseware_result.id,
                    "raccoon_job_id": state.job_id,
                    "raccoon_status": state.status,
                }
                self.repository.save(task)
                self._sync_task_steps(task.id, state=state, step_status=TASK_STATUS_PROCESSING)

        self.repository.save(courseware_result)

    def archive_pptx(self, courseware_result: CoursewareResult, state: RaccoonPptJobState) -> None:
        """下载 PPTX 并归档到 OBS。"""
        generation_batch = self.repository.get_generation_batch(courseware_result.generation_batch_id)
        if generation_batch is None:
            raise AppException(BusinessErrorCode.GENERATION_BATCH_NOT_FOUND, "生成批次不存在")
        pptx_content = self.ppt_service.download_pptx(state.download_url)
        file_hash = hashlib.sha256(pptx_content).hexdigest()
        filename = f"courseware_{courseware_result.id}.pptx"
        object_key = self.storage_client.build_object_key(
            str(generation_batch.project_id),
            "courseware",
            str(generation_batch.id),
            filename=filename,
        )
        try:
            self.storage_client.upload_bytes(object_key, pptx_content, content_type=PPTX_MIME_TYPE)
        except Exception as exc:  # noqa: BLE001
            raise AppException(BusinessErrorCode.FILE_UPLOAD_FAILED, "课件文件上传失败", {"error": str(exc)}) from exc

        file_object = self.repository.create_file_object(
            FileObject(
                project_id=generation_batch.project_id,
                biz_type=COURSEWARE_EXPORT_BIZ_TYPE,
                bucket_name=self.storage_client.settings.obs_bucket,
                object_key=object_key,
                original_filename=filename,
                file_ext=".pptx",
                mime_type=PPTX_MIME_TYPE,
                file_size=len(pptx_content),
                content_hash=file_hash,
                source_type="raccoon_ppt",
                upload_status="uploaded",
                uploaded_by=generation_batch.created_by,
                metadata_json={"raccoon_job_id": state.job_id, "generation_batch_id": generation_batch.id},
            )
        )
        courseware_result.export_file_id = file_object.id

    def build_generation_context(self, generation_batch_id: int) -> dict[str, Any]:
        """构造课件生成上下文。"""
        generation_batch = self.repository.get_generation_batch(generation_batch_id)
        if generation_batch is None:
            raise AppException(BusinessErrorCode.GENERATION_BATCH_NOT_FOUND, "生成批次不存在")
        if generation_batch.lesson_plan_id is None or generation_batch.curriculum_plan_id is None:
            raise AppException(BusinessErrorCode.GENERATION_BASELINE_INVALID, "生成批次缺少课程大纲或教案")

        project = self.repository.get_project(generation_batch.project_id)
        curriculum_plan = self.repository.get_curriculum_plan(generation_batch.curriculum_plan_id)
        lesson_plan = self.repository.get_lesson_plan(generation_batch.lesson_plan_id)
        profile_version = self.repository.get_learner_profile_version(generation_batch.learner_profile_version_id)
        if project is None:
            raise AppException(BusinessErrorCode.PROJECT_NOT_FOUND, "项目不存在")
        if curriculum_plan is None or curriculum_plan.version_status != VERSION_STATUS_READY:
            raise AppException(BusinessErrorCode.CURRICULUM_PLAN_NOT_FOUND, "课程大纲不存在或不可用")
        if lesson_plan is None or lesson_plan.version_status != VERSION_STATUS_READY:
            raise AppException(BusinessErrorCode.LESSON_PLAN_NOT_FOUND, "教案不存在或不可用")
        if profile_version is None:
            raise AppException(BusinessErrorCode.LEARNER_PROFILE_NOT_FOUND, "学情版本不存在")

        return {
            "project": project,
            "generation_batch": generation_batch,
            "curriculum_plan": curriculum_plan,
            "lesson_plan": lesson_plan,
            "profile_version": profile_version,
            "profile_records": self.repository.list_profile_records(profile_version.id),
            "knowledge_points": self.repository.list_knowledge_points(generation_batch.knowledge_version_id),
            "assessment_blueprint": (
                self.repository.get_assessment_blueprint(generation_batch.assessment_blueprint_id)
                if generation_batch.assessment_blueprint_id
                else None
            ),
            "paper_result": self.repository.get_paper_result_by_batch(generation_batch.id),
        }

    @staticmethod
    def build_raccoon_prompt(context: dict[str, Any]) -> str:
        """构造 Raccoon PPT 生成提示词。"""
        project = context["project"]
        generation_batch = context["generation_batch"]
        curriculum_plan = context["curriculum_plan"]
        lesson_plan = context["lesson_plan"]
        profile_version = context["profile_version"]
        knowledge_points = context["knowledge_points"]
        profile_records = context["profile_records"]
        assessment_blueprint = context["assessment_blueprint"]
        paper_result = context["paper_result"]

        payload = {
            "项目": {
                "名称": project.name,
                "学科": project.subject_code,
                "年级": project.grade_code,
                "适用对象": project.applicable_target,
            },
            "生成要求": {
                "课次": generation_batch.course_count,
                "单次课时分钟": generation_batch.session_duration_minutes,
                "章节范围": generation_batch.chapter_range_json,
                "课件页型": ["封面", "目录", "知识讲解", "例题讲解", "课堂互动", "总结", "课后作业"],
            },
            "课程大纲": {
                "标题": curriculum_plan.plan_title,
                "摘要": curriculum_plan.summary_text,
                "内容": curriculum_plan.content_json,
            },
            "教案": {
                "标题": lesson_plan.lesson_title,
                "摘要": lesson_plan.summary_text,
                "内容": lesson_plan.content_json,
            },
            "学情": {
                "摘要": profile_version.summary_text,
                "画像": [
                    {
                        "学生": record.student_name or record.student_key,
                        "学科": record.subject_code,
                        "分数": float(record.score_value) if record.score_value is not None else None,
                        "优势": record.advantage_tags_json,
                        "薄弱点": record.weakness_tags_json,
                        "能力": record.ability_tags_json,
                        "习惯": record.habit_tags_json,
                        "摘要": record.summary_text,
                    }
                    for record in profile_records
                ],
            },
            "知识点": [
                {
                    "id": point.id,
                    "名称": point.point_name,
                    "重要度": point.importance_level,
                    "难度": point.difficulty_level,
                    "摘要": point.summary_text,
                }
                for point in knowledge_points[:30]
            ],
            "测评": {
                "蓝图": assessment_blueprint.content_json if assessment_blueprint is not None else None,
                "试卷": paper_result.paper_json if paper_result is not None else None,
            },
        }
        return (
            "请基于以下结构化教学材料，生成一份可直接用于课堂授课的中文 PPTX 课件。"
            "课件要逻辑清晰、页面标题明确、每页信息密度适合学生课堂学习；"
            "请覆盖封面、目录、核心知识讲解、例题、互动练习、总结和课后作业。"
            "请不要输出解释文字，只生成课件。\n\n"
            f"{json.dumps(payload, ensure_ascii=False)}"
        )

    @staticmethod
    def build_structure_json(
        context: dict[str, Any],
        prompt: str,
        state: RaccoonPptJobState,
        operator_user_id: int | None,
    ) -> dict[str, Any]:
        """构造课件结构与生成摘要。"""
        generation_batch = context["generation_batch"]
        lesson_plan = context["lesson_plan"]
        return {
            "generator": "raccoon_ppt",
            "role": RACCOON_ROLE,
            "scene": RACCOON_SCENE,
            "audience": RACCOON_AUDIENCE,
            "prompt_text": prompt,
            "prompt_summary": {
                "generation_batch_id": generation_batch.id,
                "lesson_plan_id": lesson_plan.id,
                "knowledge_version_id": generation_batch.knowledge_version_id,
                "learner_profile_version_id": generation_batch.learner_profile_version_id,
                "operator_user_id": operator_user_id,
            },
            "raccoon_job": state.model_dump(mode="json"),
        }

    @staticmethod
    def build_preview_json(state: RaccoonPptJobState) -> dict[str, Any]:
        """构造课件远程任务预览状态。"""
        return {
            "raccoon_job_id": state.job_id,
            "raccoon_status": state.status,
            "download_url": state.download_url,
            "required_user_input": state.required_user_input,
            "error_message": state.error_message,
            "raw_payload": state.raw_payload,
            "refreshed_at": DateTimeUtil.to_isoformat(DateTimeUtil.now_utc()),
        }

    @staticmethod
    def build_courseware_response(courseware_result: CoursewareResult) -> CoursewareResultListItemResponse:
        """构造课件结果响应。"""
        return CoursewareResultListItemResponse.model_validate(courseware_result, from_attributes=True)

    def _sync_task_steps(
        self,
        task_record_id: int,
        *,
        state: RaccoonPptJobState,
        step_status: str,
        export_file_id: int | None = None,
    ) -> None:
        """同步刷新接口触发后的课件任务步骤状态。"""
        now = DateTimeUtil.now_utc()
        if step_status == TASK_STATUS_SUCCESS:
            self._mark_task_step(
                task_record_id,
                "poll_raccoon_ppt_job",
                TASK_STATUS_SUCCESS,
                100,
                detail_json={"raccoon_status": state.status, "raccoon_job_id": state.job_id},
                started_at=now,
                finished_at=now,
            )
            self._mark_task_step(
                task_record_id,
                "archive_courseware_result",
                TASK_STATUS_SUCCESS,
                100,
                detail_json={"export_file_id": export_file_id},
                started_at=now,
                finished_at=now,
            )
            self._mark_task_step(
                task_record_id,
                "finalize_generation_batch",
                TASK_STATUS_SUCCESS,
                100,
                detail_json={"batch_status": TASK_STATUS_SUCCESS},
                started_at=now,
                finished_at=now,
            )
            return

        if step_status == TASK_STATUS_FAILURE:
            self._mark_task_step(
                task_record_id,
                "poll_raccoon_ppt_job",
                TASK_STATUS_FAILURE,
                100,
                detail_json={"raccoon_status": state.status, "error": state.error_message},
                started_at=now,
                finished_at=now,
            )
            return

        self._mark_task_step(
            task_record_id,
            "poll_raccoon_ppt_job",
            TASK_STATUS_PROCESSING,
            80,
            detail_json={
                "raccoon_status": state.status,
                "raccoon_job_id": state.job_id,
                "required_user_input": state.required_user_input,
            },
            started_at=now,
        )

    def _mark_task_step(
        self,
        task_record_id: int,
        step_code: str,
        step_status: str,
        progress_percent: int,
        *,
        detail_json: dict[str, Any] | None = None,
        started_at=None,
        finished_at=None,
    ) -> None:
        """更新课件任务步骤状态。"""
        step = self.repository.get_task_step(task_record_id, step_code)
        if step is None:
            return
        step.step_status = step_status
        step.progress_percent = progress_percent
        if detail_json is not None:
            step.detail_json = detail_json
        if started_at is not None:
            step.started_at = step.started_at or started_at
        if finished_at is not None:
            step.finished_at = finished_at
        self.repository.save(step)

    @staticmethod
    def _get_raccoon_job_id(courseware_result: CoursewareResult) -> str:
        preview_json = courseware_result.preview_json or {}
        job_id = preview_json.get("raccoon_job_id")
        if not job_id:
            raise AppException(BusinessErrorCode.RACCOON_RESULT_INVALID, "课件结果缺少 Raccoon 任务ID")
        return str(job_id)
