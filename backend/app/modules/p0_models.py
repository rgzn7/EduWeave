"""
@Date: 2026-05-28
@Author: xisy
@Discription: EduWeave P0 阶段数据库模型骨架
"""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, String, Text, func, text
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

MYSQL_BIGINT_UNSIGNED = Integer().with_variant(mysql.BIGINT(unsigned=True), "mysql")
MYSQL_DATETIME_MS = DateTime().with_variant(mysql.DATETIME(fsp=3), "mysql")
MYSQL_TINYINT = Integer().with_variant(mysql.TINYINT(display_width=1), "mysql")
MYSQL_TINYINT_UNSIGNED = Integer().with_variant(mysql.TINYINT(unsigned=True), "mysql")
MYSQL_JSON = mysql.JSON()
MYSQL_MEDIUMTEXT = mysql.MEDIUMTEXT()
MYSQL_DECIMAL_6_2 = Numeric(6, 2).with_variant(mysql.DECIMAL(6, 2), "mysql")
MYSQL_DECIMAL_8_4 = Numeric(8, 4).with_variant(mysql.DECIMAL(8, 4), "mysql")


class TimestampMixin:
    """统一维护创建时间与更新时间。"""

    created_at: Mapped[datetime] = mapped_column(
        MYSQL_DATETIME_MS,
        nullable=False,
        server_default=func.now(),
        comment="创建时间",
    )
    updated_at: Mapped[datetime] = mapped_column(
        MYSQL_DATETIME_MS,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        comment="更新时间",
    )


class CreatedAtMixin:
    """仅维护创建时间。"""

    created_at: Mapped[datetime] = mapped_column(
        MYSQL_DATETIME_MS,
        nullable=False,
        server_default=func.now(),
        comment="创建时间",
    )


class Project(TimestampMixin, Base):
    """项目表。"""

    __tablename__ = "project"
    __table_args__ = (
        Index("uk_project_project_code", "project_code", unique=True),
        Index("idx_project_owner_status", "owner_user_id", "status"),
        Index("idx_project_subject_grade", "subject_code", "grade_code"),
        {"comment": "项目表"},
    )

    id: Mapped[int] = mapped_column(MYSQL_BIGINT_UNSIGNED, primary_key=True, autoincrement=True, comment="主键")
    owner_user_id: Mapped[int] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("sys_user.id"),
        nullable=False,
        comment="负责人",
    )
    project_code: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="项目编码")
    name: Mapped[str] = mapped_column(String(128), nullable=False, comment="项目名称")
    subject_code: Mapped[str] = mapped_column(String(32), nullable=False, comment="学科编码")
    grade_code: Mapped[str] = mapped_column(String(32), nullable=False, comment="年级编码")
    applicable_target: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="适用对象")
    remark: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="备注")
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="active",
        server_default=text("'active'"),
        comment="状态：active/archived/disabled",
    )
    current_textbook_version_id: Mapped[int | None] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("textbook_version.id"),
        nullable=True,
        comment="当前教材版本",
    )
    current_learner_profile_version_id: Mapped[int | None] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("learner_profile_version.id"),
        nullable=True,
        comment="当前学情版本",
    )
    latest_generation_batch_id: Mapped[int | None] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("generation_batch.id"),
        nullable=True,
        comment="最近生成批次",
    )
    active_generation_run_id: Mapped[int | None] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("generation_run.id"),
        nullable=True,
        comment="当前活跃一键生成运行",
    )
    last_activity_at: Mapped[datetime | None] = mapped_column(MYSQL_DATETIME_MS, nullable=True, comment="最近活动时间")


class FileObject(TimestampMixin, Base):
    """统一文件对象表。"""

    __tablename__ = "file_object"
    __table_args__ = (
        Index("uk_file_object_bucket_key", "bucket_name", "object_key", unique=True),
        Index("idx_file_object_project_biz", "project_id", "biz_type"),
        Index("idx_file_object_hash", "content_hash"),
        {"comment": "统一文件对象表"},
    )

    id: Mapped[int] = mapped_column(MYSQL_BIGINT_UNSIGNED, primary_key=True, autoincrement=True, comment="主键")
    project_id: Mapped[int] = mapped_column(MYSQL_BIGINT_UNSIGNED, ForeignKey("project.id"), nullable=False, comment="所属项目")
    biz_type: Mapped[str] = mapped_column(String(32), nullable=False, comment="文件业务类型")
    storage_provider: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="obs",
        server_default=text("'obs'"),
        comment="存储提供商",
    )
    bucket_name: Mapped[str] = mapped_column(String(128), nullable=False, comment="存储桶")
    object_key: Mapped[str] = mapped_column(String(512), nullable=False, comment="对象路径")
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False, comment="原始文件名")
    file_ext: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="扩展名")
    mime_type: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="MIME类型")
    file_size: Mapped[int] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        nullable=False,
        default=0,
        server_default=text("0"),
        comment="文件大小",
    )
    content_hash: Mapped[str] = mapped_column(String(128), nullable=False, comment="文件哈希")
    source_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="user_upload",
        server_default=text("'user_upload'"),
        comment="来源类型",
    )
    upload_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="uploaded",
        server_default=text("'uploaded'"),
        comment="上传状态",
    )
    uploaded_by: Mapped[int | None] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("sys_user.id"),
        nullable=True,
        comment="上传人",
    )
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(MYSQL_JSON, nullable=True, comment="附加元数据")


class TextbookVersion(TimestampMixin, Base):
    """教材版本表。"""

    __tablename__ = "textbook_version"
    __table_args__ = (
        Index("uk_textbook_version_project_no", "project_id", "version_no", unique=True),
        Index("idx_textbook_version_project_status", "project_id", "version_status", "created_at"),
        Index("idx_textbook_version_subject_grade", "subject_code", "grade_code"),
        {"comment": "教材版本表"},
    )

    id: Mapped[int] = mapped_column(MYSQL_BIGINT_UNSIGNED, primary_key=True, autoincrement=True, comment="主键")
    project_id: Mapped[int] = mapped_column(MYSQL_BIGINT_UNSIGNED, ForeignKey("project.id"), nullable=False, comment="所属项目")
    source_file_id: Mapped[int] = mapped_column(MYSQL_BIGINT_UNSIGNED, ForeignKey("file_object.id"), nullable=False, comment="教材源文件")
    version_no: Mapped[int] = mapped_column(Integer, nullable=False, comment="版本号")
    textbook_name: Mapped[str] = mapped_column(String(255), nullable=False, comment="教材名称")
    publisher: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="出版社")
    subject_code: Mapped[str] = mapped_column(String(32), nullable=False, comment="学科编码")
    grade_code: Mapped[str] = mapped_column(String(32), nullable=False, comment="年级编码")
    volume_code: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="册别")
    edition_label: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="版本标签")
    isbn: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="ISBN")
    file_hash: Mapped[str] = mapped_column(String(128), nullable=False, comment="文件哈希")
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="页数")
    parse_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="pending",
        server_default=text("'pending'"),
        comment="解析状态",
    )
    version_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="ready",
        server_default=text("'ready'"),
        comment="版本状态",
    )
    auto_identify_json: Mapped[dict[str, Any] | None] = mapped_column(MYSQL_JSON, nullable=True, comment="自动识别信息")
    remark: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="备注")
    uploaded_by: Mapped[int | None] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("sys_user.id"),
        nullable=True,
        comment="上传人",
    )


