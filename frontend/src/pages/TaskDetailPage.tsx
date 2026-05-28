import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Clock3, ExternalLink, Loader2, RotateCw } from "lucide-react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ErrorNotice } from "../components/ErrorNotice";
import { JsonViewer } from "../components/JsonViewer";
import { ProgressBar } from "../components/ProgressBar";
import { StatusBadge } from "../components/StatusBadge";
import { isTaskActiveStatus } from "../hooks/useTaskPolling";
import { api } from "../lib/api";
import type { TaskDetail, TaskStep } from "../types";
import { formatDate, getErrorMessage, toNumberId } from "../utils";

function DetailItem({ label, value }: { label: string; value?: string | number | null }) {
  return (
    <div className="rounded-md border border-line bg-paper/60 px-4 py-3">
      <div className="label">{label}</div>
      <div className="mt-1 break-words text-sm font-semibold text-ink">{value ?? "-"}</div>
    </div>
  );
}

function StepTimeline({ steps }: { steps: TaskStep[] }) {
  if (!steps.length) {
    return <div className="rounded-md border border-line bg-paper/60 p-4 text-sm text-ink/45">暂无步骤记录</div>;
  }

  return (
    <div className="space-y-3">
      {[...steps]
        .sort((a, b) => a.step_order - b.step_order)
        .map((step) => (
          <div className="rounded-md border border-line bg-white p-4" key={step.id}>
            <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-xs font-bold text-ink/45">#{step.step_order}</span>
                  <h3 className="text-sm font-bold">{step.step_name}</h3>
                  <StatusBadge status={step.step_status} />
                </div>
                <div className="mt-1 text-xs text-ink/45">{step.step_code}</div>
              </div>
              <div className="w-full md:w-48">
                <ProgressBar value={step.progress_percent} />
              </div>
            </div>
            <div className="mt-4 grid gap-3 text-xs text-ink/55 md:grid-cols-3">
              <span>开始：{formatDate(step.started_at)}</span>
              <span>结束：{formatDate(step.finished_at)}</span>
              <span>更新：{formatDate(step.updated_at)}</span>
            </div>
            {step.detail_json ? (
              <div className="mt-4">
                <JsonViewer title="步骤明细" value={step.detail_json} />
              </div>
            ) : null}
          </div>
        ))}
    </div>
  );
}

function TaskErrorPanel({ task }: { task: TaskDetail }) {
  const hasError = task.last_error_code || task.last_error_message;
  return (
    <section className="panel overflow-hidden">
      <div className="panel-header">
        <div>
          <h2 className="text-lg font-bold">错误与载荷</h2>
          <div className="text-sm text-ink/55">后端原始诊断信息</div>
        </div>
      </div>
      <div className="space-y-4 p-5">
        {hasError ? (
          <ErrorNotice title={task.last_error_code ?? "任务失败"} message={task.last_error_message ?? "后端未返回错误描述"} />
        ) : (
          <div className="rounded-md border border-line bg-paper/60 p-4 text-sm text-ink/45">当前任务暂无错误记录</div>
        )}
        <div className="grid gap-4 xl:grid-cols-2">
          <JsonViewer title="payload_json" value={task.payload_json} />
          <JsonViewer title="result_json" value={task.result_json} />
        </div>
      </div>
    </section>
  );
}

export function TaskDetailPage() {
  const navigate = useNavigate();
  const taskId = toNumberId(useParams().taskId);

  const taskQuery = useQuery({
    queryKey: ["task", taskId],
    queryFn: () => api.getTask(taskId),
    enabled: taskId > 0,
    refetchInterval: (query) => {
      const task = query.state.data as TaskDetail | undefined;
      return !task || isTaskActiveStatus(task.task_status) ? 5_000 : false;
    },
  });

  const currentTask = taskQuery.data;

  if (taskId <= 0) {
    return <EmptyTaskState title="任务地址无效" />;
  }

  if (taskQuery.isLoading && !currentTask) {
    return (
      <div className="flex h-[60vh] items-center justify-center text-sm text-ink/55">
        <Loader2 className="mr-2 animate-spin" size={17} />
        加载任务详情
      </div>
    );
  }

  if (taskQuery.error && !currentTask) {
    return <EmptyTaskState title="任务详情获取失败" message={getErrorMessage(taskQuery.error)} />;
  }

  if (!currentTask) {
    return <EmptyTaskState title="任务不存在" />;
  }

  return (
    <div className="space-y-6">
      <section className="flex flex-col justify-between gap-4 xl:flex-row xl:items-end">
        <div>
          <button className="mb-4 inline-flex items-center gap-2 text-sm font-semibold text-ink/55 hover:text-ink" onClick={() => navigate(-1)} type="button">
            <ArrowLeft size={16} />
            返回
          </button>
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-3xl font-bold">任务 #{currentTask.id}</h1>
            <StatusBadge status={currentTask.task_status} />
          </div>
          <div className="mt-2 flex flex-wrap gap-2 text-sm text-ink/55">
            <span>{currentTask.module_code}</span>
            <span>/</span>
            <span>{currentTask.task_type}</span>
            <span>/</span>
            <span>{currentTask.current_stage ?? "未记录阶段"}</span>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link className="btn btn-secondary" to={`/projects/${currentTask.project_id}`}>
            <ExternalLink size={16} />
            项目
          </Link>
          <button className="btn btn-secondary" disabled={taskQuery.isFetching} onClick={() => taskQuery.refetch()} type="button">
            <RotateCw className={taskQuery.isFetching ? "animate-spin" : ""} size={16} />
            刷新
          </button>
        </div>
      </section>

      <section className="panel overflow-hidden">
        <div className="panel-header">
          <div>
            <h2 className="text-lg font-bold">任务概览</h2>
            <div className="text-sm text-ink/55">基础信息与实时进度</div>
          </div>
        </div>
        <div className="space-y-5 p-5">
          <ProgressBar value={currentTask.progress_percent} />
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            <DetailItem label="项目 ID" value={currentTask.project_id} />
            <DetailItem label="生成批次 ID" value={currentTask.generation_batch_id} />
            <DetailItem label="队列" value={currentTask.queue_name} />
            <DetailItem label="业务键" value={currentTask.biz_key} />
            <DetailItem label="Worker Task" value={currentTask.worker_task_id} />
            <DetailItem label="重试" value={`${currentTask.retry_count}/${currentTask.max_retry_count}`} />
            <DetailItem label="开始时间" value={formatDate(currentTask.started_at)} />
            <DetailItem label="结束时间" value={formatDate(currentTask.finished_at)} />
          </div>
          <div className="flex items-center gap-2 text-xs font-semibold text-ink/45">
            <Clock3 size={14} />
            最近更新：{formatDate(currentTask.updated_at)}
          </div>
        </div>
      </section>

      <section className="panel overflow-hidden">
        <div className="panel-header">
          <div>
            <h2 className="text-lg font-bold">执行步骤</h2>
            <div className="text-sm text-ink/55">{currentTask.steps.length} 个步骤</div>
          </div>
        </div>
        <div className="p-5">
          <StepTimeline steps={currentTask.steps} />
        </div>
      </section>

      <TaskErrorPanel task={currentTask} />
    </div>
  );
}

function EmptyTaskState({ title, message }: { title: string; message?: string }) {
  return (
    <div className="panel p-8">
      <ErrorNotice title={title} message={message ?? "请从任务列表进入一个真实任务。"} />
      <Link className="btn btn-secondary mt-5" to="/">
        返回项目总览
      </Link>
    </div>
  );
}
