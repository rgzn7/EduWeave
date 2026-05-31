"""
@Date: 2026-05-31
@Author: xisy
@Discription: 存量修复脚本——把 agent 改写教案丢失的 generation_batch 槽位转交给最新 ready 版本

历史问题：小助手写教案新版本时曾把 generation_batch_id 置空（脱离批次），
导致改过的教案在「最新 ready 版本」上 batch 为 NULL，下游作业/课件按批次定位失败、
测评静默使用旧版。本脚本对每个 (curriculum_plan_id, class_session_no) 课次，
把 batch 从仍持有它的旧版本（通常是归档的原始版）转交给当前最新 ready 版本，
转交后旧版本 batch 置空，保证 (generation_batch_id, class_session_no) 唯一约束不破。

默认仅打印将执行的转交计划（dry-run）；加 --apply 才真正落库。
"""

import argparse
import sys
from collections import defaultdict
from pathlib import Path

CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import select

from app.core.database import SessionLocal
from app.modules.auth import models as _auth_models  # noqa: F401  注册 sys_user，供 FK 依赖排序
from app.modules.p0_models import LessonPlan


def _latest_ready(versions: list[LessonPlan]) -> LessonPlan | None:
    """取课次内版本号最大的 ready 教案，即当前对外生效的最新版本。"""
    ready_versions = [item for item in versions if item.version_status == "ready"]
    if not ready_versions:
        return None
    return max(ready_versions, key=lambda item: item.version_no)


def _collect_transfers(session) -> list[dict]:
    """扫描全部教案，产出需要转交批次的课次计划。"""
    statement = select(LessonPlan).order_by(
        LessonPlan.curriculum_plan_id.asc(),
        LessonPlan.class_session_no.asc(),
        LessonPlan.version_no.asc(),
    )
    groups: dict[tuple[int, int], list[LessonPlan]] = defaultdict(list)
    for lesson_plan in session.scalars(statement):
        if lesson_plan.class_session_no is None:
            continue
        groups[(lesson_plan.curriculum_plan_id, lesson_plan.class_session_no)].append(lesson_plan)

    transfers: list[dict] = []
    for (curriculum_plan_id, class_session_no), versions in groups.items():
        latest = _latest_ready(versions)
        if latest is None:
            continue
        # 最新 ready 版本已挂批次，说明该课次健康，无需处理
        if latest.generation_batch_id is not None:
            continue
        # 找仍持有批次的旧版本（同课次原始版）。正常只有一个、且 batch 一致
        donors = [item for item in versions if item.generation_batch_id is not None and item.id != latest.id]
        if not donors:
            transfers.append(
                {
                    "curriculum_plan_id": curriculum_plan_id,
                    "class_session_no": class_session_no,
                    "latest_id": latest.id,
                    "batch_id": None,
                    "donor_ids": [],
                    "skip_reason": "no_batch_donor",
                }
            )
            continue
        distinct_batches = sorted({item.generation_batch_id for item in donors})
        # 取版本号最小的 donor（原始生成版）作为批次来源
        inherited_batch_id = min(donors, key=lambda item: item.version_no).generation_batch_id
        # 仅清空与待继承批次相同的 donor（同 (batch, session) 槽位的占用者），其余历史不动
        donor_ids = [item.id for item in donors if item.generation_batch_id == inherited_batch_id]
        transfers.append(
            {
                "curriculum_plan_id": curriculum_plan_id,
                "class_session_no": class_session_no,
                "latest_id": latest.id,
                "batch_id": inherited_batch_id,
                "donor_ids": donor_ids,
                "skip_reason": "multi_batch_donor" if len(distinct_batches) > 1 else None,
            }
        )
    return transfers


def _apply_transfer(session, transfer: dict) -> None:
    """执行单课次的批次转交：先清空旧占用者，flush 后再挂到最新版本。"""
    donors = session.scalars(
        select(LessonPlan).where(LessonPlan.id.in_(transfer["donor_ids"]))
    ).all()
    for donor in donors:
        donor.generation_batch_id = None
        session.add(donor)
    # 先 flush 让出 (batch, session) 槽位，再挂新版本，规避唯一键冲突
    session.flush()

    latest = session.get(LessonPlan, transfer["latest_id"])
    latest.generation_batch_id = transfer["batch_id"]
    session.add(latest)
    session.flush()


def main() -> None:
    """扫描并（可选）执行 agent 教案批次回填。"""
    parser = argparse.ArgumentParser(description="回填 agent 改写教案丢失的 generation_batch")
    parser.add_argument("--apply", action="store_true", help="真正落库；缺省仅打印计划（dry-run）")
    args = parser.parse_args()

    session = SessionLocal()
    try:
        transfers = _collect_transfers(session)
        actionable = [item for item in transfers if item["batch_id"] is not None]
        warnings = [item for item in transfers if item["batch_id"] is None or item["skip_reason"]]

        if not transfers:
            print("未发现 batch 为空的最新 ready 教案，无需回填。")
            return

        print(f"共发现 {len(transfers)} 个待修复课次，其中可转交 {len(actionable)} 个：")
        for item in transfers:
            tag = "转交" if item["batch_id"] is not None else "跳过"
            reason = f"（{item['skip_reason']}）" if item["skip_reason"] else ""
            print(
                f"  [{tag}] cp={item['curriculum_plan_id']} session={item['class_session_no']} "
                f"最新版本 id={item['latest_id']} <- batch={item['batch_id']} "
                f"清空旧版本 {item['donor_ids']}{reason}"
            )
        if warnings:
            print(f"注意：{len(warnings)} 个课次需人工确认（无批次来源或存在多个不同批次）。")

        if not args.apply:
            print("\n当前为 dry-run，未改动数据库。确认无误后加 --apply 执行。")
            return

        for item in actionable:
            _apply_transfer(session, item)
        session.commit()
        print(f"\n已提交，完成 {len(actionable)} 个课次的批次转交。")
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    main()
