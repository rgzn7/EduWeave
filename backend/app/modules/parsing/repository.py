"""
@Date: 2026-04-13
@Author: xisy
@Discription: 解析模块数据访问层
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.p0_models import FileObject, ParseBlock, ParseIssue, ParsePage, ParseVersion, Project, TextbookVersion


class ParsingRepository:
    """解析模块仓储。"""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_textbook_version_for_owner(self, textbook_version_id: int, owner_user_id: int) -> TextbookVersion | None:
        """查询当前教师可见的教材版本。"""
        statement = (
            select(TextbookVersion)
            .join(Project, Project.id == TextbookVersion.project_id)
            .where(TextbookVersion.id == textbook_version_id, Project.owner_user_id == owner_user_id)
        )
        return self.session.scalar(statement)

    def get_textbook_version(self, textbook_version_id: int) -> TextbookVersion | None:
        """按主键查询教材版本。"""
        statement = select(TextbookVersion).where(TextbookVersion.id == textbook_version_id)
        return self.session.scalar(statement)

    def get_file_object(self, file_object_id: int) -> FileObject | None:
        """按主键查询文件对象。"""
        statement = select(FileObject).where(FileObject.id == file_object_id)
        return self.session.scalar(statement)

    def get_next_parse_version_no(self, textbook_version_id: int) -> int:
        """获取教材版本下一个解析版本号。"""
        statement = select(func.max(ParseVersion.version_no)).where(ParseVersion.textbook_version_id == textbook_version_id)
        current_max = self.session.scalar(statement)
        return int(current_max or 0) + 1

    def create_parse_version(self, parse_version: ParseVersion) -> ParseVersion:
        """创建解析版本。"""
        self.session.add(parse_version)
        self.session.flush()
        return parse_version

    def create_parse_page(self, parse_page: ParsePage) -> ParsePage:
        """创建解析页。"""
        self.session.add(parse_page)
        self.session.flush()
        return parse_page

    def create_parse_block(self, parse_block: ParseBlock) -> ParseBlock:
        """创建解析块。"""
        self.session.add(parse_block)
        self.session.flush()
        return parse_block

    def create_parse_issue(self, parse_issue: ParseIssue) -> ParseIssue:
        """创建解析异常。"""
        self.session.add(parse_issue)
        self.session.flush()
        return parse_issue

    def list_parse_versions(self, textbook_version_id: int, offset: int, limit: int) -> list[ParseVersion]:
        """分页查询解析版本。"""
        statement = (
            select(ParseVersion)
            .where(ParseVersion.textbook_version_id == textbook_version_id)
            .order_by(ParseVersion.version_no.desc(), ParseVersion.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.scalars(statement))

    def count_parse_versions(self, textbook_version_id: int) -> int:
        """统计解析版本数量。"""
        statement = select(func.count()).select_from(ParseVersion).where(
            ParseVersion.textbook_version_id == textbook_version_id
        )
        return int(self.session.scalar(statement) or 0)

    def get_parse_version_for_owner(self, parse_version_id: int, owner_user_id: int) -> ParseVersion | None:
        """查询当前教师可见的解析版本。"""
        statement = (
            select(ParseVersion)
            .join(Project, Project.id == ParseVersion.project_id)
            .where(ParseVersion.id == parse_version_id, Project.owner_user_id == owner_user_id)
        )
        return self.session.scalar(statement)

    def count_parse_issues(self, parse_version_id: int) -> int:
        """统计解析异常数量。"""
        statement = select(func.count()).select_from(ParseIssue).where(ParseIssue.parse_version_id == parse_version_id)
        return int(self.session.scalar(statement) or 0)

    def list_parse_pages(self, parse_version_id: int, offset: int, limit: int) -> list[ParsePage]:
        """分页查询解析页。"""
        statement = (
            select(ParsePage)
            .where(ParsePage.parse_version_id == parse_version_id)
            .order_by(ParsePage.page_no.asc())
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.scalars(statement))

    def count_parse_pages(self, parse_version_id: int) -> int:
        """统计解析页数量。"""
        statement = select(func.count()).select_from(ParsePage).where(ParsePage.parse_version_id == parse_version_id)
        return int(self.session.scalar(statement) or 0)

    def list_blocks_by_page_ids(self, page_ids: list[int]) -> list[ParseBlock]:
        """查询指定解析页的块。"""
        if not page_ids:
            return []
        statement = (
            select(ParseBlock)
            .where(ParseBlock.parse_page_id.in_(page_ids))
            .order_by(ParseBlock.parse_page_id.asc(), ParseBlock.block_no.asc())
        )
        return list(self.session.scalars(statement))

    def list_parse_issues(self, parse_version_id: int, offset: int, limit: int) -> list[ParseIssue]:
        """分页查询解析异常。"""
        statement = (
            select(ParseIssue)
            .where(ParseIssue.parse_version_id == parse_version_id)
            .order_by(ParseIssue.created_at.desc(), ParseIssue.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(self.session.scalars(statement))

    def save(self, instance) -> None:
        """保存实体。"""
        self.session.add(instance)
        self.session.flush()
