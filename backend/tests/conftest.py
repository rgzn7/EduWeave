"""
@Date: 2026-05-03
@Author: xisy
@Discription: 测试环境公共夹具
"""

import os
from collections.abc import Generator
from io import BytesIO
from pathlib import Path
from uuid import uuid4
from urllib.parse import quote_plus

os.environ.setdefault("APP_NAME", "EduWeave Backend Test")
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("APP_HOST", "127.0.0.1")
os.environ.setdefault("APP_PORT", "8001")
os.environ.setdefault("APP_VERSION", "0.1.0-test")
os.environ.setdefault("APP_LOAD_DOTENV", "0")
os.environ.setdefault("API_V1_PREFIX", "/api/v1")
os.environ.setdefault("LOG_LEVEL", "INFO")
os.environ.setdefault("CORS_ALLOWED_ORIGINS", "http://localhost:5173")
os.environ.setdefault("MYSQL_HOST", "127.0.0.1")
os.environ.setdefault("MYSQL_PORT", "3306")
os.environ.setdefault("MYSQL_USER", "root")
os.environ.setdefault("MYSQL_PASSWORD", "boss1114")
os.environ.setdefault("MYSQL_DATABASE", "eduweave")
os.environ.setdefault("REDIS_URL", "redis://127.0.0.1:6379/0")
os.environ.setdefault("TASK_EAGER_MODE", "1")
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "120")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("OBS_ENDPOINT", "https://obs.test.example.com")
os.environ.setdefault("OBS_AK", "test-ak")
os.environ.setdefault("OBS_SK", "test-sk")
os.environ.setdefault("OBS_BUCKET", "test-bucket")
os.environ.setdefault("OBS_BASE_PREFIX", "projects")
os.environ.setdefault("LLM_API_BASE_URL", "https://llm.test.example.com/v1")
os.environ.setdefault("LLM_API_KEY", "test-llm-key")
os.environ.setdefault("LLM_MODEL", "test-llm-model")
os.environ.setdefault("LLM_TIMEOUT_SECONDS", "60")
os.environ.setdefault("EMBEDDING_API_BASE_URL", "https://embedding.test.example.com/v1")
os.environ.setdefault("EMBEDDING_API_KEY", "test-embedding-key")
os.environ.setdefault("EMBEDDING_MODEL", "test-embedding-model")
os.environ.setdefault("EMBEDDING_TIMEOUT_SECONDS", "60")
os.environ.setdefault("RACCOON_API_HOST", "https://raccoon.test.example.com")
os.environ.setdefault("RACCOON_API_TOKEN", "test-raccoon-key")
os.environ.setdefault("RACCOON_REQUEST_TIMEOUT_SECONDS", "60")
os.environ.setdefault("RACCOON_POLL_INTERVAL_SECONDS", "1")
os.environ.setdefault("RACCOON_SHORT_POLL_TIMEOUT_SECONDS", "1")
os.environ.setdefault("MILVUS_URI", "http://127.0.0.1:19530")
os.environ.setdefault("MILVUS_TOKEN", "")
os.environ.setdefault("MILVUS_DB_NAME", "default")
os.environ.setdefault("MILVUS_COLLECTION_PREFIX", "eduweave_test")
os.environ.setdefault("MILVUS_EMBEDDING_DIM", "4")
os.environ.setdefault("MILVUS_INDEX_TYPE", "HNSW")
os.environ.setdefault("MILVUS_METRIC_TYPE", "COSINE")

import pytest
import pymysql
from fastapi.testclient import TestClient
from pypdf import PdfReader
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.core.database import get_db_session
from app.core.security import hash_password
from app.main import app
from app.modules.auth.models import SysUser
from app.shared.document import LocalDocxParseService
from app.shared.mineru import NormalizedBlock, NormalizedDocument, NormalizedPage, MineruDocumentService
from app.shared.storage import ObsStorageClient

TEST_PASSWORD = "Teacher@123"
SCHEMA_SQL_PATH = Path(__file__).resolve().parents[2] / "sql" / "20260430_eduweave_mysql_28_tables.sql"
HOMEWORK_SCHEMA_SQL_PATH = Path(__file__).resolve().parents[2] / "sql" / "20260525_eduweave_homework_tables.sql"


def build_mysql_uri(database_name: str) -> str:
    """构建指定数据库的 SQLAlchemy 连接串。"""
    settings = get_settings()
    return (
        f"mysql+pymysql://{quote_plus(settings.mysql_user)}:{quote_plus(settings.mysql_password)}"
        f"@{settings.mysql_host}:{settings.mysql_port}/{database_name}?charset=utf8mb4"
    )


