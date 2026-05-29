import { Eye } from "lucide-react";
import { Link } from "react-router-dom";
import { ProgressBar } from "./ProgressBar";
import { StatusBadge } from "./StatusBadge";
import { formatDate } from "../utils";
import type { Task } from "../types";

export function TaskTable({ tasks }: { tasks: Task[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[820px] border-collapse text-left text-sm">
        <thead>
          <tr className="border-b border-line text-xs uppercase tracking-wide text-ink/50">
            <th className="px-5 py-3 font-semibold">模块</th>
            <th className="px-5 py-3 font-semibold">类型</th>
            <th className="px-5 py-3 font-semibold">状态</th>
            <th className="px-5 py-3 font-semibold">进度</th>
            <th className="px-5 py-3 font-semibold">更新时间</th>
            <th className="px-5 py-3 font-semibold">错误</th>
            <th className="px-5 py-3 font-semibold">操作</th>
          </tr>
        </thead>
        <tbody>
          {tasks.map((task) => (
            <tr className="border-b border-line/70 last:border-0" key={task.id}>
              <td className="px-5 py-3 font-semibold text-ink">{task.module_code}</td>
              <td className="px-5 py-3 text-ink/70">{task.task_type}</td>
              <td className="px-5 py-3">
                <StatusBadge status={task.task_status} />
              </td>
              <td className="px-5 py-3">
                <ProgressBar value={task.progress_percent} />
              </td>
              <td className="px-5 py-3 text-ink/60">{formatDate(task.updated_at)}</td>
              <td className="max-w-[220px] truncate px-5 py-3 text-coral" title={task.last_error_message ?? ""}>
                {task.last_error_message ?? "-"}
              </td>
              <td className="px-5 py-3">
                <Link className="btn btn-secondary h-8 px-3 text-xs" to={`/tasks/${task.id}`}>
                  <Eye size={14} />
                  详情
                </Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