class LearnerProfileFile(TimestampMixin, Base):
    """学情文件表。"""

    __tablename__ = "learner_profile_file"
    __table_args__ = (
        Index("idx_profile_file_project_status", "project_id", "file_status", "created_at"),
        {"comment": "学情文件表"},
    )

    id: Mapped[int] = mapped_column(MYSQL_BIGINT_UNSIGNED, primary_key=True, autoincrement=True, comment="主键")
    project_id: Mapped[int] = mapped_column(MYSQL_BIGINT_UNSIGNED, ForeignKey("project.id"), nullable=False, comment="所属项目")
    source_file_id: Mapped[int] = mapped_column(MYSQL_BIGINT_UNSIGNED, ForeignKey("file_object.id"), nullable=False, comment="学情源文件")
    title: Mapped[str] = mapped_column(String(255), nullable=False, comment="学情文档标题")
    file_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="uploaded",
        server_default=text("'uploaded'"),
        comment="文件状态",
    )
    uploaded_by: Mapped[int | None] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("sys_user.id"),
        nullable=True,
        comment="上传人",
    )


class LearnerProfileVersion(TimestampMixin, Base):
    """学情版本表。"""

    __tablename__ = "learner_profile_version"
    __table_args__ = (
        Index("uk_profile_version_file_no", "profile_file_id", "version_no", unique=True),
        Index("idx_profile_version_project_status", "project_id", "version_status", "created_at"),
        {"comment": "学情版本表"},
    )

    id: Mapped[int] = mapped_column(MYSQL_BIGINT_UNSIGNED, primary_key=True, autoincrement=True, comment="主键")
    project_id: Mapped[int] = mapped_column(MYSQL_BIGINT_UNSIGNED, ForeignKey("project.id"), nullable=False, comment="所属项目")
    profile_file_id: Mapped[int] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("learner_profile_file.id"),
        nullable=False,
        comment="学情文件",
    )
    parent_version_id: Mapped[int | None] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("learner_profile_version.id"),
        nullable=True,
        comment="父版本",
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False, comment="版本号")
    textbook_version_hint_id: Mapped[int | None] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("textbook_version.id"),
        nullable=True,
        comment="教材提示版本",
    )
    grade_code: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="年级提示")
    subject_scope: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="学科范围")
    extract_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="pending",
        server_default=text("'pending'"),
        comment="抽取状态",
    )
    review_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="pending",
        server_default=text("'pending'"),
        comment="审核状态",
    )
    version_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="ready",
        server_default=text("'ready'"),
        comment="版本状态",
    )
    summary_text: Mapped[str | None] = mapped_column(Text, nullable=True, comment="摘要")
    raw_result_json: Mapped[dict[str, Any] | None] = mapped_column(MYSQL_JSON, nullable=True, comment="抽取结果JSON")
    source_snapshot_json: Mapped[dict[str, Any] | None] = mapped_column(MYSQL_JSON, nullable=True, comment="输入快照")
    created_by: Mapped[int | None] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("sys_user.id"),
        nullable=True,
        comment="创建人",
    )


class LearnerProfileRecord(TimestampMixin, Base):
    """学情画像记录表。"""

    __tablename__ = "learner_profile_record"
    __table_args__ = (
        Index("uk_profile_record_scope", "profile_version_id", "student_key", "subject_code", unique=True),
        Index("idx_profile_record_project_subject", "project_id", "subject_code"),
        {"comment": "学情画像记录表"},
    )

    id: Mapped[int] = mapped_column(MYSQL_BIGINT_UNSIGNED, primary_key=True, autoincrement=True, comment="主键")
    project_id: Mapped[int] = mapped_column(MYSQL_BIGINT_UNSIGNED, ForeignKey("project.id"), nullable=False, comment="所属项目")
    profile_version_id: Mapped[int] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("learner_profile_version.id"),
        nullable=False,
        comment="学情版本",
    )
    student_key: Mapped[str] = mapped_column(String(128), nullable=False, comment="学生标识")
    student_name: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="学生姓名")
    is_anonymous: Mapped[int] = mapped_column(
        MYSQL_TINYINT,
        nullable=False,
        default=0,
        server_default=text("0"),
        comment="是否匿名",
    )
    region_name: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="地区")
    grade_code: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="年级")
    subject_code: Mapped[str] = mapped_column(String(32), nullable=False, comment="学科")
    textbook_version_hint_id: Mapped[int | None] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("textbook_version.id"),
        nullable=True,
        comment="教材提示版本",
    )
    score_value: Mapped[float | None] = mapped_column(MYSQL_DECIMAL_6_2, nullable=True, comment="分数")
    advantage_tags_json: Mapped[dict[str, Any] | None] = mapped_column(MYSQL_JSON, nullable=True, comment="优势标签")
    weakness_tags_json: Mapped[dict[str, Any] | None] = mapped_column(MYSQL_JSON, nullable=True, comment="薄弱标签")
    ability_tags_json: Mapped[dict[str, Any] | None] = mapped_column(MYSQL_JSON, nullable=True, comment="能力标签")
    habit_tags_json: Mapped[dict[str, Any] | None] = mapped_column(MYSQL_JSON, nullable=True, comment="学习习惯标签")
    behavior_traits_json: Mapped[dict[str, Any] | None] = mapped_column(MYSQL_JSON, nullable=True, comment="行为特征")
    time_plan_json: Mapped[dict[str, Any] | None] = mapped_column(MYSQL_JSON, nullable=True, comment="时间规划")
    summary_text: Mapped[str | None] = mapped_column(Text, nullable=True, comment="摘要")
    evidence_json: Mapped[dict[str, Any] | None] = mapped_column(MYSQL_JSON, nullable=True, comment="原文依据")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"), comment="排序")


class LearnerProfileSource(TimestampMixin, Base):
    """学情班级源文件表（一个班级挂多个学生 docx）。"""

    __tablename__ = "learner_profile_source"
    __table_args__ = (
        Index("uk_profile_source_file_seq", "profile_file_id", "student_seq", unique=True),
        Index("idx_profile_source_file", "profile_file_id"),
        {"comment": "学情班级源文件表"},
    )

    id: Mapped[int] = mapped_column(MYSQL_BIGINT_UNSIGNED, primary_key=True, autoincrement=True, comment="主键")
    project_id: Mapped[int] = mapped_column(MYSQL_BIGINT_UNSIGNED, ForeignKey("project.id"), nullable=False, comment="所属项目")
    profile_file_id: Mapped[int] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("learner_profile_file.id"),
        nullable=False,
        comment="学情文件（班级）",
    )
    file_object_id: Mapped[int] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("file_object.id"),
        nullable=False,
        comment="学生源 docx 文件对象",
    )
    student_seq: Mapped[int] = mapped_column(Integer, nullable=False, comment="班级内学生序号（从 1 递增）")
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False, comment="原始文件名")
    student_name: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="学生姓名（解析后回填）")