def execute_schema_sql(database_name: str) -> None:
    """向指定 MySQL 数据库执行基础 28 张表 + homework 增量 schema 脚本。"""
    settings = get_settings()
    connection = pymysql.connect(
        host=settings.mysql_host,
        port=settings.mysql_port,
        user=settings.mysql_user,
        password=settings.mysql_password,
        database=database_name,
        charset="utf8mb4",
        autocommit=True,
    )
    try:
        all_statements: list[str] = []
        for schema_path in (SCHEMA_SQL_PATH, HOMEWORK_SCHEMA_SQL_PATH):
            raw_script = schema_path.read_text(encoding="utf-8")
            filtered_lines: list[str] = []
            skip_database_block = False
            for line in raw_script.splitlines():
                stripped = line.strip()
                if stripped.startswith("--"):
                    continue
                if stripped.startswith("CREATE DATABASE IF NOT EXISTS"):
                    skip_database_block = True
                    continue
                if skip_database_block:
                    if stripped.endswith(";"):
                        skip_database_block = False
                    continue
                if stripped.startswith("USE "):
                    continue
                filtered_lines.append(line)
            all_statements.extend(
                statement.strip()
                for statement in "\n".join(filtered_lines).split(";")
                if statement.strip()
            )
        with connection.cursor() as cursor:
            for statement in all_statements:
                cursor.execute(statement)
    finally:
        connection.close()


@pytest.fixture(scope="session")
def mysql_test_database_name() -> Generator[str, None, None]:
    """创建供测试使用的临时 MySQL 数据库。"""
    settings = get_settings()
    database_name = f"eduweave_test_{uuid4().hex[:8]}"
    admin_connection = pymysql.connect(
        host=settings.mysql_host,
        port=settings.mysql_port,
        user=settings.mysql_user,
        password=settings.mysql_password,
        database="mysql",
        charset="utf8mb4",
        autocommit=True,
    )
    try:
        with admin_connection.cursor() as cursor:
            cursor.execute(f"DROP DATABASE IF EXISTS `{database_name}`")
            cursor.execute(
                f"CREATE DATABASE `{database_name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
        execute_schema_sql(database_name)
        yield database_name
    finally:
        with admin_connection.cursor() as cursor:
            cursor.execute(f"DROP DATABASE IF EXISTS `{database_name}`")
        admin_connection.close()


@pytest.fixture()
def mysql_session_factory(mysql_test_database_name):
    """提供 MySQL 会话工厂。"""
    engine = create_engine(
        build_mysql_uri(mysql_test_database_name),
        pool_pre_ping=True,
        future=True,
    )
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, class_=Session)
    try:
        yield factory
    finally:
        engine.dispose()


@pytest.fixture()
def seeded_session_factory(mysql_session_factory):
    """初始化测试教师账号并返回会话工厂。"""
    session = mysql_session_factory()
    try:
        session.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
        for table_name in [
            "audit_log",
            "generation_trace",
            "task_step_record",
            "task_record",
            "coverage_report",
            "homework_question",
            "homework_result",
            "homework_blueprint",
            "question_item",
            "paper_result",
            "courseware_result",
            "generation_batch",
            "assessment_blueprint",
            "lesson_plan",
            "curriculum_plan",
            "knowledge_evidence",
            "knowledge_point",
            "semantic_chunk",
            "chapter_node",
            "knowledge_version",
            "parse_issue",
            "parse_block",
            "parse_page",
            "parse_version",
            "learner_profile_record",
            "learner_profile_version",
            "learner_profile_file",
            "textbook_version",
            "file_object",
            "project",
            "sys_user",
        ]:
            session.execute(text(f"DELETE FROM {table_name}"))
        session.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
        session.commit()
        session.add_all(
            [
                SysUser(
                    username="teacher_demo",
                    display_name="示例教师",
                    password_hash=hash_password(TEST_PASSWORD),
                    role_code="teacher",
                    status="active",
                ),
                SysUser(
                    username="teacher_disabled",
                    display_name="禁用教师",
                    password_hash=hash_password(TEST_PASSWORD),
                    role_code="teacher",
                    status="disabled",
                ),
            ]
        )
        session.commit()
        yield mysql_session_factory
    finally:
        session.close()


