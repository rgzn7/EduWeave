"""
@Date: 2026-05-27
@Author: xisy
@Discription: 配置模型测试
"""

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def apply_required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """写入测试所需最小环境变量。"""
    monkeypatch.setenv("APP_LOAD_DOTENV", "0")
    monkeypatch.setenv("MYSQL_HOST", "127.0.0.1")
    monkeypatch.setenv("MYSQL_PORT", "3306")
    monkeypatch.setenv("MYSQL_USER", "root")
    monkeypatch.setenv("MYSQL_PASSWORD", "boss1114")
    monkeypatch.setenv("MYSQL_DATABASE", "eduweave")
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:6379/0")
    monkeypatch.setenv("OBS_ENDPOINT", "https://obs.test.example.com")
    monkeypatch.setenv("OBS_AK", "test-ak")
    monkeypatch.setenv("OBS_SK", "test-sk")
    monkeypatch.setenv("OBS_BUCKET", "test-bucket")
    monkeypatch.setenv("OBS_BASE_PREFIX", "projects")
    monkeypatch.setenv("MILVUS_URI", "http://127.0.0.1:19530")
    monkeypatch.setenv("MILVUS_DB_NAME", "default")
    monkeypatch.setenv("MILVUS_COLLECTION_PREFIX", "eduweave_test")
    monkeypatch.setenv("MILVUS_EMBEDDING_DIM", "4")


def test_missing_jwt_secret_should_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    """缺少 JWT_SECRET 时应启动失败。"""
    apply_required_env(monkeypatch)
    monkeypatch.delenv("JWT_SECRET", raising=False)
    with pytest.raises(ValidationError):
        Settings()


def test_missing_milvus_uri_should_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    """缺少 MILVUS_URI 时应启动失败。"""
    apply_required_env(monkeypatch)
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.delenv("MILVUS_URI", raising=False)
    with pytest.raises(ValidationError):
        Settings()


def test_missing_milvus_embedding_dim_should_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    """缺少 MILVUS_EMBEDDING_DIM 时应启动失败。"""
    apply_required_env(monkeypatch)
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.delenv("MILVUS_EMBEDDING_DIM", raising=False)
    with pytest.raises(ValidationError):
        Settings()


def test_blank_milvus_collection_prefix_should_be_normalized_to_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """空的 Milvus 集合前缀应归一为 None。"""
    apply_required_env(monkeypatch)
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.setenv("MILVUS_COLLECTION_PREFIX", "   ")

    settings = Settings()

    assert settings.milvus_collection_prefix is None


def test_llm_reasoning_effort_should_be_optional_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    """LLM 推理强度配置应为空关闭、有值开启。"""
    apply_required_env(monkeypatch)
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.setenv("LLM_REASONING_EFFORT", "   ")

    settings = Settings()

    assert settings.llm_reasoning_effort is None

    monkeypatch.setenv("LLM_REASONING_EFFORT", "medium")
    settings = Settings()

    assert settings.llm_reasoning_effort == "medium"


def test_llm_api_format_should_support_response_and_chat(monkeypatch: pytest.MonkeyPatch) -> None:
    """结构化 LLM 调用格式应支持 response 与 chat。"""
    apply_required_env(monkeypatch)
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.delenv("LLM_API_FORMAT", raising=False)

    settings = Settings()

    assert settings.llm_api_format == "response"

    monkeypatch.setenv("LLM_API_FORMAT", "chat_completions")
    settings = Settings()

    assert settings.llm_api_format == "chat"

    monkeypatch.setenv("LLM_API_FORMAT", "responses")
    settings = Settings()

    assert settings.llm_api_format == "response"


def test_invalid_llm_api_format_should_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    """结构化 LLM 调用格式非法时应启动失败。"""
    apply_required_env(monkeypatch)
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.setenv("LLM_API_FORMAT", "legacy")

    with pytest.raises(ValidationError):
        Settings()


def test_knowledge_extract_max_concurrency_should_default_to_ten(monkeypatch: pytest.MonkeyPatch) -> None:
    """知识抽取语义块并发数默认应为 10。"""
    apply_required_env(monkeypatch)
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.delenv("KNOWLEDGE_EXTRACT_MAX_CONCURRENCY", raising=False)

    settings = Settings()

    assert settings.knowledge_extract_max_concurrency == 10


def test_knowledge_extract_max_concurrency_should_allow_ten(monkeypatch: pytest.MonkeyPatch) -> None:
    """知识抽取语义块并发数应允许设置为 10。"""
    apply_required_env(monkeypatch)
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.setenv("KNOWLEDGE_EXTRACT_MAX_CONCURRENCY", "10")

    settings = Settings()

    assert settings.knowledge_extract_max_concurrency == 10


@pytest.mark.parametrize("value", ["0", "11"])
def test_invalid_knowledge_extract_max_concurrency_should_fail(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    """知识抽取语义块并发数超出 1 到 10 时应启动失败。"""
    apply_required_env(monkeypatch)
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.setenv("KNOWLEDGE_EXTRACT_MAX_CONCURRENCY", value)

    with pytest.raises(ValidationError):
        Settings()


def test_lesson_plan_max_concurrency_should_default_to_ten(monkeypatch: pytest.MonkeyPatch) -> None:
    """教案生成并发数默认应为 10。"""
    apply_required_env(monkeypatch)
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.delenv("LESSON_PLAN_MAX_CONCURRENCY", raising=False)

    settings = Settings()

    assert settings.lesson_plan_max_concurrency == 10


def test_lesson_plan_max_concurrency_should_allow_ten(monkeypatch: pytest.MonkeyPatch) -> None:
    """教案生成并发数应允许设置为 10。"""
    apply_required_env(monkeypatch)
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.setenv("LESSON_PLAN_MAX_CONCURRENCY", "10")

    settings = Settings()

    assert settings.lesson_plan_max_concurrency == 10


@pytest.mark.parametrize("value", ["0", "11"])
def test_invalid_lesson_plan_max_concurrency_should_fail(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    """教案生成并发数超出 1 到 10 时应启动失败。"""
    apply_required_env(monkeypatch)
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.setenv("LESSON_PLAN_MAX_CONCURRENCY", value)

    with pytest.raises(ValidationError):
        Settings()