class ParseVersion(TimestampMixin, Base):
    """解析版本表。"""

    __tablename__ = "parse_version"
    __table_args__ = (
        Index("uk_parse_version_textbook_no", "textbook_version_id", "version_no", unique=True),
        Index("idx_parse_version_project_status", "project_id", "version_status", "created_at"),
        {"comment": "解析版本表"},
    )

    id: Mapped[int] = mapped_column(MYSQL_BIGINT_UNSIGNED, primary_key=True, autoincrement=True, comment="主键")
    project_id: Mapped[int] = mapped_column(MYSQL_BIGINT_UNSIGNED, ForeignKey("project.id"), nullable=False, comment="所属项目")
    textbook_version_id: Mapped[int] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("textbook_version.id"),
        nullable=False,
        comment="教材版本",
    )
    parent_parse_version_id: Mapped[int | None] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("parse_version.id"),
        nullable=True,
        comment="父解析版本",
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False, comment="版本号")
    parse_mode: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="full",
        server_default=text("'full'"),
        comment="解析模式",
    )
    page_range_text: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="页范围")
    strategy_code: Mapped[str] = mapped_column(String(64), nullable=False, comment="策略编码")
    mineru_model: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="MinerU模型")
    parse_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="pending",
        server_default=text("'pending'"),
        comment="解析状态",
    )
    review_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="pending",
        server_default=text("'pending'"),
        comment="审核状态",
    )
    version_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="ready",
        server_default=text("'ready'"),
        comment="版本状态",
    )
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="页数")
    source_markdown_file_id: Mapped[int | None] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("file_object.id"),
        nullable=True,
        comment="解析Markdown文件",
    )
    source_json_file_id: Mapped[int | None] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("file_object.id"),
        nullable=True,
        comment="解析JSON文件",
    )
    asset_manifest_json: Mapped[dict[str, Any] | None] = mapped_column(MYSQL_JSON, nullable=True, comment="解析资源清单")
    diff_json: Mapped[dict[str, Any] | None] = mapped_column(MYSQL_JSON, nullable=True, comment="差异摘要")
    error_summary: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="错误摘要")
    started_at: Mapped[datetime | None] = mapped_column(MYSQL_DATETIME_MS, nullable=True, comment="开始时间")
    finished_at: Mapped[datetime | None] = mapped_column(MYSQL_DATETIME_MS, nullable=True, comment="结束时间")


class ParsePage(TimestampMixin, Base):
    """解析页结果表。"""

    __tablename__ = "parse_page"
    __table_args__ = (
        Index("uk_parse_page_version_page_no", "parse_version_id", "page_no", unique=True),
        Index("idx_parse_page_status", "parse_version_id", "page_status"),
        {"comment": "解析页结果表"},
    )

    id: Mapped[int] = mapped_column(MYSQL_BIGINT_UNSIGNED, primary_key=True, autoincrement=True, comment="主键")
    parse_version_id: Mapped[int] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("parse_version.id"),
        nullable=False,
        comment="解析版本",
    )
    page_no: Mapped[int] = mapped_column(Integer, nullable=False, comment="页码")
    source_page_image_file_id: Mapped[int | None] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("file_object.id"),
        nullable=True,
        comment="页图文件",
    )
    page_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="success",
        server_default=text("'success'"),
        comment="页状态",
    )
    has_issue: Mapped[int] = mapped_column(
        MYSQL_TINYINT,
        nullable=False,
        default=0,
        server_default=text("0"),
        comment="是否有异常",
    )
    text_content: Mapped[str | None] = mapped_column(MYSQL_MEDIUMTEXT, nullable=True, comment="页文本")
    markdown_content: Mapped[str | None] = mapped_column(MYSQL_MEDIUMTEXT, nullable=True, comment="页Markdown")
    layout_json: Mapped[dict[str, Any] | None] = mapped_column(MYSQL_JSON, nullable=True, comment="页布局JSON")


class ParseBlock(TimestampMixin, Base):
    """解析块结果表。"""

    __tablename__ = "parse_block"
    __table_args__ = (
        Index("uk_parse_block_page_no", "parse_page_id", "block_no", unique=True),
        Index("idx_parse_block_version_type", "parse_version_id", "block_type"),
        {"comment": "解析块结果表"},
    )

    id: Mapped[int] = mapped_column(MYSQL_BIGINT_UNSIGNED, primary_key=True, autoincrement=True, comment="主键")
    parse_version_id: Mapped[int] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("parse_version.id"),
        nullable=False,
        comment="解析版本",
    )
    parse_page_id: Mapped[int] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("parse_page.id"),
        nullable=False,
        comment="解析页",
    )
    block_no: Mapped[int] = mapped_column(Integer, nullable=False, comment="块序号")
    block_type: Mapped[str] = mapped_column(String(32), nullable=False, comment="块类型")
    heading_level: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="标题级别")
    bbox_json: Mapped[dict[str, Any] | None] = mapped_column(MYSQL_JSON, nullable=True, comment="坐标框")
    text_content: Mapped[str | None] = mapped_column(MYSQL_MEDIUMTEXT, nullable=True, comment="块文本")
    markdown_content: Mapped[str | None] = mapped_column(MYSQL_MEDIUMTEXT, nullable=True, comment="块Markdown")
    asset_file_id: Mapped[int | None] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("file_object.id"),
        nullable=True,
        comment="资源文件",
    )
    origin_ref_json: Mapped[dict[str, Any] | None] = mapped_column(MYSQL_JSON, nullable=True, comment="来源引用")
    is_deleted: Mapped[int] = mapped_column(
        MYSQL_TINYINT,
        nullable=False,
        default=0,
        server_default=text("0"),
        comment="是否删除",
    )


class ParseIssue(TimestampMixin, Base):
    """解析异常表。"""

    __tablename__ = "parse_issue"
    __table_args__ = (
        Index("idx_parse_issue_status", "parse_version_id", "issue_status", "severity"),
        Index("idx_parse_issue_page", "parse_page_id"),
        {"comment": "解析异常表"},
    )

    id: Mapped[int] = mapped_column(MYSQL_BIGINT_UNSIGNED, primary_key=True, autoincrement=True, comment="主键")
    parse_version_id: Mapped[int] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("parse_version.id"),
        nullable=False,
        comment="解析版本",
    )
    parse_page_id: Mapped[int | None] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("parse_page.id"),
        nullable=True,
        comment="解析页",
    )
    parse_block_id: Mapped[int | None] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("parse_block.id"),
        nullable=True,
        comment="解析块",
    )
    related_reparse_version_id: Mapped[int | None] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("parse_version.id"),
        nullable=True,
        comment="关联重解析版本",
    )
    issue_type: Mapped[str] = mapped_column(String(64), nullable=False, comment="异常类型")
    severity: Mapped[str] = mapped_column(String(32), nullable=False, comment="严重级别")
    issue_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="open",
        server_default=text("'open'"),
        comment="异常状态",
    )
    detected_by: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="system",
        server_default=text("'system'"),
        comment="发现来源",
    )
    description: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="异常描述")
    resolution_note: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="处理说明")
    created_by: Mapped[int | None] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("sys_user.id"),
        nullable=True,
        comment="创建人",
    )
    resolved_by: Mapped[int | None] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("sys_user.id"),
        nullable=True,
        comment="处理人",
    )


class KnowledgeVersion(TimestampMixin, Base):
    """知识版本表。"""

    __tablename__ = "knowledge_version"
    __table_args__ = (
        Index("uk_knowledge_version_project_no", "project_id", "version_no", unique=True),
        Index("idx_knowledge_version_parse", "parse_version_id"),
        {"comment": "知识版本表"},
    )

    id: Mapped[int] = mapped_column(MYSQL_BIGINT_UNSIGNED, primary_key=True, autoincrement=True, comment="主键")
    project_id: Mapped[int] = mapped_column(MYSQL_BIGINT_UNSIGNED, ForeignKey("project.id"), nullable=False, comment="所属项目")
    parse_version_id: Mapped[int] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("parse_version.id"),
        nullable=False,
        comment="解析版本",
    )
    parent_knowledge_version_id: Mapped[int | None] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("knowledge_version.id"),
        nullable=True,
        comment="父知识版本",
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False, comment="版本号")
    version_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="ready",
        server_default=text("'ready'"),
        comment="版本状态",
    )
    summary_json: Mapped[dict[str, Any] | None] = mapped_column(MYSQL_JSON, nullable=True, comment="知识结构摘要")
    created_by: Mapped[int | None] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("sys_user.id"),
        nullable=True,
        comment="创建人",
    )


