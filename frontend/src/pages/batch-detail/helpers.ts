import { isTaskActiveStatus } from "../../hooks/useTaskPolling";
import type { GenerationBatch, LessonPlan, Task } from "../../types";

export type JsonObject = Record<string, unknown>;

export function asRecord(value: unknown): JsonObject | null {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as JsonObject) : null;
}

export function asRecordList(value: unknown): JsonObject[] {
  return Array.isArray(value) ? value.map(asRecord).filter((item): item is JsonObject => Boolean(item)) : [];
}

export function asStringList(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.map((item) => String(item)).filter((item) => item.trim().length > 0);
  }
  return typeof value === "string" && value.trim() ? [value] : [];
}

export function asNumberList(value: unknown): number[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.map((item) => Number(item)).filter((item) => Number.isFinite(item));
}

export function displayValue(value: unknown): string {
  if (value === undefined || value === null || value === "") {
    return "-";
  }
  if (Array.isArray(value)) {
    return value.length ? value.map((item) => displayValue(item)).join("、") : "-";
  }
  if (typeof value === "object") {
    try {
      return JSON.stringify(value);
    } catch {
      return String(value);
    }
  }
  return String(value);
}

export function formatLessonTitle(title?: string | null) {
  const original = String(title ?? "").trim();
  if (!original) {
    return "未命名课程";
  }
  const cleaned = original
    .replace(/^第\s*[一二三四五六七八九十百千万\d]+\s*(?:课次|课时|讲|课|节|次)\s*[：:、,，.\-\s]*/u, "")
    .replace(/^(?:课次|课时|次)\s*[：:、,，.\-\s]+/u, "")
    .trim();
  return cleaned || original;
}

export function latestByUpdated<T extends { id: number; updated_at: string }>(items: T[]) {
  return [...items].sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime() || b.id - a.id)[0];
}

export function sortLessons(items: LessonPlan[]) {
  return [...items].sort((a, b) => {
    const sessionDiff = (a.class_session_no ?? Number.MAX_SAFE_INTEGER) - (b.class_session_no ?? Number.MAX_SAFE_INTEGER);
    return sessionDiff || b.id - a.id;
  });
}

export function taskMatches(task: Task, moduleCode: string) {
  return task.module_code === moduleCode || task.task_type.includes(moduleCode);
}

export function latestTask(tasks: Task[], moduleCode: string) {
  return latestByUpdated(tasks.filter((task) => taskMatches(task, moduleCode)));
}

export function hasActiveTask(batch?: GenerationBatch) {
  return (batch?.tasks ?? []).some((task) => isTaskActiveStatus(task.task_status));
}

export function isBatchLive(batch?: GenerationBatch) {
  return !batch || isTaskActiveStatus(batch.batch_status) || hasActiveTask(batch);
}
