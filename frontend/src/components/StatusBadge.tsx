import { CheckCircle2, Clock3, Loader2, XCircle } from "lucide-react";
import { cn } from "../utils";

const statusTone: Record<string, string> = {
  success: "border-leaf/20 bg-leaf/10 text-leaf",
  ready: "border-leaf/20 bg-leaf/10 text-leaf",
  active: "border-leaf/20 bg-leaf/10 text-leaf",
  available: "border-leaf/20 bg-leaf/10 text-leaf",
  confirmed: "border-leaf/20 bg-leaf/10 text-leaf",
  uploaded: "border-leaf/20 bg-leaf/10 text-leaf",
  running: "border-accent/20 bg-accent/10 text-accent",
  processing: "border-accent/20 bg-accent/10 text-accent",
  pending: "border-gold/25 bg-gold/10 text-gold",
  draft: "border-gold/25 bg-gold/10 text-gold",
  archived: "border-ink/10 bg-ink/5 text-ink/65",
  failed: "border-coral/25 bg-coral/10 text-coral",
  failure: "border-coral/25 bg-coral/10 text-coral",
  error: "border-coral/25 bg-coral/10 text-coral",
  cancelled: "border-ink/10 bg-ink/5 text-ink/65",
  partial_success: "border-gold/25 bg-gold/10 text-gold",
};

const statusLabel: Record<string, string> = {
  success: "成功",
  ready: "就绪",
  active: "启用",
  available: "可用",
  confirmed: "已确认",
  uploaded: "已上传",
  running: "运行中",
  processing: "处理中",
  pending: "等待",
  draft: "草稿",
  archived: "已归档",
  failed: "失败",
  failure: "失败",
  error: "异常",
  cancelled: "已取消",
  partial_success: "部分成功",
  unknown: "未知",
};

function StatusIcon({ status }: { status: string }) {
  if (["success", "ready", "available", "confirmed", "active", "uploaded"].includes(status)) {
    return <CheckCircle2 size={14} />;
  }
  if (status === "running" || status === "processing") {
    return <Loader2 className="animate-spin" size={14} />;
  }
  if (status === "failed" || status === "failure" || status === "error") {
    return <XCircle size={14} />;
  }
  return <Clock3 size={14} />;
}

export function StatusBadge({ status }: { status?: string | null }) {
  const normalized = status ?? "unknown";
  return (
    <span
      className={cn(
        "inline-flex h-7 items-center gap-1.5 rounded-md border px-2 text-xs font-semibold",
        statusTone[normalized] ?? "border-ink/10 bg-ink/5 text-ink/65",
      )}
    >
      <StatusIcon status={normalized} />
      {statusLabel[normalized] ?? normalized}
    </span>
  );
}