class ChapterNode(TimestampMixin, Base):
    """章节节点表。"""

    __tablename__ = "chapter_node"
    __table_args__ = (
        Index("uk_chapter_node_version_path", "knowledge_version_id", "node_path", unique=True),
        Index("idx_chapter_node_parent", "parent_id"),
        {"comment": "章节节点表"},
    )

    id: Mapped[int] = mapped_column(MYSQL_BIGINT_UNSIGNED, primary_key=True, autoincrement=True, comment="主键")
    knowledge_version_id: Mapped[int] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("knowledge_version.id"),
        nullable=False,
        comment="知识版本",
    )
    parent_id: Mapped[int | None] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("chapter_node.id"),
        nullable=True,
        comment="父章节",
    )
    node_path: Mapped[str] = mapped_column(String(255), nullable=False, comment="路径编码")
    node_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=text("1"), comment="节点序号")
    node_level: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=text("1"), comment="层级")
    node_type: Mapped[str] = mapped_column(String(32), nullable=False, comment="节点类型")
    title: Mapped[str] = mapped_column(String(255), nullable=False, comment="标题")
    summary_text: Mapped[str | None] = mapped_column(Text, nullable=True, comment="摘要")
    page_start: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="起始页")
    page_end: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="结束页")
    line_start: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="Markdown起始行号")
    line_end: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="Markdown结束行号")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"), comment="排序")


class SemanticChunk(TimestampMixin, Base):
    """教材语义块表。"""

    __tablename__ = "semantic_chunk"
    __table_args__ = (
        Index("uk_semantic_chunk_knowledge_no", "knowledge_version_id", "chunk_no", unique=True),
        Index("idx_semantic_chunk_project", "project_id", "created_at"),
        Index("idx_semantic_chunk_knowledge", "knowledge_version_id", "chapter_node_id"),
        Index("idx_semantic_chunk_page_range", "parse_version_id", "page_start", "page_end"),
        {"comment": "教材语义块表"},
    )

    id: Mapped[int] = mapped_column(MYSQL_BIGINT_UNSIGNED, primary_key=True, autoincrement=True, comment="主键")
    project_id: Mapped[int] = mapped_column(MYSQL_BIGINT_UNSIGNED, ForeignKey("project.id"), nullable=False, comment="所属项目")
    parse_version_id: Mapped[int] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("parse_version.id"),
        nullable=False,
        comment="解析版本",
    )
    knowledge_version_id: Mapped[int | None] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("knowledge_version.id"),
        nullable=True,
        comment="知识版本",
    )
    chapter_node_id: Mapped[int | None] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("chapter_node.id"),
        nullable=True,
        comment="章节节点",
    )
    chunk_no: Mapped[int] = mapped_column(Integer, nullable=False, comment="语义块序号")
    chunk_title: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="语义块标题")
    chunk_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="semantic",
        server_default=text("'semantic'"),
        comment="语义块类型",
    )
    page_start: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="起始页")
    page_end: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="结束页")
    line_start: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="Markdown起始行号")
    line_end: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="Markdown结束行号")
    source_block_refs_json: Mapped[dict[str, Any] | None] = mapped_column(
        MYSQL_JSON,
        nullable=True,
        comment="来源解析块引用，保留页码、块号、坐标和资源文件",
    )
    source_text_hash: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="来源文本哈希")
    chunk_text: Mapped[str] = mapped_column(MYSQL_MEDIUMTEXT, nullable=False, comment="语义块正文")
    summary_text: Mapped[str | None] = mapped_column(Text, nullable=True, comment="摘要")
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(MYSQL_JSON, nullable=True, comment="附加元数据")
    created_by: Mapped[int | None] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("sys_user.id"),
        nullable=True,
        comment="创建人",
    )


class KnowledgePoint(TimestampMixin, Base):
    """知识点表。"""

    __tablename__ = "knowledge_point"
    __table_args__ = (
        Index("idx_knowledge_point_version_chapter", "knowledge_version_id", "chapter_node_id"),
        Index("idx_knowledge_point_name", "point_name"),
        {"comment": "知识点表"},
    )

    id: Mapped[int] = mapped_column(MYSQL_BIGINT_UNSIGNED, primary_key=True, autoincrement=True, comment="主键")
    knowledge_version_id: Mapped[int] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("knowledge_version.id"),
        nullable=False,
        comment="知识版本",
    )
    chapter_node_id: Mapped[int | None] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("chapter_node.id"),
        nullable=True,
        comment="章节节点",
    )
    point_code: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="知识点编码")
    point_name: Mapped[str] = mapped_column(String(255), nullable=False, comment="知识点名称")
    point_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="knowledge",
        server_default=text("'knowledge'"),
        comment="知识点类型",
    )
    importance_level: Mapped[int | None] = mapped_column(MYSQL_TINYINT_UNSIGNED, nullable=True, comment="重要度")
    difficulty_level: Mapped[int | None] = mapped_column(MYSQL_TINYINT_UNSIGNED, nullable=True, comment="难度")
    mastery_level_hint: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="掌握建议")
    tags_json: Mapped[dict[str, Any] | None] = mapped_column(MYSQL_JSON, nullable=True, comment="标签")
    summary_text: Mapped[str | None] = mapped_column(Text, nullable=True, comment="摘要")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"), comment="排序")


class KnowledgeEvidence(CreatedAtMixin, Base):
    """知识点证据表。"""

    __tablename__ = "knowledge_evidence"
    __table_args__ = (
        Index("idx_knowledge_evidence_point", "knowledge_point_id"),
        Index("idx_knowledge_evidence_semantic_chunk", "semantic_chunk_id"),
        Index("idx_knowledge_evidence_block", "parse_block_id"),
        {"comment": "知识点证据表"},
    )

    id: Mapped[int] = mapped_column(MYSQL_BIGINT_UNSIGNED, primary_key=True, autoincrement=True, comment="主键")
    knowledge_point_id: Mapped[int] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("knowledge_point.id"),
        nullable=False,
        comment="知识点",
    )
    semantic_chunk_id: Mapped[int | None] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("semantic_chunk.id"),
        nullable=True,
        comment="语义块",
    )
    parse_version_id: Mapped[int] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("parse_version.id"),
        nullable=False,
        comment="解析版本",
    )
    parse_page_id: Mapped[int | None] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("parse_page.id"),
        nullable=True,
        comment="解析页",
    )
    parse_block_id: Mapped[int | None] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("parse_block.id"),
        nullable=True,
        comment="解析块",
    )
    source_file_id: Mapped[int | None] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("file_object.id"),
        nullable=True,
        comment="来源文件",
    )
    evidence_type: Mapped[str] = mapped_column(String(32), nullable=False, comment="证据类型")
    page_no: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="页码")
    excerpt_text: Mapped[str | None] = mapped_column(Text, nullable=True, comment="原文片段")
    bbox_json: Mapped[dict[str, Any] | None] = mapped_column(MYSQL_JSON, nullable=True, comment="坐标框")
    score_value: Mapped[float | None] = mapped_column(MYSQL_DECIMAL_8_4, nullable=True, comment="证据分数")


