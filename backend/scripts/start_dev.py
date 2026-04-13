"""
@Date: 2026-04-13
@Author: xisy
@Discription: 后端本地开发启动脚本
"""

import sys
from pathlib import Path

CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent
EXPECTED_VENV_PATH = PROJECT_ROOT / ".venv"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import get_settings


def ensure_project_venv() -> None:
    """确保当前启动命令使用项目独立虚拟环境。"""
    current_prefix_path = Path(sys.prefix).resolve()
    expected_venv_path = EXPECTED_VENV_PATH.resolve()

    if current_prefix_path == expected_venv_path:
        return

    print("检测到当前未使用 backend/.venv 虚拟环境，已停止启动。")
    print("请使用以下任一方式重新启动：")
    print(f"1. source {EXPECTED_VENV_PATH}/bin/activate && python scripts/start_dev.py")
    print(f"2. {EXPECTED_VENV_PATH}/bin/python scripts/start_dev.py")
    raise SystemExit(1)


def main() -> None:
    """以项目虚拟环境启动本地开发服务。"""
    ensure_project_venv()
    settings = get_settings()

    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=True,
        reload_dirs=[str(PROJECT_ROOT)],
    )


if __name__ == "__main__":
    main()
