"""
@Date: 2026-05-27
@Author: xisy
@Discription: 清空 4 类资产的旧 DOCX export_file_id

upgrade：把 curriculum_plan / lesson_plan / homework_result / paper_result 的 export_file_id 全部置 NULL，
        让前端在下次访问时主动触发 /export-docx，由新模板（DOCX_TEMPLATE_VERSION）落到新 object_key。
downgrade：无数据可恢复，保留为空，避免回滚误操作。
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "20260527_0011"
down_revision = "20260526_0010"
branch_labels = None
depends_on = None

_STALE_EXPORT_TABLES = (
    "curriculum_plan",
    "lesson_plan",
    "homework_result",
    "paper_result",
)


def upgrade() -> None:
    """清空 4 类资产残留的 export_file_id，触发模板升级后的重新生成。"""
    for table_name in _STALE_EXPORT_TABLES:
        op.execute(f"UPDATE {table_name} SET export_file_id = NULL WHERE export_file_id IS NOT NULL")


def downgrade() -> None:
    """旧 export_file_id 已无法恢复，保留为空操作。"""
    return
