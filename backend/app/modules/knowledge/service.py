"""
@Date: 2026-04-14
@Author: xisy
@Discription: 知识结构化模块业务服务
"""

from copy import deepcopy
from typing import Any

from sqlalchemy.orm import Session

from app.core.constants import KNOWLEDGE_EXTRACT_TASK_TYPE, KNOWLEDGE_MODULE_CODE, KNOWLEDGE_QUEUE_NAME
from app.core.exceptions import AppException, BusinessErrorCode
from app.core.middleware import get_request_id
from app.modules.knowledge.domain import (
    ChapterDraft,
    KnowledgeEvidenceDraft,
    KnowledgePointDraft,
    PersistedKnowledgeSnapshot,
    build_knowledge_point_embedding_text,
    build_knowledge_point_vector_records,
    build_textbook_chunk_embedding_text,
    build_textbook_chunk_vector_records,
    parent_node_path,
    persist_knowledge_snapshot,
    sort_node_path,
)
from app.modules.knowledge.repository import KnowledgeRepository
from app.modules.knowledge.schemas import (
    ChapterNodeResponse,
    KnowledgeEvidenceResponse,
    KnowledgeManualRevisionEvidenceRequest,
    KnowledgeManualRevisionOperationRequest,
    KnowledgeManualRevisionRequest,
    KnowledgePointDetailResponse,
    KnowledgePointListItemResponse,
    KnowledgeTaskCreateRequest,
    KnowledgeVersionDetailResponse,
    KnowledgeVersionListItemResponse,
)
from app.modules.task_center.repository import TaskCenterRepository
from app.modules.task_center.schemas import TaskListItemResponse
from app.modules.task_center.service import TaskCenterService
from app.shared.llm import OpenAICompatibleEmbeddingService
from app.shared.queue import dispatch_task
from app.shared.vector import MilvusVectorService


