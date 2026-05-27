"""
@Date: 2026-05-04
@Author: xisy
@Discription: 覆盖率分析模块业务服务
"""

import json
from collections import defaultdict
from typing import Any

from sqlalchemy.orm import Session

from app.core.constants import (
    COVERAGE_ANALYZE_TASK_TYPE,
    COVERAGE_MODULE_CODE,
    GENERATION_QUEUE_NAME,
    TASK_STATUS_PENDING,
    TASK_STATUS_SUCCESS,
)
from app.core.exceptions import AppException, BusinessErrorCode
from app.modules.assessment.presets import ASSESSMENT_SCENE_PRESETS, resolve_assessment_strategy
from app.modules.coverage.repository import CoverageRepository
from app.modules.coverage.schemas import CoverageReportDetailResponse, CoverageReportListItemResponse
from app.modules.p0_models import (
    ChapterNode,
    CoverageReport,
    GenerationBatch,
    GenerationTrace,
    KnowledgeEvidence,
    KnowledgePoint,
    LearnerProfileRecord,
    Project,
)
from app.modules.task_center.repository import TaskCenterRepository
from app.shared.question_basis import build_assessment_position
from app.shared.queue import dispatch_task
from app.shared.utils import DateTimeUtil, safe_int
from app.shared.utils.chapter_range_util import build_chapter_range_selection, filter_knowledge_points_by_chapter_selection

COVERAGE_REFERENCE_KEYS = {
    "knowledge_point_id",
    "knowledge_point_ids",
    "knowledge_point_refs",
    "coverage_knowledge_points",
}
QUESTION_TYPE_KEYS = ("single_choice", "fill_blank", "short_answer")
DIFFICULTY_LEVEL_KEYS = ("1", "2", "3", "4", "5")
ARTIFACT_BUCKETS = {
    "curriculum_plan": "课程大纲",
    "lesson_plan": "教案",
    "question_item": "试卷题目",
    "homework_question": "作业题目",
    "courseware_slide": "课件页面",
}
CLOSURE_ARTIFACT_TYPES = (
    "curriculum_plan",
    "lesson_plan",
    "courseware_slide",
    "question_item",
    "homework_question",
)
DIFFICULTY_BAND_ORDER = ("基础掌握题", "典型应用题", "综合提升题")
DIFFICULTY_BAND_LEVELS = {
    "基础掌握题": [1, 2],
    "典型应用题": [3],
    "综合提升题": [4, 5],
}
SCENE_ORDER = {"homework": 0, "unit_test": 1, "final_exam": 2}
STEM_EXCERPT_LIMIT = 80


