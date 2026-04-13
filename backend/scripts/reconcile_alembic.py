"""
@Date: 2026-04-13
@Author: xisy
@Discription: 已有数据库 Alembic 对齐脚本
"""

import sys
from pathlib import Path

CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from alembic import command
from alembic.config import Config

from app.core.database import engine
from app.core.logging import configure_logging
from app.core.schema_sync import collect_schema_diffs, format_schema_diffs, get_alembic_version


def build_alembic_config() -> Config:
    """构造 Alembic 配置对象。"""
    alembic_ini_path = Path(__file__).resolve().parents[1] / "alembic.ini"
    config = Config(str(alembic_ini_path))
    return config


def main() -> None:
    """校验现有数据库结构并在通过后打上 Alembic 版本。"""
    configure_logging()

    current_version = get_alembic_version(engine)
    schema_diffs = collect_schema_diffs(engine)
    if schema_diffs:
        print("数据库结构与当前 metadata 不一致，已停止对齐：")
        print(format_schema_diffs(schema_diffs))
        raise SystemExit(1)

    if current_version is not None:
        print(f"当前数据库已存在 Alembic 版本记录：{current_version}")
        print("结构校验通过，无需再次 stamp。")
        return

    config = build_alembic_config()
    command.stamp(config, "head")
    print("数据库结构校验通过，已执行 Alembic stamp head。")


if __name__ == "__main__":
    main()
