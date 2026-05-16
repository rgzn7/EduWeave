import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, BookOpenCheck, ClipboardList, Layers3, Loader2, RotateCw } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { EmptyState } from "../components/EmptyState";
import { ErrorNotice } from "../components/ErrorNotice";
import { JsonViewer } from "../components/JsonViewer";
import { ProgressBar } from "../components/ProgressBar";
import { StatusBadge } from "../components/StatusBadge";
import { TaskTable } from "../components/TaskTable";
import { isTaskActiveStatus } from "../hooks/useTaskPolling";
import { api } from "../lib/api";
import type { GenerationBatch } from "../types";
import { cn, formatDate, getErrorMessage, toNumberId } from "../utils";

const tabs = [
  { id: "overview", label: "概览" },
  { id: "curriculum", label: "课程方案" },
  { id: "lesson", label: "教案" },
  { id: "assessment", label: "测评" },
  { id: "courseware", label: "课件" },
  { id: "coverage", label: "覆盖报告" },
  { id: "tasks", label: "关联任务" },
] as const;

type TabId = (typeof tabs)[number]["id"];

function StatCard({ label, value }: { label: string; value?: string | number | null }) {
  return (
    <div className="rounded-md border border-line bg-paper/60 px-4 py-3">
      <div className="label">{label}</div>
      <div className="mt-1 break-words text-lg font-bold text-ink">{value ?? "-"}</div>
    </div>
  );
}

function ResultPlaceholder({ title, description }: { title: string; description: string }) {
  return (
    <div className="rounded-md border border-line bg-paper/60 p-5">
      <h3 className="font-bold">{title}</h3>
      <p className="mt-2 text-sm leading-6 text-ink/55">{description}</p>
    </div>
  );
}

function hasActiveTask(batch?: GenerationBatch) {
  return (batch?.tasks ?? []).some((task) => isTaskActiveStatus(task.task_status));
}

export function BatchDetailPage() {
  const routeProjectId = toNumberId(useParams().projectId);
  const batchId = toNumberId(useParams().batchId);
  const [activeTab, setActiveTab] = useState<TabId>("overview");

  const batchQuery = useQuery({
    queryKey: ["generation-batch", batchId],
    queryFn: () => api.getGenerationBatch(batchId),
    enabled: batchId > 0,
    refetchInterval: (query) => {
      const batch = query.state.data as GenerationBatch | undefined;
      return !batch || isTaskActiveStatus(batch.batch_status) || hasActiveTask(batch) ? 5_000 : false;
    },
  });

  const batch = batchQuery.data;
  const projectId = batch?.project_id ?? routeProjectId;
  const tasks = useMemo(() => batch?.tasks ?? [], [batch?.tasks]);

  const projectQuery = useQuery({
    queryKey: ["project", projectId],
    queryFn: () => api.getProject(projectId),
    enabled: projectId > 0,
  });

  if (routeProjectId <= 0 || batchId <= 0) {
    return <ErrorNotice title="批次地址无效" message="请从项目工作台进入一个真实生成批次。" />;
  }

  if (batchQuery.isLoading && !batch) {
    return (
      <div className="flex h-[60vh] items-center justify-center text-sm text-ink/55">
        <Loader2 className="mr-2 animate-spin" size={17} />
        加载批次详情
      </div>
    );
  }

  if (batchQuery.error && !batch) {
    return <ErrorNotice title="批次详情获取失败" message={getErrorMessage(batchQuery.error)} />;
  }

  if (!batch) {
    return <EmptyState title="批次不存在" action={<Link className="btn btn-secondary" to={`/projects/${projectId}`}>返回项目</Link>} />;
  }

  return (
    <div className="space-y-6">
      <section className="flex flex-col justify-between gap-4 xl:flex-row xl:items-end">
        <div>
          <Link className="mb-4 inline-flex items-center gap-2 text-sm font-semibold text-ink/55 hover:text-ink" to={`/projects/${projectId}`}>
            <ArrowLeft size={16} />
            项目工作台
          </Link>
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-3xl font-bold">{batch.batch_name ?? `生成批次 #${batch.batch_no}`}</h1>
            <StatusBadge status={batch.batch_status} />
          </div>
          <div className="mt-2 flex flex-wrap gap-2 text-sm text-ink/55">
            <span>{projectQuery.data?.name ?? `项目 #${projectId}`}</span>
            <span>/</span>
            <span>批次 ID {batch.id}</span>
            <span>/</span>
            <span>{formatDate(batch.updated_at)}</span>
          </div>
        </div>
        <button className="btn btn-secondary" disabled={batchQuery.isFetching} onClick={() => batchQuery.refetch()} type="button">
          <RotateCw className={batchQuery.isFetching ? "animate-spin" : ""} size={16} />
          刷新
        </button>
      </section>

      <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <StatCard label="知识版本" value={batch.knowledge_version_id} />
        <StatCard label="学情版本" value={batch.learner_profile_version_id} />
        <StatCard label="课次" value={batch.course_count} />
        <StatCard label="课时分钟" value={batch.session_duration_minutes} />
      </section>

      <section className="panel overflow-hidden">
        <div className="border-b border-line px-3 py-3">
          <div className="flex gap-2 overflow-x-auto">
            {tabs.map((tab) => (
              <button
                className={cn(
                  "h-9 shrink-0 rounded-md px-3 text-sm font-semibold text-ink/60 transition hover:bg-paper hover:text-ink",
                  activeTab === tab.id && "bg-ink text-white hover:bg-ink hover:text-white",
                )}
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                type="button"
              >
                {tab.label}
              </button>
            ))}
          </div>
        </div>
        <div className="p-5">
          {activeTab === "overview" ? <OverviewTab batch={batch} /> : null}
          {activeTab === "curriculum" ? (
            <ResultPlaceholder
              title={batch.curriculum_plan_id ? `课程方案 #${batch.curriculum_plan_id}` : "暂未产生课程方案"}
              description="Phase 1 只保留成果入口和真实空状态。课程方案详情、导出和阅读体验将在 Phase 4/5 接入。"
            />
          ) : null}
          {activeTab === "lesson" ? (
            <ResultPlaceholder
              title={batch.lesson_plan_ids?.length ? `${batch.lesson_plan_ids.length} 份教案` : "暂未产生教案"}
              description="教案列表和文档式详情将在成果页阶段接入。当前页面只展示批次基线和关联任务。"
            />
          ) : null}
          {activeTab === "assessment" ? (
            <ResultPlaceholder title="测评结果入口" description="测评蓝图、试卷和题目详情已补齐 API client，页面展示留给 Phase 4。" />
          ) : null}
          {activeTab === "courseware" ? (
            <ResultPlaceholder title="课件结果入口" description="课件结果、刷新和回复接口已补齐，PPTX 下载与交互留给 Phase 5。" />
          ) : null}
          {activeTab === "coverage" ? (
            <ResultPlaceholder title="覆盖报告入口" description="覆盖报告列表和详情接口已补齐，报告可视化留给 Phase 4。" />
          ) : null}
          {activeTab === "tasks" ? (
            tasks.length ? <TaskTable tasks={tasks} /> : <EmptyState title="暂无关联任务" />
          ) : null}
        </div>
      </section>
    </div>
  );
}

function OverviewTab({ batch }: { batch: GenerationBatch }) {
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
    </div>
  );
}