class CurriculumPlan(TimestampMixin, Base):
    """课程大纲表。"""

    __tablename__ = "curriculum_plan"
    __table_args__ = (
        Index("uk_curriculum_plan_project_no", "project_id", "version_no", unique=True),
        Index("idx_curriculum_plan_project_status", "project_id", "version_status", "created_at"),
        {"comment": "课程大纲表"},
    )

    id: Mapped[int] = mapped_column(MYSQL_BIGINT_UNSIGNED, primary_key=True, autoincrement=True, comment="主键")
    project_id: Mapped[int] = mapped_column(MYSQL_BIGINT_UNSIGNED, ForeignKey("project.id"), nullable=False, comment="所属项目")
    knowledge_version_id: Mapped[int] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("knowledge_version.id"),
        nullable=False,
        comment="知识版本",
    )
    learner_profile_version_id: Mapped[int] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("learner_profile_version.id"),
        nullable=False,
        comment="学情版本",
    )
    parent_plan_id: Mapped[int | None] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("curriculum_plan.id"),
        nullable=True,
        comment="父课程大纲",
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False, comment="版本号")
    plan_title: Mapped[str] = mapped_column(String(255), nullable=False, comment="课程大纲标题")
    target_subject_code: Mapped[str] = mapped_column(String(32), nullable=False, comment="目标学科")
    target_grade_code: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="目标年级")
    chapter_range_json: Mapped[dict[str, Any] | None] = mapped_column(MYSQL_JSON, nullable=True, comment="章节范围")
    course_count: Mapped[int] = mapped_column(Integer, nullable=False, comment="总课次")
    session_duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False, comment="单次时长")
    generation_mode: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="ai",
        server_default=text("'ai'"),
        comment="生成模式",
    )
    version_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="ready",
        server_default=text("'ready'"),
        comment="版本状态",
    )
    summary_text: Mapped[str | None] = mapped_column(Text, nullable=True, comment="摘要")
    content_json: Mapped[dict[str, Any]] = mapped_column(MYSQL_JSON, nullable=False, comment="课程大纲内容")
    export_file_id: Mapped[int | None] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("file_object.id"),
        nullable=True,
        comment="导出文件",
    )
    created_by: Mapped[int | None] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("sys_user.id"),
        nullable=True,
        comment="创建人",
    )


class LessonPlan(TimestampMixin, Base):
    """教案表。"""

    __tablename__ = "lesson_plan"
    __table_args__ = (
        Index("uk_lesson_plan_curriculum_no", "curriculum_plan_id", "version_no", unique=True),
        Index("uk_lesson_plan_batch_session", "generation_batch_id", "class_session_no", unique=True),
        Index("idx_lesson_plan_curriculum_status", "curriculum_plan_id", "version_status", "created_at"),
        Index("idx_lesson_plan_generation_batch", "generation_batch_id", "class_session_no"),
        {"comment": "教案表"},
    )

    id: Mapped[int] = mapped_column(MYSQL_BIGINT_UNSIGNED, primary_key=True, autoincrement=True, comment="主键")
    curriculum_plan_id: Mapped[int] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("curriculum_plan.id"),
        nullable=False,
        comment="课程大纲",
    )
    generation_batch_id: Mapped[int | None] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("generation_batch.id"),
        nullable=True,
        comment="生成批次",
    )
    class_session_no: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="课次序号")
    version_no: Mapped[int] = mapped_column(Integer, nullable=False, comment="版本号")
    lesson_title: Mapped[str] = mapped_column(String(255), nullable=False, comment="教案标题")
    style_code: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="教案风格")
    version_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="ready",
        server_default=text("'ready'"),
        comment="版本状态",
    )
    summary_text: Mapped[str | None] = mapped_column(Text, nullable=True, comment="摘要")
    content_json: Mapped[dict[str, Any]] = mapped_column(MYSQL_JSON, nullable=False, comment="教案内容")
    export_file_id: Mapped[int | None] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("file_object.id"),
        nullable=True,
        comment="导出文件",
    )
    created_by: Mapped[int | None] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("sys_user.id"),
        nullable=True,
        comment="创建人",
    )


class LessonPlanGenerationItem(TimestampMixin, Base):
    """教案课次生成中间结果表。"""

    __tablename__ = "lesson_plan_generation_item"
    __table_args__ = (
        Index("uk_lesson_plan_generation_item_session", "generation_batch_id", "class_session_no", unique=True),
        Index("idx_lesson_plan_generation_item_task", "task_record_id", "item_status"),
        Index("idx_lesson_plan_generation_item_batch_status", "generation_batch_id", "item_status"),
        {"comment": "教案课次生成中间结果表"},
    )

    id: Mapped[int] = mapped_column(MYSQL_BIGINT_UNSIGNED, primary_key=True, autoincrement=True, comment="主键")
    generation_batch_id: Mapped[int] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("generation_batch.id"),
        nullable=False,
        comment="生成批次",
    )
    task_record_id: Mapped[int | None] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("task_record.id"),
        nullable=True,
        comment="任务主表",
    )
    class_session_no: Mapped[int] = mapped_column(Integer, nullable=False, comment="课次序号")
    lesson_title: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="课次标题")
    item_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="pending",
        server_default=text("'pending'"),
        comment="课次生成状态：pending/processing/success/failure",
    )
    summary_text: Mapped[str | None] = mapped_column(Text, nullable=True, comment="摘要")
    content_json: Mapped[dict[str, Any] | None] = mapped_column(MYSQL_JSON, nullable=True, comment="教案内容")
    llm_usage_json: Mapped[dict[str, Any] | None] = mapped_column(MYSQL_JSON, nullable=True, comment="LLM 用量")
    last_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="错误码")
    last_error_message: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="错误信息")
    last_error_detail_json: Mapped[dict[str, Any] | None] = mapped_column(MYSQL_JSON, nullable=True, comment="错误详情")
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"), comment="重试次数")


class AssessmentBlueprint(TimestampMixin, Base):
    """测评蓝图表。"""

    __tablename__ = "assessment_blueprint"
    __table_args__ = (
        Index("uk_assessment_blueprint_scope", "curriculum_plan_id", "scenario_type", "version_no", unique=True),
        Index("idx_assessment_blueprint_curriculum_status", "curriculum_plan_id", "version_status", "created_at"),
        {"comment": "测评蓝图表"},
    )

    id: Mapped[int] = mapped_column(MYSQL_BIGINT_UNSIGNED, primary_key=True, autoincrement=True, comment="主键")
    curriculum_plan_id: Mapped[int] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("curriculum_plan.id"),
        nullable=False,
        comment="课程大纲",
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False, comment="版本号")
    scenario_type: Mapped[str] = mapped_column(String(32), nullable=False, comment="场景类型")
    blueprint_name: Mapped[str] = mapped_column(String(255), nullable=False, comment="蓝图名称")
    version_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="ready",
        server_default=text("'ready'"),
        comment="版本状态",
    )
    strategy_json: Mapped[dict[str, Any] | None] = mapped_column(MYSQL_JSON, nullable=True, comment="策略配置")
    content_json: Mapped[dict[str, Any]] = mapped_column(MYSQL_JSON, nullable=False, comment="蓝图内容")
    export_file_id: Mapped[int | None] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("file_object.id"),
        nullable=True,
        comment="导出文件",
    )
    created_by: Mapped[int | None] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("sys_user.id"),
        nullable=True,
        comment="创建人",
    )


