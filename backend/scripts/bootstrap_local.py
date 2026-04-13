"""
@Date: 2026-04-13
@Author: xisy
@Discription: 本地开发基础环境 bootstrap 脚本
"""

import sys
from pathlib import Path

CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.bootstrap import DEMO_TEACHER_PASSWORD, ensure_demo_teacher
from app.core.database import SessionLocal
from app.core.logging import configure_logging


def main() -> None:
    """初始化本地演示账号与 Milvus 必需集合。"""
    configure_logging()

    session = SessionLocal()
    try:
        seed_result = ensure_demo_teacher(session)
    finally:
        session.close()

    print("本地 bootstrap 完成：")
    print(f"- 演示教师账号：{seed_result.username}（动作：{seed_result.action}，ID：{seed_result.user_id}）")
    print(f"- 演示教师密码：{DEMO_TEACHER_PASSWORD}")

    try:
        from app.shared.vector import MilvusVectorService

        vector_service = MilvusVectorService()
        created_collections = vector_service.ensure_collections()
        if created_collections:
            print("- 新建 Milvus 集合：")
            for collection_name in created_collections:
                print(f"  - {collection_name}")
        else:
            print("- Milvus 必需集合已存在，无需新增")
    except Exception as exc:  # noqa: BLE001
        print(f"- Milvus 初始化失败：{exc}")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
