"""
@Date: 2026-05-28
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
    # 任务卡在 processing 超过该秒数视为僵尸任务，由 reaper 回收
    task_stale_threshold_seconds: int = 1800
    # reaper 周期扫描间隔（秒）
    task_reaper_interval_seconds: int = 300
    # 任务级失败重试的指数退避基数（秒）
    task_retry_backoff_base_seconds: int = 30
    # 课件 Raccoon PPT 远程状态后台复查间隔（秒）
    courseware_remote_poll_interval_seconds: int = 60

    jwt_secret: str
    jwt_access_token_expire_minutes: int = 120
    jwt_algorithm: str = "HS256"

    obs_endpoint: str
    obs_ak: str
    obs_sk: str
    obs_bucket: str
    obs_base_prefix: str = "projects"
    obs_signed_url_expire_seconds: int = 3600

    mineru_api_base_url: str = "https://mineru.net"
    mineru_api_token: str | None = None
    mineru_model_version: str = "vlm"
    mineru_poll_interval_seconds: int = 3
    mineru_poll_timeout_seconds: int = 600
    mineru_default_language: str = "ch"
    mineru_enable_formula: bool = True
    mineru_enable_table: bool = True

    llm_api_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str | None = None
    llm_model: str | None = None
    llm_api_format: str = "response"
    llm_reasoning_effort: str | None = None
    llm_timeout_seconds: int = 60
    llm_max_retries: int = 2
    llm_retry_base_seconds: int = 1
    llm_stream_error_detail_max_chars: int = 4096
    llm_parse_repair_max_attempts: int = 2
    # 多模态开关：开启前需将 llm_model 配置为具备视觉能力的模型，否则保持关闭零影响。
    llm_multimodal_enabled: bool = False
    # 单次教案生成注入的证据图片数量上限，控制 token 与成本。
    llm_multimodal_max_images: int = 6
    # 是否给稳定前缀消息注入显式 cache_control 标记（仅 Anthropic 兼容端有效；OpenAI 兼容端会忽略）。
    llm_prompt_cache_explicit_markers: bool = False
    # 是否在请求载荷上注入 prompt_cache_key，让多账号代理稳定命中同一前缀缓存分片。
    llm_prompt_cache_identity_enabled: bool = True
    # 是否额外注入 user 字段；默认关闭，部分 OpenAI 代理在 Responses 模式下不兼容 user 字段。
    llm_prompt_cache_user_enabled: bool = False
    # prompt_cache_key 前缀；最终下发为 f"{prefix}-{biz_key}"，按业务键分片以最大化前缀复用。
    llm_prompt_cache_key_prefix: str = "eduweave"
    # 知识抽取阶段按语义块并行调用 LLM 的最大并发数，1 等价于串行。
    knowledge_extract_max_concurrency: int = 10
    # 教案生成阶段第 1 课暖缓存后，其余课次并行调用 LLM 的最大并发数，1 等价于串行。
    lesson_plan_max_concurrency: int = 10
    # 单课次教案生成在 LLM 客户端重试耗尽后的业务级重试次数，0 表示不重试。
    lesson_plan_session_max_retries: int = 2
    # 单课次教案生成业务级重试的指数退避基数（秒）。
    lesson_plan_session_retry_base_seconds: int = 3

    embedding_api_base_url: str = "https://api.openai.com/v1"
    embedding_api_key: str | None = None
    embedding_model: str | None = None
    embedding_timeout_seconds: int = 60

    raccoon_api_host: str = "https://xiaohuanxiong.com"
    raccoon_api_token: str | None = None
    raccoon_request_timeout_seconds: int = 60
    raccoon_poll_interval_seconds: int = 5
    raccoon_short_poll_timeout_seconds: int = 120

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

    @field_validator("obs_signed_url_expire_seconds")
    @classmethod
    def validate_obs_signed_url_expire_seconds(cls, value: int) -> int:
        """校验签名下载地址有效期。"""
        if value <= 0:
            raise ValueError("OBS_SIGNED_URL_EXPIRE_SECONDS 必须大于 0")
        return value

    @field_validator("mineru_api_base_url")
    @classmethod
    def normalize_mineru_api_base_url(cls, value: str) -> str:
        """归一化 MinerU API 基础地址。"""
        normalized_value = value.strip().rstrip("/")
        if not normalized_value:
            raise ValueError("MINERU_API_BASE_URL 不能为空")
        return normalized_value

    @field_validator("llm_api_base_url", "embedding_api_base_url")
    @classmethod
    def normalize_openai_compatible_base_url(cls, value: str) -> str:
        """归一化 OpenAI 兼容接口基础地址。"""
        normalized_value = value.strip().rstrip("/")
        if not normalized_value:
            raise ValueError("OpenAI 兼容基础地址不能为空")
        return normalized_value

    @field_validator("llm_api_format", mode="before")
    @classmethod
    def normalize_llm_api_format(cls, value: str | None) -> str:
        """归一化结构化 LLM 调用格式。"""
        if value is None:
            return "response"
        normalized_value = value.strip().lower().replace("_", "-")
        if not normalized_value:
            return "response"
        if normalized_value in {"response", "responses", "openai-response", "openai-responses"}:
            return "response"
        if normalized_value in {"chat", "chat-completion", "chat-completions", "openai-chat"}:
            return "chat"
        raise ValueError("LLM_API_FORMAT 仅支持 response 或 chat")

    @field_validator("raccoon_api_host")
    @classmethod
    def normalize_raccoon_api_host(cls, value: str) -> str:
        """归一化 Raccoon PPT API 基础地址。"""
        normalized_value = value.strip().rstrip("/")
        if not normalized_value:
            raise ValueError("RACCOON_API_HOST 不能为空")
        return normalized_value

    @field_validator("mineru_api_token", mode="before")
    @classmethod
    def normalize_mineru_api_token(cls, value: str | None) -> str | None:
        """将空 MinerU Token 归一为 None。"""
        if value is None:
            return None
        normalized_value = value.strip()
        if not normalized_value:
            return None
        return normalized_value

    @field_validator(
        "llm_api_key",
        "embedding_api_key",
        "llm_model",
        "llm_reasoning_effort",
        "embedding_model",
        "raccoon_api_token",
        mode="before",
    )
    @classmethod
    def normalize_optional_openai_compatible_value(cls, value: str | None) -> str | None:
        """将空的外部服务配置归一为 None。"""
        if value is None:
            return None
        normalized_value = value.strip()
        if not normalized_value:
            return None
        return normalized_value

    @field_validator("mineru_poll_interval_seconds", "mineru_poll_timeout_seconds")
    @classmethod
    def validate_mineru_poll_values(cls, value: int) -> int:
        """校验 MinerU 轮询配置。"""
        if value <= 0:
            raise ValueError("MinerU 轮询配置必须大于 0")
        return value

    @field_validator("llm_timeout_seconds", "embedding_timeout_seconds", "raccoon_request_timeout_seconds")
    @classmethod
    def validate_openai_compatible_timeout(cls, value: int) -> int:
        """校验外部接口超时时间。"""
        if value <= 0:
            raise ValueError("外部接口超时时间必须大于 0")
        return value

    @field_validator("llm_max_retries", "llm_parse_repair_max_attempts")
    @classmethod
    def validate_llm_retry_count(cls, value: int) -> int:
        """校验 LLM 重试与修复次数，允许为 0 表示不重试。"""
        if value < 0:
            raise ValueError("LLM 重试与修复次数不能为负数")
        return value

    @field_validator("llm_retry_base_seconds", "llm_stream_error_detail_max_chars")
    @classmethod
    def validate_llm_retry_base_seconds(cls, value: int) -> int:
        """校验 LLM 重试退避与错误详情配置。"""
        if value <= 0:
            raise ValueError("LLM 重试退避与错误详情配置必须大于 0")
        return value

    @field_validator("knowledge_extract_max_concurrency")
    @classmethod
    def validate_knowledge_extract_max_concurrency(cls, value: int) -> int:
        """校验知识抽取语义块并发数。"""
        if value < 1 or value > 10:
            raise ValueError("知识抽取语义块并发数必须在 1 到 10 之间")
        return value

    @field_validator("lesson_plan_max_concurrency")
    @classmethod
    def validate_lesson_plan_max_concurrency(cls, value: int) -> int:
        """校验教案生成并发数。"""
        if value < 1 or value > 10:
            raise ValueError("教案生成并发数必须在 1 到 10 之间")
        return value

    @field_validator("lesson_plan_session_max_retries")
    @classmethod
    def validate_lesson_plan_session_max_retries(cls, value: int) -> int:
        """校验单课次教案生成重试次数。"""
        if value < 0:
            raise ValueError("单课次教案生成重试次数不能为负数")
        return value

    @field_validator("lesson_plan_session_retry_base_seconds")
    @classmethod
    def validate_lesson_plan_session_retry_base_seconds(cls, value: int) -> int:
        """校验单课次教案生成重试退避基数。"""
        if value <= 0:
            raise ValueError("单课次教案生成重试退避基数必须大于 0")
        return value

    @field_validator(
        "task_stale_threshold_seconds",
        "task_reaper_interval_seconds",
        "task_retry_backoff_base_seconds",
        "courseware_remote_poll_interval_seconds",
    )
    @classmethod
    def validate_task_recovery_seconds(cls, value: int) -> int:
        """校验后台周期任务相关秒数配置必须为正。"""
        if value <= 0:
            raise ValueError("后台周期任务相关秒数配置必须大于 0")
        return value

    @field_validator("raccoon_poll_interval_seconds", "raccoon_short_poll_timeout_seconds")
    @classmethod
    def validate_raccoon_poll_values(cls, value: int) -> int:
        """校验 Raccoon PPT 轮询配置。"""
        if value <= 0:
            raise ValueError("Raccoon PPT 轮询配置必须大于 0")
        return value

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
