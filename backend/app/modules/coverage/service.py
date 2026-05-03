"""
@Date: 2026-05-03
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
from app.modules.coverage.repository import CoverageRepository
from app.modules.coverage.schemas import CoverageReportDetailResponse, CoverageReportListItemResponse
from app.modules.p0_models import CoverageReport, GenerationTrace
from app.modules.task_center.repository import TaskCenterRepository
from app.shared.queue import dispatch_task
from app.shared.utils import DateTimeUtil

COVERAGE_REFERENCE_KEYS = {
    "knowledge_point_id",
    "knowledge_point_ids",
    "knowledge_point_refs",
    "coverage_knowledge_points",
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

        knowledge_points = self.repository.list_knowledge_points(generation_batch.knowledge_version_id)
        if not knowledge_points:
            raise AppException(BusinessErrorCode.GENERATION_BASELINE_INVALID, "知识版本缺少知识点，无法分析覆盖率")

        knowledge_point_map = {point.id: point for point in knowledge_points}
        valid_ids = set(knowledge_point_map)
        important_ids = {
            point.id
            for point in knowledge_points
            if point.importance_level is not None and int(point.importance_level) >= 4
        }
        artifacts = self._collect_artifact_references(generation_batch_id)
        reference_counter: dict[int, int] = defaultdict(int)
        artifact_names_by_point: dict[int, set[str]] = defaultdict(set)
        warnings: list[dict[str, Any]] = []
        artifact_coverage: dict[str, Any] = {}

        for artifact in artifacts:
            refs = artifact["knowledge_point_ids"]
            valid_refs = [point_id for point_id in refs if point_id in valid_ids]
            invalid_refs = sorted({point_id for point_id in refs if point_id not in valid_ids})
            for point_id in valid_refs:
                reference_counter[point_id] += 1
                artifact_names_by_point[point_id].add(artifact["artifact_type"])
            if invalid_refs:
                warnings.append(
                    {
                        "code": "INVALID_KNOWLEDGE_POINT_REF",
                        "message": "成果物包含不属于当前知识版本的知识点引用",
                        "artifact_type": artifact["artifact_type"],
                        "artifact_id": artifact["artifact_id"],
                        "knowledge_point_ids": invalid_refs,
                    }
                )
            artifact_coverage_key = f"{artifact['artifact_type']}:{artifact['artifact_id']}"
            artifact_coverage[artifact_coverage_key] = {
                "artifact_type": artifact["artifact_type"],
                "artifact_id": artifact["artifact_id"],
                "reference_count": len(refs),
                "valid_knowledge_point_ids": sorted(set(valid_refs)),
                "invalid_knowledge_point_ids": invalid_refs,
            }

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
        """创建或复用覆盖率报告。"""
        existing_report = self.repository.get_coverage_report_by_batch(generation_batch_id)
        if existing_report is not None:
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

        if curriculum_plan is not None:
            artifacts.append(
                self._build_artifact_reference(
                    "curriculum_plan",
                    curriculum_plan.id,
                    curriculum_plan.content_json,
                )
            )
        for lesson_plan in lesson_plans:
            artifacts.append(
                self._build_artifact_reference(
                    "lesson_plan",
                    lesson_plan.id,
                    lesson_plan.content_json,
                )
            )
        return artifacts

    @staticmethod
    def _build_artifact_reference(artifact_type: str, artifact_id: int, payload: Any) -> dict[str, Any]:
        """构造成果物引用摘要。"""
        return {
            "artifact_type": artifact_type,
            "artifact_id": artifact_id,
            "knowledge_point_ids": _extract_knowledge_point_ids(payload),
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
            "database_url": session.get_bind().url.render_as_string(hide_password=False),
        },
    )
    if dispatch_result.worker_task_id:
        task.worker_task_id = dispatch_result.worker_task_id
        service.task_repository.save(task)
        session.commit()
    return task


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
