import { BookOpenCheck, ClipboardList, FileText, Layers3, ListChecks, Target } from "lucide-react";
import { JsonViewer } from "../../components/JsonViewer";
import { ProgressBar } from "../../components/ProgressBar";
import { StatusBadge } from "../../components/StatusBadge";
import type { GenerationBatch } from "../../types";
import { formatDate } from "../../utils";
import { StatCard } from "./shared";

export function OverviewTab({ batch }: { batch: GenerationBatch }) {
  const taskProgress = batch.tasks?.length
    ? Math.round(batch.tasks.reduce((sum, task) => sum + (task.progress_percent ?? 0), 0) / batch.tasks.length)
    : 0;

  return (
    <div className="space-y-5">
      <div className="grid gap-4 xl:grid-cols-[1fr_360px]">
        <div className="space-y-4">
          <div className="grid gap-3 md:grid-cols-3">
            <StatCard label="课程方案" value={batch.curriculum_plan_id ? `#${batch.curriculum_plan_id}` : "未生成"} />
            <StatCard label="首份教案" value={batch.lesson_plan_id ? `#${batch.lesson_plan_id}` : "未生成"} />
            <StatCard label="关联任务" value={batch.tasks?.length ?? 0} />
          </div>
          <div className="rounded-md border border-line bg-paper/60 p-4">
            <div className="mb-3 flex items-center gap-2 text-sm font-bold">
              <ClipboardList size={16} />
              任务平均进度
            </div>
            <ProgressBar value={taskProgress} />
          </div>
        </div>
        <div className="grid gap-3">
          <div className="flex items-center gap-3 rounded-md border border-line bg-paper/60 p-4">
            <BookOpenCheck className="text-accent" size={22} />
            <div>
              <div className="text-sm font-bold">创建时间</div>
              <div className="text-sm text-ink/55">{formatDate(batch.created_at)}</div>
            </div>
          </div>
          <div className="flex items-center gap-3 rounded-md border border-line bg-paper/60 p-4">
            <Layers3 className="text-leaf" size={22} />
            <div>
              <div className="text-sm font-bold">完成时间</div>
              <div className="text-sm text-ink/55">{formatDate(batch.finished_at)}</div>
            </div>
          </div>
        </div>
      </div>
      <div className="grid gap-4 xl:grid-cols-2">
        <JsonViewer title="chapter_range_json" value={batch.chapter_range_json} />
        <JsonViewer title="assessment_strategy_json" value={batch.assessment_strategy_json} />
      </div>
      <div className="grid gap-4 xl:grid-cols-3">
        <section className="rounded-md border border-line bg-paper/60 p-4">
          <div className="mb-3 flex items-center gap-2 text-sm font-bold">
            <Target size={16} />
            课程方案
          </div>
          <StatusBadge status={batch.curriculum_plan_id ? "ready" : "pending"} />
        </section>
        <section className="rounded-md border border-line bg-paper/60 p-4">
          <div className="mb-3 flex items-center gap-2 text-sm font-bold">
            <FileText size={16} />
            教案
          </div>
          <StatusBadge status={batch.lesson_plan_ids?.length ? "ready" : "pending"} />
        </section>
        <section className="rounded-md border border-line bg-paper/60 p-4">
          <div className="mb-3 flex items-center gap-2 text-sm font-bold">
            <ListChecks size={16} />
            覆盖报告
          </div>
          <StatusBadge status={batch.batch_status} />
        </section>
      </div>
    </div>
  );
}
