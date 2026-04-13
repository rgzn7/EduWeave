"""
@Date: 2026-04-11
@Author: xisy
@Discription: 初始化 Milvus 必需集合脚本
"""

import sys
from pathlib import Path

CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.logging import configure_logging


def main() -> None:
    """初始化 Milvus 集合。"""
    configure_logging()

    from app.shared.vector import MilvusVectorService

    service = MilvusVectorService()
    created = service.ensure_collections()
    if created:
        print("已创建集合：")
        for item in created:
            print(f"- {item}")
    else:
        print("Milvus 必需集合已全部存在，无需创建。")


if __name__ == "__main__":
    main()
