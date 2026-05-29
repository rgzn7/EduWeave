export type AutoCoreGenerationMarker = {
  createdAt: string;
  courseCount: number;
  sessionDurationMinutes: number;
};

export const DEFAULT_COURSE_COUNT = 12;
export const DEFAULT_SESSION_DURATION_MINUTES = 40;
export const COURSE_COUNT_MIN = 1;
export const COURSE_COUNT_MAX = 36;
export const SESSION_DURATION_MINUTES_MIN = 15;
export const SESSION_DURATION_MINUTES_MAX = 90;

const AUTO_CORE_GENERATION_KEY_PREFIX = "eduweave:auto-core-generation:";

function getAutoCoreGenerationKey(projectId: number) {
  return `${AUTO_CORE_GENERATION_KEY_PREFIX}${projectId}`;
}

function canUseLocalStorage() {
  return typeof window !== "undefined" && Boolean(window.localStorage);
}

function normalizeCourseCount(value: unknown) {
  return typeof value === "number" && Number.isFinite(value)
    ? Math.min(COURSE_COUNT_MAX, Math.max(COURSE_COUNT_MIN, Math.round(value)))
    : DEFAULT_COURSE_COUNT;
}

function normalizeSessionDurationMinutes(value: unknown) {
  return typeof value === "number" && Number.isFinite(value)
    ? Math.min(SESSION_DURATION_MINUTES_MAX, Math.max(SESSION_DURATION_MINUTES_MIN, Math.round(value)))
    : DEFAULT_SESSION_DURATION_MINUTES;
}

export function markAutoCoreGeneration(
  projectId: number,
  settings: { courseCount: number; sessionDurationMinutes: number } = {
    courseCount: DEFAULT_COURSE_COUNT,
    sessionDurationMinutes: DEFAULT_SESSION_DURATION_MINUTES,
  },
) {
  if (!canUseLocalStorage()) {
    return;
  }
  const marker: AutoCoreGenerationMarker = {
    createdAt: new Date().toISOString(),
    courseCount: normalizeCourseCount(settings.courseCount),
    sessionDurationMinutes: normalizeSessionDurationMinutes(settings.sessionDurationMinutes),
  };
  window.localStorage.setItem(getAutoCoreGenerationKey(projectId), JSON.stringify(marker));
}

export function readAutoCoreGenerationMarker(projectId: number): AutoCoreGenerationMarker | null {
  if (!canUseLocalStorage() || projectId <= 0) {
    return null;
  }
  const rawValue = window.localStorage.getItem(getAutoCoreGenerationKey(projectId));
  if (!rawValue) {
    return null;
  }
  try {
    const parsed = JSON.parse(rawValue) as Partial<AutoCoreGenerationMarker>;
    return typeof parsed.createdAt === "string"
      ? {
          createdAt: parsed.createdAt,
          courseCount: normalizeCourseCount(parsed.courseCount),
          sessionDurationMinutes: normalizeSessionDurationMinutes(parsed.sessionDurationMinutes),
        }
      : null;
  } catch {
    return null;
  }
}

export function clearAutoCoreGenerationMarker(projectId: number) {
  if (!canUseLocalStorage()) {
    return;
  }
  window.localStorage.removeItem(getAutoCoreGenerationKey(projectId));
}