class KnowledgeService:
    """知识结构化模块服务。"""

    def __init__(
        self,
        session: Session,
        repository: KnowledgeRepository | None = None,
        embedding_service: OpenAICompatibleEmbeddingService | None = None,
        vector_service: MilvusVectorService | None = None,
    ) -> None:
        self.session = session
        self.repository = repository or KnowledgeRepository(session)
        self.embedding_service = embedding_service or OpenAICompatibleEmbeddingService()
        self.vector_service = vector_service or MilvusVectorService()
        self.task_repository = TaskCenterRepository(session)

    def create_extract_task(
        self,
        *,
        owner_user_id: int,
        parse_version_id: int,
        request: KnowledgeTaskCreateRequest,
    ) -> TaskListItemResponse:
        """创建知识抽取任务。"""
        parse_version = self.repository.get_parse_version_for_owner(parse_version_id, owner_user_id)
        if parse_version is None:
            raise AppException(BusinessErrorCode.PARSE_VERSION_NOT_FOUND, "解析版本不存在")
        _ensure_parse_version_confirmed(parse_version)

        active_task = self.task_repository.get_active_task_by_biz_key(
            module_code=KNOWLEDGE_MODULE_CODE,
            task_type=KNOWLEDGE_EXTRACT_TASK_TYPE,
            biz_key=f"parse_version:{parse_version.id}:knowledge",
        )
        if active_task is not None:
            raise AppException(BusinessErrorCode.TASK_CONFLICT, "当前已有运行中的知识抽取任务")

        ready_knowledge_version = self.repository.get_ready_knowledge_version(parse_version.id)
        if ready_knowledge_version is not None and not request.force_regenerate:
            raise AppException(BusinessErrorCode.TASK_CONFLICT, "当前解析版本已存在可用知识版本")

        task = self._create_task_record(
            owner_user_id=owner_user_id,
            parse_version_id=parse_version.id,
            force_regenerate=request.force_regenerate,
        )
        dispatch_result = dispatch_task(
            "app.modules.knowledge.tasks.run_extract_task",
            {
                "task_record_id": task.id,
                "parse_version_id": parse_version.id,
                "operator_user_id": owner_user_id,
                "force_regenerate": request.force_regenerate,
                "database_url": self.session.get_bind().url.render_as_string(hide_password=False),
            },
        )
        if dispatch_result.worker_task_id:
            task.worker_task_id = dispatch_result.worker_task_id
            self.task_repository.save(task)
            self.session.commit()

        self.session.expire_all()
        fresh_task = self.task_repository.get_task_by_id(task.id)
        return TaskCenterService.build_task_list_item(fresh_task)

    def list_knowledge_versions(
        self,
        *,
        owner_user_id: int,
        parse_version_id: int,
        page: int,
        page_size: int,
    ) -> tuple[list[KnowledgeVersionListItemResponse], int]:
        """分页获取知识版本列表。"""
        parse_version = self.repository.get_parse_version_for_owner(parse_version_id, owner_user_id)
        if parse_version is None:
            raise AppException(BusinessErrorCode.PARSE_VERSION_NOT_FOUND, "解析版本不存在")
        offset = (page - 1) * page_size
        versions = self.repository.list_knowledge_versions(parse_version.id, offset, page_size)
        total_count = self.repository.count_knowledge_versions(parse_version.id)
        items = [self.build_knowledge_version_response(version) for version in versions]
        return items, total_count

    def get_knowledge_version_detail(
        self,
        *,
        owner_user_id: int,
        knowledge_version_id: int,
    ) -> KnowledgeVersionDetailResponse:
        """查询知识版本详情。"""
        knowledge_version = self.repository.get_knowledge_version_for_owner(knowledge_version_id, owner_user_id)
        if knowledge_version is None:
            raise AppException(BusinessErrorCode.KNOWLEDGE_VERSION_NOT_FOUND, "知识版本不存在")
        return KnowledgeVersionDetailResponse(**self.build_knowledge_version_response(knowledge_version).model_dump())

    def list_chapters(
        self,
        *,
        owner_user_id: int,
        knowledge_version_id: int,
    ) -> list[ChapterNodeResponse]:
        """查询知识版本下的平铺章节树。"""
        knowledge_version = self.repository.get_knowledge_version_for_owner(knowledge_version_id, owner_user_id)
        if knowledge_version is None:
            raise AppException(BusinessErrorCode.KNOWLEDGE_VERSION_NOT_FOUND, "知识版本不存在")
        chapters = self.repository.list_chapter_nodes(knowledge_version.id)
        return [ChapterNodeResponse.model_validate(chapter, from_attributes=True) for chapter in chapters]

    def list_points(
        self,
        *,
        owner_user_id: int,
        knowledge_version_id: int,
        chapter_node_id: int | None,
        keyword: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[KnowledgePointListItemResponse], int]:
        """分页查询知识点列表。"""
        knowledge_version = self.repository.get_knowledge_version_for_owner(knowledge_version_id, owner_user_id)
        if knowledge_version is None:
            raise AppException(BusinessErrorCode.KNOWLEDGE_VERSION_NOT_FOUND, "知识版本不存在")
        offset = (page - 1) * page_size
        points = self.repository.list_knowledge_points(
            knowledge_version.id,
            chapter_node_id=chapter_node_id,
            keyword=keyword,
            offset=offset,
            limit=page_size,
        )
        total_count = self.repository.count_knowledge_points(
            knowledge_version.id,
            chapter_node_id=chapter_node_id,
            keyword=keyword,
        )
        chapters = self.repository.list_chapter_nodes(knowledge_version.id)
        chapter_map = {chapter.id: chapter.title for chapter in chapters}
        evidences = self.repository.list_knowledge_evidences_by_point_ids([point.id for point in points])
        evidence_count_map: dict[int, int] = {}
        for evidence in evidences:
            evidence_count_map[evidence.knowledge_point_id] = evidence_count_map.get(evidence.knowledge_point_id, 0) + 1
        items = [self._build_point_list_item(point, chapter_map, evidence_count_map.get(point.id, 0)) for point in points]
        return items, total_count

    def get_point_detail(
        self,
        *,
        owner_user_id: int,
        knowledge_point_id: int,
    ) -> KnowledgePointDetailResponse:
        """查询知识点详情。"""
        point = self.repository.get_knowledge_point_for_owner(knowledge_point_id, owner_user_id)
        if point is None:
            raise AppException(BusinessErrorCode.KNOWLEDGE_VERSION_NOT_FOUND, "知识点不存在")
        chapters = self.repository.list_chapter_nodes(point.knowledge_version_id)
        chapter_map = {chapter.id: chapter.title for chapter in chapters}
        evidences = self.repository.list_knowledge_evidences(point.id)
        return KnowledgePointDetailResponse(
            **self._build_point_list_item(point, chapter_map, len(evidences)).model_dump(),
            evidences=[KnowledgeEvidenceResponse.model_validate(evidence, from_attributes=True) for evidence in evidences],
        )

    def create_manual_revision(
        self,
        *,
        owner_user_id: int,
        knowledge_version_id: int,
        request: KnowledgeManualRevisionRequest,
    ) -> KnowledgeVersionDetailResponse:
        """根据补丁操作生成新的知识版本。"""
        parent_knowledge_version = self.repository.get_knowledge_version_for_owner(knowledge_version_id, owner_user_id)
        if parent_knowledge_version is None:
            raise AppException(BusinessErrorCode.KNOWLEDGE_VERSION_NOT_FOUND, "知识版本不存在")
        parse_version = self.repository.get_parse_version(parent_knowledge_version.parse_version_id)
        if parse_version is None:
            raise AppException(BusinessErrorCode.PARSE_VERSION_NOT_FOUND, "关联解析版本不存在")
        textbook_version = self.repository.get_textbook_version(parse_version.textbook_version_id)
        if textbook_version is None:
            raise AppException(BusinessErrorCode.TEXTBOOK_NOT_FOUND, "教材版本不存在")

        chapters = self.repository.list_chapter_nodes(parent_knowledge_version.id)
        points = self.repository.list_all_knowledge_points(parent_knowledge_version.id)
        evidences = self.repository.list_knowledge_evidences_by_point_ids([point.id for point in points])
        parse_pages = self.repository.list_parse_pages(parse_version.id)
        parse_blocks = self.repository.list_parse_blocks(parse_version.id)
        page_lookup = {page.page_no: page for page in parse_pages}
        block_lookup = {
            (page_lookup[page.page_no].page_no, block.block_no): block
            for block in parse_blocks
            for page in parse_pages
            if page.id == block.parse_page_id
        }

        summary_json = deepcopy(parent_knowledge_version.summary_json or {})
        chapter_drafts = _clone_chapter_drafts(chapters)
        point_drafts = _clone_point_drafts(points, evidences)
        next_draft_index = 1

        for operation in request.operations:
            if operation.op_type == "update_summary":
                summary_json = deepcopy(operation.summary_json or {})
                continue

            if operation.op_type == "update_chapter":
                chapter_draft = chapter_drafts.get(operation.chapter_node_id)
                if chapter_draft is None:
                    raise AppException(BusinessErrorCode.KNOWLEDGE_REVISION_INVALID, "章节节点不存在于当前知识版本")
                if operation.title is not None:
                    chapter_draft.title = operation.title
                if operation.summary_text is not None:
                    chapter_draft.summary_text = operation.summary_text
                if operation.page_start is not None:
                    chapter_draft.page_start = operation.page_start
                if operation.page_end is not None:
                    chapter_draft.page_end = operation.page_end
                if operation.sort_order is not None:
                    chapter_draft.sort_order = operation.sort_order
                continue

            if operation.op_type == "add_point":
                _ensure_chapter_exists(chapter_drafts, operation.chapter_node_id)
                point_drafts[f"new_point_{next_draft_index}"] = KnowledgePointDraft(
                    draft_id=f"new_point_{next_draft_index}",
                    chapter_ref_id=operation.chapter_node_id,
                    point_name=operation.point_name or "",
                    point_code=operation.point_code,
                    point_type=operation.point_type or "knowledge",
                    importance_level=operation.importance_level,
                    difficulty_level=operation.difficulty_level,
                    mastery_level_hint=operation.mastery_level_hint,
                    tags_json=deepcopy(operation.tags_json),
                    summary_text=operation.summary_text,
                    sort_order=operation.sort_order or 0,
                    evidences=_build_manual_evidence_drafts(
                        evidences=operation.evidences or [],
                        parse_version_id=parse_version.id,
                        page_lookup=page_lookup,
                        block_lookup=block_lookup,
                        textbook_source_file_id=textbook_version.source_file_id,
                    ),
                )
                next_draft_index += 1
                continue

            if operation.op_type == "update_point":
                point_draft = point_drafts.get(operation.knowledge_point_id)
                if point_draft is None:
                    raise AppException(BusinessErrorCode.KNOWLEDGE_REVISION_INVALID, "知识点不存在于当前知识版本")
                if operation.chapter_node_id is not None:
                    _ensure_chapter_exists(chapter_drafts, operation.chapter_node_id)
                    point_draft.chapter_ref_id = operation.chapter_node_id
                if operation.point_code is not None:
                    point_draft.point_code = operation.point_code
                if operation.point_name is not None:
                    point_draft.point_name = operation.point_name
                if operation.point_type is not None:
                    point_draft.point_type = operation.point_type
                if operation.importance_level is not None:
                    point_draft.importance_level = operation.importance_level
                if operation.difficulty_level is not None:
                    point_draft.difficulty_level = operation.difficulty_level
                if operation.mastery_level_hint is not None:
                    point_draft.mastery_level_hint = operation.mastery_level_hint
                if operation.tags_json is not None:
                    point_draft.tags_json = deepcopy(operation.tags_json)
                if operation.summary_text is not None:
                    point_draft.summary_text = operation.summary_text
                if operation.sort_order is not None:
                    point_draft.sort_order = operation.sort_order
                if operation.evidences is not None:
                    point_draft.evidences = _build_manual_evidence_drafts(
                        evidences=operation.evidences,
                        parse_version_id=parse_version.id,
                        page_lookup=page_lookup,
                        block_lookup=block_lookup,
                        textbook_source_file_id=textbook_version.source_file_id,
                    )
                continue

            if operation.op_type == "delete_point":
                if point_drafts.pop(operation.knowledge_point_id, None) is None:
                    raise AppException(BusinessErrorCode.KNOWLEDGE_REVISION_INVALID, "知识点不存在于当前知识版本")
                continue

            if operation.op_type == "merge_points":
                source_point_ids = operation.source_knowledge_point_ids or []
                if len(set(source_point_ids)) != len(source_point_ids):
                    raise AppException(BusinessErrorCode.KNOWLEDGE_REVISION_INVALID, "待合并知识点不能重复")
                source_points = []
                for source_point_id in source_point_ids:
                    point_draft = point_drafts.get(source_point_id)
                    if point_draft is None:
                        raise AppException(BusinessErrorCode.KNOWLEDGE_REVISION_INVALID, "待合并知识点不存在于当前知识版本")
                    source_points.append(point_draft)
                target_chapter_id = operation.chapter_node_id or source_points[0].chapter_ref_id
                if target_chapter_id is not None:
                    _ensure_chapter_exists(chapter_drafts, target_chapter_id)
                merged_evidences = (
                    _build_manual_evidence_drafts(
                        evidences=operation.evidences,
                        parse_version_id=parse_version.id,
                        page_lookup=page_lookup,
                        block_lookup=block_lookup,
                        textbook_source_file_id=textbook_version.source_file_id,
                    )
                    if operation.evidences is not None
                    else _merge_evidence_drafts(source_points)
                )
                point_drafts[f"merged_point_{next_draft_index}"] = KnowledgePointDraft(
                    draft_id=f"merged_point_{next_draft_index}",
                    chapter_ref_id=target_chapter_id,
                    point_name=operation.point_name or source_points[0].point_name,
                    point_code=operation.point_code,
                    point_type=operation.point_type or source_points[0].point_type,
                    importance_level=operation.importance_level if operation.importance_level is not None else _max_int_value(source_points, "importance_level"),
                    difficulty_level=operation.difficulty_level if operation.difficulty_level is not None else _max_int_value(source_points, "difficulty_level"),
                    mastery_level_hint=operation.mastery_level_hint or source_points[0].mastery_level_hint,
                    tags_json=deepcopy(operation.tags_json) if operation.tags_json is not None else deepcopy(source_points[0].tags_json),
                    summary_text=operation.summary_text or f"由{'、'.join(point.point_name for point in source_points)}归并而成",
                    sort_order=operation.sort_order if operation.sort_order is not None else source_points[0].sort_order,
                    evidences=merged_evidences,
                )
                next_draft_index += 1
                for source_point_id in source_point_ids:
                    point_drafts.pop(source_point_id, None)
                continue

        new_knowledge_version = self.repository.create_knowledge_version(
            _build_knowledge_version_model(
                project_id=parent_knowledge_version.project_id,
                parse_version_id=parent_knowledge_version.parse_version_id,
                parent_knowledge_version_id=parent_knowledge_version.id,
                version_no=self.repository.get_next_knowledge_version_no(parent_knowledge_version.project_id),
                summary_json=summary_json,
                created_by=owner_user_id,
            )
        )
        snapshot = persist_knowledge_snapshot(
            self.repository,
            knowledge_version=new_knowledge_version,
            chapter_drafts=list(chapter_drafts.values()),
            point_drafts=list(point_drafts.values()),
        )
        new_knowledge_version.summary_json = _normalize_summary_payload(
            new_knowledge_version.summary_json,
            chapter_count=len(snapshot.chapters),
            point_count=len(snapshot.points),
        )
        self.repository.save(new_knowledge_version)
        self.repository.archive_other_ready_knowledge_versions(new_knowledge_version.parse_version_id, new_knowledge_version.id)
        upsert_vectors_for_knowledge_version(
            repository=self.repository,
            parse_version=parse_version,
            textbook_version=textbook_version,
            knowledge_version=new_knowledge_version,
            snapshot=snapshot,
            embedding_service=self.embedding_service,
            vector_service=self.vector_service,
        )
        self.session.commit()
        return self.get_knowledge_version_detail(
            owner_user_id=owner_user_id,
            knowledge_version_id=new_knowledge_version.id,
        )

    def build_knowledge_version_response(self, knowledge_version) -> KnowledgeVersionListItemResponse:
        """构造知识版本响应。"""
        return KnowledgeVersionListItemResponse(
            id=knowledge_version.id,
            project_id=knowledge_version.project_id,
            parse_version_id=knowledge_version.parse_version_id,
            parent_knowledge_version_id=knowledge_version.parent_knowledge_version_id,
            version_no=knowledge_version.version_no,
            version_status=knowledge_version.version_status,
            summary_json=knowledge_version.summary_json,
            chapter_count=self.repository.count_chapter_nodes(knowledge_version.id),
            point_count=self.repository.count_knowledge_points(
                knowledge_version.id,
                chapter_node_id=None,
                keyword=None,
            ),
            created_by=knowledge_version.created_by,
            created_at=knowledge_version.created_at,
            updated_at=knowledge_version.updated_at,
        )

    def _build_point_list_item(
        self,
        point,
        chapter_map: dict[int, str],
        evidence_count: int,
    ) -> KnowledgePointListItemResponse:
        return KnowledgePointListItemResponse(
            id=point.id,
            knowledge_version_id=point.knowledge_version_id,
            chapter_node_id=point.chapter_node_id,
            chapter_title=chapter_map.get(point.chapter_node_id) if point.chapter_node_id is not None else None,
            point_code=point.point_code,
            point_name=point.point_name,
            point_type=point.point_type,
            importance_level=point.importance_level,
            difficulty_level=point.difficulty_level,
            mastery_level_hint=point.mastery_level_hint,
            tags_json=point.tags_json,
            summary_text=point.summary_text,
            sort_order=point.sort_order,
            evidence_count=evidence_count,
            created_at=point.created_at,
            updated_at=point.updated_at,
        )

    def _create_task_record(
        self,
        *,
        owner_user_id: int,
        parse_version_id: int,
        force_regenerate: bool,
    ):
        parse_version = self.repository.get_parse_version_for_owner(parse_version_id, owner_user_id)
        if parse_version is None:
            raise AppException(BusinessErrorCode.PARSE_VERSION_NOT_FOUND, "解析版本不存在")
        task = self.task_repository.create_task(
            project_id=parse_version.project_id,
            module_code=KNOWLEDGE_MODULE_CODE,
            task_type=KNOWLEDGE_EXTRACT_TASK_TYPE,
            task_status="pending",
            queue_name=KNOWLEDGE_QUEUE_NAME,
            biz_key=f"parse_version:{parse_version.id}:knowledge",
            operator_user_id=owner_user_id,
            payload_json={
                "parse_version_id": parse_version.id,
                "force_regenerate": force_regenerate,
            },
            request_id=get_request_id() or None,
        )
        step_names = [
            ("prepare_parse_source", "准备解析基线"),
            ("invoke_llm_extract", "调用 LLM 抽取知识结构"),
            ("persist_knowledge_result", "落库知识结构"),
            ("upsert_vectors", "写入向量索引"),
        ]
        for step_order, (step_code, step_name) in enumerate(step_names, start=1):
            self.task_repository.create_task_step(
                task_record_id=task.id,
                step_code=step_code,
                step_name=step_name,
                step_order=step_order,
                step_status="pending",
            )
        self.session.commit()
        return task