class CoverageService:
    """覆盖率分析模块服务。"""

    def __init__(self, session: Session, repository: CoverageRepository | None = None) -> None:
        self.session = session
        self.repository = repository or CoverageRepository(session)
        self.task_repository = TaskCenterRepository(session)

    def list_coverage_reports(
        self,
        *,
        owner_user_id: int,
        generation_batch_id: int,
        page: int,
        page_size: int,
    ) -> tuple[list[CoverageReportListItemResponse], int]:
        """分页查询覆盖率报告。"""
        generation_batch = self.repository.get_generation_batch_for_owner(generation_batch_id, owner_user_id)
        if generation_batch is None:
            raise AppException(BusinessErrorCode.GENERATION_BATCH_NOT_FOUND, "生成批次不存在")
        offset = (page - 1) * page_size
        reports = self.repository.list_coverage_reports_for_owner(
            owner_user_id,
            generation_batch_id=generation_batch_id,
            offset=offset,
            limit=page_size,
        )
        total_count = self.repository.count_coverage_reports_for_owner(
            owner_user_id,
            generation_batch_id=generation_batch_id,
        )
        return [self.build_coverage_report_response(report) for report in reports], total_count

    def get_coverage_report_detail(
        self,
        *,
        owner_user_id: int,
        coverage_report_id: int,
    ) -> CoverageReportDetailResponse:
        """查询覆盖率报告详情。"""
        report = self.repository.get_coverage_report_for_owner(coverage_report_id, owner_user_id)
        if report is None:
            raise AppException(BusinessErrorCode.COVERAGE_REPORT_NOT_FOUND, "覆盖率报告不存在")
        return CoverageReportDetailResponse(**self.build_coverage_report_response(report).model_dump())

    def refresh_coverage_report(
        self,
        *,
        owner_user_id: int,
        generation_batch_id: int,
    ) -> CoverageReportDetailResponse:
        """重新分析并刷新指定批次的覆盖率报告。"""
        generation_batch = self.repository.get_generation_batch_for_owner(generation_batch_id, owner_user_id)
        if generation_batch is None:
            raise AppException(BusinessErrorCode.GENERATION_BATCH_NOT_FOUND, "生成批次不存在")
        report = self.refresh_coverage_report_by_batch(generation_batch_id)
        self.session.commit()
        self.session.refresh(report)
        return CoverageReportDetailResponse(**self.build_coverage_report_response(report).model_dump())

    def refresh_coverage_report_by_batch(self, generation_batch_id: int) -> CoverageReport:
        """按批次同步重算覆盖率报告，供按需成果物生成后刷新。"""
        payload = self.build_coverage_payload(generation_batch_id)
        report = self.create_coverage_report(generation_batch_id, payload)
        self.write_generation_traces(report, payload["trace_metadata"])
        return report

    def create_coverage_task_if_needed(
        self,
        *,
        generation_batch_id: int,
        operator_user_id: int | None,
        request_id: str | None,
    ):
        """按批次幂等创建覆盖率分析任务。"""
        generation_batch = self.repository.get_generation_batch(generation_batch_id)
        if generation_batch is None:
            raise AppException(BusinessErrorCode.GENERATION_BATCH_NOT_FOUND, "生成批次不存在")
        if self.repository.get_coverage_report_by_batch(generation_batch_id) is not None:
            return None
        existing_task = self.repository.get_existing_coverage_task(generation_batch_id)
        if existing_task is not None:
            return None

        task = self.task_repository.create_task(
            project_id=generation_batch.project_id,
            generation_batch_id=generation_batch.id,
            module_code=COVERAGE_MODULE_CODE,
            task_type=COVERAGE_ANALYZE_TASK_TYPE,
            task_status=TASK_STATUS_PENDING,
            queue_name=GENERATION_QUEUE_NAME,
            biz_key=f"generation_batch:{generation_batch.id}:coverage",
            operator_user_id=operator_user_id,
            payload_json={"generation_batch_id": generation_batch.id},
            request_id=request_id,
        )
        step_names = [
            ("prepare_coverage_baseline", "准备覆盖率分析基线"),
            ("collect_artifact_refs", "收集成果物知识点引用"),
            ("persist_coverage_report", "落库覆盖率报告"),
            ("write_generation_trace", "写入生成追溯"),
            ("finalize_generation_batch", "完成生成批次"),
        ]
        for step_order, (step_code, step_name) in enumerate(step_names, start=1):
            self.task_repository.create_task_step(
                task_record_id=task.id,
                step_code=step_code,
                step_name=step_name,
                step_order=step_order,
                step_status=TASK_STATUS_PENDING,
            )
        return task

    def build_coverage_payload(self, generation_batch_id: int) -> dict[str, Any]:
        """构造覆盖率报告内容。"""
        generation_batch = self.repository.get_generation_batch(generation_batch_id)
        if generation_batch is None:
            raise AppException(BusinessErrorCode.GENERATION_BATCH_NOT_FOUND, "生成批次不存在")

        all_knowledge_points = self.repository.list_knowledge_points(generation_batch.knowledge_version_id)
        if not all_knowledge_points:
            raise AppException(BusinessErrorCode.GENERATION_BASELINE_INVALID, "知识版本缺少知识点，无法分析覆盖率")
        chapters = self.repository.list_chapter_nodes(generation_batch.knowledge_version_id)
        chapter_selection = build_chapter_range_selection(
            chapters=chapters,
            chapter_range_json=generation_batch.chapter_range_json,
        )
        knowledge_points = filter_knowledge_points_by_chapter_selection(
            knowledge_points=all_knowledge_points,
            selection=chapter_selection,
        )
        knowledge_scope = {
            "chapter_range_scoped": chapter_selection.is_scoped,
            "requested_chapter_ids": chapter_selection.requested_chapter_ids,
            "effective_chapter_ids": chapter_selection.effective_chapter_ids,
            "total_knowledge_version_point_count": len(all_knowledge_points),
            "scoped_knowledge_point_count": len(knowledge_points),
        }

        chapter_map = {chapter.id: chapter for chapter in chapters}
        knowledge_point_map = {point.id: point for point in knowledge_points}
        valid_ids = set(knowledge_point_map)
        knowledge_evidences = self.repository.list_knowledge_evidence_by_point_ids(list(valid_ids))
        best_evidence_by_point = _select_best_evidence_by_point_id(knowledge_evidences)
        knowledge_point_summaries = _build_knowledge_point_summaries(
            knowledge_points=knowledge_points,
            chapter_map=chapter_map,
            evidence_map=best_evidence_by_point,
        )
        project = self.repository.get_project(generation_batch.project_id)
        profile_records = self.repository.list_learner_profile_records(generation_batch.learner_profile_version_id)
        learner_profile_alignment = _build_learner_profile_alignment(
            generation_batch=generation_batch,
            project=project,
            profile_records=profile_records,
        )
        weakness_tags = learner_profile_alignment.get("weakness_tags", [])
        if not isinstance(weakness_tags, list):
            weakness_tags = []
        important_ids = {
            point.id
            for point in knowledge_points
            if point.importance_level is not None and int(point.importance_level) >= 4
        }
        artifacts = self._collect_artifact_references(generation_batch_id)
        artifact_coverage = _init_artifact_coverage()
        artifact_valid_sets: dict[str, set[int]] = {artifact_type: set() for artifact_type in ARTIFACT_BUCKETS}
        artifact_invalid_sets: dict[str, set[int]] = {artifact_type: set() for artifact_type in ARTIFACT_BUCKETS}
        reference_counter: dict[int, int] = defaultdict(int)
        artifact_names_by_point: dict[int, set[str]] = defaultdict(set)
        artifact_reference_counts_by_point: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        warnings: list[dict[str, Any]] = []

        for artifact in artifacts:
            artifact_type = artifact["artifact_type"]
            refs = artifact["knowledge_point_ids"]
            valid_refs = [point_id for point_id in refs if point_id in valid_ids]
            invalid_refs = sorted({point_id for point_id in refs if point_id not in valid_ids})
            for point_id in valid_refs:
                reference_counter[point_id] += 1
                artifact_names_by_point[point_id].add(artifact_type)
                artifact_reference_counts_by_point[point_id][artifact_type] += 1
            artifact_coverage.setdefault(artifact_type, _build_empty_artifact_bucket(artifact_type))
            artifact_valid_sets.setdefault(artifact_type, set()).update(valid_refs)
            artifact_invalid_sets.setdefault(artifact_type, set()).update(invalid_refs)
            artifact_coverage[artifact_type]["reference_count"] += len(refs)
            artifact_coverage[artifact_type]["items"].append(
                _build_artifact_coverage_item(
                    artifact=artifact,
                    valid_refs=valid_refs,
                    invalid_refs=invalid_refs,
                )
            )
            if invalid_refs:
                warnings.append(_build_invalid_reference_warning(artifact, invalid_refs))

        for artifact_type, bucket in artifact_coverage.items():
            bucket["covered_knowledge_point_ids"] = sorted(artifact_valid_sets.get(artifact_type, set()))
            bucket["invalid_knowledge_point_ids"] = sorted(artifact_invalid_sets.get(artifact_type, set()))
            bucket["item_count"] = len(bucket["items"])

        assessment_quality, assessment_quality_v2, assessment_warnings = _build_assessment_quality(artifacts)
        warnings.extend(assessment_warnings)

        covered_ids = sorted(reference_counter)
        uncovered_ids = sorted(valid_ids - set(covered_ids))
        duplicate_ids = sorted(point_id for point_id, count in reference_counter.items() if count > 1)
        important_covered_ids = sorted(important_ids & set(covered_ids))
        coverage_rate = round(len(covered_ids) / len(valid_ids) * 100, 2)
        important_rate = round(len(important_covered_ids) / len(important_ids) * 100, 2) if important_ids else 100.0
        knowledge_point_coverage_matrix = _build_knowledge_point_coverage_matrix(
            knowledge_points=knowledge_points,
            summaries=knowledge_point_summaries,
            artifact_reference_counts_by_point=artifact_reference_counts_by_point,
        )
        matrix_by_point = {
            row["knowledge_point_id"]: row
            for row in knowledge_point_coverage_matrix
        }
        uncovered_knowledge_points = _build_uncovered_knowledge_points(
            uncovered_ids=uncovered_ids,
            summaries=knowledge_point_summaries,
            matrix_by_point=matrix_by_point,
        )
        artifact_gap_analysis = _build_artifact_gap_analysis(
            artifact_coverage=artifact_coverage,
            total_knowledge_point_count=len(valid_ids),
        )
        action_suggestions = _build_action_suggestions(
            matrix_rows=knowledge_point_coverage_matrix,
            summaries=knowledge_point_summaries,
            weakness_tags=weakness_tags,
        )

        if uncovered_ids:
            warnings.append(_build_uncovered_warning(uncovered_ids, knowledge_point_summaries))
        if important_ids and important_rate < 100:
            warnings.append(
                {
                    "code": "IMPORTANT_KNOWLEDGE_POINTS_UNCOVERED",
                    "severity": "warning",
                    "title": "存在未覆盖重点知识点",
                    "message": "存在未覆盖重点知识点",
                    "knowledge_point_ids": sorted(important_ids - set(important_covered_ids)),
                    "knowledge_points": _build_warning_knowledge_points(
                        sorted(important_ids - set(important_covered_ids)),
                        knowledge_point_summaries,
                    ),
                }
            )

        generated_at = DateTimeUtil.to_isoformat(DateTimeUtil.now_utc())
        important_coverage = {
            "total_count": len(important_ids),
            "covered_count": len(important_covered_ids),
            "coverage_rate": important_rate,
            "covered_knowledge_point_ids": important_covered_ids,
            "uncovered_knowledge_point_ids": sorted(important_ids - set(important_covered_ids)),
        }
        report_json = {
            "total_knowledge_point_count": len(valid_ids),
            "covered_knowledge_point_ids": covered_ids,
            "uncovered_knowledge_point_ids": uncovered_ids,
            "duplicate_knowledge_point_ids": duplicate_ids,
            "important_knowledge_point_coverage": important_coverage,
            "artifact_coverage": artifact_coverage,
            "assessment_quality": assessment_quality,
            "knowledge_point_summaries": knowledge_point_summaries,
            "uncovered_knowledge_points": uncovered_knowledge_points,
            "knowledge_point_coverage_matrix": knowledge_point_coverage_matrix,
            "artifact_gap_analysis": artifact_gap_analysis,
            "assessment_quality_v2": assessment_quality_v2,
            "learner_profile_alignment": learner_profile_alignment,
            "action_suggestions": action_suggestions,
            "knowledge_scope": knowledge_scope,
            "warnings": warnings,
            "generated_at": generated_at,
        }
        summary_json = {
            "total_count": len(valid_ids),
            "covered_count": len(covered_ids),
            "uncovered_count": len(uncovered_ids),
            "coverage_rate": coverage_rate,
            "warning_count": len(warnings),
            "important_total_count": len(important_ids),
            "important_covered_count": len(important_covered_ids),
            "important_coverage_rate": important_rate,
            "assessment_quality": assessment_quality,
            "knowledge_scope": knowledge_scope,
        }
        trace_metadata = {
            point_id: {
                "artifact_types": sorted(artifact_names_by_point[point_id]),
                "reference_count": reference_counter[point_id],
                "is_important": point_id in important_ids,
                "point_name": knowledge_point_map[point_id].point_name,
            }
            for point_id in covered_ids
        }
        return {
            "coverage_rate": coverage_rate,
            "warning_count": len(warnings),
            "coverage_summary_json": summary_json,
            "report_json": report_json,
            "trace_metadata": trace_metadata,
        }

    def create_coverage_report(self, generation_batch_id: int, payload: dict[str, Any]) -> CoverageReport:
        """创建或更新覆盖率报告。"""
        existing_report = self.repository.get_coverage_report_by_batch(generation_batch_id)
        if existing_report is not None:
            existing_report.report_status = TASK_STATUS_SUCCESS
            existing_report.coverage_rate = payload["coverage_rate"]
            existing_report.warning_count = payload["warning_count"]
            existing_report.coverage_summary_json = payload["coverage_summary_json"]
            existing_report.report_json = payload["report_json"]
            self.repository.save(existing_report)
            return existing_report
        return self.repository.create_coverage_report(
            CoverageReport(
                generation_batch_id=generation_batch_id,
                report_status=TASK_STATUS_SUCCESS,
                coverage_rate=payload["coverage_rate"],
                warning_count=payload["warning_count"],
                coverage_summary_json=payload["coverage_summary_json"],
                report_json=payload["report_json"],
                export_file_id=None,
            )
        )

    def write_generation_traces(self, report: CoverageReport, trace_metadata: dict[int, dict[str, Any]]) -> None:
        """写入覆盖率报告的轻量来源追溯。"""
        self.repository.delete_generation_traces_for_report(report.id)
        for rank, (point_id, metadata) in enumerate(sorted(trace_metadata.items()), start=1):
            self.repository.create_generation_trace(
                GenerationTrace(
                    generation_batch_id=report.generation_batch_id,
                    trace_type="coverage",
                    target_type="coverage_report",
                    target_id=report.id,
                    source_type="knowledge_point",
                    source_id=str(point_id),
                    source_rank=rank,
                    source_score=None,
                    evidence_text=metadata.get("point_name"),
                    metadata_json={**metadata, "coverage_report_id": report.id},
                )
            )

    def _collect_artifact_references(self, generation_batch_id: int) -> list[dict[str, Any]]:
        """收集批次内成果物的知识点引用。"""
        generation_batch = self.repository.get_generation_batch(generation_batch_id)
        if generation_batch is None:
            return []

        artifacts: list[dict[str, Any]] = []
        curriculum_plan = self.repository.get_curriculum_plan(generation_batch.curriculum_plan_id)
        lesson_plans = self.repository.list_lesson_plans_by_batch(generation_batch_id)
        lesson_plan_map = {lesson_plan.id: lesson_plan for lesson_plan in lesson_plans}
        paper_results = self.repository.list_paper_results_by_batch(generation_batch_id)
        paper_result_map = {paper_result.id: paper_result for paper_result in paper_results}
        question_items = self.repository.list_question_items_by_batch(generation_batch_id)
        homework_results = self.repository.list_homework_results_by_batch(generation_batch_id)
        homework_result_map = {homework_result.id: homework_result for homework_result in homework_results}
        homework_questions = self.repository.list_homework_questions_by_batch(generation_batch_id)
        courseware_results = self.repository.list_courseware_results_by_batch(generation_batch_id)

        if curriculum_plan is not None:
            artifacts.append(
                self._build_artifact_reference(
                    "curriculum_plan",
                    curriculum_plan.id,
                    curriculum_plan.content_json,
                    {
                        "curriculum_plan_id": curriculum_plan.id,
                        "title": curriculum_plan.plan_title,
                    },
                )
            )
        for lesson_plan in lesson_plans:
            artifacts.append(
                self._build_artifact_reference(
                    "lesson_plan",
                    lesson_plan.id,
                    lesson_plan.content_json,
                    {
                        "lesson_plan_id": lesson_plan.id,
                        "class_session_no": lesson_plan.class_session_no,
                        "title": lesson_plan.lesson_title,
                    },
                )
            )
        for question in question_items:
            paper_result = paper_result_map.get(question.paper_result_id)
            scene_type = paper_result.scene_type if paper_result is not None else None
            strategy = _safe_resolve_assessment_strategy(scene_type)
            difficulty_band = build_assessment_position(question.difficulty_level)
            artifacts.append(
                {
                    "artifact_type": "question_item",
                    "artifact_id": question.id,
                    "knowledge_point_ids": _normalize_id_values(question.knowledge_point_id),
                    "metadata": {
                        "question_item_id": question.id,
                        "paper_result_id": question.paper_result_id,
                        "source_type": "paper_result",
                        "source_id": question.paper_result_id,
                        "question_no": question.question_no,
                        "question_type": question.question_type,
                        "difficulty_level": question.difficulty_level,
                        "difficulty_band": difficulty_band,
                        "scene_type": scene_type,
                        "scene_label": strategy.get("scene_label") if strategy else _build_scene_label(scene_type),
                        "difficulty_range": strategy.get("difficulty_range") if strategy else None,
                        "expected_band_range": _build_expected_band_range(
                            strategy.get("difficulty_range") if strategy else None
                        ),
                        "stem_excerpt": _build_text_excerpt(question.stem_text),
                    },
                }
            )
        homework_strategy = _safe_resolve_assessment_strategy("homework")
        for question in homework_questions:
            homework_result = homework_result_map.get(question.homework_result_id)
            lesson_plan = lesson_plan_map.get(question.lesson_plan_id)
            difficulty_band = build_assessment_position(question.difficulty_level)
            artifacts.append(
                {
                    "artifact_type": "homework_question",
                    "artifact_id": question.id,
                    "knowledge_point_ids": _normalize_id_values(question.knowledge_point_id),
                    "metadata": {
                        "homework_question_id": question.id,
                        "homework_result_id": question.homework_result_id,
                        "source_type": "homework_result",
                        "source_id": question.homework_result_id,
                        "lesson_plan_id": question.lesson_plan_id,
                        "class_session_no": lesson_plan.class_session_no if lesson_plan else None,
                        "lesson_title": lesson_plan.lesson_title if lesson_plan else None,
                        "homework_title": homework_result.title if homework_result else None,
                        "question_no": question.question_no,
                        "question_type": question.question_type,
                        "difficulty_level": question.difficulty_level,
                        "difficulty_band": difficulty_band,
                        "scene_type": "homework",
                        "scene_label": (
                            homework_strategy.get("scene_label")
                            if homework_strategy
                            else _build_scene_label("homework")
                        ),
                        "difficulty_range": homework_strategy.get("difficulty_range") if homework_strategy else None,
                        "expected_band_range": _build_expected_band_range(
                            homework_strategy.get("difficulty_range") if homework_strategy else None
                        ),
                        "stem_excerpt": _build_text_excerpt(question.stem_text),
                    },
                }
            )
        for courseware_result in courseware_results:
            structure_json = courseware_result.structure_json or {}
            deck = structure_json.get("deck") if isinstance(structure_json, dict) else None
            slides = deck.get("slides") if isinstance(deck, dict) else None
            if not isinstance(slides, list):
                continue
            for slide_index, slide in enumerate(slides, start=1):
                if not isinstance(slide, dict):
                    continue
                slide_no = safe_int(slide.get("slide_no"), default=slide_index)
                artifacts.append(
                    {
                        "artifact_type": "courseware_slide",
                        "artifact_id": courseware_result.id,
                        "knowledge_point_ids": _normalize_id_values(slide.get("knowledge_point_refs")),
                        "metadata": {
                            "courseware_result_id": courseware_result.id,
                            "lesson_plan_id": courseware_result.lesson_plan_id,
                            "slide_no": slide_no,
                            "slide_type": slide.get("slide_type"),
                            "title": slide.get("title"),
                        },
                    }
                )
        return artifacts

    @staticmethod
    def _build_artifact_reference(
        artifact_type: str,
        artifact_id: int,
        payload: Any,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """构造成果物引用摘要。"""
        return {
            "artifact_type": artifact_type,
            "artifact_id": artifact_id,
            "knowledge_point_ids": _extract_knowledge_point_ids(payload),
            "metadata": metadata or {},
        }

    @staticmethod
    def build_coverage_report_response(report: CoverageReport) -> CoverageReportListItemResponse:
        """构造覆盖率报告响应。"""
        return CoverageReportListItemResponse.model_validate(report, from_attributes=True)


def dispatch_coverage_task_if_needed(
    *,
    session: Session,
    generation_batch_id: int,
    operator_user_id: int | None,
    request_id: str | None,
):
    """幂等创建并投递覆盖率分析任务。"""
    service = CoverageService(session)
    task = service.create_coverage_task_if_needed(
        generation_batch_id=generation_batch_id,
        operator_user_id=operator_user_id,
        request_id=request_id,
    )
    if task is None:
        session.commit()
        return None

    session.commit()
    dispatch_result = dispatch_task(
        "app.modules.coverage.tasks.run_analyze_coverage_task",
        {
            "task_record_id": task.id,
            "generation_batch_id": generation_batch_id,
            "operator_user_id": operator_user_id,
        },
        queue=GENERATION_QUEUE_NAME,
        session=session,
    )
    if dispatch_result.worker_task_id:
        task.worker_task_id = dispatch_result.worker_task_id
        service.task_repository.save(task)
        session.commit()
    return task


def _init_artifact_coverage() -> dict[str, dict[str, Any]]:
    """初始化成果物覆盖矩阵。"""
    return {artifact_type: _build_empty_artifact_bucket(artifact_type) for artifact_type in ARTIFACT_BUCKETS}


def _build_empty_artifact_bucket(artifact_type: str) -> dict[str, Any]:
    """构造单类成果物覆盖桶。"""
    return {
        "artifact_type": artifact_type,
        "display_name": ARTIFACT_BUCKETS.get(artifact_type, artifact_type),
        "item_count": 0,
        "reference_count": 0,
        "covered_knowledge_point_ids": [],
        "invalid_knowledge_point_ids": [],
        "items": [],
    }


def _build_artifact_coverage_item(
    *,
    artifact: dict[str, Any],
    valid_refs: list[int],
    invalid_refs: list[int],
) -> dict[str, Any]:
    """构造成果物覆盖矩阵中的单条明细。"""
    refs = artifact["knowledge_point_ids"]
    return {
        "artifact_id": artifact["artifact_id"],
        **(artifact.get("metadata") or {}),
        "reference_count": len(refs),
        "knowledge_point_ids": refs,
        "valid_knowledge_point_ids": sorted(set(valid_refs)),
        "invalid_knowledge_point_ids": invalid_refs,
    }


def _build_invalid_reference_warning(artifact: dict[str, Any], invalid_refs: list[int]) -> dict[str, Any]:
    """构造成果物非法知识点引用告警。"""
    warning = {
        "code": "INVALID_KNOWLEDGE_POINT_REF",
        "severity": "warning",
        "title": "成果物包含非法知识点引用",
        "message": "成果物包含不属于当前覆盖范围或知识版本的知识点引用",
        "artifact_type": artifact["artifact_type"],
        "artifact_id": artifact["artifact_id"],
        "knowledge_point_ids": invalid_refs,
    }
    warning.update(artifact.get("metadata") or {})
    return warning


def _select_best_evidence_by_point_id(evidences: list[KnowledgeEvidence]) -> dict[int, KnowledgeEvidence]:
    """按知识点选择最优教材证据。"""
    best: dict[int, KnowledgeEvidence] = {}
    for evidence in evidences:
        current = best.get(evidence.knowledge_point_id)
        if current is None or _is_better_evidence(evidence, current):
            best[evidence.knowledge_point_id] = evidence
    return best


def _is_better_evidence(candidate: KnowledgeEvidence, current: KnowledgeEvidence) -> bool:
    """判断候选证据是否优于当前证据。"""
    candidate_score = _to_optional_float(candidate.score_value)
    current_score = _to_optional_float(current.score_value)
    candidate_rank = candidate_score if candidate_score is not None else -1.0
    current_rank = current_score if current_score is not None else -1.0
    if candidate_rank != current_rank:
        return candidate_rank > current_rank
    return candidate.id < current.id


def _build_knowledge_point_summaries(
    *,
    knowledge_points: list[KnowledgePoint],
    chapter_map: dict[int, ChapterNode],
    evidence_map: dict[int, KnowledgeEvidence],
) -> dict[str, dict[str, Any]]:
    """构造知识点可读摘要索引。"""
    summaries: dict[str, dict[str, Any]] = {}
    for point in knowledge_points:
        chapter = chapter_map.get(point.chapter_node_id) if point.chapter_node_id is not None else None
        summaries[str(point.id)] = {
            "id": point.id,
            "point_name": point.point_name,
            "point_code": point.point_code,
            "point_type": point.point_type,
            "chapter_node_id": point.chapter_node_id,
            "chapter_title": chapter.title if chapter is not None else None,
            "chapter_page_range": _build_chapter_page_range(chapter),
            "importance_level": point.importance_level,
            "is_important": point.importance_level is not None and int(point.importance_level) >= 4,
            "difficulty_level": point.difficulty_level,
            "difficulty_band": build_assessment_position(point.difficulty_level),
            "mastery_level_hint": point.mastery_level_hint,
            "tags_json": point.tags_json or {},
            "summary_text": point.summary_text,
            "evidence": _build_evidence_payload(evidence_map.get(point.id)),
        }
    return summaries


def _build_chapter_page_range(chapter: ChapterNode | None) -> str | None:
    """构造章节页码范围展示值。"""
    if chapter is None:
        return None
    if chapter.page_start is None and chapter.page_end is None:
        return None
    if chapter.page_start is None:
        return str(chapter.page_end)
    if chapter.page_end is None or chapter.page_end == chapter.page_start:
        return str(chapter.page_start)
    return f"{chapter.page_start}-{chapter.page_end}"


def _build_evidence_payload(evidence: KnowledgeEvidence | None) -> dict[str, Any] | None:
    """构造教材证据展示字段。"""
    if evidence is None:
        return None
    return {
        "page_no": evidence.page_no,
        "excerpt_text": evidence.excerpt_text,
        "evidence_type": evidence.evidence_type,
        "score_value": _to_optional_float(evidence.score_value),
    }


def _build_knowledge_point_coverage_matrix(
    *,
    knowledge_points: list[KnowledgePoint],
    summaries: dict[str, dict[str, Any]],
    artifact_reference_counts_by_point: dict[int, dict[str, int]],
) -> list[dict[str, Any]]:
    """构造知识点闭环覆盖矩阵。"""
    rows: list[dict[str, Any]] = []
    for point in knowledge_points:
        counts = artifact_reference_counts_by_point.get(point.id, {})
        covered_by = {
            artifact_type: {
                "covered": int(counts.get(artifact_type, 0)) > 0,
                "reference_count": int(counts.get(artifact_type, 0)),
            }
            for artifact_type in CLOSURE_ARTIFACT_TYPES
        }
        summary = summaries[str(point.id)]
        rows.append(
            {
                "knowledge_point_id": point.id,
                "point_name": summary["point_name"],
                "chapter_title": summary["chapter_title"],
                "difficulty_band": summary["difficulty_band"],
                "covered_by": covered_by,
                "closure_status": _resolve_closure_status(covered_by),
                "gap_types": _build_gap_types(covered_by),
            }
        )
    return rows


def _resolve_closure_status(covered_by: dict[str, dict[str, Any]]) -> str:
    """根据矩阵覆盖情况判断资源闭环状态。"""
    has_curriculum = bool(covered_by["curriculum_plan"]["covered"])
    has_lesson = bool(covered_by["lesson_plan"]["covered"])
    has_courseware = bool(covered_by["courseware_slide"]["covered"])
    has_question = bool(covered_by["question_item"]["covered"])
    has_homework = bool(covered_by["homework_question"]["covered"])
    has_assessment = has_question or has_homework
    if not any(item["covered"] for item in covered_by.values()):
        return "no_coverage"
    if has_lesson and has_courseware and has_assessment:
        return "complete_loop"
    if has_assessment and not (has_lesson and has_courseware):
        return "assessment_no_teaching"
    if (has_curriculum or has_lesson) and not has_courseware and not has_assessment:
        return "planning_only"
    if (has_lesson or has_courseware) and not has_assessment:
        return "teaching_no_assessment"
    return "planning_only"


def _build_gap_types(covered_by: dict[str, dict[str, Any]]) -> list[str]:
    """构造闭环缺口类型。"""
    gap_types: list[str] = []
    if not covered_by["curriculum_plan"]["covered"]:
        gap_types.append("not_planned")
    if not covered_by["lesson_plan"]["covered"]:
        gap_types.append("not_taught")
    if not covered_by["courseware_slide"]["covered"]:
        gap_types.append("not_in_courseware")
    if not covered_by["homework_question"]["covered"]:
        gap_types.append("not_practiced")
    if not covered_by["question_item"]["covered"]:
        gap_types.append("not_assessed")
    return gap_types


def _build_uncovered_knowledge_points(
    *,
    uncovered_ids: list[int],
    summaries: dict[str, dict[str, Any]],
    matrix_by_point: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    """构造未覆盖知识点可读明细。"""
    details: list[dict[str, Any]] = []
    for point_id in uncovered_ids:
        summary = summaries[str(point_id)]
        matrix_row = matrix_by_point.get(point_id)
        if matrix_row is None:
            missing_from = list(CLOSURE_ARTIFACT_TYPES)
        else:
            missing_from = [
                artifact_type
                for artifact_type, item in matrix_row["covered_by"].items()
                if not item["covered"]
            ]
        details.append(
            {
                "id": summary["id"],
                "point_name": summary["point_name"],
                "chapter_title": summary["chapter_title"],
                "difficulty_level": summary["difficulty_level"],
                "difficulty_band": summary["difficulty_band"],
                "mastery_level_hint": summary["mastery_level_hint"],
                "evidence": summary["evidence"],
                "missing_from": missing_from,
                "suggested_action": _build_suggested_action(summary, missing_from),
            }
        )
    return details


def _build_uncovered_warning(
    uncovered_ids: list[int],
    summaries: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """构造未覆盖知识点告警。"""
    return {
        "code": "UNCOVERED_KNOWLEDGE_POINTS",
        "severity": "warning",
        "title": "存在未覆盖知识点",
        "message": f"仍有 {len(uncovered_ids)} 个知识点未进入完整资源闭环。",
        "knowledge_point_ids": uncovered_ids,
        "knowledge_points": _build_warning_knowledge_points(uncovered_ids, summaries),
    }


def _build_warning_knowledge_points(
    point_ids: list[int],
    summaries: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """构造告警中的知识点可读摘要。"""
    result: list[dict[str, Any]] = []
    for point_id in point_ids:
        summary = summaries.get(str(point_id))
        if summary is None:
            continue
        result.append(
            {
                "id": summary["id"],
                "point_name": summary["point_name"],
                "chapter_title": summary["chapter_title"],
                "difficulty_band": summary["difficulty_band"],
            }
        )
    return result


def _build_artifact_gap_analysis(
    *,
    artifact_coverage: dict[str, dict[str, Any]],
    total_knowledge_point_count: int,
) -> dict[str, dict[str, Any]]:
    """构造成果物覆盖充分性分析。"""
    analysis: dict[str, dict[str, Any]] = {}
    for artifact_type, bucket in artifact_coverage.items():
        covered_count = len(bucket.get("covered_knowledge_point_ids") or [])
        coverage_rate = (
            round(covered_count / total_knowledge_point_count * 100, 2)
            if total_knowledge_point_count
            else 0.0
        )
        coverage_status = _resolve_coverage_status(coverage_rate)
        has_invalid_refs = bool(bucket.get("invalid_knowledge_point_ids"))
        analysis[artifact_type] = {
            "display_name": bucket.get("display_name") or ARTIFACT_BUCKETS.get(artifact_type, artifact_type),
            "covered_count": covered_count,
            "total_count": total_knowledge_point_count,
            "coverage_rate": coverage_rate,
            "valid_reference_status": "has_invalid_refs" if has_invalid_refs else "valid",
            "coverage_status": coverage_status,
            "gap_summary": _build_artifact_gap_summary(artifact_type, coverage_status),
            "suggestions": _build_artifact_gap_suggestions(artifact_type, coverage_status, has_invalid_refs),
        }
    return analysis


def _resolve_coverage_status(coverage_rate: float) -> str:
    """根据覆盖率判断覆盖充分性。"""
    if coverage_rate <= 0:
        return "missing"
    if coverage_rate < 30:
        return "weak"
    if coverage_rate < 80:
        return "partial"
    return "strong"


def _build_artifact_gap_summary(artifact_type: str, coverage_status: str) -> str:
    """构造成果物覆盖缺口摘要。"""
    display_name = ARTIFACT_BUCKETS.get(artifact_type, artifact_type)
    if coverage_status == "strong":
        return f"{display_name}覆盖较充分，可支撑当前知识范围展示。"
    if coverage_status == "partial":
        return f"{display_name}已覆盖部分知识点，仍需补齐未形成闭环的内容。"
    if coverage_status == "weak":
        return f"{display_name}仅覆盖少量知识点，当前更适合作为局部成果，仍需继续补齐。"
    return f"{display_name}尚未覆盖当前知识范围，需要补充对应成果物。"


def _build_artifact_gap_suggestions(
    artifact_type: str,
    coverage_status: str,
    has_invalid_refs: bool,
) -> list[str]:
    """构造成果物缺口建议。"""
    suggestions: list[str] = []
    if coverage_status in {"missing", "weak", "partial"}:
        if artifact_type == "courseware_slide":
            suggestions.append("继续为未进入课件的知识点补齐 PPT 讲解页。")
        elif artifact_type == "lesson_plan":
            suggestions.append("补齐未进入教案的知识点，保证课堂讲授有明确承接。")
        elif artifact_type == "curriculum_plan":
            suggestions.append("在课程方案中补充对应知识点安排，形成整体规划。")
        elif artifact_type == "homework_question":
            suggestions.append("为基础掌握类知识点补充课后作业题，强化巩固练习。")
        elif artifact_type == "question_item":
            suggestions.append("为典型应用和综合提升类知识点补充测评题，形成考查闭环。")
    if has_invalid_refs:
        suggestions.append("修正成果物中的非法知识点引用，确保只引用当前覆盖范围内知识点。")
    return suggestions


def _build_action_suggestions(
    *,
    matrix_rows: list[dict[str, Any]],
    summaries: dict[str, dict[str, Any]],
    weakness_tags: list[Any],
) -> list[dict[str, Any]]:
    """构造可执行补救建议。"""
    suggestions: list[dict[str, Any]] = []
    for row in matrix_rows:
        if row["closure_status"] == "complete_loop":
            continue
        summary = summaries[str(row["knowledge_point_id"])]
        target_artifact_type = _select_target_artifact_type(row, summary)
        priority = _resolve_suggestion_priority(summary, weakness_tags)
        suggestion: dict[str, Any] = {
            "priority": priority,
            "type": _build_suggestion_type(target_artifact_type),
            "target_artifact_type": target_artifact_type,
            "knowledge_point_id": summary["id"],
            "point_name": summary["point_name"],
            "chapter_title": summary["chapter_title"],
            "suggested_question_band": summary["difficulty_band"],
            "suggested_scene_type": _build_suggested_scene_type(summary["difficulty_band"]),
            "reason": _build_suggestion_reason(row, summary, target_artifact_type),
        }
        suggestions.append(suggestion)
    return suggestions


def _select_target_artifact_type(row: dict[str, Any], summary: dict[str, Any]) -> str:
    """根据闭环缺口选择优先补救成果物。"""
    covered_by = row["covered_by"]
    if not covered_by["lesson_plan"]["covered"]:
        return "lesson_plan"
    if not covered_by["courseware_slide"]["covered"]:
        return "courseware_slide"
    if not covered_by["homework_question"]["covered"] and summary["difficulty_band"] == "基础掌握题":
        return "homework_question"
    if not covered_by["question_item"]["covered"]:
        return "question_item"
    return "homework_question"


def _build_suggestion_type(target_artifact_type: str) -> str:
    """根据目标成果物生成建议类型。"""
    if target_artifact_type == "question_item":
        return "add_assessment_question"
    if target_artifact_type == "homework_question":
        return "add_homework_question"
    if target_artifact_type == "courseware_slide":
        return "add_courseware_slide"
    if target_artifact_type == "lesson_plan":
        return "add_lesson_plan_content"
    return "add_curriculum_plan_content"


def _resolve_suggestion_priority(summary: dict[str, Any], weakness_tags: list[Any]) -> str:
    """根据重要度和学情薄弱点判断建议优先级。"""
    if summary.get("importance_level") is not None and int(summary["importance_level"]) >= 4:
        return "high"
    if _matches_weakness(summary, weakness_tags):
        return "medium"
    return "low"


def _matches_weakness(summary: dict[str, Any], weakness_tags: list[Any]) -> bool:
    """判断知识点是否与学情薄弱标签存在弱匹配。"""
    summary_text = " ".join(
        [
            str(summary.get("point_name") or ""),
            str(summary.get("summary_text") or ""),
            json.dumps(summary.get("tags_json") or {}, ensure_ascii=False),
        ]
    )
    for tag in weakness_tags:
        tag_text = str(tag or "").strip()
        if not tag_text:
            continue
        if tag_text in summary_text or summary["point_name"] in tag_text:
            return True
    return False


def _build_suggested_scene_type(difficulty_band: str) -> str:
    """根据难度语义选择建议测练场景。"""
    if difficulty_band == "基础掌握题":
        return "homework"
    return "final_exam"


def _build_suggestion_reason(
    row: dict[str, Any],
    summary: dict[str, Any],
    target_artifact_type: str,
) -> str:
    """构造补救建议原因。"""
    point_name = summary["point_name"]
    if row["closure_status"] == "no_coverage":
        return f"「{point_name}」未被任何成果物覆盖，建议先补齐教学资源，再补充测练形成闭环。"
    if target_artifact_type == "courseware_slide":
        return f"「{point_name}」已进入教学设计，但缺少 PPT 讲解页支撑课堂呈现。"
    if target_artifact_type in {"question_item", "homework_question"}:
        return f"「{point_name}」已进入教学资源，但尚未通过作业或测评形成学习反馈闭环。"
    return f"「{point_name}」缺少教案承接，建议先补充课堂教学设计。"


def _build_suggested_action(summary: dict[str, Any], missing_from: list[str]) -> str:
    """构造未覆盖知识点的规则化补救动作。"""
    point_name = summary["point_name"]
    difficulty_band = summary["difficulty_band"]
    if difficulty_band == "基础掌握题":
        assessment_text = "课后作业中增加 1 道基础掌握题"
    elif difficulty_band == "典型应用题":
        assessment_text = "期末综合测或单元测中增加 1 道典型应用题"
    else:
        assessment_text = "期末综合测中增加 1 道综合提升题"
    missing_display = "、".join(ARTIFACT_BUCKETS.get(item, item) for item in missing_from)
    return f"「{point_name}」缺少{missing_display}覆盖，建议补充到教案和 PPT 讲解页，并在{assessment_text}。"


def _build_learner_profile_alignment(
    *,
    generation_batch: GenerationBatch,
    project: Project | None,
    profile_records: list[LearnerProfileRecord],
) -> dict[str, Any]:
    """构造学情适配摘要。"""
    subject_code = project.subject_code if project is not None else None
    target_record = _select_target_profile_record(profile_records, subject_code)
    if target_record is None:
        return {"status": "not_available"}
    weakness_tags = [_stringify_json_item(item) for item in _extract_json_items(target_record.weakness_tags_json)]
    ability_tags = [_stringify_json_item(item) for item in _extract_json_items(target_record.ability_tags_json)]
    time_plan_items = [_stringify_json_item(item) for item in _extract_json_items(target_record.time_plan_json)]
    return {
        "status": "available",
        "profile_version_id": generation_batch.learner_profile_version_id,
        "subject_code": target_record.subject_code,
        "score_value": _to_optional_float(target_record.score_value),
        "weakness_tags": weakness_tags,
        "ability_tags": ability_tags,
        "time_plan_items": time_plan_items,
        "summary": target_record.summary_text,
        "assessment_fit_summary": _build_assessment_fit_summary(weakness_tags),
    }


def _select_target_profile_record(
    profile_records: list[LearnerProfileRecord],
    subject_code: str | None,
) -> LearnerProfileRecord | None:
    """优先选择与项目学科匹配的学情记录。"""
    if not profile_records:
        return None
    if subject_code:
        for record in profile_records:
            if record.subject_code == subject_code:
                return record
    return profile_records[0]


def _build_assessment_fit_summary(weakness_tags: list[Any]) -> str:
    """根据薄弱标签生成测练适配摘要。"""
    weakness_text = "、".join(str(item) for item in weakness_tags if str(item).strip())
    if "应用" in weakness_text or "综合" in weakness_text:
        return "测练中应保留基础掌握题巩固基础，同时提高典型应用题占比，用于训练应用题分析能力。"
    if "计算" in weakness_text or "基础" in weakness_text:
        return "测练中应增加基础掌握题和课后作业巩固，帮助学生稳定基础能力。"
    return "测练结构应兼顾基础掌握、典型应用和综合提升，持续贴合学生当前学情。"


def _extract_json_items(value: Any) -> list[Any]:
    """从常见标签 JSON 中提取条目列表。"""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        items = value.get("items")
        if isinstance(items, list):
            return items
        return [value]
    return [value]


def _stringify_json_item(item: Any) -> str:
    """将时间规划条目转为展示字符串。"""
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        for key in ("summary", "content", "text", "plan", "description"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return value
        return json.dumps(item, ensure_ascii=False)
    return str(item)


def _build_assessment_quality(
    artifacts: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    """统计测评 / 作业题型、难度分布并校验难度策略。"""
    question_artifacts = [
        artifact
        for artifact in artifacts
        if artifact["artifact_type"] in {"question_item", "homework_question"}
    ]
    question_type_distribution = {question_type: 0 for question_type in QUESTION_TYPE_KEYS}
    difficulty_distribution = {difficulty_level: 0 for difficulty_level in DIFFICULTY_LEVEL_KEYS}
    global_band_counts = {band: 0 for band in DIFFICULTY_BAND_ORDER}
    strategy_check_map: dict[tuple[Any, Any, Any], dict[str, Any]] = {}
    scene_check_map: dict[str, dict[str, Any]] = {}

    for artifact in question_artifacts:
        metadata = artifact.get("metadata") or {}
        question_type = str(metadata.get("question_type") or "unknown")
        question_type_distribution[question_type] = question_type_distribution.get(question_type, 0) + 1

        difficulty_level = metadata.get("difficulty_level")
        difficulty_key = str(difficulty_level) if difficulty_level is not None else "unknown"
        difficulty_distribution[difficulty_key] = difficulty_distribution.get(difficulty_key, 0) + 1
        difficulty_band = metadata.get("difficulty_band") or build_assessment_position(difficulty_level)
        global_band_counts[difficulty_band] = global_band_counts.get(difficulty_band, 0) + 1

        source_type = str(metadata.get("source_type") or "paper_result")
        source_id = metadata.get("source_id")
        scene_type = str(metadata.get("scene_type") or "unit_test")
        scene_label = metadata.get("scene_label") or _build_scene_label(scene_type)
        difficulty_range = metadata.get("difficulty_range")
        expected_band_range = metadata.get("expected_band_range") or _build_expected_band_range(difficulty_range)
        artifact_id_field = (
            "homework_question_ids" if artifact["artifact_type"] == "homework_question" else "question_item_ids"
        )
        question_id_field = (
            "homework_question_id" if artifact["artifact_type"] == "homework_question" else "question_item_id"
        )
        question_detail_field = (
            "homework_questions" if artifact["artifact_type"] == "homework_question" else "question_items"
        )
        question_detail = _build_question_warning_detail(metadata, question_id_field)
        check_key = (source_type, source_id, scene_type)
        strategy_check = strategy_check_map.setdefault(
            check_key,
            {
                "source_type": source_type,
                "source_id": source_id,
                "scene_type": scene_type,
                "scene_label": scene_label,
                "difficulty_range": difficulty_range,
                "expected_band_range": expected_band_range,
                "question_count": 0,
                "out_of_range_ids": [],
                "out_of_range_details": [],
                "question_id_field": question_id_field,
                "artifact_id_field": artifact_id_field,
                "question_detail_field": question_detail_field,
                "passed": True,
            },
        )
        strategy_check["question_count"] += 1
        if not _is_difficulty_in_range(difficulty_level, difficulty_range):
            strategy_check["out_of_range_ids"].append(metadata.get(question_id_field))
            strategy_check["out_of_range_details"].append(question_detail)

        scene_check = scene_check_map.setdefault(
            scene_type,
            {
                "scene_type": scene_type,
                "scene_label": scene_label,
                "question_count": 0,
                "expected_difficulty_range": difficulty_range,
                "expected_band_range": expected_band_range,
                "difficulty_band_counts": {band: 0 for band in DIFFICULTY_BAND_ORDER},
                "out_of_range_questions": [],
            },
        )
        scene_check["question_count"] += 1
        scene_check["difficulty_band_counts"][difficulty_band] = (
            scene_check["difficulty_band_counts"].get(difficulty_band, 0) + 1
        )
        if not _is_difficulty_in_range(difficulty_level, difficulty_range):
            scene_check["out_of_range_questions"].append(question_detail)

    warnings: list[dict[str, Any]] = []
    strategy_checks_raw = sorted(
        strategy_check_map.values(),
        key=lambda item: (
            str(item["source_type"]),
            0 if item["source_id"] is None else int(item["source_id"]),
            str(item["scene_type"] or ""),
        ),
    )
    strategy_checks: list[dict[str, Any]] = []
    for strategy_check in strategy_checks_raw:
        out_of_range_ids = [
            question_id for question_id in strategy_check["out_of_range_ids"] if question_id is not None
        ]
        question_id_field = strategy_check["question_id_field"]
        artifact_id_field = strategy_check["artifact_id_field"]
        normalized = {
            "source_type": strategy_check["source_type"],
            "source_id": strategy_check["source_id"],
            "scene_type": strategy_check["scene_type"],
            "difficulty_range": strategy_check["difficulty_range"],
            "question_count": strategy_check["question_count"],
            "passed": not out_of_range_ids,
            artifact_id_field: out_of_range_ids,
        }
        strategy_checks.append(normalized)
        if out_of_range_ids:
            warnings.append(
                {
                    "code": "QUESTION_DIFFICULTY_OUT_OF_RANGE",
                    "severity": "warning",
                    "title": "题目难度超出场景预设",
                    "message": (
                        f"{strategy_check['scene_label']}中有 {len(out_of_range_ids)} 道题"
                        "超出预设难度范围。"
                    ),
                    "source_type": strategy_check["source_type"],
                    "source_id": strategy_check["source_id"],
                    "scene_type": strategy_check["scene_type"],
                    "scene_label": strategy_check["scene_label"],
                    "expected_difficulty_range": strategy_check["difficulty_range"],
                    "expected_band_range": strategy_check["expected_band_range"],
                    "difficulty_range": strategy_check["difficulty_range"],
                    strategy_check["question_detail_field"]: strategy_check["out_of_range_details"],
                    artifact_id_field: out_of_range_ids,
                }
            )

    by_scene = []
    for scene_check in sorted(scene_check_map.values(), key=lambda item: SCENE_ORDER.get(item["scene_type"], 99)):
        out_of_range_questions = scene_check["out_of_range_questions"]
        by_scene.append(
            {
                "scene_type": scene_check["scene_type"],
                "scene_label": scene_check["scene_label"],
                "question_count": scene_check["question_count"],
                "expected_difficulty_range": scene_check["expected_difficulty_range"],
                "expected_band_range": scene_check["expected_band_range"],
                "difficulty_band_distribution": _format_band_distribution(
                    scene_check["difficulty_band_counts"],
                    scene_check["question_count"],
                ),
                "passed": not out_of_range_questions,
                "out_of_range_questions": out_of_range_questions,
            }
        )

    return (
        {
            "question_count": len(question_artifacts),
            "question_type_distribution": question_type_distribution,
            "difficulty_distribution": difficulty_distribution,
            "strategy_checks": strategy_checks,
        },
        {
            "question_count": len(question_artifacts),
            "difficulty_band_distribution": _format_band_distribution(
                global_band_counts,
                len(question_artifacts),
            ),
            "by_scene": by_scene,
        },
        warnings,
    )


def _build_question_warning_detail(metadata: dict[str, Any], question_id_field: str) -> dict[str, Any]:
    """构造题目告警可读明细。"""
    return {
        "id": metadata.get(question_id_field),
        "question_no": metadata.get("question_no"),
        "question_type": metadata.get("question_type"),
        "difficulty_level": metadata.get("difficulty_level"),
        "difficulty_band": metadata.get("difficulty_band")
        or build_assessment_position(metadata.get("difficulty_level")),
        "stem_excerpt": metadata.get("stem_excerpt"),
    }


def _format_band_distribution(band_counts: dict[str, int], total_count: int) -> dict[str, dict[str, Any]]:
    """格式化三档难度分布。"""
    distribution: dict[str, dict[str, Any]] = {}
    for band in DIFFICULTY_BAND_ORDER:
        count = int(band_counts.get(band, 0))
        distribution[band] = {
            "count": count,
            "percent": round(count / total_count * 100, 2) if total_count else 0.0,
            "levels": DIFFICULTY_BAND_LEVELS[band],
        }
    return distribution


def _is_difficulty_in_range(difficulty_level: Any, difficulty_range: Any) -> bool:
    """判断题目难度是否落在策略区间。"""
    if not isinstance(difficulty_range, list) or len(difficulty_range) != 2:
        return False
    try:
        difficulty = int(difficulty_level)
        min_difficulty = int(difficulty_range[0])
        max_difficulty = int(difficulty_range[1])
    except (TypeError, ValueError):
        return False
    return min_difficulty <= difficulty <= max_difficulty


def _safe_resolve_assessment_strategy(scene_type: str | None) -> dict[str, Any] | None:
    """解析测评策略，异常时返回空用于报告告警兜底。"""
    try:
        return resolve_assessment_strategy(scene_type)
    except AppException:
        return None


def _build_scene_label(scene_type: str | None) -> str | None:
    """根据场景类型生成展示名称。"""
    if scene_type is None:
        return None
    preset = ASSESSMENT_SCENE_PRESETS.get(str(scene_type))
    if preset is not None:
        return preset["scene_label"]
    return str(scene_type)


def _build_expected_band_range(difficulty_range: Any) -> list[str]:
    """根据难度区间生成预期难度语义范围。"""
    if not isinstance(difficulty_range, list) or len(difficulty_range) != 2:
        return []
    try:
        min_difficulty = int(difficulty_range[0])
        max_difficulty = int(difficulty_range[1])
    except (TypeError, ValueError):
        return []
    bands: list[str] = []
    for level in range(min_difficulty, max_difficulty + 1):
        band = build_assessment_position(level)
        if band not in bands:
            bands.append(band)
    return [band for band in DIFFICULTY_BAND_ORDER if band in bands]


def _build_text_excerpt(value: str | None, limit: int = STEM_EXCERPT_LIMIT) -> str | None:
    """截取题干摘要。"""
    if value is None:
        return None
    normalized = " ".join(str(value).split())
    if len(normalized) <= limit:
        return normalized
    return normalized[:limit] + "..."


def _to_optional_float(value: Any) -> float | None:
    """安全转换可选浮点数。"""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _extract_knowledge_point_ids(payload: Any) -> list[int]:
    """从 JSON 对象中递归提取知识点引用。"""
    result: list[int] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in COVERAGE_REFERENCE_KEYS:
                result.extend(_normalize_id_values(value))
            else:
                result.extend(_extract_knowledge_point_ids(value))
    elif isinstance(payload, list):
        for item in payload:
            result.extend(_extract_knowledge_point_ids(item))
    return result


def _normalize_id_values(value: Any) -> list[int]:
    """将知识点引用字段归一为整数列表。"""
    if isinstance(value, bool):
        return []
    if isinstance(value, int):
        return [value]
    if isinstance(value, str) and value.isdigit():
        return [int(value)]
    if isinstance(value, list):
        ids: list[int] = []
        for item in value:
            ids.extend(_normalize_id_values(item))
        return ids
    return []
