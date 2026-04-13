"""
@Date: 2026-04-11
@Author: xisy
@Discription: 应用配置定义
"""

from functools import lru_cache
import os
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, PydanticBaseSettingsSource, SettingsConfigDict


class Settings(BaseSettings):
    """集中式应用配置。"""

    app_name: str = "EduWeave Backend"
    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_version: str = "0.1.0"
    api_v1_prefix: str = "/api/v1"
    log_level: str = "INFO"
    cors_allowed_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)

    mysql_host: str
    mysql_port: int = 3306
    mysql_user: str
    mysql_password: str
    mysql_database: str = "eduweave"

    redis_url: str
    task_eager_mode: bool = False

    jwt_secret: str
    jwt_access_token_expire_minutes: int = 120
    jwt_algorithm: str = "HS256"

    obs_endpoint: str
    obs_ak: str
    obs_sk: str
    obs_bucket: str
    obs_base_prefix: str = "projects"

    milvus_uri: str
    milvus_token: str | None = None
    milvus_db_name: str = "default"
    milvus_collection_prefix: str | None = None
    milvus_embedding_dim: int
    milvus_index_type: str = "HNSW"
    milvus_metric_type: str = "COSINE"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls,
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """允许在测试场景显式关闭 .env 注入，避免本地环境污染单测。"""
        should_load_dotenv = os.environ.get("APP_LOAD_DOTENV", "1").strip().lower() not in {"0", "false", "no"}
        if should_load_dotenv:
            return (init_settings, env_settings, dotenv_settings, file_secret_settings)
        return (init_settings, env_settings, file_secret_settings)

    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def parse_cors_allowed_origins(cls, value: str | list[str]) -> list[str]:
        """兼容逗号分隔与列表形式的跨域配置。"""
        if isinstance(value, list):
            return value
        if not value:
            return []
        return [item.strip() for item in value.split(",") if item.strip()]

    @field_validator("jwt_secret")
    @classmethod
    def validate_jwt_secret(cls, value: str) -> str:
        """校验 JWT 密钥必须提供有效值。"""
        normalized_value = value.strip()
        if not normalized_value:
            raise ValueError("JWT_SECRET 不能为空")
        return normalized_value

    @field_validator("milvus_uri")
    @classmethod
    def validate_milvus_uri(cls, value: str) -> str:
        """校验 Milvus 连接地址。"""
        normalized_value = value.strip()
        if not normalized_value:
            raise ValueError("MILVUS_URI 不能为空")
        return normalized_value

    @field_validator("milvus_embedding_dim")
    @classmethod
    def validate_milvus_embedding_dim(cls, value: int) -> int:
        """校验向量维度必须为正整数。"""
        if value <= 0:
            raise ValueError("MILVUS_EMBEDDING_DIM 必须大于 0")
        return value

    @field_validator("milvus_collection_prefix", mode="before")
    @classmethod
    def normalize_milvus_collection_prefix(cls, value: str | None) -> str | None:
        """将空前缀归一为 None。"""
        if value is None:
            return None
        normalized_value = value.strip()
        if not normalized_value:
            return None
        return normalized_value

    @property
    def sqlalchemy_database_uri(self) -> str:
        """拼接 SQLAlchemy 数据库连接串。"""
        return (
            f"mysql+pymysql://{self.mysql_user}:{self.mysql_password}"
            f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_database}?charset=utf8mb4"
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """获取缓存后的配置对象。"""
    return Settings()
