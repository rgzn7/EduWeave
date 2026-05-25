"""
@Date: 2026-05-25
@Author: xisy
@Discription: 拆分课后作业到课次维度，新增 homework_blueprint / homework_result / homework_question 三张表

upgrade 流程：
1. 建表
2. 把历史 scene_type='homework' 的 paper_result / question_item / assessment_blueprint 数据搬运到新表。
   旧 homework 是批次级整包，无法精确拆分到课次，统一绑定到该批次最小 class_session_no 的 lesson_plan 作为占位。
3. 从旧表中清理 homework 数据

downgrade：反向把 homework_* 数据搬回 paper_result / question_item / assessment_blueprint，丢失课次维度信息。
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = "20260525_0008"
down_revision = "20260503_0007"
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    """判断表是否存在。"""
    return table_name in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    """新增 homework 三表并迁移历史数据。"""
    if not _table_exists("homework_blueprint"):
        op.create_table(
            "homework_blueprint",
            sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False, comment="主键"),
            sa.Column("lesson_plan_id", mysql.BIGINT(unsigned=True), nullable=False, comment="所属教案"),
            sa.Column("generation_batch_id", mysql.BIGINT(unsigned=True), nullable=False, comment="生成批次"),
            sa.Column("version_no", sa.Integer(), nullable=False, comment="版本号"),
            sa.Column("blueprint_name", sa.String(length=255), nullable=False, comment="蓝图名称"),
            sa.Column(
                "version_status",
                sa.String(length=32),
                server_default=sa.text("'ready'"),
                nullable=False,
                comment="版本状态",
            ),
            sa.Column("strategy_json", mysql.JSON(), nullable=True, comment="策略配置"),
            sa.Column("content_json", mysql.JSON(), nullable=False, comment="蓝图内容"),
            sa.Column("export_file_id", mysql.BIGINT(unsigned=True), nullable=True, comment="导出文件"),
            sa.Column("created_by", mysql.BIGINT(unsigned=True), nullable=True, comment="创建人"),
            sa.Column(
                "created_at",
                mysql.DATETIME(fsp=3),
                server_default=sa.text("CURRENT_TIMESTAMP(3)"),
                nullable=False,
                comment="创建时间",
            ),
            sa.Column(
                "updated_at",
                mysql.DATETIME(fsp=3),
                server_default=sa.text("CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3)"),
                nullable=False,
                comment="更新时间",
            ),
            sa.PrimaryKeyConstraint("id"),
            mysql_charset="utf8mb4",
            mysql_collate="utf8mb4_unicode_ci",
            mysql_comment="课后作业蓝图表",
        )
        op.create_index(
            "uk_homework_blueprint_lesson_version",
            "homework_blueprint",
            ["lesson_plan_id", "version_no"],
            unique=True,
        )
        op.create_index("idx_homework_blueprint_batch", "homework_blueprint", ["generation_batch_id"])
        op.create_index(
            "idx_homework_blueprint_lesson_status",
            "homework_blueprint",
            ["lesson_plan_id", "version_status", "created_at"],
        )
        op.create_foreign_key(
            "fk_homework_blueprint_lesson_plan",
            "homework_blueprint",
            "lesson_plan",
            ["lesson_plan_id"],
            ["id"],
        )
        op.create_foreign_key(
            "fk_homework_blueprint_batch",
            "homework_blueprint",
            "generation_batch",
            ["generation_batch_id"],
            ["id"],
        )
        op.create_foreign_key(
            "fk_homework_blueprint_export_file",
            "homework_blueprint",
            "file_object",
            ["export_file_id"],
            ["id"],
        )
        op.create_foreign_key(
            "fk_homework_blueprint_created_by",
            "homework_blueprint",
            "sys_user",
            ["created_by"],
            ["id"],
        )

    if not _table_exists("homework_result"):
        op.create_table(
            "homework_result",
            sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False, comment="主键"),
            sa.Column("generation_batch_id", mysql.BIGINT(unsigned=True), nullable=False, comment="生成批次"),
            sa.Column("lesson_plan_id", mysql.BIGINT(unsigned=True), nullable=False, comment="所属教案"),
            sa.Column("homework_blueprint_id", mysql.BIGINT(unsigned=True), nullable=False, comment="作业蓝图"),
            sa.Column("title", sa.String(length=255), nullable=False, comment="作业标题"),
            sa.Column(
                "result_status",
                sa.String(length=32),
                server_default=sa.text("'success'"),
                nullable=False,
                comment="结果状态",
            ),
            sa.Column(
                "question_count",
                sa.Integer(),
                server_default=sa.text("0"),
                nullable=False,
                comment="题目数量",
            ),
            sa.Column("difficulty_stats_json", mysql.JSON(), nullable=True, comment="难度统计"),
            sa.Column("content_json", mysql.JSON(), nullable=False, comment="作业内容"),
            sa.Column("export_file_id", mysql.BIGINT(unsigned=True), nullable=True, comment="导出文件"),
            sa.Column(
                "created_at",
                mysql.DATETIME(fsp=3),
                server_default=sa.text("CURRENT_TIMESTAMP(3)"),
                nullable=False,
                comment="创建时间",
            ),
            sa.Column(
                "updated_at",
                mysql.DATETIME(fsp=3),
                server_default=sa.text("CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3)"),
                nullable=False,
                comment="更新时间",
            ),
            sa.PrimaryKeyConstraint("id"),
            mysql_charset="utf8mb4",
            mysql_collate="utf8mb4_unicode_ci",
            mysql_comment="课后作业结果表",
        )
        op.create_index("uk_homework_result_lesson", "homework_result", ["lesson_plan_id"], unique=True)
        op.create_index(
            "idx_homework_result_batch",
            "homework_result",
            ["generation_batch_id", "lesson_plan_id"],
        )
        op.create_index(
            "idx_homework_result_blueprint",
            "homework_result",
            ["homework_blueprint_id", "created_at"],
        )
        op.create_foreign_key(
            "fk_homework_result_batch",
            "homework_result",
            "generation_batch",
            ["generation_batch_id"],
            ["id"],
        )
        op.create_foreign_key(
            "fk_homework_result_lesson_plan",
            "homework_result",
            "lesson_plan",
            ["lesson_plan_id"],
            ["id"],
        )
        op.create_foreign_key(
            "fk_homework_result_blueprint",
            "homework_result",
            "homework_blueprint",
            ["homework_blueprint_id"],
            ["id"],
        )
        op.create_foreign_key(
            "fk_homework_result_export_file",
            "homework_result",
            "file_object",
            ["export_file_id"],
            ["id"],
        )

    if not _table_exists("homework_question"):
        op.create_table(
            "homework_question",
            sa.Column("id", mysql.BIGINT(unsigned=True), autoincrement=True, nullable=False, comment="主键"),
            sa.Column("generation_batch_id", mysql.BIGINT(unsigned=True), nullable=False, comment="生成批次"),
            sa.Column("homework_result_id", mysql.BIGINT(unsigned=True), nullable=False, comment="作业结果"),
            sa.Column("lesson_plan_id", mysql.BIGINT(unsigned=True), nullable=False, comment="所属教案"),
            sa.Column("knowledge_point_id", mysql.BIGINT(unsigned=True), nullable=True, comment="知识点"),
            sa.Column("question_no", sa.Integer(), nullable=False, comment="题号"),
            sa.Column("question_type", sa.String(length=32), nullable=False, comment="题型"),
            sa.Column("difficulty_level", mysql.TINYINT(unsigned=True), nullable=True, comment="难度"),
            sa.Column("score_value", mysql.DECIMAL(6, 2), nullable=True, comment="分值"),
            sa.Column("stem_text", mysql.MEDIUMTEXT(), nullable=False, comment="题干"),
            sa.Column("options_json", mysql.JSON(), nullable=True, comment="选项"),
            sa.Column("answer_text", sa.Text(), nullable=True, comment="答案"),
            sa.Column("analysis_text", sa.Text(), nullable=True, comment="解析"),
            sa.Column("source_trace_json", mysql.JSON(), nullable=True, comment="题目来源摘要"),
            sa.Column(
                "created_at",
                mysql.DATETIME(fsp=3),
                server_default=sa.text("CURRENT_TIMESTAMP(3)"),
                nullable=False,
                comment="创建时间",
            ),
            sa.Column(
                "updated_at",
                mysql.DATETIME(fsp=3),
                server_default=sa.text("CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3)"),
                nullable=False,
                comment="更新时间",
            ),
            sa.PrimaryKeyConstraint("id"),
            mysql_charset="utf8mb4",
            mysql_collate="utf8mb4_unicode_ci",
            mysql_comment="课后作业题目明细表",
        )
        op.create_index(
            "uk_homework_question_scope",
            "homework_question",
            ["homework_result_id", "question_no"],
            unique=True,
        )
        op.create_index(
            "idx_homework_question_lesson_kp",
            "homework_question",
            ["lesson_plan_id", "knowledge_point_id"],
        )
        op.create_index(
            "idx_homework_question_batch_kp",
            "homework_question",
            ["generation_batch_id", "knowledge_point_id"],
        )
        op.create_index(
            "idx_homework_question_type_diff",
            "homework_question",
            ["question_type", "difficulty_level"],
        )
        op.create_foreign_key(
            "fk_homework_question_batch",
            "homework_question",
            "generation_batch",
            ["generation_batch_id"],
            ["id"],
        )
        op.create_foreign_key(
            "fk_homework_question_result",
            "homework_question",
            "homework_result",
            ["homework_result_id"],
            ["id"],
        )
        op.create_foreign_key(
            "fk_homework_question_lesson_plan",
            "homework_question",
            "lesson_plan",
            ["lesson_plan_id"],
            ["id"],
        )
        op.create_foreign_key(
            "fk_homework_question_knowledge_point",
            "homework_question",
            "knowledge_point",
            ["knowledge_point_id"],
            ["id"],
        )

    _migrate_legacy_homework_data()
    _cleanup_legacy_homework_rows()


def downgrade() -> None:
    """回退：把 homework_* 数据回写到旧表，再删除三张新表。"""
    _restore_legacy_homework_data()

    for table_name in ("homework_question", "homework_result", "homework_blueprint"):
        if _table_exists(table_name):
            op.drop_table(table_name)


def _migrate_legacy_homework_data() -> None:
    """把历史 homework 数据从 paper_result / assessment_blueprint / question_item 搬运到新表。"""
    bind = op.get_bind()
    legacy_papers = bind.execute(
        sa.text(
            """
            SELECT pr.id, pr.generation_batch_id, pr.assessment_blueprint_id, pr.title,
                   pr.result_status, pr.question_count, pr.difficulty_stats_json, pr.paper_json,
                   pr.export_file_id, pr.created_at, pr.updated_at
            FROM paper_result pr
            WHERE pr.scene_type = 'homework'
            """
        )
    ).mappings().all()

    for paper in legacy_papers:
        placeholder_lesson = bind.execute(
            sa.text(
                """
                SELECT lp.id
                FROM lesson_plan lp
                WHERE lp.generation_batch_id = :batch_id
                ORDER BY COALESCE(lp.class_session_no, 0) ASC, lp.id ASC
                LIMIT 1
                """
            ),
            {"batch_id": paper["generation_batch_id"]},
        ).scalar()
        if placeholder_lesson is None:
            # 该批次没有教案，整组 homework 数据无法落地课次，跳过搬运（清理阶段也会删除原行）
            continue

        legacy_blueprint = bind.execute(
            sa.text(
                """
                SELECT id, version_no, blueprint_name, version_status, strategy_json, content_json,
                       export_file_id, created_by, created_at, updated_at
                FROM assessment_blueprint
                WHERE id = :blueprint_id
                """
            ),
            {"blueprint_id": paper["assessment_blueprint_id"]},
        ).mappings().first()
        if legacy_blueprint is None:
            continue

        new_blueprint_id = bind.execute(
            sa.text(
                """
                INSERT INTO homework_blueprint
                    (lesson_plan_id, generation_batch_id, version_no, blueprint_name, version_status,
                     strategy_json, content_json, export_file_id, created_by, created_at, updated_at)
                VALUES
                    (:lesson_plan_id, :batch_id, :version_no, :blueprint_name, :version_status,
                     :strategy_json, :content_json, :export_file_id, :created_by, :created_at, :updated_at)
                """
            ),
            {
                "lesson_plan_id": placeholder_lesson,
                "batch_id": paper["generation_batch_id"],
                "version_no": legacy_blueprint["version_no"],
                "blueprint_name": legacy_blueprint["blueprint_name"],
                "version_status": legacy_blueprint["version_status"],
                "strategy_json": legacy_blueprint["strategy_json"],
                "content_json": legacy_blueprint["content_json"],
                "export_file_id": legacy_blueprint["export_file_id"],
                "created_by": legacy_blueprint["created_by"],
                "created_at": legacy_blueprint["created_at"],
                "updated_at": legacy_blueprint["updated_at"],
            },
        ).lastrowid

        new_result_id = bind.execute(
            sa.text(
                """
                INSERT INTO homework_result
                    (generation_batch_id, lesson_plan_id, homework_blueprint_id, title, result_status,
                     question_count, difficulty_stats_json, content_json, export_file_id, created_at, updated_at)
                VALUES
                    (:batch_id, :lesson_plan_id, :blueprint_id, :title, :result_status,
                     :question_count, :difficulty_stats_json, :content_json, :export_file_id,
                     :created_at, :updated_at)
                """
            ),
            {
                "batch_id": paper["generation_batch_id"],
                "lesson_plan_id": placeholder_lesson,
                "blueprint_id": new_blueprint_id,
                "title": paper["title"],
                "result_status": paper["result_status"],
                "question_count": paper["question_count"],
                "difficulty_stats_json": paper["difficulty_stats_json"],
                "content_json": paper["paper_json"],
                "export_file_id": paper["export_file_id"],
                "created_at": paper["created_at"],
                "updated_at": paper["updated_at"],
            },
        ).lastrowid

        bind.execute(
            sa.text(
                """
                INSERT INTO homework_question
                    (generation_batch_id, homework_result_id, lesson_plan_id, knowledge_point_id,
                     question_no, question_type, difficulty_level, score_value, stem_text, options_json,
                     answer_text, analysis_text, source_trace_json, created_at, updated_at)
                SELECT generation_batch_id, :result_id, :lesson_plan_id, knowledge_point_id,
                       question_no, question_type, difficulty_level, score_value, stem_text, options_json,
                       answer_text, analysis_text, source_trace_json, created_at, updated_at
                FROM question_item
                WHERE paper_result_id = :paper_result_id
                """
            ),
            {
                "result_id": new_result_id,
                "lesson_plan_id": placeholder_lesson,
                "paper_result_id": paper["id"],
            },
        )


def _cleanup_legacy_homework_rows() -> None:
    """从旧表中清理已迁移的 homework 数据。"""
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            DELETE qi FROM question_item qi
            JOIN paper_result pr ON pr.id = qi.paper_result_id
            WHERE pr.scene_type = 'homework'
            """
        )
    )
    bind.execute(sa.text("DELETE FROM paper_result WHERE scene_type = 'homework'"))
    bind.execute(sa.text("DELETE FROM assessment_blueprint WHERE scenario_type = 'homework'"))