def _ensure_parse_version_confirmed(parse_version) -> None:
    """校验解析版本已确认可用于知识抽取。"""
    if parse_version.parse_status != "success" or parse_version.review_status != "confirmed":
        raise AppException(
            BusinessErrorCode.PARSE_VERSION_NOT_CONFIRMED,
            "解析版本尚未确认，无法发起知识抽取",
            {
                "parse_status": parse_version.parse_status,
                "review_status": parse_version.review_status,
            },
        )


def _build_knowledge_version_model(
    *,
    project_id: int,
    parse_version_id: int,
    parent_knowledge_version_id: int | None,
    version_no: int,
    summary_json: dict[str, Any] | None,
    created_by: int | None,
):
    from app.modules.p0_models import KnowledgeVersion

    return KnowledgeVersion(
        project_id=project_id,
        parse_version_id=parse_version_id,
        parent_knowledge_version_id=parent_knowledge_version_id,
        version_no=version_no,
        version_status="ready",
        summary_json=summary_json,
        created_by=created_by,
    )


def _normalize_summary_payload(summary_json: dict[str, Any] | None, *, chapter_count: int, point_count: int) -> dict[str, Any]:
    normalized_summary = dict(summary_json or {})
    normalized_summary["chapter_count"] = chapter_count
    normalized_summary["knowledge_point_count"] = point_count
    return normalized_summary


