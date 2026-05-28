import { ShieldCheck } from "lucide-react";
import type { JsonRecord, QuestionBasis } from "../types";
import { cn } from "../utils";

function isRecord(value: unknown): value is JsonRecord {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

export function getQuestionBasis(value: unknown): QuestionBasis | null {
  return isRecord(value) ? (value as QuestionBasis) : null;
}

export function getQuestionBasisText(value: unknown) {
  if (typeof value === "string") {
    return value.trim();
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return "";
}

function formatBasisSummary(value: unknown) {
  return getQuestionBasisText(value).replace(/^作为(?:基础掌握题|典型应用题|综合提升题|拓展挑战题)，/, "");
}

export function QuestionBasisBlock({ basis, className }: { basis: unknown; className?: string }) {
  const record = getQuestionBasis(basis);
  if (!record) {
    return null;
  }

  const summary = formatBasisSummary(record.basis_summary);
  const entries = [
    ["教材知识点", getQuestionBasisText(record.knowledge_point_name)],
    ["教学目标", getQuestionBasisText(record.teaching_goal)],
  ].filter((entry): entry is [string, string] => Boolean(entry[1]));

  if (!summary && !entries.length) {
    return null;
  }

  return (
    <section className={cn("rounded-2xl border border-line bg-[#fafafa] p-4", className)}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-white text-ink shadow-sm">
            <ShieldCheck size={16} />
          </span>
          <div className="min-w-0">
            <h3 className="text-sm font-semibold text-ink">考查依据</h3>
            {summary ? <p className="mt-1 break-words text-sm leading-6 text-ink/62">{summary}</p> : null}
          </div>
        </div>
      </div>

      {entries.length ? (
        <div className="mt-4 grid gap-3 md:grid-cols-2">
          {entries.map(([label, value]) => (
            <div className="min-w-0 rounded-xl border border-line bg-white px-3 py-2" key={label}>
              <div className="text-xs font-semibold text-ink/42">{label}</div>
              <div className="mt-1 break-words text-sm font-semibold leading-6 text-ink/72">{value}</div>
            </div>
          ))}
        </div>
      ) : null}
    </section>
  );
}