class GenerationBatch(TimestampMixin, Base):
    """生成批次表。"""

    __tablename__ = "generation_batch"
    __table_args__ = (
        Index("uk_generation_batch_project_no", "project_id", "batch_no", unique=True),
        Index("idx_generation_batch_status", "project_id", "batch_status", "created_at"),
        {"comment": "生成批次表"},
    )

    id: Mapped[int] = mapped_column(MYSQL_BIGINT_UNSIGNED, primary_key=True, autoincrement=True, comment="主键")
    project_id: Mapped[int] = mapped_column(MYSQL_BIGINT_UNSIGNED, ForeignKey("project.id"), nullable=False, comment="所属项目")
    batch_no: Mapped[int] = mapped_column(Integer, nullable=False, comment="批次号")
    batch_name: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="批次名称")
    trigger_mode: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="manual",
        server_default=text("'manual'"),
        comment="触发模式",
    )
    batch_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="pending",
        server_default=text("'pending'"),
        comment="批次状态",
    )
    knowledge_version_id: Mapped[int] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("knowledge_version.id"),
        nullable=False,
        comment="知识版本",
    )
    learner_profile_version_id: Mapped[int] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("learner_profile_version.id"),
        nullable=False,
        comment="学情版本",
    )
    chapter_range_json: Mapped[dict[str, Any] | None] = mapped_column(MYSQL_JSON, nullable=True, comment="章节范围快照")
    course_count: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="总课次快照")
    session_duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="单次时长快照")
    template_snapshot_json: Mapped[dict[str, Any] | None] = mapped_column(MYSQL_JSON, nullable=True, comment="模板快照")
    assessment_strategy_json: Mapped[dict[str, Any] | None] = mapped_column(MYSQL_JSON, nullable=True, comment="测评策略快照")
    pipeline_options_json: Mapped[dict[str, Any] | None] = mapped_column(MYSQL_JSON, nullable=True, comment="编排选项")
    curriculum_plan_id: Mapped[int | None] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("curriculum_plan.id"),
        nullable=True,
        comment="生成的大纲版本",
    )
    lesson_plan_id: Mapped[int | None] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("lesson_plan.id"),
        nullable=True,
        comment="生成的教案版本",
    )
    started_at: Mapped[datetime | None] = mapped_column(MYSQL_DATETIME_MS, nullable=True, comment="开始时间")
    finished_at: Mapped[datetime | None] = mapped_column(MYSQL_DATETIME_MS, nullable=True, comment="结束时间")
    created_by: Mapped[int | None] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("sys_user.id"),
        nullable=True,
        comment="创建人",
    )


class GenerationRun(TimestampMixin, Base):
    """一键生成运行表。"""

    __tablename__ = "generation_run"
    __table_args__ = (
        Index("idx_generation_run_project_status", "project_id", "run_status", "created_at"),
        {"comment": "一键生成运行表"},
    )

    id: Mapped[int] = mapped_column(MYSQL_BIGINT_UNSIGNED, primary_key=True, autoincrement=True, comment="主键")
    project_id: Mapped[int] = mapped_column(MYSQL_BIGINT_UNSIGNED, ForeignKey("project.id"), nullable=False, comment="所属项目")
    run_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="pending",
        server_default=text("'pending'"),
        comment="运行状态：pending/running/waiting_user_confirm/succeeded/failed/cancelled",
    )
    course_count: Mapped[int] = mapped_column(Integer, nullable=False, comment="课次数")
    session_duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False, comment="单次时长")
    chapter_range_json: Mapped[dict[str, Any] | None] = mapped_column(MYSQL_JSON, nullable=True, comment="章节范围")
    auto_confirm_parse: Mapped[int] = mapped_column(
        MYSQL_TINYINT,
        nullable=False,
        default=1,
        server_default=text("1"),
        comment="解析自动确认开关",
    )
    parse_version_id: Mapped[int | None] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("parse_version.id"),
        nullable=True,
        comment="本次运行使用的解析版本",
    )
    knowledge_version_id: Mapped[int | None] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("knowledge_version.id"),
        nullable=True,
        comment="本次运行使用的知识版本",
    )
    generation_batch_id: Mapped[int | None] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("generation_batch.id"),
        nullable=True,
        comment="本次运行创建的生成批次",
    )
    last_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="错误码")
    last_error_message: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="错误信息")
    blocked_reason: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="阻塞原因编码")
    started_at: Mapped[datetime | None] = mapped_column(MYSQL_DATETIME_MS, nullable=True, comment="开始时间")
    finished_at: Mapped[datetime | None] = mapped_column(MYSQL_DATETIME_MS, nullable=True, comment="结束时间")
    created_by: Mapped[int | None] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("sys_user.id"),
        nullable=True,
        comment="创建人",
    )


class CoursewareResult(TimestampMixin, Base):
    """课件结果表。"""

    __tablename__ = "courseware_result"
    __table_args__ = (
        Index("uk_courseware_result_batch_lesson", "generation_batch_id", "lesson_plan_id", unique=True),
        Index("idx_courseware_result_lesson", "lesson_plan_id", "created_at"),
        {"comment": "课件结果表"},
    )

    id: Mapped[int] = mapped_column(MYSQL_BIGINT_UNSIGNED, primary_key=True, autoincrement=True, comment="主键")
    generation_batch_id: Mapped[int] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("generation_batch.id"),
        nullable=False,
        comment="生成批次",
    )
    lesson_plan_id: Mapped[int] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("lesson_plan.id"),
        nullable=False,
        comment="教案版本",
    )
    template_code: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="模板编码")
    template_version: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="模板版本")
    result_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="success",
        server_default=text("'success'"),
        comment="结果状态",
    )
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="页数")
    page_type_stats_json: Mapped[dict[str, Any] | None] = mapped_column(MYSQL_JSON, nullable=True, comment="页面类型统计")
    structure_json: Mapped[dict[str, Any]] = mapped_column(MYSQL_JSON, nullable=False, comment="幻灯片结构")
    preview_json: Mapped[dict[str, Any] | None] = mapped_column(MYSQL_JSON, nullable=True, comment="预览信息")
    export_file_id: Mapped[int | None] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("file_object.id"),
        nullable=True,
        comment="导出文件",
    )


class PaperResult(TimestampMixin, Base):
    """作业试卷结果表。"""

    __tablename__ = "paper_result"
    __table_args__ = (
        Index("uk_paper_result_batch_scene", "generation_batch_id", "scene_type", unique=True),
        Index("idx_paper_result_blueprint", "assessment_blueprint_id", "created_at"),
        {"comment": "作业试卷结果表"},
    )

    id: Mapped[int] = mapped_column(MYSQL_BIGINT_UNSIGNED, primary_key=True, autoincrement=True, comment="主键")
    generation_batch_id: Mapped[int] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("generation_batch.id"),
        nullable=False,
        comment="生成批次",
    )
    assessment_blueprint_id: Mapped[int] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("assessment_blueprint.id"),
        nullable=False,
        comment="测评蓝图",
    )
    scene_type: Mapped[str] = mapped_column(String(32), nullable=False, comment="场景类型")
    title: Mapped[str] = mapped_column(String(255), nullable=False, comment="标题")
    result_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="success",
        server_default=text("'success'"),
        comment="结果状态",
    )
    question_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"), comment="题目数量")
    difficulty_stats_json: Mapped[dict[str, Any] | None] = mapped_column(MYSQL_JSON, nullable=True, comment="难度统计")
    paper_json: Mapped[dict[str, Any]] = mapped_column(MYSQL_JSON, nullable=False, comment="试卷内容")
    export_file_id: Mapped[int | None] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("file_object.id"),
        nullable=True,
        comment="导出文件",
    )