def _clone_chapter_drafts(chapters: list) -> dict[int, ChapterDraft]:
    chapter_drafts = {
        chapter.id: ChapterDraft(
            draft_id=chapter.id,
            parent_ref_id=chapter.parent_id,
            node_path=chapter.node_path,
            node_no=chapter.node_no,
            node_level=chapter.node_level,
            node_type=chapter.node_type,
            title=chapter.title,
            summary_text=chapter.summary_text,
            page_start=chapter.page_start,
            page_end=chapter.page_end,
            sort_order=chapter.sort_order,
        )
        for chapter in chapters
    }
    return dict(sorted(chapter_drafts.items(), key=lambda item: sort_node_path(item[1].node_path)))


def _clone_point_drafts(points: list, evidences: list) -> dict[int | str, KnowledgePointDraft]:
    evidences_by_point_id: dict[int, list[KnowledgeEvidenceDraft]] = {}
    for evidence in evidences:
        evidences_by_point_id.setdefault(evidence.knowledge_point_id, []).append(
            KnowledgeEvidenceDraft(
                parse_version_id=evidence.parse_version_id,
                parse_page_id=evidence.parse_page_id,
                parse_block_id=evidence.parse_block_id,
                source_file_id=evidence.source_file_id,
                evidence_type=evidence.evidence_type,
                page_no=evidence.page_no,
                excerpt_text=evidence.excerpt_text,
                bbox_json=deepcopy(evidence.bbox_json),
                score_value=float(evidence.score_value) if evidence.score_value is not None else None,
            )
        )
    return {
        point.id: KnowledgePointDraft(
            draft_id=point.id,
            chapter_ref_id=point.chapter_node_id,
            point_name=point.point_name,
            point_code=point.point_code,
            point_type=point.point_type,
            importance_level=point.importance_level,
            difficulty_level=point.difficulty_level,
            mastery_level_hint=point.mastery_level_hint,
            tags_json=deepcopy(point.tags_json),
            summary_text=point.summary_text,
            sort_order=point.sort_order,
            evidences=evidences_by_point_id.get(point.id, []),
        )
        for point in points
    }


