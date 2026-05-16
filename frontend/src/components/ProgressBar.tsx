export function ProgressBar({ value, label }: { value?: number | null; label?: string }) {
  const normalized = Math.max(0, Math.min(100, value ?? 0));
  return (
    <div className="flex items-center gap-3">
      <div className="h-2 w-full min-w-24 rounded-full bg-ink/10">
        <div className="h-2 rounded-full bg-accent transition-all" style={{ width: `${normalized}%` }} />
      </div>
      <span className="w-12 shrink-0 text-right text-xs font-semibold text-ink/55">{label ?? `${normalized}%`}</span>
    </div>
  );
}
