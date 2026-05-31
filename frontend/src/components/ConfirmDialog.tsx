/**
 * @Date: 2026-05-31
 * @Author: xisy
 * @Discription: 通用确认弹窗，用于重新生成等不可逆操作的二次确认
 */
import { useEffect, type ReactNode } from "react";
import { Loader2 } from "lucide-react";
import { cn } from "../utils";

export function ConfirmDialog({
  open,
  title,
  description,
  confirmText = "确认",
  cancelText = "取消",
  tone = "default",
  loading = false,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  description?: ReactNode;
  confirmText?: string;
  cancelText?: string;
  tone?: "default" | "danger";
  loading?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  // 打开时支持 Esc 取消（生成中禁止关闭，避免误触中断）
  useEffect(() => {
    if (!open) {
      return;
    }
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !loading) {
        onCancel();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [open, loading, onCancel]);

  if (!open) {
    return null;
  }

  return (
    <div
      aria-modal="true"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/35 px-4"
      onClick={() => !loading && onCancel()}
      role="dialog"
    >
      <div
        className="w-full max-w-md rounded-[22px] border border-line bg-white p-6 shadow-panel"
        onClick={(event) => event.stopPropagation()}
      >
        <h3 className="text-lg font-semibold text-ink">{title}</h3>
        {description ? <div className="mt-3 text-sm leading-6 text-ink/64">{description}</div> : null}
        <div className="mt-6 flex justify-end gap-3">
          <button className="btn btn-secondary rounded-full px-5" disabled={loading} onClick={onCancel} type="button">
            {cancelText}
          </button>
          <button
            className={cn(
              "btn rounded-full px-5",
              tone === "danger" ? "bg-coral text-white hover:bg-coral/90" : "btn-primary",
            )}
            disabled={loading}
            onClick={onConfirm}
            type="button"
          >
            {loading ? <Loader2 className="animate-spin" size={16} /> : null}
            {confirmText}
          </button>
        </div>
      </div>
    </div>
  );
}