def _build_manual_evidence_drafts(
    *,
    evidences: list[KnowledgeManualRevisionEvidenceRequest],
    parse_version_id: int,
    page_lookup: dict[int, Any],
    block_lookup: dict[tuple[int, int], Any],
    textbook_source_file_id: int | None,
) -> list[KnowledgeEvidenceDraft]:
    evidence_drafts: list[KnowledgeEvidenceDraft] = []
    for evidence in evidences:
        parse_page = page_lookup.get(evidence.page_no)
        if parse_page is None:
            raise AppException(BusinessErrorCode.KNOWLEDGE_REVISION_INVALID, "证据页码不存在于当前解析版本")
        parse_block = None
        if evidence.block_no is not None:
            parse_block = block_lookup.get((evidence.page_no, evidence.block_no))
            if parse_block is None:
                raise AppException(BusinessErrorCode.KNOWLEDGE_REVISION_INVALID, "证据块不存在于当前解析版本")
        excerpt_text = evidence.excerpt_text
        if excerpt_text is None:
            excerpt_text = (
                (parse_block.markdown_content or parse_block.text_content)
                if parse_block is not None
                else (parse_page.markdown_content or parse_page.text_content)
            )
        evidence_drafts.append(
            KnowledgeEvidenceDraft(
                parse_version_id=parse_version_id,
                parse_page_id=parse_page.id,
                parse_block_id=parse_block.id if parse_block is not None else None,
                source_file_id=(
                    parse_block.asset_file_id
                    if parse_block is not None and parse_block.asset_file_id is not None
                    else parse_page.source_page_image_file_id or textbook_source_file_id
                ),
                evidence_type=evidence.evidence_type,
                page_no=evidence.page_no,
                excerpt_text=excerpt_text,
                bbox_json=deepcopy(evidence.bbox_json),
                score_value=evidence.score_value,
            )
        )
    return evidence_drafts


