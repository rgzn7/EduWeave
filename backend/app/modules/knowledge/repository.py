"""
@Date: 2026-04-14
@Author: xisy
@Discription: 知识结构化模块数据访问层
"""

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.modules.p0_models import (
    ChapterNode,
    KnowledgeEvidence,
    KnowledgePoint,
    KnowledgeVersion,
    ParseBlock,
    ParsePage,
    ParseVersion,
    Project,
    TextbookVersion,
)


class KnowledgeRepository:
    """知识结构化模块仓储。"""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_parse_version_for_owner(self, parse_version_id: int, owner_user_id: int) -> ParseVersion | None:
        """查询当前教师可见的解析版本。"""
        statement = (
            select(ParseVersion)
            .join(Project, Project.id == ParseVersion.project_id)
            .where(ParseVersion.id == parse_version_id, Project.owner_user_id == owner_user_id)
        )
        return self.session.scalar(statement)

    def get_parse_version(self, parse_version_id: int) -> ParseVersion | None:
        """按主键查询解析版本。"""
        statement = select(ParseVersion).where(ParseVersion.id == parse_version_id)
        return self.session.scalar(statement)

    def get_textbook_version(self, textbook_version_id: int) -> TextbookVersion | None:
        """按主键查询教材版本。"""
        statement = select(TextbookVersion).where(TextbookVersion.id == textbook_version_id)
        return self.session.scalar(statement)

    def list_parse_pages(self, parse_version_id: int) -> list[ParsePage]:
        """查询解析版本下全部解析页。"""
        statement = (
            select(ParsePage)
            .where(ParsePage.parse_version_id == parse_version_id)
            .order_by(ParsePage.page_no.asc(), ParsePage.id.asc())
        )
        return list(self.session.scalars(statement))

    def list_parse_blocks(self, parse_version_id: int) -> list[ParseBlock]:
        """查询解析版本下全部解析块。"""
        statement = (
            select(ParseBlock)
            .where(ParseBlock.parse_version_id == parse_version_id)
            .order_by(ParseBlock.parse_page_id.asc(), ParseBlock.block_no.asc(), ParseBlock.id.asc())
        )
        return list(self.session.scalars(statement))

    def get_next_knowledge_version_no(self, project_id: int) -> int:
        """获取项目下一个知识版本号。"""
        statement = select(func.max(KnowledgeVersion.version_no)).where(KnowledgeVersion.project_id == project_id)
        current_max = self.session.scalar(statement)
        return int(current_max or 0) + 1

    def get_ready_knowledge_version(self, parse_version_id: int) -> KnowledgeVersion | None:
        """查询解析版本当前可用的知识版本。"""
        statement = (
            select(KnowledgeVersion)
            .where(
                KnowledgeVersion.parse_version_id == parse_version_id,
                KnowledgeVersion.version_status == "ready",
            )
            .order_by(KnowledgeVersion.version_no.desc(), KnowledgeVersion.id.desc())
            .limit(1)
        )
        return self.session.scalar(statement)

    def get_latest_knowledge_version(self, parse_version_id: int) -> KnowledgeVersion | None:
        """查询解析版本下最新知识版本。"""
        statement = (
            select(KnowledgeVersion)
            .where(KnowledgeVersion.parse_version_id == parse_version_id)
            .order_by(KnowledgeVersion.version_no.desc(), KnowledgeVersion.id.desc())
            .limit(1)
        )
        return self.session.scalar(statement)

    def create_knowledge_version(self, knowledge_version: KnowledgeVersion) -> KnowledgeVersion:
        """创建知识版本。"""
        self.session.add(knowledge_version)
        self.session.flush()
        return knowledge_version

    def create_chapter_node(self, chapter_node: ChapterNode) -> ChapterNode:
        """创建章节节点。"""
        self.session.add(chapter_node)
        self.session.flush()
        return chapter_node

    def create_knowledge_point(self, knowledge_point: KnowledgePoint) -> KnowledgePoint:
        """创建知识点。"""
        self.session.add(knowledge_point)
        self.session.flush()
        return knowledge_point

    def create_knowledge_evidence(self, knowledge_evidence: KnowledgeEvidence) -> KnowledgeEvidence:
        """创建知识点证据。"""
        self.session.add(knowledge_evidence)
        self.session.flush()
        return knowledge_evidence

    def list_knowledge_versions(self, parse_version_id: int, offset: int, limit: int) -> list[KnowledgeVersion]:
        """分页查询知识版本列表。"""
        statement = (
            select(KnowledgeVersion)
            .where(KnowledgeVersion.parse_version_id == parse_version_id)
            .order_by(KnowledgeVersion.version_no.desc(), KnowledgeVersion.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.scalars(statement))

    def count_knowledge_versions(self, parse_version_id: int) -> int:
        """统计知识版本数量。"""
        statement = select(func.count()).select_from(KnowledgeVersion).where(
            KnowledgeVersion.parse_version_id == parse_version_id
        )
        return int(self.session.scalar(statement) or 0)

    def get_knowledge_version_for_owner(self, knowledge_version_id: int, owner_user_id: int) -> KnowledgeVersion | None:
        """查询当前教师可见的知识版本。"""
        statement = (
            select(KnowledgeVersion)
            .join(Project, Project.id == KnowledgeVersion.project_id)
            .where(KnowledgeVersion.id == knowledge_version_id, Project.owner_user_id == owner_user_id)
        )
        return self.session.scalar(statement)

    def get_knowledge_version(self, knowledge_version_id: int) -> KnowledgeVersion | None:
        """按主键查询知识版本。"""
        statement = select(KnowledgeVersion).where(KnowledgeVersion.id == knowledge_version_id)
        return self.session.scalar(statement)

    def archive_other_ready_knowledge_versions(self, parse_version_id: int, exclude_knowledge_version_id: int) -> None:
        """归档同解析版本下的其他活动知识版本。"""
        statement = select(KnowledgeVersion).where(
            KnowledgeVersion.parse_version_id == parse_version_id,
            KnowledgeVersion.id != exclude_knowledge_version_id,
            KnowledgeVersion.version_status == "ready",
        )
        for knowledge_version in self.session.scalars(statement):
            knowledge_version.version_status = "archived"
            self.session.add(knowledge_version)
        self.session.flush()

    def list_chapter_nodes(self, knowledge_version_id: int) -> list[ChapterNode]:
        """查询知识版本下全部章节节点。"""
        statement = (
            select(ChapterNode)
            .where(ChapterNode.knowledge_version_id == knowledge_version_id)
            .order_by(ChapterNode.node_path.asc(), ChapterNode.id.asc())
        )
        return list(self.session.scalars(statement))

    def count_chapter_nodes(self, knowledge_version_id: int) -> int:
        """统计知识版本章节节点数量。"""
        statement = select(func.count()).select_from(ChapterNode).where(
            ChapterNode.knowledge_version_id == knowledge_version_id
        )
        return int(self.session.scalar(statement) or 0)

    def list_knowledge_points(
        self,
        knowledge_version_id: int,
        *,
        chapter_node_id: int | None,
        keyword: str | None,
        offset: int,
        limit: int,
    ) -> list[KnowledgePoint]:
        """分页查询知识点。"""
        statement = select(KnowledgePoint).where(KnowledgePoint.knowledge_version_id == knowledge_version_id)
        if chapter_node_id is not None:
            statement = statement.where(KnowledgePoint.chapter_node_id == chapter_node_id)
        if keyword:
            like_keyword = f"%{keyword}%"
            statement = statement.where(
                or_(
                    KnowledgePoint.point_name.like(like_keyword),
                    KnowledgePoint.summary_text.like(like_keyword),
                )
            )
        statement = statement.order_by(KnowledgePoint.sort_order.asc(), KnowledgePoint.id.asc()).offset(offset).limit(limit)
        return list(self.session.scalars(statement))

    def count_knowledge_points(
        self,
        knowledge_version_id: int,
        *,
        chapter_node_id: int | None,
        keyword: str | None,
    ) -> int:
        """统计知识点数量。"""
        statement = select(func.count()).select_from(KnowledgePoint).where(
            KnowledgePoint.knowledge_version_id == knowledge_version_id
        )
        if chapter_node_id is not None:
            statement = statement.where(KnowledgePoint.chapter_node_id == chapter_node_id)
        if keyword:
            like_keyword = f"%{keyword}%"
            statement = statement.where(
                or_(
                    KnowledgePoint.point_name.like(like_keyword),
                    KnowledgePoint.summary_text.like(like_keyword),
                )
            )
        return int(self.session.scalar(statement) or 0)

    def list_all_knowledge_points(self, knowledge_version_id: int) -> list[KnowledgePoint]:
        """查询知识版本下全部知识点。"""
        statement = (
            select(KnowledgePoint)
            .where(KnowledgePoint.knowledge_version_id == knowledge_version_id)
            .order_by(KnowledgePoint.sort_order.asc(), KnowledgePoint.id.asc())
        )
        return list(self.session.scalars(statement))

    def get_knowledge_point_for_owner(self, knowledge_point_id: int, owner_user_id: int) -> KnowledgePoint | None:
        """查询当前教师可见的知识点。"""
        statement = (
            select(KnowledgePoint)
            .join(KnowledgeVersion, KnowledgeVersion.id == KnowledgePoint.knowledge_version_id)
            .join(Project, Project.id == KnowledgeVersion.project_id)
            .where(KnowledgePoint.id == knowledge_point_id, Project.owner_user_id == owner_user_id)
        )
        return self.session.scalar(statement)

    def list_knowledge_evidences_by_point_ids(self, knowledge_point_ids: list[int]) -> list[KnowledgeEvidence]:
        """批量查询知识点证据。"""
        if not knowledge_point_ids:
            return []
        statement = (
            select(KnowledgeEvidence)
            .where(KnowledgeEvidence.knowledge_point_id.in_(knowledge_point_ids))
            .order_by(KnowledgeEvidence.id.asc())
        )
        return list(self.session.scalars(statement))

    def list_knowledge_evidences(self, knowledge_point_id: int) -> list[KnowledgeEvidence]:
        """查询知识点下全部证据。"""
        statement = (
            select(KnowledgeEvidence)
            .where(KnowledgeEvidence.knowledge_point_id == knowledge_point_id)
            .order_by(KnowledgeEvidence.id.asc())
        )
        return list(self.session.scalars(statement))

    def save(self, instance) -> None:
        """保存实体。"""
        self.session.add(instance)
        self.session.flush()