def _restore_legacy_homework_data() -> None:
    """downgrade 兜底：把 homework_* 数据回写到旧表，丢失课次维度。"""
    if not _table_exists("homework_result"):
        return
    bind = op.get_bind()
    legacy_results = bind.execute(
        sa.text(
            """
            SELECT hr.id, hr.generation_batch_id, hr.homework_blueprint_id, hr.title,
                   hr.result_status, hr.question_count, hr.difficulty_stats_json, hr.content_json,
                   hr.export_file_id, hr.created_at, hr.updated_at,
                   hb.version_no, hb.blueprint_name, hb.version_status, hb.strategy_json,
                   hb.content_json AS blueprint_content_json, hb.export_file_id AS blueprint_export_file_id,
                   hb.created_by AS blueprint_created_by, hb.created_at AS blueprint_created_at,
                   hb.updated_at AS blueprint_updated_at,
                   gb.curriculum_plan_id
            FROM homework_result hr
            JOIN homework_blueprint hb ON hb.id = hr.homework_blueprint_id
            JOIN generation_batch gb ON gb.id = hr.generation_batch_id
            """
        )
    ).mappings().all()

    for legacy in legacy_results:
        new_blueprint_id = bind.execute(
            sa.text(
                """
                INSERT INTO assessment_blueprint
                    (curriculum_plan_id, version_no, scenario_type, blueprint_name, version_status,
                     strategy_json, content_json, export_file_id, created_by, created_at, updated_at)
                VALUES
                    (:curriculum_plan_id, :version_no, 'homework', :blueprint_name, :version_status,
                     :strategy_json, :content_json, :export_file_id, :created_by, :created_at, :updated_at)
                """
            ),
            {
                "curriculum_plan_id": legacy["curriculum_plan_id"],
                "version_no": legacy["version_no"],
                "blueprint_name": legacy["blueprint_name"],
                "version_status": legacy["version_status"],
                "strategy_json": legacy["strategy_json"],
                "content_json": legacy["blueprint_content_json"],
                "export_file_id": legacy["blueprint_export_file_id"],
                "created_by": legacy["blueprint_created_by"],
                "created_at": legacy["blueprint_created_at"],
                "updated_at": legacy["blueprint_updated_at"],
            },
        ).lastrowid

        new_paper_id = bind.execute(
            sa.text(
                """
                INSERT INTO paper_result
                    (generation_batch_id, assessment_blueprint_id, scene_type, title, result_status,
                     question_count, difficulty_stats_json, paper_json, export_file_id, created_at, updated_at)
                VALUES
                    (:batch_id, :blueprint_id, 'homework', :title, :result_status,
                     :question_count, :difficulty_stats_json, :paper_json, :export_file_id,
                     :created_at, :updated_at)
                """
            ),
            {
                "batch_id": legacy["generation_batch_id"],
                "blueprint_id": new_blueprint_id,
                "title": legacy["title"],
                "result_status": legacy["result_status"],
                "question_count": legacy["question_count"],
                "difficulty_stats_json": legacy["difficulty_stats_json"],
                "paper_json": legacy["content_json"],
                "export_file_id": legacy["export_file_id"],
                "created_at": legacy["created_at"],
                "updated_at": legacy["updated_at"],
            },
        ).lastrowid

        bind.execute(
            sa.text(
                """
                INSERT INTO question_item
                    (generation_batch_id, paper_result_id, knowledge_point_id, question_no,
                     question_type, difficulty_level, score_value, stem_text, options_json,
                     answer_text, analysis_text, source_trace_json, created_at, updated_at)
                SELECT generation_batch_id, :paper_id, knowledge_point_id, question_no,
                       question_type, difficulty_level, score_value, stem_text, options_json,
                       answer_text, analysis_text, source_trace_json, created_at, updated_at
                FROM homework_question
                WHERE homework_result_id = :result_id
                """
            ),
            {"paper_id": new_paper_id, "result_id": legacy["id"]},
        )
