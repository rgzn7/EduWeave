import type { ReactNode } from "react";
import { AlertCircle } from "lucide-react";

export function ErrorNotice({ title = "请求失败", message, action }: { title?: string; message?: string; action?: ReactNode }) {
  return (
    <div className="flex gap-3 rounded-md border border-coral/25 bg-coral/10 p-4 text-sm text-coral">
      <AlertCircle className="mt-0.5 shrink-0" size={18} />
      <div className="min-w-0">
        <div className="font-bold">{title}</div>
        <div className="mt-1 break-words text-coral/85">{message ?? "请稍后重试，或进入任务详情查看后端返回的真实错误。"}</div>
        {action ? <div className="mt-3">{action}</div> : null}
      </div>
    </div>
  );
}