@pytest.fixture()
def client(seeded_session_factory):
    """提供测试客户端并覆写数据库依赖。"""

    def override_get_db_session():
        session = seeded_session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db_session] = override_get_db_session

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def mock_obs_storage(monkeypatch: pytest.MonkeyPatch):
    """使用内存对象模拟 OBS 读写。"""
    storage: dict[str, bytes] = {}

    def fake_upload_bytes(self, object_key: str, content: bytes, content_type=None, metadata=None):
        _ = (self, content_type, metadata)
        storage[object_key] = content
        return {
            "bucket_name": get_settings().obs_bucket,
            "object_key": object_key,
            "etag": "fake-etag",
            "request_id": "fake-request-id",
        }

    def fake_download_bytes(self, object_key: str) -> bytes:
        return storage[object_key]

    def fake_delete_object(self, object_key: str) -> bool:
        storage.pop(object_key, None)
        return True

    def fake_head_object(self, object_key: str) -> dict[str, int]:
        if object_key not in storage:
            raise RuntimeError("对象不存在")
        return {"etag": "fake-etag", "content_length": len(storage[object_key]), "last_modified": None}

    def fake_create_download_signed_url(self, object_key: str, expires_in_seconds=None):  # noqa: ANN001
        _ = (self, expires_in_seconds)
        if object_key not in storage:
            raise RuntimeError("对象不存在")
        return f"https://obs.test.example.com/{object_key}?signed=fake"

    monkeypatch.setattr(ObsStorageClient, "upload_bytes", fake_upload_bytes)
    monkeypatch.setattr(ObsStorageClient, "download_bytes", fake_download_bytes)
    monkeypatch.setattr(ObsStorageClient, "delete_object", fake_delete_object)
    monkeypatch.setattr(ObsStorageClient, "head_object", fake_head_object)
    monkeypatch.setattr(ObsStorageClient, "create_download_signed_url", fake_create_download_signed_url)
    yield storage


@pytest.fixture(autouse=True)
def mock_mineru_service(monkeypatch: pytest.MonkeyPatch):
    """用内存桩替换 MinerU 实际调用。"""

    def fake_parse_document(self, *, file_name: str, content: bytes, strategy_code: str, data_id: str, language=None):  # noqa: ANN001
        _ = (self, strategy_code, language)
        if file_name.lower().endswith((".doc", ".docx")):
            markdown_text = (
                "王xx — 学情分析\n"
                "一、基本信息\n"
                "姓名\n王xx\n"
                "所属地区\n上海\n"
                "年级\n三年级\n"
                "学习科目\n语文、数学\n"
                "二、使用教材\n"
                "科目\n教材版本\n"
                "语文\n人民教育出版社-语文-三年级下册\n"
                "数学\n北京出版社-数学-三年级下册\n"
                "三、科目成绩\n"
                "语文：89分（月考，三年级上学期期中考试）\n"
                "数学：82分（期末质检，三年级上学期期末考试）\n"
                "四、学生基本情况描述\n"
                "该学生认知理解能力较强，阅读理解题目中寻找关键信息的准确率较高，作文思路清晰。"
                "数学方面，基础计算能力尚可，但乘法口诀记忆尚不牢固，遇到需要逆向思维的题目时容易卡壳。"
                "课堂注意力基本能保持30分钟左右，课后作业完成及时，但存在粗心大意的毛病。\n"
                "五、培训时间规划\n"
                "计划每周安排2次数学课（每次2课时），重点训练乘法运算能力和应用题分析能力；"
                "每周1次语文课（每次2课时），侧重阅读理解能力和看图写话表达能力。预计在接下来的12次课程后，"
                "乘法运算熟练度和逆向思维解题能力明显提升，阅读理解得分率改善。"
            )
            raw_blocks = [
                {"page_idx": 0, "type": "heading", "text": "学情分析"},
                {"page_idx": 0, "type": "paragraph", "text": markdown_text},
            ]
            page = NormalizedPage(
                page_no=1,
                text_content=markdown_text,
                markdown_content=markdown_text,
                layout_json={"raw_items": raw_blocks},
                blocks=[
                    NormalizedBlock(
                        page_no=1,
                        block_no=1,
                        block_type="paragraph",
                        text_content=markdown_text,
                        markdown_content=markdown_text,
                    )
                ],
            )
            return NormalizedDocument(
                batch_id=f"batch-{data_id}",
                file_name=file_name,
                data_id=data_id,
                model_version="vlm",
                markdown_text=markdown_text,
                content_list_json=raw_blocks,
                pages=[page],
                full_zip_bytes=b"fake-profile-zip",
                asset_files={"images/profile_preview.png": b"profile-preview"},
                raw_metadata={"mocked": True},
            )

        reader = PdfReader(BytesIO(content))
        page_count = len(reader.pages)
        pages: list[NormalizedPage] = []
        raw_blocks: list[dict] = []
        for page_index in range(page_count):
            page_no = page_index + 1
            heading_text = f"第{page_no}页标题"
            paragraph_text = f"{file_name} 第{page_no}页解析内容"
            page_blocks = [
                NormalizedBlock(
                    page_no=page_no,
                    block_no=1,
                    block_type="heading",
                    text_content=heading_text,
                    markdown_content=f"# {heading_text}",
                    heading_level=1,
                ),
                NormalizedBlock(
                    page_no=page_no,
                    block_no=2,
                    block_type="paragraph",
                    text_content=paragraph_text,
                    markdown_content=paragraph_text,
                    asset_relative_path=f"images/page_{page_no}.png",
                    origin_ref_json={"page_idx": page_index, "img_path": f"images/page_{page_no}.png"},
                ),
            ]
            pages.append(
                NormalizedPage(
                    page_no=page_no,
                    text_content=f"{heading_text}\n{paragraph_text}",
                    markdown_content=f"# {heading_text}\n\n{paragraph_text}",
                    layout_json={"raw_items": [{"page_idx": page_index}]},
                    blocks=page_blocks,
                )
            )
            raw_blocks.extend(
                [
                    {"page_idx": page_index, "type": "heading", "text": heading_text},
                    {"page_idx": page_index, "type": "paragraph", "text": paragraph_text, "img_path": f"images/page_{page_no}.png"},
                ]
            )
        return NormalizedDocument(
            batch_id=f"batch-{data_id}",
            file_name=file_name,
            data_id=data_id,
            model_version="vlm",
            markdown_text="\n\n".join(page.markdown_content or "" for page in pages),
            content_list_json=raw_blocks,
            pages=pages,
            full_zip_bytes=b"fake-parse-zip",
            asset_files={f"images/page_{index + 1}.png": f"page-{index + 1}".encode("utf-8") for index in range(page_count)},
            raw_metadata={"mocked": True},
        )

    monkeypatch.setattr(MineruDocumentService, "parse_document", fake_parse_document)