def _ensure_chapter_exists(chapter_drafts: dict[int, ChapterDraft], chapter_node_id: int | None) -> None:
    if chapter_node_id is None or chapter_node_id not in chapter_drafts:
        raise AppException(BusinessErrorCode.KNOWLEDGE_REVISION_INVALID, "章节节点不存在于当前知识版本")


def _merge_evidence_drafts(points: list[KnowledgePointDraft]) -> list[KnowledgeEvidenceDraft]:
    merged_evidences: list[KnowledgeEvidenceDraft] = []
    seen_keys: set[tuple[Any, ...]] = set()
    for point in points:
        for evidence in point.evidences:
            key = (
                evidence.parse_page_id,
                evidence.parse_block_id,
                evidence.page_no,
                evidence.excerpt_text,
            )
            if key in seen_keys:
                continue
            seen_keys.add(key)
            merged_evidences.append(
                KnowledgeEvidenceDraft(
                    parse_version_id=evidence.parse_version_id,
                    parse_page_id=evidence.parse_page_id,
                    parse_block_id=evidence.parse_block_id,
                    source_file_id=evidence.source_file_id,
                    evidence_type=evidence.evidence_type,
                    page_no=evidence.page_no,
                    excerpt_text=evidence.excerpt_text,
                    bbox_json=deepcopy(evidence.bbox_json),
                    score_value=evidence.score_value,
                )
            )
    return merged_evidences


