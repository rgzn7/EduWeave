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

    def get_parse_version(self, parse_version_id: int) -> ParseVersion | None:
        """按主键查询解析版本。"""
        statement = select(ParseVersion).where(ParseVersion.id == parse_version_id)
        return self.session.scalar(statement)

    def get_file_object(self, file_object_id: int) -> FileObject | None:
        """按主键查询文件对象。"""
        statement = select(FileObject).where(FileObject.id == file_object_id)
        return self.session.scalar(statement)

    def create_file_object(self, file_object: FileObject) -> FileObject:
        """创建文件对象。"""
        self.session.add(file_object)
        self.session.flush()
        return file_object

    def get_next_parse_version_no(self, textbook_version_id: int) -> int:
        """获取教材版本下一个解析版本号。"""
        statement = select(func.max(ParseVersion.version_no)).where(ParseVersion.textbook_version_id == textbook_version_id)
        current_max = self.session.scalar(statement)
        return int(current_max or 0) + 1

    def get_active_parse_version(self, textbook_version_id: int) -> ParseVersion | None:
        """查询教材当前活动解析版本。"""
        statement = (
            select(ParseVersion)
            .where(
                ParseVersion.textbook_version_id == textbook_version_id,
                ParseVersion.version_status == "ready",
            )
            .order_by(ParseVersion.version_no.desc(), ParseVersion.id.desc())
            .limit(1)
        )
        return self.session.scalar(statement)

    def create_parse_version(self, parse_version: ParseVersion) -> ParseVersion:
        """创建解析版本。"""
        self.session.add(parse_version)
        self.session.flush()
        return parse_version

    def build_parse_page_model(
        self,
        *,
        parse_version_id: int,
        page_no: int,
        source_page_image_file_id: int | None,
        page_status: str,
        has_issue: int,
        text_content: str | None,
        markdown_content: str | None,
        layout_json: dict | None,
    ) -> ParsePage:
        """构造解析页模型。"""
        return ParsePage(
            parse_version_id=parse_version_id,
            page_no=page_no,
            source_page_image_file_id=source_page_image_file_id,
            page_status=page_status,
            has_issue=has_issue,
            text_content=text_content,
            markdown_content=markdown_content,
            layout_json=layout_json,
        )

    def build_parse_block_model(
        self,
        *,
        parse_version_id: int,
        parse_page_id: int,
        block_no: int,
        block_type: str,
        heading_level: int | None,
        bbox_json: dict | None,
        text_content: str | None,
        markdown_content: str | None,
        asset_file_id: int | None,
        origin_ref_json: dict | None,
        is_deleted: int,
    ) -> ParseBlock:
        """构造解析块模型。"""
        return ParseBlock(
            parse_version_id=parse_version_id,
            parse_page_id=parse_page_id,
            block_no=block_no,
            block_type=block_type,
            heading_level=heading_level,
            bbox_json=bbox_json,
            text_content=text_content,
            markdown_content=markdown_content,
            asset_file_id=asset_file_id,
            origin_ref_json=origin_ref_json,
            is_deleted=is_deleted,
        )

    def build_parse_issue_model(
        self,
        *,
        parse_version_id: int,
        parse_page_id: int | None,
        parse_block_id: int | None,
        related_reparse_version_id: int | None,
        issue_type: str,
        severity: str,
        issue_status: str,
        detected_by: str,
        description: str | None,
        resolution_note: str | None,
        created_by: int | None,
        resolved_by: int | None,
    ) -> ParseIssue:
        """构造解析异常模型。"""
        return ParseIssue(
            parse_version_id=parse_version_id,
            parse_page_id=parse_page_id,
            parse_block_id=parse_block_id,
            related_reparse_version_id=related_reparse_version_id,
            issue_type=issue_type,
            severity=severity,
            issue_status=issue_status,
            detected_by=detected_by,
            description=description,
            resolution_note=resolution_note,
            created_by=created_by,
            resolved_by=resolved_by,
        )

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

    def list_all_parse_pages(self, parse_version_id: int) -> list[ParsePage]:
        """查询解析版本下全部页。"""
        statement = (
            select(ParsePage)
            .where(ParsePage.parse_version_id == parse_version_id)
            .order_by(ParsePage.page_no.asc())
        )
        return list(self.session.scalars(statement))

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

    def list_all_blocks_by_version(self, parse_version_id: int) -> list[ParseBlock]:
        """查询解析版本下全部结构块。"""
        statement = (
            select(ParseBlock)
            .where(ParseBlock.parse_version_id == parse_version_id)
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

    def list_all_parse_issues(self, parse_version_id: int) -> list[ParseIssue]:
        """查询解析版本下全部异常。"""
        statement = (
            select(ParseIssue)
            .where(ParseIssue.parse_version_id == parse_version_id)
            .order_by(ParseIssue.created_at.asc(), ParseIssue.id.asc())
        )
        return list(self.session.scalars(statement))

    def archive_other_parse_versions(self, textbook_version_id: int, exclude_parse_version_id: int) -> None:
        """将教材下除目标版本外的活动版本归档。"""
        statement = select(ParseVersion).where(
            ParseVersion.textbook_version_id == textbook_version_id,
            ParseVersion.id != exclude_parse_version_id,
            ParseVersion.version_status == "ready",
        )
        for parse_version in self.session.scalars(statement):
            parse_version.version_status = "archived"
            self.session.add(parse_version)
        self.session.flush()

    def get_parse_page_by_version_and_page_no(self, parse_version_id: int, page_no: int) -> ParsePage | None:
        """按版本和页码查询解析页。"""
        statement = select(ParsePage).where(ParsePage.parse_version_id == parse_version_id, ParsePage.page_no == page_no)
        return self.session.scalar(statement)

    def count_block_types(self, parse_version_id: int) -> list[tuple[str, int]]:
        """统计解析版本下各 block 类型的数量。"""
        statement = (
            select(ParseBlock.block_type, func.count())
            .where(
                ParseBlock.parse_version_id == parse_version_id,
                ParseBlock.is_deleted == 0,
            )
            .group_by(ParseBlock.block_type)
        )
        return [(row[0], int(row[1] or 0)) for row in self.session.execute(statement).all()]

    def count_blocks_with_asset(self, parse_version_id: int) -> int:
        """统计带资源文件的块数量。"""
        statement = (
            select(func.count())
            .select_from(ParseBlock)
            .where(
                ParseBlock.parse_version_id == parse_version_id,
                ParseBlock.is_deleted == 0,
                ParseBlock.asset_file_id.is_not(None),
            )
        )
        return int(self.session.scalar(statement) or 0)

    def count_blocks_with_bbox(self, parse_version_id: int) -> int:
        """统计带坐标框的块数量。"""
        statement = (
            select(func.count())
            .select_from(ParseBlock)
            .where(
                ParseBlock.parse_version_id == parse_version_id,
                ParseBlock.is_deleted == 0,
                ParseBlock.bbox_json.is_not(None),
            )
        )
        return int(self.session.scalar(statement) or 0)

    def count_blocks_total(self, parse_version_id: int) -> int:
        """统计解析版本下的有效块总数。"""
        statement = (
            select(func.count())
            .select_from(ParseBlock)
            .where(
                ParseBlock.parse_version_id == parse_version_id,
                ParseBlock.is_deleted == 0,
            )
        )
        return int(self.session.scalar(statement) or 0)

    def list_sample_blocks_with_page_no(self, parse_version_id: int, limit: int) -> list[tuple[ParseBlock, int]]:
        """抽取证据示例 block 并带页码，优先覆盖多种类型。"""
        statement = (
            select(ParseBlock, ParsePage.page_no)
            .join(ParsePage, ParsePage.id == ParseBlock.parse_page_id)
            .where(
                ParseBlock.parse_version_id == parse_version_id,
                ParseBlock.is_deleted == 0,
            )
            .order_by(ParsePage.page_no.asc(), ParseBlock.block_no.asc())
            .limit(max(limit * 4, limit))
        )
        return [(row[0], int(row[1])) for row in self.session.execute(statement).all()]

    def save(self, instance) -> None:
        """保存实体。"""
        self.session.add(instance)
        self.session.flush()