@pytest.fixture(autouse=True)
def mock_local_docx_parser(monkeypatch: pytest.MonkeyPatch):
    """用内存桩替换学情本地 docx 解析，避免测试依赖真实 docx 二进制内容。"""

    def fake_parse_document(self, *, file_name: str, content: bytes, data_id: str):  # noqa: ANN001
        _ = (self, content)
        markdown_text = (
            "王xx — 学情分析\n"
            "一、基本信息\n"
            "姓名\n王xx\n"
            "所属地区\n上海\n"
            "年级\n三年级\n"
            "学习科目\n语文、数学\n"
            "二、使用教材\n"
            "科目\n教材版本\n"
            "语文\n人民教育出版社-语文-三年级下册\n"
            "数学\n北京出版社-数学-三年级下册\n"
            "三、科目成绩\n"
            "语文：89分（月考，三年级上学期期中考试）\n"
            "数学：82分（期末质检，三年级上学期期末考试）\n"
            "四、学生基本情况描述\n"
            "该学生认知理解能力较强，阅读理解题目中寻找关键信息的准确率较高，作文思路清晰。"
            "数学方面，基础计算能力尚可，但乘法口诀记忆尚不牢固，遇到需要逆向思维的题目时容易卡壳。"
            "课堂注意力基本能保持30分钟左右，课后作业完成及时，但存在粗心大意的毛病。\n"
            "五、培训时间规划\n"
            "计划每周安排2次数学课（每次2课时），重点训练乘法运算能力和应用题分析能力；"
            "每周1次语文课（每次2课时），侧重阅读理解能力和看图写话表达能力。预计在接下来的12次课程后，"
            "乘法运算熟练度和逆向思维解题能力明显提升，阅读理解得分率改善。"
        )
        raw_blocks = [
            {"page_idx": 0, "type": "paragraph", "text": markdown_text},
        ]
        block = NormalizedBlock(
            page_no=1,
            block_no=1,
            block_type="paragraph",
            text_content=markdown_text,
            markdown_content=markdown_text,
        )
        page = NormalizedPage(
            page_no=1,
            text_content=markdown_text,
            markdown_content=markdown_text,
            layout_json={"raw_items": raw_blocks},
            blocks=[block],
        )
        return NormalizedDocument(
            batch_id=f"local-{data_id}",
            file_name=file_name,
            data_id=data_id,
            model_version="local_docx",
            markdown_text=markdown_text,
            content_list_json=raw_blocks,
            pages=[page],
            full_zip_bytes=content or b"fake-profile-zip",
            asset_files={},
            raw_metadata={"mocked": True, "parser": "local_docx"},
        )

    monkeypatch.setattr(LocalDocxParseService, "parse_document", fake_parse_document)
