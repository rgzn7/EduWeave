import type { ReactNode } from "react";

export function EmptyState({ title, description, action }: { title: string; description?: string; action?: ReactNode }) {
  return (
    <div className="flex min-h-36 flex-col items-center justify-center gap-3 rounded-md border border-dashed border-line bg-paper/65 px-4 py-6 text-center">
      <div className="text-sm font-semibold text-ink/70">{title}</div>
      {description ? <div className="max-w-xl text-xs leading-5 text-ink/45">{description}</div> : null}
      {action}
    </div>
  );
}
