import type { ReactNode } from "react";
import { AlertTriangle, ArrowRight, Clock3, Loader2 } from "lucide-react";
import { Link } from "react-router-dom";
import { ProgressBar } from "../../components/ProgressBar";
import { StatusBadge } from "../../components/StatusBadge";
import type { Task } from "../../types";
import { formatDate } from "../../utils";
import { displayValue, type JsonObject } from "./helpers";

export function StatCard({ label, value }: { label: string; value?: string | number | null }) {
  return (
    <div className="rounded-md border border-line bg-paper/60 px-4 py-3">
      <div className="label">{label}</div>
      <div className="mt-1 break-words text-lg font-bold text-ink">{value ?? "-"}</div>
    </div>
  );
}

export function ResultPlaceholder({ title, description }: { title: string; description: string }) {
  return (
    <div className="rounded-md border border-line bg-paper/60 p-5">
      <h3 className="font-bold">{title}</h3>
      <p className="mt-2 text-sm leading-6 text-ink/55">{description}</p>
    </div>
  );
}

export function LoadingBlock({ text, description }: { text: string; description?: string }) {
  return (
    <div className="flex min-h-36 flex-col items-center justify-center rounded-md border border-line bg-paper/60 px-4 text-center text-sm font-semibold text-ink/55">
      <div className="flex items-center justify-center">
        <Loader2 className="mr-2 animate-spin" size={17} />
        {text}
      </div>
      {description ? <div className="mt-2 max-w-xl text-xs font-medium leading-5 text-ink/40">{description}</div> : null}
    </div>
  );
}

export function SectionBlock({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="rounded-md border border-line bg-paper/60 p-4">
      <h3 className="text-sm font-bold text-ink">{title}</h3>
      <div className="mt-3">{children}</div>
    </section>
  );
}

export function TextList({ items, empty = "暂无记录" }: { items: string[]; empty?: string }) {
  if (!items.length) {
    return <div className="text-sm text-ink/45">{empty}</div>;
  }
  return (
    <ul className="space-y-2 text-sm leading-6 text-ink/70">
      {items.map((item, index) => (
        <li className="flex gap-2" key={`${item}-${index}`}>
          <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-accent" />
          <span className="min-w-0 break-words">{item}</span>
        </li>
      ))}
    </ul>
  );
}

export function KeyValueGrid({ record }: { record: JsonObject | null }) {
  const entries = Object.entries(record ?? {}).filter(([, value]) => value !== undefined && value !== null && value !== "");
  if (!entries.length) {
    return <div className="text-sm text-ink/45">暂无记录</div>;
  }
  return (
    <div className="grid gap-3 md:grid-cols-2">
      {entries.map(([key, value]) => (
        <div className="rounded-md border border-line bg-white px-3 py-2" key={key}>
          <div className="text-xs font-semibold text-ink/45">{key}</div>
          <div className="mt-1 break-words text-sm font-semibold text-ink/75">{displayValue(value)}</div>
        </div>
      ))}
    </div>
  );
}

export function KnowledgeRefs({ ids }: { ids: number[] }) {
  if (!ids.length) {
    return <span className="text-xs font-semibold text-ink/40">暂无知识点引用</span>;
  }
  const visible = ids.slice(0, 18);
  return (
    <div className="flex flex-wrap gap-2">
      {visible.map((id) => (
        <span className="rounded-md border border-line bg-white px-2 py-1 text-xs font-semibold text-ink/65" key={id}>
          #{id}
        </span>
      ))}
      {ids.length > visible.length ? <span className="px-1 py-1 text-xs font-semibold text-ink/45">+{ids.length - visible.length}</span> : null}
    </div>
  );
}

export function TaskSummaryCard({ title, task, description }: { title: string; task?: Task; description?: string }) {
  return (
    <aside className="rounded-md border border-line bg-paper/60 p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="label">{title}</div>
          <div className="mt-1 text-sm font-bold text-ink">{task ? `任务 #${task.id}` : "暂无关联任务"}</div>
          {description ? <div className="mt-1 max-w-2xl text-xs leading-5 text-ink/45">{description}</div> : null}
        </div>
        {task ? <StatusBadge status={task.task_status} /> : null}
      </div>
      {task ? (
        <>
          <div className="mt-3">
            <ProgressBar value={task.progress_percent} />
          </div>
          <div className="mt-3 grid gap-2 text-xs text-ink/55 md:grid-cols-2">
            <span>类型：{task.task_type}</span>
            <span>阶段：{task.current_stage ?? "-"}</span>
            <span className="flex items-center gap-1">
              <Clock3 size={13} />
              更新：{formatDate(task.updated_at)}
            </span>
            <span>队列：{task.queue_name ?? "-"}</span>
          </div>
          {task.last_error_message ? (
            <div className="mt-3 flex gap-2 rounded-md border border-coral/20 bg-coral/10 p-3 text-xs font-semibold text-coral">
              <AlertTriangle className="mt-0.5 shrink-0" size={14} />
              <div>
                <div>{task.last_error_code ?? "TASK_FAILED"}</div>
                <div className="mt-1 line-clamp-3">{task.last_error_message}</div>
              </div>
            </div>
          ) : null}
          <Link className="btn btn-secondary mt-4 h-9 w-full text-xs" to={`/tasks/${task.id}`}>
            任务详情
            <ArrowRight size={14} />
          </Link>
        </>
      ) : (
        <div className="mt-3 text-xs leading-5 text-ink/50">当前批次还没有产生这个模块的任务记录。</div>
      )}
    </aside>
  );
}
