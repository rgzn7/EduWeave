"""
@Date: 2026-05-17
@Author: xisy
@Discription: 真实重跑知识抽取任务（同步执行）验证 LLM 流式调用修复，不 patch 任何 LLM/向量服务
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path

# 同步执行任务，无需本地 Celery worker；真实调用 PackyAPI / Embedding / Milvus。
os.environ["TASK_EAGER_MODE"] = "1"

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import get_settings
from app.core.database import SessionLocal

# 显式 import 全量 ORM 模型，确保 SQLAlchemy metadata 完整（task_record 外键引用 sys_user）。
import app.modules.auth.models  # noqa: E402,F401
import app.modules.p0_models  # noqa: E402,F401
from app.modules.knowledge.repository import KnowledgeRepository  # noqa: E402
from app.modules.knowledge.schemas import KnowledgeTaskCreateRequest  # noqa: E402
from app.modules.knowledge.service import KnowledgeService  # noqa: E402

PARSE_VERSION_ID = int(os.environ.get("VERIFY_PARSE_VERSION_ID", "15"))
OWNER_USER_ID = int(os.environ.get("VERIFY_OWNER_USER_ID", "1"))


def main() -> None:
    """触发一次真实知识抽取并打印结果。"""
    settings = get_settings()
    print(
        "RUNTIME "
        + json.dumps(
            {
                "llm_api_format": settings.llm_api_format,
                "llm_api_base_url": settings.llm_api_base_url,
                "llm_model": settings.llm_model,
                "llm_timeout_seconds": settings.llm_timeout_seconds,
                "parse_version_id": PARSE_VERSION_ID,
                "owner_user_id": OWNER_USER_ID,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )

    session = SessionLocal()
    try:
        task = KnowledgeService(session, KnowledgeRepository(session)).create_extract_task(
            owner_user_id=OWNER_USER_ID,
            parse_version_id=PARSE_VERSION_ID,
            request=KnowledgeTaskCreateRequest(force_regenerate=True),
        )
        print("TASK_RESULT " + json.dumps(task.model_dump(mode="json"), ensure_ascii=False, default=str), flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"TASK_ERROR {type(exc).__name__}: {exc}", flush=True)
        traceback.print_exc()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    main()