class QuestionItem(TimestampMixin, Base):
    """题目明细表。"""

    __tablename__ = "question_item"
    __table_args__ = (
        Index("uk_question_item_scope", "paper_result_id", "question_no", unique=True),
        Index("idx_question_item_batch_kp", "generation_batch_id", "knowledge_point_id"),
        Index("idx_question_item_type_diff", "question_type", "difficulty_level"),
        {"comment": "题目明细表"},
    )

    id: Mapped[int] = mapped_column(MYSQL_BIGINT_UNSIGNED, primary_key=True, autoincrement=True, comment="主键")
    generation_batch_id: Mapped[int] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("generation_batch.id"),
        nullable=False,
        comment="生成批次",
    )
    paper_result_id: Mapped[int] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("paper_result.id"),
        nullable=False,
        comment="试卷结果",
    )
    knowledge_point_id: Mapped[int | None] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("knowledge_point.id"),
        nullable=True,
        comment="知识点",
    )
    question_no: Mapped[int] = mapped_column(Integer, nullable=False, comment="题号")
    question_type: Mapped[str] = mapped_column(String(32), nullable=False, comment="题型")
    difficulty_level: Mapped[int | None] = mapped_column(MYSQL_TINYINT_UNSIGNED, nullable=True, comment="难度")
    score_value: Mapped[float | None] = mapped_column(MYSQL_DECIMAL_6_2, nullable=True, comment="分值")
    stem_text: Mapped[str] = mapped_column(MYSQL_MEDIUMTEXT, nullable=False, comment="题干")
    options_json: Mapped[dict[str, Any] | None] = mapped_column(MYSQL_JSON, nullable=True, comment="选项")
    answer_text: Mapped[str | None] = mapped_column(Text, nullable=True, comment="答案")
    analysis_text: Mapped[str | None] = mapped_column(Text, nullable=True, comment="解析")
    source_trace_json: Mapped[dict[str, Any] | None] = mapped_column(MYSQL_JSON, nullable=True, comment="题目来源摘要")
    question_basis_json: Mapped[dict[str, Any] | None] = mapped_column(MYSQL_JSON, nullable=True, comment="题目考查依据")


class HomeworkBlueprint(TimestampMixin, Base):
    """课后作业蓝图表（按课次维度，每课一份）。"""

    __tablename__ = "homework_blueprint"
    __table_args__ = (
        Index("uk_homework_blueprint_lesson_version", "lesson_plan_id", "version_no", unique=True),
        Index("idx_homework_blueprint_batch", "generation_batch_id"),
        Index("idx_homework_blueprint_lesson_status", "lesson_plan_id", "version_status", "created_at"),
        {"comment": "课后作业蓝图表"},
    )

    id: Mapped[int] = mapped_column(MYSQL_BIGINT_UNSIGNED, primary_key=True, autoincrement=True, comment="主键")
    lesson_plan_id: Mapped[int] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("lesson_plan.id"),
        nullable=False,
        comment="所属教案",
    )
    generation_batch_id: Mapped[int] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("generation_batch.id"),
        nullable=False,
        comment="生成批次",
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False, comment="版本号")
    blueprint_name: Mapped[str] = mapped_column(String(255), nullable=False, comment="蓝图名称")
    version_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="ready",
        server_default=text("'ready'"),
        comment="版本状态",
    )
    strategy_json: Mapped[dict[str, Any] | None] = mapped_column(MYSQL_JSON, nullable=True, comment="策略配置")
    content_json: Mapped[dict[str, Any]] = mapped_column(MYSQL_JSON, nullable=False, comment="蓝图内容")
    export_file_id: Mapped[int | None] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("file_object.id"),
        nullable=True,
        comment="导出文件",
    )
    created_by: Mapped[int | None] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("sys_user.id"),
        nullable=True,
        comment="创建人",
    )


class HomeworkResult(TimestampMixin, Base):
    """课后作业结果表（每课最多一份成功作业）。"""

    __tablename__ = "homework_result"
    __table_args__ = (
        Index("uk_homework_result_lesson", "lesson_plan_id", unique=True),
        Index("idx_homework_result_batch", "generation_batch_id", "lesson_plan_id"),
        Index("idx_homework_result_blueprint", "homework_blueprint_id", "created_at"),
        {"comment": "课后作业结果表"},
    )

    id: Mapped[int] = mapped_column(MYSQL_BIGINT_UNSIGNED, primary_key=True, autoincrement=True, comment="主键")
    generation_batch_id: Mapped[int] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("generation_batch.id"),
        nullable=False,
        comment="生成批次",
    )
    lesson_plan_id: Mapped[int] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("lesson_plan.id"),
        nullable=False,
        comment="所属教案",
    )
    homework_blueprint_id: Mapped[int] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("homework_blueprint.id"),
        nullable=False,
        comment="作业蓝图",
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False, comment="作业标题")
    result_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="success",
        server_default=text("'success'"),
        comment="结果状态",
    )
    question_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"), comment="题目数量")
    difficulty_stats_json: Mapped[dict[str, Any] | None] = mapped_column(MYSQL_JSON, nullable=True, comment="难度统计")
    content_json: Mapped[dict[str, Any]] = mapped_column(MYSQL_JSON, nullable=False, comment="作业内容")
    export_file_id: Mapped[int | None] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("file_object.id"),
        nullable=True,
        comment="导出文件",
    )


class HomeworkQuestion(TimestampMixin, Base):
    """课后作业题目明细表。"""

    __tablename__ = "homework_question"
    __table_args__ = (
        Index("uk_homework_question_scope", "homework_result_id", "question_no", unique=True),
        Index("idx_homework_question_lesson_kp", "lesson_plan_id", "knowledge_point_id"),
        Index("idx_homework_question_batch_kp", "generation_batch_id", "knowledge_point_id"),
        Index("idx_homework_question_type_diff", "question_type", "difficulty_level"),
        {"comment": "课后作业题目明细表"},
    )

    id: Mapped[int] = mapped_column(MYSQL_BIGINT_UNSIGNED, primary_key=True, autoincrement=True, comment="主键")
    generation_batch_id: Mapped[int] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("generation_batch.id"),
        nullable=False,
        comment="生成批次",
    )
    homework_result_id: Mapped[int] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("homework_result.id"),
        nullable=False,
        comment="作业结果",
    )
    lesson_plan_id: Mapped[int] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("lesson_plan.id"),
        nullable=False,
        comment="所属教案",
    )
    knowledge_point_id: Mapped[int | None] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("knowledge_point.id"),
        nullable=True,
        comment="知识点",
    )
    question_no: Mapped[int] = mapped_column(Integer, nullable=False, comment="题号")
    question_type: Mapped[str] = mapped_column(String(32), nullable=False, comment="题型")
    difficulty_level: Mapped[int | None] = mapped_column(MYSQL_TINYINT_UNSIGNED, nullable=True, comment="难度")
    score_value: Mapped[float | None] = mapped_column(MYSQL_DECIMAL_6_2, nullable=True, comment="分值")
    stem_text: Mapped[str] = mapped_column(MYSQL_MEDIUMTEXT, nullable=False, comment="题干")
    options_json: Mapped[dict[str, Any] | None] = mapped_column(MYSQL_JSON, nullable=True, comment="选项")
    answer_text: Mapped[str | None] = mapped_column(Text, nullable=True, comment="答案")
    analysis_text: Mapped[str | None] = mapped_column(Text, nullable=True, comment="解析")
    source_trace_json: Mapped[dict[str, Any] | None] = mapped_column(MYSQL_JSON, nullable=True, comment="题目来源摘要")
    question_basis_json: Mapped[dict[str, Any] | None] = mapped_column(MYSQL_JSON, nullable=True, comment="题目考查依据")


class CoverageReport(TimestampMixin, Base):
    """覆盖率报告表。"""

    __tablename__ = "coverage_report"
    __table_args__ = (
        Index("uk_coverage_report_batch", "generation_batch_id", unique=True),
        Index("idx_coverage_report_created_at", "created_at"),
        {"comment": "覆盖率报告表"},
    )

    id: Mapped[int] = mapped_column(MYSQL_BIGINT_UNSIGNED, primary_key=True, autoincrement=True, comment="主键")
    generation_batch_id: Mapped[int] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("generation_batch.id"),
        nullable=False,
        comment="生成批次",
    )
    report_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="success",
        server_default=text("'success'"),
        comment="报告状态",
    )
    coverage_rate: Mapped[float | None] = mapped_column(MYSQL_DECIMAL_6_2, nullable=True, comment="覆盖率")
    warning_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"), comment="告警数量")
    coverage_summary_json: Mapped[dict[str, Any] | None] = mapped_column(MYSQL_JSON, nullable=True, comment="覆盖摘要")
    report_json: Mapped[dict[str, Any]] = mapped_column(MYSQL_JSON, nullable=False, comment="报告内容")
    export_file_id: Mapped[int | None] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("file_object.id"),
        nullable=True,
        comment="导出文件",
    )


