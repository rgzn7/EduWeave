const ACTIVE_TASK_STATUSES = new Set(["pending", "running", "processing"]);

export function isTaskActiveStatus(status?: string | null) {
  return ACTIVE_TASK_STATUSES.has(status ?? "");
}
