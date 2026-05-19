import { BookOpenCheck, ClipboardList, FileQuestion, FileText, Layers3, ListChecks, Presentation, Target } from "lucide-react";
import type { ReactNode } from "react";
import { JsonViewer } from "../../components/JsonViewer";
import { ProgressBar } from "../../components/ProgressBar";
import { StatusBadge } from "../../components/StatusBadge";
import type { GenerationBatch } from "../../types";
import { formatDate } from "../../utils";
import { StatCard } from "./shared";

function FlowItem({
  icon,
  title,
  status,
  detail,
}: {
  icon: ReactNode;
  title: string;
  status: string;
  detail: string;
}) {
  return (
    <section className="rounded-md border border-line bg-paper/60 p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          <div className="mt-0.5 text-accent">{icon}</div>
          <div className="min-w-0">
            <div className="break-words text-sm font-bold text-ink">{title}</div>
            <div className="mt-1 break-words text-xs leading-5 text-ink/50">{detail}</div>
          </div>
        </div>
        <StatusBadge status={status} />
      </div>
    </section>
  );
}

export function OverviewTab({
  batch,
  lessonCount,
  assessmentCount,
  assessmentStatus,
  coursewareCount,
  coursewareStatus,
  coverageCount,
  coverageStatus,
}: {
  batch: GenerationBatch;
  lessonCount: number;
  assessmentCount: number;
  assessmentStatus: string;
  coursewareCount: number;
  coursewareStatus: string;
  coverageCount: number;
  coverageStatus: string;
}) {
  const taskProgress = batch.tasks?.length
    ? Math.round(batch.tasks.reduce((sum, task) => sum + (task.progress_percent ?? 0), 0) / batch.tasks.length)
    : 0;

  return (
    <div className="space-y-5">
      <div className="grid gap-4 xl:grid-cols-[1fr_360px]">
        <div className="space-y-4">
          <div className="grid gap-3 md:grid-cols-3">
            <StatCard label="课程方案" value={batch.curriculum_plan_id ? `#${batch.curriculum_plan_id}` : "未生成"} />
            <StatCard label="教案数量" value={lessonCount || "未生成"} />
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
      <section className="rounded-md border border-line bg-white p-5">
        <div className="flex flex-col justify-between gap-3 md:flex-row md:items-end">
          <div>
            <div className="label">教学资源闭环</div>
            <h2 className="mt-1 text-xl font-bold text-ink">输入基线到成果校验</h2>
          </div>
          <StatusBadge status={batch.batch_status} />
        </div>
        <div className="mt-4 grid gap-3 xl:grid-cols-5">
          <FlowItem
            detail={batch.curriculum_plan_id ? `课程方案 #${batch.curriculum_plan_id}` : "等待课程方案"}
            icon={<Target size={18} />}
            status={batch.curriculum_plan_id ? "ready" : "pending"}
            title="课程方案"
          />
          <FlowItem
            detail={lessonCount ? `${lessonCount} 份就绪教案` : "等待教案结果"}
            icon={<FileText size={18} />}
            status={lessonCount ? "ready" : "pending"}
            title="教案"
          />
          <FlowItem
            detail={assessmentCount ? `${assessmentCount} 份试卷结果` : "按需生成单元测评"}
            icon={<FileQuestion size={18} />}
            status={assessmentStatus}
            title="测评"
          />
          <FlowItem
            detail={coursewareCount ? `${coursewareCount} 份课件结果` : "按需生成 PPTX"}
            icon={<Presentation size={18} />}
            status={coursewareStatus}
            title="课件"
          />
          <FlowItem
            detail={coverageCount ? `${coverageCount} 份覆盖报告` : "等待覆盖分析"}
            icon={<ListChecks size={18} />}
            status={coverageStatus}
            title="覆盖校验"
          />
        </div>
      </section>
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
