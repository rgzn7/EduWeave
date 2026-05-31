"""
@Date: 2026-05-31
@Author: xisy
@Discription: 存量修复脚本——为缺摘要的最新 ready 教案从同课次旧版本恢复 summary_text

历史问题：小助手早期整体回写教案时，读出的 content 缺 summary_text（已由读工具回填修复），
导致改写后的版本 summary_text 落库为空。本脚本对每个 version_status='ready' 且缺摘要的教案，
从同课次（curriculum_plan_id + class_session_no）版本号更小、仍保有摘要的最近版本恢复其 summary_text。
agent 的改写均在同一课主题内精修、标题不变，旧版摘要仍准确可用，故采用恢复而非重新生成。

默认仅打印将执行的恢复计划（dry-run）；加 --apply 才真正落库。
"""

import argparse
import sys
from pathlib import Path

CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import select

from app.core.database import SessionLocal
from app.modules.auth import models as _auth_models  # noqa: F401  注册 sys_user，供 FK 依赖排序
from app.modules.p0_models import LessonPlan


def _has_summary(lesson_plan: LessonPlan) -> bool:
    """判断教案摘要是否有效（非空白）。"""
    return bool(lesson_plan.summary_text and lesson_plan.summary_text.strip())


def _collect_recoveries(session) -> list[dict]:
    """扫描缺摘要的 ready 教案，产出从旧版本恢复摘要的计划。"""
    targets = session.scalars(
        select(LessonPlan)
        .where(
            LessonPlan.version_status == "ready",
            LessonPlan.class_session_no.is_not(None),
        )
        .order_by(LessonPlan.curriculum_plan_id.asc(), LessonPlan.class_session_no.asc())
    ).all()

    recoveries: list[dict] = []
    for target in targets:
        if _has_summary(target):
            continue
        # 同课次、版本号更小、仍有摘要的最近版本作为恢复源
        donor = session.scalars(
            select(LessonPlan)
            .where(
                LessonPlan.curriculum_plan_id == target.curriculum_plan_id,
                LessonPlan.class_session_no == target.class_session_no,
                LessonPlan.version_no < target.version_no,
                LessonPlan.summary_text.is_not(None),
                LessonPlan.summary_text != "",
            )
            .order_by(LessonPlan.version_no.desc())
            .limit(1)
        ).first()
        recoveries.append(
            {
                "target_id": target.id,
                "curriculum_plan_id": target.curriculum_plan_id,
                "class_session_no": target.class_session_no,
                "donor_id": donor.id if donor else None,
                "summary": donor.summary_text if donor else None,
            }
        )
    return recoveries


def main() -> None:
    """扫描并（可选）执行教案摘要恢复。"""
    parser = argparse.ArgumentParser(description="为缺摘要的 ready 教案从旧版本恢复 summary_text")
    parser.add_argument("--apply", action="store_true", help="真正落库；缺省仅打印计划（dry-run）")
    args = parser.parse_args()

    session = SessionLocal()
    try:
        recoveries = _collect_recoveries(session)
        actionable = [item for item in recoveries if item["donor_id"] is not None]
        orphans = [item for item in recoveries if item["donor_id"] is None]

        if not recoveries:
            print("未发现缺摘要的 ready 教案，无需恢复。")
            return

        print(f"共发现 {len(recoveries)} 个缺摘要的 ready 教案，其中可恢复 {len(actionable)} 个：")
        for item in recoveries:
            if item["donor_id"] is None:
                print(
                    f"  [跳过] 教案 id={item['target_id']} cp={item['curriculum_plan_id']} "
                    f"session={item['class_session_no']}（无可恢复的旧版摘要）"
                )
                continue
            preview = (item["summary"] or "")[:50]
            print(
                f"  [恢复] 教案 id={item['target_id']} session={item['class_session_no']} "
                f"<- 旧版 id={item['donor_id']}：{preview}…"
            )
        if orphans:
            print(f"注意：{len(orphans)} 个教案无旧版摘要可恢复，需人工补写或重新生成。")

        if not args.apply:
            print("\n当前为 dry-run，未改动数据库。确认无误后加 --apply 执行。")
            return

        for item in actionable:
            target = session.get(LessonPlan, item["target_id"])
            target.summary_text = item["summary"]
            session.add(target)
        session.commit()
        print(f"\n已提交，完成 {len(actionable)} 个教案的摘要恢复。")
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    main()