class TaskRecord(TimestampMixin, Base):
    """任务主表。"""

    __tablename__ = "task_record"
    __table_args__ = (
        Index("idx_task_record_project_status", "project_id", "task_status", "created_at"),
        Index("idx_task_record_batch_type", "generation_batch_id", "task_type"),
        {"comment": "任务主表"},
    )

    id: Mapped[int] = mapped_column(MYSQL_BIGINT_UNSIGNED, primary_key=True, autoincrement=True, comment="主键")
    project_id: Mapped[int] = mapped_column(MYSQL_BIGINT_UNSIGNED, ForeignKey("project.id"), nullable=False, comment="所属项目")
    generation_batch_id: Mapped[int | None] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("generation_batch.id"),
        nullable=True,
        comment="生成批次",
    )
    module_code: Mapped[str] = mapped_column(String(32), nullable=False, comment="模块编码")
    task_type: Mapped[str] = mapped_column(String(64), nullable=False, comment="任务类型")
    biz_key: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="业务键")
    task_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="pending",
        server_default=text("'pending'"),
        comment="任务状态",
    )
    queue_name: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="队列名")
    current_stage: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="当前阶段")
    progress_percent: Mapped[int] = mapped_column(
        MYSQL_TINYINT_UNSIGNED,
        nullable=False,
        default=0,
        server_default=text("0"),
        comment="进度",
    )
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"), comment="重试次数")
    max_retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=3, server_default=text("3"), comment="最大重试次数")
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="请求ID")
    worker_task_id: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="Worker任务ID")
    operator_user_id: Mapped[int | None] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("sys_user.id"),
        nullable=True,
        comment="操作人",
    )
    payload_json: Mapped[dict[str, Any] | None] = mapped_column(MYSQL_JSON, nullable=True, comment="任务载荷")
    result_json: Mapped[dict[str, Any] | None] = mapped_column(MYSQL_JSON, nullable=True, comment="任务结果")
    last_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="错误码")
    last_error_message: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="错误信息")
    started_at: Mapped[datetime | None] = mapped_column(MYSQL_DATETIME_MS, nullable=True, comment="开始时间")
    finished_at: Mapped[datetime | None] = mapped_column(MYSQL_DATETIME_MS, nullable=True, comment="结束时间")
    # 长任务自报心跳：与 updated_at 二选一参与 reaper 判定，使长 LLM 阶段不被误判
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(MYSQL_DATETIME_MS, nullable=True, comment="最近心跳时间")
    # 执行实例 ID：每次 dispatch / reaper 重排都会轮换，配合 CAS UPDATE 防止两个 worker 并发写库
    execution_attempt_id: Mapped[str | None] = mapped_column(String(36), nullable=True, comment="本次执行实例ID")


class TaskStepRecord(TimestampMixin, Base):
    """任务步骤表。"""

    __tablename__ = "task_step_record"
    __table_args__ = (
        Index("uk_task_step_record_scope", "task_record_id", "step_code", unique=True),
        Index("idx_task_step_status", "task_record_id", "step_status"),
        {"comment": "任务步骤表"},
    )

    id: Mapped[int] = mapped_column(MYSQL_BIGINT_UNSIGNED, primary_key=True, autoincrement=True, comment="主键")
    task_record_id: Mapped[int] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("task_record.id"),
        nullable=False,
        comment="任务主表",
    )
    step_code: Mapped[str] = mapped_column(String(64), nullable=False, comment="步骤编码")
    step_name: Mapped[str] = mapped_column(String(128), nullable=False, comment="步骤名称")
    step_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"), comment="步骤顺序")
    step_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="pending",
        server_default=text("'pending'"),
        comment="步骤状态",
    )
    progress_percent: Mapped[int] = mapped_column(
        MYSQL_TINYINT_UNSIGNED,
        nullable=False,
        default=0,
        server_default=text("0"),
        comment="步骤进度",
    )
    detail_json: Mapped[dict[str, Any] | None] = mapped_column(MYSQL_JSON, nullable=True, comment="步骤明细")
    started_at: Mapped[datetime | None] = mapped_column(MYSQL_DATETIME_MS, nullable=True, comment="开始时间")
    finished_at: Mapped[datetime | None] = mapped_column(MYSQL_DATETIME_MS, nullable=True, comment="结束时间")


class GenerationTrace(CreatedAtMixin, Base):
    """生成追溯表。"""

    __tablename__ = "generation_trace"
    __table_args__ = (
        Index("idx_generation_trace_batch_target", "generation_batch_id", "target_type", "target_id"),
        Index("idx_generation_trace_source", "source_type", "source_id"),
        {"comment": "生成追溯表"},
    )

    id: Mapped[int] = mapped_column(MYSQL_BIGINT_UNSIGNED, primary_key=True, autoincrement=True, comment="主键")
    generation_batch_id: Mapped[int] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("generation_batch.id"),
        nullable=False,
        comment="生成批次",
    )
    trace_type: Mapped[str] = mapped_column(String(32), nullable=False, comment="追溯类型")
    target_type: Mapped[str] = mapped_column(String(32), nullable=False, comment="目标类型")
    target_id: Mapped[int] = mapped_column(MYSQL_BIGINT_UNSIGNED, nullable=False, comment="目标ID")
    source_type: Mapped[str] = mapped_column(String(32), nullable=False, comment="来源类型")
    source_id: Mapped[str] = mapped_column(String(64), nullable=False, comment="来源ID")
    source_rank: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="来源排序")
    source_score: Mapped[float | None] = mapped_column(MYSQL_DECIMAL_8_4, nullable=True, comment="来源分数")
    evidence_text: Mapped[str | None] = mapped_column(Text, nullable=True, comment="证据文本")
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(MYSQL_JSON, nullable=True, comment="附加元数据")


class AuditLog(CreatedAtMixin, Base):
    """审计日志表。"""

    __tablename__ = "audit_log"
    __table_args__ = (
        Index("idx_audit_log_project_created_at", "project_id", "created_at"),
        Index("idx_audit_log_module_action", "module_code", "action_code", "created_at"),
        {"comment": "审计日志表"},
    )

    id: Mapped[int] = mapped_column(MYSQL_BIGINT_UNSIGNED, primary_key=True, autoincrement=True, comment="主键")
    project_id: Mapped[int | None] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("project.id"),
        nullable=True,
        comment="所属项目",
    )
    task_record_id: Mapped[int | None] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("task_record.id"),
        nullable=True,
        comment="任务",
    )
    operator_user_id: Mapped[int | None] = mapped_column(
        MYSQL_BIGINT_UNSIGNED,
        ForeignKey("sys_user.id"),
        nullable=True,
        comment="操作人",
    )
    module_code: Mapped[str] = mapped_column(String(32), nullable=False, comment="模块编码")
    action_code: Mapped[str] = mapped_column(String(64), nullable=False, comment="动作编码")
    biz_type: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="业务类型")
    biz_id: Mapped[int | None] = mapped_column(MYSQL_BIGINT_UNSIGNED, nullable=True, comment="业务主键")
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="请求ID")
    action_result: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="success",
        server_default=text("'success'"),
        comment="动作结果",
    )
    detail_json: Mapped[dict[str, Any] | None] = mapped_column(MYSQL_JSON, nullable=True, comment="明细")
