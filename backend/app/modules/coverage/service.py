"""
@Date: 2026-05-04
@Author: xisy
@Discription: 覆盖率分析模块业务服务
"""

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
from app.modules.assessment.presets import resolve_assessment_strategy
from app.modules.coverage.repository import CoverageRepository
from app.modules.coverage.schemas import CoverageReportDetailResponse, CoverageReportListItemResponse
from app.modules.p0_models import CoverageReport, GenerationTrace
from app.modules.task_center.repository import TaskCenterRepository
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
    "courseware_slide": "课件页面",
}


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

        knowledge_point_map = {point.id: point for point in knowledge_points}
        valid_ids = set(knowledge_point_map)
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
        warnings: list[dict[str, Any]] = []

        for artifact in artifacts:
            artifact_type = artifact["artifact_type"]
            refs = artifact["knowledge_point_ids"]
            valid_refs = [point_id for point_id in refs if point_id in valid_ids]
            invalid_refs = sorted({point_id for point_id in refs if point_id not in valid_ids})
            for point_id in valid_refs:
                reference_counter[point_id] += 1
                artifact_names_by_point[point_id].add(artifact_type)
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

        assessment_quality, assessment_warnings = _build_assessment_quality(artifacts)
        warnings.extend(assessment_warnings)

        covered_ids = sorted(reference_counter)
        uncovered_ids = sorted(valid_ids - set(covered_ids))
        duplicate_ids = sorted(point_id for point_id, count in reference_counter.items() if count > 1)
        important_covered_ids = sorted(important_ids & set(covered_ids))
        coverage_rate = round(len(covered_ids) / len(valid_ids) * 100, 2)
        important_rate = round(len(important_covered_ids) / len(important_ids) * 100, 2) if important_ids else 100.0

        if uncovered_ids:
            warnings.append(
                {
                    "code": "UNCOVERED_KNOWLEDGE_POINTS",
                    "message": "存在未覆盖知识点",
                    "knowledge_point_ids": uncovered_ids,
                }
            )
        if important_ids and important_rate < 100:
            warnings.append(
                {
                    "code": "IMPORTANT_KNOWLEDGE_POINTS_UNCOVERED",
                    "message": "存在未覆盖重点知识点",
                    "knowledge_point_ids": sorted(important_ids - set(important_covered_ids)),
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
        paper_results = self.repository.list_paper_results_by_batch(generation_batch_id)
        paper_result_map = {paper_result.id: paper_result for paper_result in paper_results}
        question_items = self.repository.list_question_items_by_batch(generation_batch_id)
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
            artifacts.append(
                {
                    "artifact_type": "question_item",
                    "artifact_id": question.id,
                    "knowledge_point_ids": _normalize_id_values(question.knowledge_point_id),
                    "metadata": {
                        "question_item_id": question.id,
                        "paper_result_id": question.paper_result_id,
                        "question_no": question.question_no,
                        "question_type": question.question_type,
                        "difficulty_level": question.difficulty_level,
                        "scene_type": scene_type,
                        "difficulty_range": strategy.get("difficulty_range") if strategy else None,
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
        "message": "成果物包含不属于当前覆盖范围或知识版本的知识点引用",
        "artifact_type": artifact["artifact_type"],
        "artifact_id": artifact["artifact_id"],
        "knowledge_point_ids": invalid_refs,
    }
    warning.update(artifact.get("metadata") or {})
    return warning


def _build_assessment_quality(artifacts: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """统计测评题型、难度分布并校验难度策略。"""
    question_artifacts = [artifact for artifact in artifacts if artifact["artifact_type"] == "question_item"]
    question_type_distribution = {question_type: 0 for question_type in QUESTION_TYPE_KEYS}
    difficulty_distribution = {difficulty_level: 0 for difficulty_level in DIFFICULTY_LEVEL_KEYS}
    strategy_check_map: dict[tuple[Any, Any], dict[str, Any]] = {}

    for artifact in question_artifacts:
        metadata = artifact.get("metadata") or {}
        question_type = str(metadata.get("question_type") or "unknown")
        question_type_distribution[question_type] = question_type_distribution.get(question_type, 0) + 1

        difficulty_level = metadata.get("difficulty_level")
        difficulty_key = str(difficulty_level) if difficulty_level is not None else "unknown"
        difficulty_distribution[difficulty_key] = difficulty_distribution.get(difficulty_key, 0) + 1

        paper_result_id = metadata.get("paper_result_id")
        scene_type = metadata.get("scene_type")
        difficulty_range = metadata.get("difficulty_range")
        check_key = (paper_result_id, scene_type)
        strategy_check = strategy_check_map.setdefault(
            check_key,
            {
                "paper_result_id": paper_result_id,
                "scene_type": scene_type,
                "difficulty_range": difficulty_range,
                "question_count": 0,
                "out_of_range_question_item_ids": [],
                "passed": True,
            },
        )
        strategy_check["question_count"] += 1
        if not _is_difficulty_in_range(difficulty_level, difficulty_range):
            strategy_check["out_of_range_question_item_ids"].append(metadata.get("question_item_id"))

    warnings: list[dict[str, Any]] = []
    strategy_checks = sorted(
        strategy_check_map.values(),
        key=lambda item: (
            0 if item["paper_result_id"] is None else int(item["paper_result_id"]),
            str(item["scene_type"] or ""),
        ),
    )
    for strategy_check in strategy_checks:
        out_of_range_ids = [
            question_id for question_id in strategy_check["out_of_range_question_item_ids"] if question_id is not None
        ]
        strategy_check["out_of_range_question_item_ids"] = out_of_range_ids
        strategy_check["passed"] = not out_of_range_ids
        if out_of_range_ids:
            warnings.append(
                {
                    "code": "QUESTION_DIFFICULTY_OUT_OF_RANGE",
                    "message": "题目难度不符合测评场景预设范围",
                    "paper_result_id": strategy_check["paper_result_id"],
                    "scene_type": strategy_check["scene_type"],
                    "difficulty_range": strategy_check["difficulty_range"],
                    "question_item_ids": out_of_range_ids,
                }
            )

    return (
        {
            "question_count": len(question_artifacts),
            "question_type_distribution": question_type_distribution,
            "difficulty_distribution": difficulty_distribution,
            "strategy_checks": strategy_checks,
        },
        warnings,
    )


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