def _max_int_value(points: list[KnowledgePointDraft], field_name: str) -> int | None:
    candidate_values = [getattr(point, field_name) for point in points if getattr(point, field_name) is not None]
    return max(candidate_values) if candidate_values else None


def upsert_vectors_for_knowledge_version(
    *,
    repository: KnowledgeRepository,
    parse_version,
    textbook_version,
    knowledge_version,
    snapshot: PersistedKnowledgeSnapshot,
    embedding_service: OpenAICompatibleEmbeddingService,
    vector_service: MilvusVectorService,
) -> dict[str, int]:
    """为知识版本补写教材块与知识点向量。"""
    parse_pages = repository.list_parse_pages(parse_version.id)
    parse_blocks = repository.list_parse_blocks(parse_version.id)
    valid_blocks = [
        block
        for block in parse_blocks
        if block.is_deleted == 0 and (block.markdown_content or block.text_content)
    ]
    chunk_vector_count = 0
    if valid_blocks:
        chunk_texts = [build_textbook_chunk_embedding_text(block) for block in valid_blocks]
        chunk_embeddings = embedding_service.embed_texts(chunk_texts)
        chunk_records = build_textbook_chunk_vector_records(
            project_id=knowledge_version.project_id,
            textbook_version_id=textbook_version.id,
            parse_version=parse_version,
            parse_pages=parse_pages,
            parse_blocks=parse_blocks,
            chapters=snapshot.chapters,
            embeddings=chunk_embeddings,
            embedding_model=embedding_service.settings.embedding_model or "unknown",
        )
        vector_service.upsert_vectors("textbook_chunk_vector", chunk_records)
        chunk_vector_count = len(chunk_records)

    knowledge_point_vector_count = 0
    if snapshot.points:
        point_texts = [
            build_knowledge_point_embedding_text(
                point,
                next((chapter.title for chapter in snapshot.chapters if chapter.id == point.chapter_node_id), None),
            )
            for point in snapshot.points
        ]
        point_embeddings = embedding_service.embed_texts(point_texts)
        point_records = build_knowledge_point_vector_records(
            project_id=knowledge_version.project_id,
            knowledge_version_id=knowledge_version.id,
            chapters=snapshot.chapters,
            points=snapshot.points,
            embeddings=point_embeddings,
            embedding_model=embedding_service.settings.embedding_model or "unknown",
        )
        vector_service.upsert_vectors("knowledge_point_vector", point_records)
        knowledge_point_vector_count = len(point_records)

    return {
        "textbook_chunk_vector_count": chunk_vector_count,
        "knowledge_point_vector_count": knowledge_point_vector_count,
    }
