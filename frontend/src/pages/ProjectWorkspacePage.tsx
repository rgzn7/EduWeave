import { type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  ArrowRight,
  BookOpen,
  Check,
  ChevronDown,
  Circle,
  ClipboardCheck,
  Clock3,
  ExternalLink,
  FileText,
  Layers3,
  ListChecks,
  Loader2,
  Presentation,
  Sparkles,
  Target,
  Upload,
  Wand2,
  type LucideIcon,
} from "lucide-react";
import { Link, useLocation, useParams } from "react-router-dom";
import { EmptyState } from "../components/EmptyState";
import { ErrorNotice } from "../components/ErrorNotice";
import { isTaskActiveStatus } from "../hooks/useTaskPolling";
import {
  DEFAULT_COURSE_COUNT,
  DEFAULT_SESSION_DURATION_MINUTES,
} from "../lib/autoCoreGeneration";
import { api } from "../lib/api";
import type {
  CoursewareResult,
  CoverageReport,
  GenerationBatch,
  GenerationProcess,
  GenerationProcessStatus,
  GenerationProcessStep,
  JsonRecord,
  KnowledgeChapter,
  KnowledgePoint,
  KnowledgeVersion,
  LearnerClassProfile,
  LearnerProfileFile,
  LearnerProfileRecord,
  LearnerProfileSubjectOverview,
  LearnerProfileTieredGroup,
  LearnerProfileVersion,
  PageResult,
  PaperResult,
  ParseEvidenceSummary,
  ParseVersion,
  Project,
  Task,
  TextbookVersion,
} from "../types";
import { cn, formatDate, getErrorMessage, toNumberId } from "../utils";

const READY_STATUS = "ready";
const SUCCESS_STATUS = "success";
const CONFIRMED_STATUS = "confirmed";
const PROCESS_STEP_COUNT = 5;
const FAST_REFETCH_WINDOW_MS = 15_000;
const FAILURE_STATUSES = new Set(["failed", "failure", "error", "cancelled"]);

type ProjectWorkspaceLocationState = {
  generationSettings?: {
    courseCount?: number;
    sessionDurationMinutes?: number;
  };
} | null;

type ProcessState = "complete" | "current" | "waiting";

type ActionConfig = {
  title: string;
  message: string;
  meta?: string;
  buttonLabel?: string;
  buttonIcon?: LucideIcon;
  disabled?: boolean;
  loading?: boolean;
  onClick?: () => void;
};

type StepMaterialAction = {
  label: string;
  href?: string;
  state?: Record<string, unknown>;
  fileName?: string;
  metaItems?: string[];
  openLabel?: string;
  opening?: boolean;
  disabled?: boolean;
  onOpen?: () => void;
};

function latestById<T extends { id: number }>(items: T[] | undefined) {
  return [...(items ?? [])].sort((a, b) => b.id - a.id)[0];
}

function latestTaskBy(tasks: Task[], predicate: (task: Task) => boolean) {
  return [...tasks]
    .filter(predicate)
    .sort((a, b) => {
      const updatedDiff = new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime();
      return updatedDiff || b.id - a.id;
    })[0];
}

function isTextbookParseTask(task: Task) {
  return task.module_code === "parsing" || task.task_type === "textbook_parse";
}

function isKnowledgeTask(task: Task) {
  return task.module_code === "knowledge" || task.task_type === "knowledge_extract";
}

function isLearnerProfileTask(task: Task) {
  return task.module_code === "learner_profile" || task.task_type === "learner_profile_extract";
}

function numberValue(value: unknown) {
  if (typeof value === "number" && Number.isFinite(value) && value > 0) {
    return value;
  }
  if (typeof value === "string" && value.trim()) {
    const number = Number(value);
    return Number.isFinite(number) && number > 0 ? number : null;
  }
  return null;
}

function parseVersionIdFromTask(task: Task) {
  const payload = valueAsRecord(task.payload_json);
  const result = valueAsRecord(task.result_json);
  return numberValue(payload?.parse_version_id) ?? numberValue(result?.parse_version_id);
}

function isReadyVersion(item?: { version_status?: string | null }) {
  return item?.version_status === READY_STATUS;
}

function isConfirmedParseVersion(parseVersion?: ParseVersion) {
  return parseVersion?.parse_status === SUCCESS_STATUS && parseVersion.review_status === CONFIRMED_STATUS;
}

function preferredParseVersion(parseVersions: ParseVersion[], tasks: Task[]) {
  const ordered = [...parseVersions].sort((a, b) => b.id - a.id);
  const knowledgeParseVersionId = [...tasks]
    .filter((task) => isKnowledgeTask(task) && !isFailureStatus(task.task_status))
    .sort((a, b) => {
      const updatedDiff = new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime();
      return updatedDiff || b.id - a.id;
    })
    .map(parseVersionIdFromTask)
    .find((id): id is number => id !== null && ordered.some((item) => item.id === id));
  const knowledgeVersionParse = ordered.find((item) => item.id === knowledgeParseVersionId);

  return (
    knowledgeVersionParse ??
    ordered.find((item) => isConfirmedParseVersion(item) && isReadyVersion(item)) ??
    ordered.find(isConfirmedParseVersion) ??
    ordered.find((item) => item.parse_status === SUCCESS_STATUS && isReadyVersion(item)) ??
    ordered.find((item) => item.parse_status === SUCCESS_STATUS) ??
    ordered[0]
  );
}

function isReadyProfileVersion(profileVersion?: LearnerProfileVersion) {
  return profileVersion?.extract_status === SUCCESS_STATUS && isReadyVersion(profileVersion);
}

function isCompleteStatus(status?: string | null) {
  return ["success", "completed", "complete", "ready", "done"].includes(String(status ?? "").toLowerCase());
}

function isTaskSuccessStatus(status?: string | null) {
  return isCompleteStatus(status);
}

function normalizeGenerationSetting(value: unknown, fallback: number) {
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? Math.round(value) : fallback;
}

function isFailureStatus(status?: string | null) {
  return FAILURE_STATUSES.has(String(status ?? "").toLowerCase());
}

function taskErrorMessage(task: Task | undefined, fallback: string) {
  return task?.last_error_message || fallback;
}

function formatElapsedTime(startedAt: string, now: number) {
  const startTime = new Date(startedAt).getTime();
  if (!Number.isFinite(startTime)) {
    return "";
  }
  const totalSeconds = Math.max(0, Math.floor((now - startTime) / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

function valueAsRecord(value: unknown): JsonRecord | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  return value as JsonRecord;
}

function stringValue(value: unknown) {
  if (typeof value === "string" && value.trim()) {
    return value.trim();
  }
  if (typeof value === "number" && Number.isFinite(value)) {
    return String(value);
  }
  return "";
}

function fileNameFrom(source: unknown, fallback?: string | null) {
  const record = valueAsRecord(source);
  const candidates = [
    record?.original_filename,
    record?.filename,
    record?.file_name,
    record?.name,
    record?.object_key,
    record?.key,
    fallback,
  ];
  return candidates.map(stringValue).find(Boolean) ?? "已上传文件";
}

function fileObjectIdFrom(source: unknown, fallback?: number | null) {
  const record = valueAsRecord(source);
  return numberValue(record?.id) ?? numberValue(record?.file_object_id) ?? numberValue(fallback);
}

function extractTagItems(value: unknown): string[] {
  if (!value) {
    return [];
  }
  if (Array.isArray(value)) {
    return value.flatMap((item) => extractTagItems(item)).filter(Boolean);
  }
  if (typeof value === "string" || typeof value === "number") {
    return [String(value)];
  }
  const record = valueAsRecord(value);
  if (!record) {
    return [];
  }
  const preferred = record.items ?? record.tags ?? record.values ?? record.list;
  if (preferred) {
    return extractTagItems(preferred);
  }
  return Object.values(record)
    .flatMap((item) => extractTagItems(item))
    .filter(Boolean);
}

function uniqueItems(items: string[], limit = 5) {
  return [...new Set(items.map((item) => item.trim()).filter(Boolean))].slice(0, limit);
}

function displayCount(value: number | null | undefined, fallback = "-") {
  return value === undefined || value === null ? fallback : String(value);
}

function stripKnownFileExtension(value: string) {
  return value.replace(/\.(pdf|docx?|pptx?)$/i, "");
}

function StepStatusIcon({ state }: { state: ProcessState }) {
  if (state === "complete") {
    return (
      <span className="flex h-6 w-6 items-center justify-center rounded-full bg-ink text-white">
        <Check size={14} strokeWidth={2.4} />
      </span>
    );
  }
  if (state === "current") {
    return (
      <span className="flex h-6 w-6 items-center justify-center rounded-full border border-ink/15 bg-white">
        <span className="h-2.5 w-2.5 rounded-full bg-ink" />
      </span>
    );
  }
  return (
    <span className="flex h-6 w-6 items-center justify-center rounded-full border border-line bg-[#f5f5f5] text-ink/25">
      <Circle size={8} fill="currentColor" />
    </span>
  );
}

function ProcessStepCard({
  state,
  icon: Icon,
  title,
  waitingText,
  currentText,
  children,
}: {
  state: ProcessState;
  icon: LucideIcon;
  title: string;
  waitingText: string;
  currentText?: string;
  children: ReactNode;
}) {
  const isOpen = state === "complete";

  return (
    <article className={cn("process-reveal relative rounded-[18px] border bg-white p-5 shadow-panel", state === "waiting" ? "border-line/70 opacity-72" : "border-line")}>
      <div className="flex items-start gap-4">
        <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-[#f4f4f4] text-ink">
          <Icon size={21} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-3">
            <h2 className="text-lg font-semibold tracking-[-0.01em] text-ink">{title}</h2>
            {state === "current" ? <Loader2 className="animate-spin text-ink/45" size={16} /> : null}
          </div>
          {!isOpen ? <p className="mt-2 text-sm leading-6 text-ink/48">{state === "current" ? currentText ?? waitingText : waitingText}</p> : null}
          {isOpen ? <div className="mt-4">{children}</div> : null}
        </div>
      </div>
    </article>
  );
}

function ProcessTimeline({ children }: { children: ReactNode }) {
  return (
    <div className="relative space-y-4">
      <div className="absolute left-3 top-4 hidden h-[calc(100%-2rem)] w-px bg-line md:block" />
      {children}
    </div>
  );
}

function FilePill({ icon: Icon, label, fileName }: { icon: LucideIcon; label: string; fileName: string }) {
  return (
    <div className="flex min-w-0 items-center gap-3 rounded-2xl border border-line bg-[#fbfbfb] px-4 py-3">
      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-white text-ink shadow-[0_1px_8px_rgba(17,17,17,0.04)]">
        <Icon size={19} />
      </div>
      <div className="min-w-0">
        <div className="text-sm font-semibold text-ink">{label}</div>
        <div className="mt-1 truncate text-sm text-ink/52">{fileName}</div>
      </div>
    </div>
  );
}

function SoftNotice({ children }: { children: ReactNode }) {
  return <div className="rounded-2xl border border-line bg-[#f7f7f7] px-4 py-3 text-sm leading-6 text-ink/55">{children}</div>;
}

function MetricStrip({ items }: { items: Array<{ label: string; value: string | number }> }) {
  return (
    <div className="grid divide-y divide-line rounded-2xl border border-line bg-[#fbfbfb] md:grid-cols-4 md:divide-x md:divide-y-0">
      {items.map((item) => (
        <div className="px-4 py-3 text-center" key={item.label}>
          <div className="text-xl font-semibold text-ink">{item.value}</div>
          <div className="mt-1 text-xs text-ink/45">{item.label}</div>
        </div>
      ))}
    </div>
  );
}

function ChipList({ items, emptyText }: { items: string[]; emptyText: string }) {
  if (!items.length) {
    return <span className="text-sm text-ink/45">{emptyText}</span>;
  }
  return (
    <div className="flex flex-wrap gap-2">
      {items.map((item) => (
        <span className="rounded-full bg-[#f1f1f1] px-3 py-1 text-xs font-medium text-ink/64" key={item}>
          {item}
        </span>
      ))}
    </div>
  );
}

function ParseSummaryCard({
  parseVersion,
  summary,
  isLoading,
}: {
  parseVersion?: ParseVersion;
  summary?: ParseEvidenceSummary;
  isLoading: boolean;
}) {
  const volume = summary?.volume;

  return (
    <div className="space-y-3">
      <MetricStrip
        items={[
          { label: "页数", value: displayCount(volume?.page_count ?? summary?.page_count ?? parseVersion?.page_count) },
          { label: "图片", value: displayCount(volume?.image_block_count) },
          { label: "表格", value: displayCount(volume?.table_block_count) },
          { label: "公式", value: displayCount(volume?.equation_block_count) },
        ]}
      />
      {!summary ? (
        <SoftNotice>{isLoading ? "正在读取教材理解结果。" : "教材理解结果已完成，结构化证据正在同步。"}</SoftNotice>
      ) : null}
    </div>
  );
}

function KnowledgeSummaryCard({
  knowledgeVersion,
  chapters,
  points,
  isLoading,
}: {
  knowledgeVersion?: KnowledgeVersion;
  chapters?: KnowledgeChapter[];
  points?: PageResult<KnowledgePoint>;
  isLoading: boolean;
}) {
  const pointItems = points?.items ?? [];
  const keyPoints = uniqueItems(pointItems.map((point) => point.point_name), 6);

  return (
    <div className="space-y-3">
      <MetricStrip
        items={[
          { label: "章节", value: displayCount(chapters?.length ?? knowledgeVersion?.chapter_count) },
          { label: "知识点", value: displayCount(points?.pagination?.total_count ?? knowledgeVersion?.point_count) },
          { label: "重点内容", value: keyPoints.length || "-" },
          { label: "证据来源", value: pointItems.reduce((total, point) => total + (point.evidence_count ?? 0), 0) || "-" },
        ]}
      />
      <div className="rounded-2xl border border-line bg-[#fbfbfb] p-4">
        <div className="text-xs font-medium text-ink/42">重点知识</div>
        <div className="mt-3">
          <ChipList items={keyPoints} emptyText={isLoading ? "正在读取知识点" : "暂无知识点摘要"} />
        </div>
      </div>
    </div>
  );
}

function ResourceChecklist({
  batch,
  lessonPlans,
  paperResults,
  coursewareResults,
  coverageReports,
}: {
  batch?: GenerationBatch;
  lessonPlans?: PageResult<{ id: number }>;
  paperResults?: PageResult<PaperResult>;
  coursewareResults?: PageResult<CoursewareResult>;
  coverageReports?: PageResult<CoverageReport>;
}) {
  const paperSceneCount = new Set((paperResults?.items ?? []).filter((item) => item.scene_type !== "unit_test").map((item) => item.scene_type)).size;
  const hasCoverage = (coverageReports?.items ?? []).some((item) => isCompleteStatus(item.report_status));
  const lessonCount = lessonPlans?.pagination?.total_count ?? 0;
  const coursewareCount = coursewareResults?.pagination?.total_count ?? 0;

  const rows = [
    { label: "课程方案", value: batch?.curriculum_plan_id ? "已生成" : "准备中" },
    { label: "多课教案", value: lessonCount ? `${lessonCount} 份` : batch?.curriculum_plan_id ? "生成中" : "等待课程方案" },
    { label: "覆盖报告", value: hasCoverage ? "已完成" : lessonCount ? "准备中" : "等待教案" },
    { label: "PPT 课件", value: coursewareCount ? `${coursewareCount} 份` : "按课生成" },
    { label: "课后作业", value: "按课生成" },
    { label: "配套测练", value: paperSceneCount ? `${paperSceneCount} 类` : "按整套生成" },
  ];

  return (
    <div className="divide-y divide-line">
      {rows.map((row) => (
        <div className="flex items-center justify-between gap-4 py-3 text-sm" key={row.label}>
          <span className="text-ink/62">{row.label}</span>
          <span className="font-semibold text-ink">{row.value}</span>
        </div>
      ))}
    </div>
  );
}

function GeneratedResourcesSummary({
  batch,
  lessonPlans,
  paperResults,
  coursewareResults,
  coverageReports,
}: {
  batch?: GenerationBatch;
  lessonPlans?: PageResult<{ id: number }>;
  paperResults?: PageResult<PaperResult>;
  coursewareResults?: PageResult<CoursewareResult>;
  coverageReports?: PageResult<CoverageReport>;
}) {
  if (!batch) {
    return <SoftNotice>整理好教学重点后，就可以生成课程方案和多课教案；PPT 与课后作业可按课生成，期末综合测可按整套生成。</SoftNotice>;
  }

  return (
    <div className="rounded-2xl border border-line bg-[#fbfbfb] px-4 py-2">
      <ResourceChecklist
        batch={batch}
        lessonPlans={lessonPlans}
        paperResults={paperResults}
        coursewareResults={coursewareResults}
        coverageReports={coverageReports}
      />
    </div>
  );
}

function CurrentActionPanel({
  action,
  batch,
  lessonPlans,
  paperResults,
  coursewareResults,
  coverageReports,
}: {
  action: ActionConfig;
  batch?: GenerationBatch;
  lessonPlans?: PageResult<{ id: number }>;
  paperResults?: PageResult<PaperResult>;
  coursewareResults?: PageResult<CoursewareResult>;
  coverageReports?: PageResult<CoverageReport>;
}) {
  const ButtonIcon = action.buttonIcon ?? ArrowRight;

  return (
    <aside className="sticky top-8 space-y-4">
      <section className="rounded-[18px] border border-line bg-white p-5 shadow-panel">
        <div className="flex items-start gap-3">
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-[#f4f4f4] text-ink">
            <Sparkles size={21} />
          </div>
          <div>
            <h2 className="text-lg font-semibold text-ink">{action.title}</h2>
            <p className="mt-2 text-sm leading-6 text-ink/55">{action.message}</p>
            {action.meta ? (
              <div className="mt-3 inline-flex rounded-full bg-[#f4f4f4] px-3 py-1 text-xs font-semibold text-ink/50">{action.meta}</div>
            ) : null}
          </div>
        </div>
        {action.buttonLabel ? (
          <button
            className="btn btn-primary mt-5 h-12 w-full rounded-full"
            disabled={action.disabled || action.loading}
            onClick={action.onClick}
            type="button"
          >
            {action.loading ? <Loader2 className="animate-spin" size={17} /> : <ButtonIcon size={17} />}
            {action.buttonLabel}
          </button>
        ) : null}
        <div className="mt-5 border-t border-line pt-2">
          <ResourceChecklist
            batch={batch}
            lessonPlans={lessonPlans}
            paperResults={paperResults}
            coursewareResults={coursewareResults}
            coverageReports={coverageReports}
          />
        </div>
      </section>
    </aside>
  );
}

const PHASE2_STEP_ORDER = [
  "learner_profile",
  "mineru_parse",
  "knowledge_structure",
  "curriculum_plan",
  "lesson_plan_generate",
  "coverage_check",
] as const;

const phase2StepOrderIndex = new Map<string, number>(PHASE2_STEP_ORDER.map((code, index) => [code, index]));

function orderPhase2Steps(steps: GenerationProcessStep[]) {
  return [...steps].sort((left, right) => {
    const leftIndex = phase2StepOrderIndex.get(left.code) ?? Number.MAX_SAFE_INTEGER;
    const rightIndex = phase2StepOrderIndex.get(right.code) ?? Number.MAX_SAFE_INTEGER;
    return leftIndex - rightIndex;
  });
}

const PHASE2_STEP_UI: Record<
  string,
  {
    title: string;
    toolName: string;
    description: string;
    icon: LucideIcon;
  }
> = {
  mineru_parse: {
    title: "教材内容解析",
    toolName: "使用 MinerU 教材解析工具",
    description: "识别教材章节、页码、图表、题目和知识点。",
    icon: FileText,
  },
  learner_profile: {
    title: "学情信息分析",
    toolName: "使用学情理解工具",
    description: "分析学情信息和班级画像。",
    icon: BookOpen,
  },
  knowledge_structure: {
    title: "重组教学内容",
    toolName: "使用知识点梳理工具",
    description: "整理课程知识点、能力目标、重点难点和关联关系。",
    icon: ListChecks,
  },
  curriculum_plan: {
    title: "整套课程规划",
    toolName: "使用课程规划工具",
    description: "生成整套课程课次安排、教学目标和课时规划。",
    icon: Clock3,
  },
  lesson_plan_generate: {
    title: "整套教案生成",
    toolName: "使用教案生成工具",
    description: "为每一课生成教学目标、重点难点、教学流程和课后安排。",
    icon: BookOpen,
  },
  coverage_check: {
    title: "校验知识覆盖",
    toolName: "使用覆盖检查工具",
    description: "检查课程、教案、题目和课件的知识点覆盖情况。",
    icon: Target,
  },
};

const CORE_OUTPUTS = [
  { label: "课程总纲", stepCode: "curriculum_plan", icon: FileText },
  { label: "整套教案", stepCode: "lesson_plan_generate", icon: BookOpen },
  { label: "覆盖报告", stepCode: "coverage_check", icon: Target },
] as const;

const FOLLOW_UP_OUTPUTS = [
  { label: "PPT 课件", icon: Presentation },
  { label: "课后作业", icon: ClipboardCheck },
  { label: "配套测练", icon: Layers3 },
] as const;

function fallbackGenerationSteps(): GenerationProcessStep[] {
  return PHASE2_STEP_ORDER.map((code) => ({
    code,
    display_name: PHASE2_STEP_UI[code].toolName,
    description: PHASE2_STEP_UI[code].description,
    status: "pending",
    progress_percent: 0,
    summary: null,
    started_at: null,
    finished_at: null,
    error_message: null,
  }));
}

function getPhase2StepMeta(step: GenerationProcessStep) {
  return (
    PHASE2_STEP_UI[step.code] ?? {
      title: step.display_name || "处理备课任务",
      toolName: step.display_name || "备课生成工具",
      description: step.description || "系统正在处理这一步。",
      icon: FileText,
    }
  );
}

function clampProgress(value: number) {
  if (!Number.isFinite(value)) {
    return 0;
  }
  return Math.max(0, Math.min(100, Math.round(value)));
}

function isGenerationActive(status?: GenerationProcessStatus) {
  return status === "running" || status === "pending";
}

function timestampMs(value?: string | null) {
  if (!value) {
    return null;
  }
  const time = new Date(value).getTime();
  return Number.isFinite(time) ? time : null;
}

function latestSucceededStepFinishedAt(process?: GenerationProcess) {
  return Math.max(
    0,
    ...(process?.steps ?? [])
      .filter((step) => step.status === "succeeded")
      .map((step) => timestampMs(step.finished_at) ?? 0),
  );
}

function formatDurationMs(durationMs: number) {
  const totalSeconds = Math.max(0, Math.floor(durationMs / 1000));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  if (hours > 0) {
    return `${hours}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
  }
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

function formatGenerationRuntime(process: GenerationProcess | undefined, currentTime: number, fallbackStartedAt?: string) {
  const fallbackStart = timestampMs(fallbackStartedAt);
  const isActive = isGenerationActive(process?.status);
  const stepStartTimes = (process?.steps ?? [])
    .map((step) => timestampMs(step.started_at))
    .filter((value): value is number => value !== null);
  const firstStepStart = stepStartTimes.length ? Math.min(...stepStartTimes) : null;

  if (isActive) {
    const startedAt = firstStepStart ?? fallbackStart;
    if (startedAt) {
      return formatDurationMs(currentTime - startedAt);
    }
  }

  const elapsedMs = (process?.steps ?? []).reduce((total, step) => {
    const startedAt = timestampMs(step.started_at);
    if (!startedAt) {
      return total;
    }
    if (step.status === "running") {
      return total + (currentTime - startedAt);
    }
    const finishedAt = timestampMs(step.finished_at);
    return finishedAt ? total + (finishedAt - startedAt) : total;
  }, 0);

  if (elapsedMs > 0) {
    return formatDurationMs(elapsedMs);
  }

  return fallbackStart ? formatDurationMs(currentTime - fallbackStart) : "--:--";
}

const COUNT_FORMATTER = new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 0 });
const PERCENT_FORMATTER = new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 2 });
type LearnerProfileDisplayVersion = LearnerProfileVersion & { records?: LearnerProfileRecord[] };

function metricNumber(detail: JsonRecord | null | undefined, key: string) {
  const value = detail?.[key];
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string" && value.trim()) {
    const numericValue = Number(value);
    return Number.isFinite(numericValue) ? numericValue : null;
  }
  return null;
}

function metricText(detail: JsonRecord | null | undefined, key: string) {
  return stringValue(detail?.[key]);
}

function formatCount(value: number) {
  return COUNT_FORMATTER.format(Math.round(value));
}

function formatPercent(value: number) {
  return `${PERCENT_FORMATTER.format(value)}%`;
}

function learnerClassProfileFrom(version?: LearnerProfileDisplayVersion | null) {
  if (version?.class_profile) {
    return version.class_profile;
  }
  const rawResult = valueAsRecord(version?.raw_result_json);
  const rawClassProfile = valueAsRecord(rawResult?.class_profile);
  return rawClassProfile ? (rawClassProfile as unknown as LearnerClassProfile) : null;
}

function subjectOverviewsFrom(profile: LearnerClassProfile | null) {
  return Array.isArray(profile?.subject_overview) ? profile.subject_overview : [];
}

function tieredGroupsFrom(profile: LearnerClassProfile | null) {
  return Array.isArray(profile?.tiered_groups) ? profile.tiered_groups : [];
}

function formatScore(value: number | null | undefined) {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return "-";
  }
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}

function formatSubjectLabel(subjectCode: string) {
  return SUBJECT_LABELS[subjectCode] ?? subjectCode;
}

const SUBJECT_ORDER = ["chinese", "math", "english"];
const TIER_LABELS: Record<string, string> = {
  high: "高分层",
  mid: "中分层",
  low: "待提升层",
};

function profileRecordsFrom(version?: LearnerProfileDisplayVersion | null) {
  return Array.isArray(version?.records) ? version.records : [];
}

function uniqueStudentKeys(records: LearnerProfileRecord[]) {
  return uniqueItems(
    records.map((record) => record.student_name || record.student_key).filter(Boolean),
    200,
  );
}

function learnerProfileStudentCount(version: LearnerProfileDisplayVersion | null | undefined, classProfile: LearnerClassProfile | null, records: LearnerProfileRecord[]) {
  const rawResult = valueAsRecord(version?.raw_result_json);
  const rawCount = metricNumber(rawResult, "student_count");
  if (rawCount !== null) {
    return rawCount;
  }
  const subjectCount = Math.max(0, ...subjectOverviewsFrom(classProfile).map((item) => item.student_count || 0));
  if (subjectCount > 0) {
    return subjectCount;
  }
  return uniqueStudentKeys(records).length || null;
}

function scorePercent(value: number | null | undefined) {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return 0;
  }
  return Math.max(0, Math.min(100, value));
}

function scoreFromRecord(record: LearnerProfileRecord) {
  const value = record.score_value;
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function tagsFromRecord(record: JsonRecord | null | undefined) {
  return uniqueItems(extractTagItems(record), 8);
}

function normalizeTierStudentKey(key: string) {
  return key.replace(/_(chinese|math|english|science|physics|chemistry|biology|history|geography|politics)$/i, "");
}

function tierStudentCount(group: LearnerProfileTieredGroup) {
  return new Set((group.student_keys ?? []).map((key) => normalizeTierStudentKey(key))).size;
}

function overviewSubjectCount(items: LearnerProfileSubjectOverview[]) {
  return new Set(items.map((item) => item.subject_code).filter(Boolean)).size;
}

function sortedSubjectOverviews(items: LearnerProfileSubjectOverview[]) {
  return [...items].sort((a, b) => {
    const orderA = SUBJECT_ORDER.indexOf(a.subject_code);
    const orderB = SUBJECT_ORDER.indexOf(b.subject_code);
    return (orderA === -1 ? 99 : orderA) - (orderB === -1 ? 99 : orderB);
  });
}

function sortedProfileRecords(records: LearnerProfileRecord[]) {
  return [...records].sort((a, b) => {
    const orderA = SUBJECT_ORDER.indexOf(a.subject_code);
    const orderB = SUBJECT_ORDER.indexOf(b.subject_code);
    return (orderA === -1 ? 99 : orderA) - (orderB === -1 ? 99 : orderB) || a.sort_order - b.sort_order;
  });
}

function LearnerReportShell({
  children,
  kicker,
  summary,
  title,
}: {
  children: ReactNode;
  kicker: string;
  summary?: string | null;
  title: string;
}) {
  return (
    <section className="rounded-xl border border-line bg-[#fafaf8] p-4 shadow-[0_18px_48px_rgba(17,17,17,0.045)] sm:p-5">
      <div className="flex flex-wrap items-start justify-between gap-4 border-b border-line/70 pb-4">
        <div>
          <div className="text-xs font-semibold tracking-[0.12em] text-[#0f8f7a]">{kicker}</div>
          <h3 className="mt-2 text-xl font-semibold text-ink">{title}</h3>
          {summary ? <p className="mt-2 max-w-4xl text-sm leading-6 text-ink/58">{summary}</p> : null}
        </div>
      </div>
      <div className="mt-5">{children}</div>
    </section>
  );
}

function ReportMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-[118px] rounded-lg border border-line/80 bg-white px-3 py-2">
      <div className="text-xs text-ink/42">{label}</div>
      <div className="mt-1 text-base font-semibold text-ink">{value}</div>
    </div>
  );
}

function ScoreRangeBar({ avg, max, min }: { avg?: number | null; max?: number | null; min?: number | null }) {
  const minValue = scorePercent(min);
  const maxValue = scorePercent(max);
  const avgValue = scorePercent(avg);
  const start = Math.min(minValue, maxValue);
  const end = Math.max(minValue, maxValue);
  return (
    <div className="relative h-1.5 w-full rounded-full bg-[#e8ebe7]">
      <span
        className="absolute top-0 h-1.5 rounded-full bg-[#b7d8cb]"
        style={{ left: `${start}%`, right: `${100 - end}%` }}
      />
      <span
        className="absolute top-1/2 h-3 w-1 -translate-y-1/2 rounded-full bg-[#0f8f7a]"
        style={{ left: `${avgValue}%` }}
      />
    </div>
  );
}

function SectionHeading({ title, description }: { title: string; description?: string }) {
  return (
    <div className="mb-3 flex items-baseline justify-between gap-3">
      <h4 className="text-sm font-semibold text-ink">{title}</h4>
      {description ? <span className="text-xs text-ink/40">{description}</span> : null}
    </div>
  );
}

function ClassSubjectOverviewTable({ items }: { items: LearnerProfileSubjectOverview[] }) {
  const visibleItems = sortedSubjectOverviews(items).slice(0, 5);
  if (!visibleItems.length) {
    return <p className="rounded-lg bg-white px-4 py-5 text-sm text-ink/45">班级基础数据暂未返回。</p>;
  }
  return (
    <div className="overflow-hidden rounded-lg border border-line bg-white">
      <div className="grid grid-cols-[0.8fr_0.9fr_0.9fr_1.1fr_1.4fr] gap-4 border-b border-line/80 bg-[#f7f8f6] px-4 py-2 text-xs font-medium text-ink/45">
        <span>学科</span>
        <span>覆盖学生</span>
        <span>平均分</span>
        <span>最高 / 最低</span>
        <span>高 / 中 / 待提升</span>
      </div>
      {visibleItems.map((item) => (
        <div className="grid grid-cols-[0.8fr_0.9fr_0.9fr_1.1fr_1.4fr] items-center gap-4 border-b border-line/70 px-4 py-3 last:border-b-0" key={item.subject_code}>
          <div className="font-semibold text-ink">{formatSubjectLabel(item.subject_code)}</div>
          <div className="text-sm text-ink/58">{formatCount(item.student_count)} 名</div>
          <div>
            <div className="text-lg font-semibold text-ink">{formatScore(item.score_avg)}</div>
            <ScoreRangeBar avg={item.score_avg} max={item.score_max} min={item.score_min} />
          </div>
          <div className="text-sm text-ink/58">
            <span className="font-medium text-ink">{formatScore(item.score_max)}</span>
            <span className="mx-1 text-ink/28">/</span>
            <span>{formatScore(item.score_min)}</span>
          </div>
          <div className="text-sm text-ink/58">
            <span className="font-semibold text-[#0f8f7a]">{formatCount(item.high_count)}</span>
            <span className="mx-1 text-ink/26">/</span>
            <span>{formatCount(item.mid_count)}</span>
            <span className="mx-1 text-ink/26">/</span>
            <span className="text-[#a35b13]">{formatCount(item.low_count)}</span>
          </div>
        </div>
      ))}
    </div>
  );
}

function SimpleInsightList({ emptyText, items }: { emptyText: string; items: string[] }) {
  const visibleItems = uniqueItems(items, 4);
  if (!visibleItems.length) {
    return <p className="text-sm leading-6 text-ink/45">{emptyText}</p>;
  }
  return (
    <div className="space-y-2">
      {visibleItems.map((item) => (
        <div className="flex gap-2 text-sm leading-6 text-ink/68" key={item}>
          <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-[#0f8f7a]" />
          <span>{item}</span>
        </div>
      ))}
    </div>
  );
}

function ClassFeaturePanel({ profile }: { profile: LearnerClassProfile }) {
  const strengths = [...(profile.common_strengths ?? []), ...(profile.common_behaviors ?? [])];
  return (
    <div className="rounded-lg border border-line bg-white p-4">
      <SectionHeading description="优势、薄弱点与习惯" title="共性特征" />
      <div className="grid gap-4 md:grid-cols-3">
        <div>
          <div className="mb-2 text-xs font-semibold text-ink/42">共性优势</div>
          <SimpleInsightList emptyText="暂未返回共性优势。" items={strengths} />
        </div>
        <div>
          <div className="mb-2 text-xs font-semibold text-ink/42">主要薄弱点</div>
          <SimpleInsightList emptyText="暂未发现明显薄弱点。" items={profile.common_weaknesses ?? []} />
        </div>
        <div>
          <div className="mb-2 text-xs font-semibold text-ink/42">学习习惯</div>
          <SimpleInsightList emptyText="学习习惯摘要暂未返回。" items={profile.common_habits ?? []} />
        </div>
      </div>
    </div>
  );
}

function ClassTeachingPanel({ groups, recommendations }: { groups: LearnerProfileTieredGroup[]; recommendations: string[] }) {
  const sortedGroups = [...groups].sort((a, b) => {
    const order = ["high", "mid", "low"];
    return order.indexOf(a.tier) - order.indexOf(b.tier);
  });
  const fallbackItems = uniqueItems(recommendations, 3);
  return (
    <div className="rounded-lg border border-line bg-white p-4">
      <SectionHeading description="按后端分层建议生成" title="教学建议" />
      {sortedGroups.length ? (
        <div className="space-y-2">
          {sortedGroups.slice(0, 3).map((group) => (
            <div className="grid gap-3 rounded-md bg-[#f7f8f6] px-3 py-3 md:grid-cols-[108px_88px_1fr]" key={group.tier}>
              <div className="font-semibold text-ink">{TIER_LABELS[group.tier] ?? group.tier}</div>
              <div className="text-sm text-ink/50">{formatCount(tierStudentCount(group))} 名</div>
              <div className="text-sm leading-6 text-ink/64">{uniqueItems(group.teaching_suggestions ?? [], 1)[0] ?? "暂无建议。"}</div>
            </div>
          ))}
        </div>
      ) : (
        <SimpleInsightList emptyText="教学建议暂未返回。" items={fallbackItems} />
      )}
    </div>
  );
}

function ClassLearnerProfileView({
  classProfile,
  profileVersion,
}: {
  classProfile: LearnerClassProfile;
  profileVersion?: LearnerProfileDisplayVersion | null;
}) {
  const subjectOverviews = subjectOverviewsFrom(classProfile);
  const records = profileRecordsFrom(profileVersion);
  const studentCount = learnerProfileStudentCount(profileVersion, classProfile, records);
  const warningCount = classProfile.warnings?.length ?? 0;
  return (
    <LearnerReportShell
      kicker="CLASS PROFILE"
      summary={classProfile.class_summary || profileVersion?.summary_text}
      title="班级学情画像"
    >
      <div className="mb-5 flex flex-wrap gap-2">
        <ReportMetric label="学生规模" value={studentCount !== null ? `${formatCount(studentCount)} 名` : "-"} />
        <ReportMetric label="覆盖学科" value={`${formatCount(overviewSubjectCount(subjectOverviews))} 个`} />
        <ReportMetric label="数据提示" value={warningCount ? `${formatCount(warningCount)} 条` : "无异常"} />
      </div>
      <div className="space-y-4">
        <div className="rounded-lg border border-line bg-white p-4">
          <SectionHeading description="平均分、最高/最低与分层人数" title="班级基础" />
          <ClassSubjectOverviewTable items={subjectOverviews} />
        </div>
        <div className="grid gap-4 xl:grid-cols-[1.05fr_0.95fr]">
          <ClassFeaturePanel profile={classProfile} />
          <ClassTeachingPanel groups={tieredGroupsFrom(classProfile)} recommendations={classProfile.teaching_recommendations ?? []} />
        </div>
      </div>
    </LearnerReportShell>
  );
}

function recordSummary(record: LearnerProfileRecord) {
  return record.summary_text?.replace(/\s+/g, " ").trim() || "暂无简述。";
}

function StudentSubjectTable({ records }: { records: LearnerProfileRecord[] }) {
  const visibleRecords = sortedProfileRecords(records).slice(0, 5);
  if (!visibleRecords.length) {
    return <p className="rounded-lg bg-white px-4 py-5 text-sm text-ink/45">学生画像记录加载中。</p>;
  }
  return (
    <div className="overflow-hidden rounded-lg border border-line bg-white">
      <div className="grid grid-cols-[0.7fr_0.8fr_1.2fr_1.2fr_1.7fr] gap-4 border-b border-line/80 bg-[#f7f8f6] px-4 py-2 text-xs font-medium text-ink/45">
        <span>学科</span>
        <span>分数</span>
        <span>能力标签</span>
        <span>薄弱点</span>
        <span>简述</span>
      </div>
      {visibleRecords.map((record) => {
        const score = scoreFromRecord(record);
        return (
          <div className="grid grid-cols-[0.7fr_0.8fr_1.2fr_1.2fr_1.7fr] items-center gap-4 border-b border-line/70 px-4 py-3 last:border-b-0" key={record.id}>
            <div className="font-semibold text-ink">{formatSubjectLabel(record.subject_code)}</div>
            <div>
              <div className="text-lg font-semibold text-ink">{formatScore(score)}</div>
              <div className="mt-1 h-1.5 rounded-full bg-[#e8ebe7]">
                <span className="block h-1.5 rounded-full bg-[#0f8f7a]" style={{ width: `${scorePercent(score)}%` }} />
              </div>
            </div>
            <div className="text-sm leading-6 text-ink/58">{uniqueItems(tagsFromRecord(record.ability_tags_json), 2).join("、") || "暂无"}</div>
            <div className="text-sm leading-6 text-ink/58">{uniqueItems(tagsFromRecord(record.weakness_tags_json), 2).join("、") || "暂无"}</div>
            <div className="line-clamp-2 text-sm leading-6 text-ink/58">{recordSummary(record)}</div>
          </div>
        );
      })}
    </div>
  );
}

function StudentFeaturePanel({ records }: { records: LearnerProfileRecord[] }) {
  const strengths = uniqueItems(
    records.flatMap((record) => [...tagsFromRecord(record.advantage_tags_json), ...tagsFromRecord(record.ability_tags_json)]),
    6,
  );
  const weaknesses = uniqueItems(records.flatMap((record) => tagsFromRecord(record.weakness_tags_json)), 6);
  const habits = uniqueItems(
    records.flatMap((record) => [...tagsFromRecord(record.habit_tags_json), ...tagsFromRecord(record.behavior_traits_json)]),
    4,
  );
  return (
    <div className="rounded-lg border border-line bg-white p-4">
      <SectionHeading description="能力、薄弱点与习惯" title="学习特征" />
      <div className="grid gap-4 md:grid-cols-3">
        <div>
          <div className="mb-2 text-xs font-semibold text-ink/42">优势能力</div>
          <SimpleInsightList emptyText="暂未返回优势能力。" items={strengths} />
        </div>
        <div>
          <div className="mb-2 text-xs font-semibold text-ink/42">薄弱点</div>
          <SimpleInsightList emptyText="暂未返回薄弱点。" items={weaknesses} />
        </div>
        <div>
          <div className="mb-2 text-xs font-semibold text-ink/42">学习习惯</div>
          <SimpleInsightList emptyText="暂未返回学习习惯。" items={habits} />
        </div>
      </div>
    </div>
  );
}

function timePlanRowsFrom(records: LearnerProfileRecord[]): Array<{ subject: string; text: string; meta?: string }> {
  return records.flatMap((record) => {
    const detail = valueAsRecord(record.time_plan_json);
    const items = Array.isArray(detail?.items) ? detail.items : [];
    return items.flatMap((item) => {
      const itemRecord = valueAsRecord(item);
      if (!itemRecord) {
        const text = stringValue(item);
        return text ? [{ subject: formatSubjectLabel(record.subject_code), text }] : [];
      }
      const subject = stringValue(itemRecord.subject_name) || formatSubjectLabel(record.subject_code);
      const text = stringValue(itemRecord.raw_text) || stringValue(itemRecord.description) || stringValue(itemRecord.summary);
      const lessonsPerWeek = metricNumber(itemRecord, "lessons_per_week");
      const hoursPerSession = metricNumber(itemRecord, "class_hours_per_session");
      const meta = [
        lessonsPerWeek !== null ? `每周 ${formatCount(lessonsPerWeek)} 次` : "",
        hoursPerSession !== null ? `每次 ${formatScore(hoursPerSession)} 课时` : "",
      ].filter(Boolean).join(" · ");
      return [{ subject, text: text || meta || "暂无安排摘要。", meta }];
    });
  });
}

function StudentPlanPanel({ records }: { records: LearnerProfileRecord[] }) {
  const rows = timePlanRowsFrom(records).slice(0, 4);
  return (
    <div className="rounded-lg border border-line bg-white p-4">
      <SectionHeading description="来自 time_plan_json" title="学习安排" />
      {rows.length ? (
        <div className="space-y-2">
          {rows.map((row, index) => (
            <div className="grid gap-2 rounded-md bg-[#f7f8f6] px-3 py-3 md:grid-cols-[84px_120px_1fr]" key={`${row.subject}-${index}`}>
              <div className="font-semibold text-ink">{row.subject}</div>
              <div className="text-sm text-ink/45">{row.meta || "安排建议"}</div>
              <div className="text-sm leading-6 text-ink/64">{row.text}</div>
            </div>
          ))}
        </div>
      ) : (
        <p className="text-sm leading-6 text-ink/45">学习安排暂未返回。</p>
      )}
    </div>
  );
}

function StudentLearnerProfileView({ profileVersion }: { profileVersion?: LearnerProfileDisplayVersion | null }) {
  const records = profileRecordsFrom(profileVersion);
  const studentName = uniqueItems(records.map((record) => record.student_name || "").filter(Boolean), 1)[0] ?? "学生";
  const scores = records.map(scoreFromRecord).filter((value): value is number => value !== null);
  const highestScore = scores.length ? Math.max(...scores) : null;
  const improvementTag = uniqueItems(records.flatMap((record) => tagsFromRecord(record.weakness_tags_json)), 1)[0] ?? "待补充";
  const subjectCount = new Set(records.map((record) => record.subject_code).filter(Boolean)).size;
  const summary = profileVersion?.summary_text || records.map((record) => record.summary_text).find(Boolean) || "";

  return (
    <LearnerReportShell
      kicker="STUDENT PROFILE"
      summary={summary}
      title="学生学情画像"
    >
      <div className="mb-5 flex flex-wrap gap-2">
        <ReportMetric label="学生" value={studentName} />
        <ReportMetric label="覆盖学科" value={subjectCount ? `${formatCount(subjectCount)} 个` : "-"} />
        <ReportMetric label="最高分" value={highestScore !== null ? formatScore(highestScore) : "-"} />
        <ReportMetric label="提升重点" value={improvementTag} />
      </div>
      <div className="space-y-4">
        <div className="rounded-lg border border-line bg-white p-4">
          <SectionHeading description="分数、能力标签与薄弱点" title="基础表现" />
          <StudentSubjectTable records={records} />
        </div>
        <div className="grid gap-4 xl:grid-cols-[1.05fr_0.95fr]">
          <StudentFeaturePanel records={records} />
          <StudentPlanPanel records={records} />
        </div>
      </div>
    </LearnerReportShell>
  );
}

function LearnerProfileLoadingCard({ recordCount }: { recordCount: number | null }) {
  return (
    <div className="rounded-lg border border-line bg-[#fbfbfb] p-4">
      <h3 className="text-sm font-semibold text-ink">画像详情加载中</h3>
      <p className="mt-2 text-sm leading-6 text-ink/55">
        已完成学情分析{recordCount !== null ? `，生成 ${formatCount(recordCount)} 条画像记录` : ""}；详情稍后刷新。
      </p>
    </div>
  );
}

function LearnerProfileDetailPanel({
  profileVersion,
  step,
}: {
  profileVersion?: LearnerProfileDisplayVersion | null;
  step?: GenerationProcessStep;
}) {
  const classProfile = learnerClassProfileFrom(profileVersion);
  const records = profileRecordsFrom(profileVersion);
  const studentCount = learnerProfileStudentCount(profileVersion, classProfile, records);
  const recordCount = metricNumber(valueAsRecord(step?.result_detail), "profile_record_count");

  if (classProfile && (studentCount ?? 0) > 1) {
    return <ClassLearnerProfileView classProfile={classProfile} profileVersion={profileVersion} />;
  }

  if (records.length) {
    return <StudentLearnerProfileView profileVersion={profileVersion} />;
  }

  return <LearnerProfileLoadingCard recordCount={recordCount} />;
}

function formatPhase2StepSummary(step: GenerationProcessStep) {
  if (step.status_detail === "retrying") {
    return "任务已重排，正在等待新的执行实例继续处理。";
  }
  if (step.status_detail === "waiting_dispatch") {
    return "";
  }
  if (step.status === "failed") {
    return step.error_message || "生成失败，请稍后重试。";
  }
  if (step.status === "pending") {
    if (step.code === "lesson_plan_generate") {
      return "等待课程规划完成后自动开始。";
    }
    if (step.code === "coverage_check") {
      return "等待核心资源生成后自动开始。";
    }
    return "等待前置步骤完成后自动开始。";
  }
  if (step.status === "running") {
    if (step.summary) {
      return step.summary;
    }
    const runningSummaries: Record<string, string> = {
      mineru_parse: "正在解析教材结构、页码与内容。",
      learner_profile: "正在分析学情画像。",
      knowledge_structure: "正在提取章节、知识点与教学线索。",
      curriculum_plan: "正在规划课次安排、教学目标与课时节奏。",
      lesson_plan_generate: "正在生成整套教案与课堂流程。",
      coverage_check: "正在检查课程、教案与资源的知识覆盖。",
    };
    return runningSummaries[step.code] ?? getPhase2StepMeta(step).description;
  }
  if (step.status === "succeeded") {
    const detail = valueAsRecord(step.result_detail);
    if (step.code === "mineru_parse") {
      const pageCount = metricNumber(detail, "page_count");
      return pageCount !== null ? `已完成教材解析，共识别 ${formatCount(pageCount)} 页内容。` : "已完成教材解析。";
    }
    if (step.code === "learner_profile") {
      const recordCount = metricNumber(detail, "profile_record_count");
      return recordCount !== null ? `已完成学情分析，生成 ${formatCount(recordCount)} 条画像记录。` : "已完成学情分析。";
    }
    if (step.code === "knowledge_structure") {
      const chapterCount = metricNumber(detail, "chapter_count");
      const pointCount = metricNumber(detail, "point_count");
      return chapterCount !== null && pointCount !== null
        ? `已完成教学重点整理，识别 ${formatCount(chapterCount)} 个章节、${formatCount(pointCount)} 个知识点。`
        : step.summary || "已完成章节结构与教学重点整理。";
    }
    if (step.code === "curriculum_plan") {
      const planTitle = metricText(detail, "plan_title");
      const courseCount = metricNumber(detail, "course_count");
      if (planTitle && courseCount !== null) {
        return `课程总纲《${planTitle}》已生成，共 ${formatCount(courseCount)} 课次。`;
      }
      return courseCount !== null
        ? `已完成整套课程的课次安排与教学目标，共 ${formatCount(courseCount)} 课次。`
        : step.summary || "已完成整套课程的课次安排与教学目标。";
    }
    if (step.code === "lesson_plan_generate") {
      const lessonPlanCount = metricNumber(detail, "lesson_plan_count");
      return lessonPlanCount !== null ? `已完成整套教案生成，共 ${formatCount(lessonPlanCount)} 个课次。` : step.summary || "已完成整套教案生成。";
    }
    if (step.code === "coverage_check") {
      const coverageRate = metricNumber(detail, "coverage_rate");
      const coveredCount = metricNumber(detail, "covered_count");
      const totalCount = metricNumber(detail, "total_count");
      if (coverageRate !== null && coveredCount !== null && totalCount !== null) {
        return `已完成核心资源覆盖检查，知识点覆盖 ${formatPercent(coverageRate)}，已覆盖 ${formatCount(coveredCount)} / ${formatCount(totalCount)}。`;
      }
      return coverageRate !== null ? `已完成核心资源覆盖检查，知识点覆盖 ${formatPercent(coverageRate)}。` : step.summary || "已完成核心资源覆盖检查。";
    }
  }
  return step.summary || getPhase2StepMeta(step).description;
}

const BLOCKED_REASON_LABELS: Record<string, string> = {
  NO_CURRENT_TEXTBOOK: "缺少当前教材版本，暂时无法继续。",
  NO_CURRENT_LEARNER_PROFILE: "缺少当前学情版本，学情抽取完成后会继续。",
  LEARNER_PROFILE_NOT_READY: "学情版本尚未就绪，完成后会继续生成。",
  WAITING_USER_CONFIRM: "等待确认教材理解结果后继续。",
};

function formatProcessStatusDetail(process: GenerationProcess | undefined, currentTime: number, fallbackStartedAt?: string) {
  if (!process?.status_detail) {
    return null;
  }
  if (process.status_detail === "waiting_dispatch") {
    return null;
  }
  if (process.status_detail === "waiting_user_confirm") {
    return "等待确认教材理解结果。";
  }
  if (process.status_detail === "retrying") {
    return "任务正在重试，新的执行实例启动后会继续推进。";
  }
  if (process.status_detail === "blocked") {
    return process.blocked_reason ? BLOCKED_REASON_LABELS[process.blocked_reason] ?? `流程暂时阻塞：${process.blocked_reason}` : "流程暂时阻塞。";
  }
  return null;
}

function TimelineMarker({ status }: { status: GenerationProcessStatus }) {
  if (status === "succeeded") {
    return (
      <span className="flex h-6 w-6 items-center justify-center rounded-full bg-ink text-white shadow-[0_0_0_4px_rgba(255,255,255,1)]">
        <Check size={13} strokeWidth={2.7} />
      </span>
    );
  }
  if (status === "running") {
    return (
      <span className="flex h-6 w-6 items-center justify-center rounded-full bg-white text-ink shadow-[0_0_0_4px_rgba(255,255,255,1)] ring-1 ring-line">
        <Loader2 className="animate-spin" size={15} />
      </span>
    );
  }
  if (status === "failed") {
    return (
      <span className="flex h-6 w-6 items-center justify-center rounded-full bg-[#b42318] text-white shadow-[0_0_0_4px_rgba(255,255,255,1)]">
        <AlertCircle size={14} strokeWidth={2.5} />
      </span>
    );
  }
  return <span className="block h-6 w-6 rounded-full border border-line bg-white shadow-[0_0_0_4px_rgba(255,255,255,1)]" />;
}

function GenerationStepCard({
  shouldStretchConnector,
  defaultExpanded,
  detailContent,
  isLast,
  materialAction,
  step,
}: {
  shouldStretchConnector?: boolean;
  defaultExpanded?: boolean;
  detailContent?: ReactNode;
  isLast: boolean;
  materialAction?: StepMaterialAction;
  step: GenerationProcessStep;
}) {
  const meta = getPhase2StepMeta(step);
  const MetaIcon = meta.icon;
  const progress = clampProgress(step.progress_percent);
  const isRunning = step.status === "running";
  const isFailed = step.status === "failed";
  const isSucceeded = step.status === "succeeded";
  const isPending = step.status === "pending";
  const isExpandable = isSucceeded;
  const [manualExpanded, setManualExpanded] = useState(defaultExpanded ?? false);
  const [materialOpen, setMaterialOpen] = useState(false);
  const materialPopoverRef = useRef<HTMLDivElement | null>(null);
  const isExpanded = isRunning || isFailed || (isSucceeded && manualExpanded);
  const stepSummary = formatPhase2StepSummary(step);

  useEffect(() => {
    if (!isSucceeded) {
      setManualExpanded(false);
    }
  }, [isSucceeded]);

  useEffect(() => {
    if (isSucceeded && defaultExpanded) {
      setManualExpanded(true);
    }
  }, [defaultExpanded, isSucceeded]);

  useEffect(() => {
    if (!materialAction) {
      setMaterialOpen(false);
    }
  }, [materialAction]);

  useEffect(() => {
    if (!materialOpen) {
      return;
    }

    const closeOnOutsidePointer = (event: PointerEvent) => {
      if (materialPopoverRef.current?.contains(event.target as Node)) {
        return;
      }
      setMaterialOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setMaterialOpen(false);
      }
    };

    window.addEventListener("pointerdown", closeOnOutsidePointer);
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      window.removeEventListener("pointerdown", closeOnOutsidePointer);
      window.removeEventListener("keydown", closeOnEscape);
    };
  }, [materialOpen]);

  return (
    <article className="relative md:pl-10">
      {!isLast ? (
        <div
          className={cn(
            "absolute left-3 top-8 hidden w-px bg-line md:block",
            shouldStretchConnector ? "bottom-[-3rem]" : "bottom-[-1rem]",
          )}
        />
      ) : null}
      <div className="absolute left-0 top-5 hidden md:block">
        <TimelineMarker status={step.status} />
      </div>
      <section
        className={cn(
          "rounded-lg border bg-white px-5 py-4 shadow-[0_10px_30px_rgba(17,17,17,0.04)] transition-colors",
          isPending ? "border-line/70 bg-white/70" : "border-line",
          isFailed ? "border-[#f3b8b3] bg-[#fffafa]" : null,
          isRunning ? "px-6 py-5" : null,
          isExpandable ? "cursor-pointer hover:border-ink/20" : null,
        )}
        onClick={isExpandable ? () => setManualExpanded((value) => !value) : undefined}
      >
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className={cn("text-lg font-semibold text-ink", isPending ? "text-ink/42" : null)}>{meta.title}</h2>
            {stepSummary ? (
              <p className={cn("mt-1 text-sm leading-6", isPending ? "text-ink/36" : isFailed ? "font-medium text-[#9f1f16]" : "text-ink/58")}>
                {stepSummary}
              </p>
            ) : null}
          </div>
          <div className="flex shrink-0 items-center gap-1.5">
            {materialAction?.href ? (
              <Link
                className="rounded-md px-2 py-1 text-sm font-semibold text-[#0F766E] underline-offset-4 transition hover:bg-[#ecfdf5] hover:text-[#0D9488] hover:underline"
                onClick={(event) => event.stopPropagation()}
                state={materialAction.state}
                to={materialAction.href}
              >
                {materialAction.label}
              </Link>
            ) : materialAction ? (
              <div className="relative" ref={materialPopoverRef}>
                <button
                  className="rounded-md px-2 py-1 text-sm font-semibold text-[#0F766E] underline-offset-4 transition hover:bg-[#ecfdf5] hover:text-[#0D9488] hover:underline"
                  onClick={(event) => {
                    event.stopPropagation();
                    setMaterialOpen((value) => !value);
                  }}
                  type="button"
                >
                  {materialAction.label}
                </button>
                {materialOpen ? (
                  <div
                    className="absolute right-0 top-full z-20 mt-2 w-[420px] max-w-[calc(100vw-2rem)] rounded-xl border border-line bg-white p-4 text-left shadow-[0_18px_45px_rgba(17,17,17,0.12)]"
                    onClick={(event) => event.stopPropagation()}
                  >
                    <div className="flex items-start gap-3">
                      <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-[#f4f4f4] text-ink/72">
                        <FileText size={19} />
                      </span>
                      <div className="min-w-0 flex-1">
                        <div className="break-words text-base font-semibold leading-6 text-ink">{materialAction.fileName}</div>
                        {materialAction.metaItems?.length ? (
                          <div className="mt-2 text-sm leading-5 text-ink/50">{materialAction.metaItems.join(" · ")}</div>
                        ) : null}
                      </div>
                    </div>
                    <button
                      className="mt-4 inline-flex h-11 w-full items-center justify-center gap-2 rounded-lg bg-ink text-sm font-semibold text-white transition hover:bg-ink/88 disabled:cursor-not-allowed disabled:bg-ink/20"
                      disabled={materialAction.disabled || materialAction.opening || !materialAction.onOpen}
                      onClick={materialAction.onOpen}
                      type="button"
                    >
                      {materialAction.opening ? <Loader2 className="animate-spin" size={15} /> : <ExternalLink size={15} />}
                      {materialAction.disabled ? "文件暂不可用" : materialAction.opening ? "正在打开" : materialAction.openLabel}
                    </button>
                  </div>
                ) : null}
              </div>
            ) : null}
            {isExpandable ? (
              <button
                aria-expanded={manualExpanded}
                aria-label={manualExpanded ? "收起步骤详情" : "展开步骤详情"}
                className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-ink/38 transition hover:bg-[#f4f4f4] hover:text-ink"
                onClick={(event) => {
                  event.stopPropagation();
                  setManualExpanded((value) => !value);
                }}
                type="button"
              >
                <ChevronDown className={cn("transition-transform", manualExpanded ? "rotate-180" : null)} size={18} />
              </button>
            ) : null}
          </div>
        </div>

        {isExpanded && !isFailed ? (
          <div className="mt-4 space-y-4">
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm leading-6 text-ink/50">
              <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-line bg-[#f7f7f7] text-ink/70">
                <MetaIcon size={16} strokeWidth={2.1} />
              </span>
              <span className="font-semibold text-ink">{meta.toolName}</span>
              <span className="text-ink/28">·</span>
              <span>{step.description || meta.description}</span>
            </div>
            {isRunning ? (
              <div className="flex items-center gap-4">
                <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-line">
                  <div className="h-full rounded-full bg-ink transition-[width]" style={{ width: `${progress}%` }} />
                </div>
                <span className="w-10 text-right text-sm font-semibold text-ink/70">{progress}%</span>
              </div>
            ) : null}
            {detailContent ? (
              <div onClick={(event) => event.stopPropagation()}>
                {detailContent}
              </div>
            ) : null}
          </div>
        ) : null}
      </section>
    </article>
  );
}

function GenerationProcessTimeline({
  currentTime,
  fallbackStartedAt,
  materialActions,
  process,
  isLoading,
  stepDetails,
}: {
  currentTime: number;
  fallbackStartedAt?: string;
  materialActions?: Partial<Record<string, StepMaterialAction>>;
  process?: GenerationProcess;
  isLoading: boolean;
  stepDetails?: Partial<Record<string, ReactNode>>;
}) {
  const steps = orderPhase2Steps(process?.steps?.length ? process.steps : fallbackGenerationSteps());
  const statusDetailMessage = formatProcessStatusDetail(process, currentTime, fallbackStartedAt);
  const shouldStretchCompletedTimeline =
    process?.status === "succeeded" && steps.length > 1 && steps.every((step) => step.status === "succeeded") && !statusDetailMessage;

  return (
    <div
      className={cn(
        "relative space-y-5",
        shouldStretchCompletedTimeline ? "md:flex md:h-full md:flex-col md:justify-between md:space-y-0" : "md:space-y-4",
      )}
    >
      {isLoading && !process ? (
        <div className="mb-2 flex items-center gap-2 text-sm text-ink/45">
          <Loader2 className="animate-spin" size={15} />
          正在同步生成过程
        </div>
      ) : null}
      {statusDetailMessage ? (
        <div className="rounded-lg border border-line bg-white px-4 py-3 text-sm font-medium leading-6 text-ink/58 shadow-[0_8px_24px_rgba(17,17,17,0.04)]">
          {statusDetailMessage}
        </div>
      ) : null}
      {steps.map((step, index) => (
          <GenerationStepCard
            defaultExpanded={step.code === "learner_profile" && step.status === "succeeded" && Boolean(stepDetails?.[step.code])}
            detailContent={stepDetails?.[step.code]}
            isLast={index === steps.length - 1}
            key={step.code}
            materialAction={materialActions?.[step.code]}
            shouldStretchConnector={shouldStretchCompletedTimeline}
            step={step}
          />
        ))}
    </div>
  );
}

function OutputRows({
  items,
  iconMode = "resource",
}: {
  items: ReadonlyArray<{ label: string; icon: LucideIcon }>;
  iconMode?: "resource" | "complete" | "muted";
}) {
  return (
    <div className="space-y-3">
      {items.map((item) => {
        const Icon = iconMode === "complete" ? Check : item.icon;
        return (
          <div className="flex items-center gap-3 text-base font-medium text-ink" key={item.label}>
            <span
              className={cn(
                "flex h-8 w-8 shrink-0 items-center justify-center rounded-md border",
                iconMode === "complete" ? "border-ink bg-ink text-white" : "border-line bg-white text-ink",
                iconMode === "muted" ? "text-ink/32" : null,
              )}
            >
              <Icon size={18} strokeWidth={iconMode === "complete" ? 2.7 : 2.1} />
            </span>
            <span className={cn(iconMode === "muted" ? "text-ink/38" : null)}>{item.label}</span>
          </div>
        );
      })}
    </div>
  );
}

function ProcessStat({
  label,
  value,
  icon: Icon,
  iconClassName,
}: {
  label: string;
  value: string;
  icon: LucideIcon;
  iconClassName?: string;
}) {
  return (
    <div className="flex items-center gap-3">
      <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-[#f4f4f4] text-ink/72">
        <Icon className={iconClassName} size={18} />
      </span>
      <div>
        <div className="text-xs font-medium text-ink/42">{label}</div>
        <div className="mt-0.5 text-lg font-semibold text-ink">{value}</div>
      </div>
    </div>
  );
}

function GenerationOutputPanel({
  process,
  currentTime,
  fallbackStartedAt,
}: {
  process?: GenerationProcess;
  currentTime: number;
  fallbackStartedAt?: string;
}) {
  const steps = process?.steps?.length ? process.steps : fallbackGenerationSteps();
  const statusByCode = new Map(steps.map((step) => [step.code, step.status]));
  const completedCount = steps.filter((step) => step.status === "succeeded").length;
  const runningCount = steps.filter((step) => step.status === "running").length;
  const totalCount = steps.length || PHASE2_STEP_ORDER.length;
  const batchId = process?.batch_id;
  const isSucceeded = process?.status === "succeeded";
  const isFailed = process?.status === "failed";
  const completedOutputs = CORE_OUTPUTS.filter((item) => statusByCode.get(item.stepCode) === "succeeded");
  const unfinishedOutputs = CORE_OUTPUTS.filter((item) => statusByCode.get(item.stepCode) !== "succeeded");
  const processingStat = isSucceeded
    ? { icon: Check, label: "流程状态", value: "已完成" }
    : isFailed
      ? { icon: AlertCircle, label: "流程状态", value: "需处理" }
      : {
          icon: Loader2,
          iconClassName: runningCount > 0 ? "animate-spin" : undefined,
          label: "正在处理",
          value: `${runningCount} 项`,
        };

  return (
    <aside className="sticky top-8 space-y-4">
      <section className="rounded-lg border border-line bg-white p-6 shadow-[0_16px_42px_rgba(17,17,17,0.06)]">
        <h2 className="text-xl font-semibold text-ink">本次备课</h2>
        <div className="mt-5 grid gap-4">
          <ProcessStat icon={Clock3} label="已运行" value={formatGenerationRuntime(process, currentTime, fallbackStartedAt)} />
          <ProcessStat icon={Check} label="已完成" value={`${completedCount} / ${totalCount} 步`} />
          <ProcessStat {...processingStat} />
        </div>

        <div className="my-6 h-px bg-line" />

        {isFailed ? (
          <div className="space-y-6">
            {completedOutputs.length ? (
              <section>
                <h3 className="mb-4 text-lg font-semibold text-ink">本次已完成</h3>
                <OutputRows iconMode="complete" items={completedOutputs} />
              </section>
            ) : null}
            <section>
              <h3 className="mb-4 text-lg font-semibold text-ink">暂未完成</h3>
              <OutputRows iconMode="muted" items={unfinishedOutputs} />
            </section>
          </div>
        ) : (
          <section>
            <h3 className="mb-4 text-lg font-semibold text-ink">{isSucceeded ? "本次已生成" : "本次将生成"}</h3>
            <OutputRows iconMode={isSucceeded ? "complete" : "resource"} items={CORE_OUTPUTS} />
          </section>
        )}

        <div className="my-6 h-px bg-line" />

        <section>
          <h3 className="mb-4 text-lg font-semibold text-ink">后续还可生成</h3>
          <OutputRows iconMode={isSucceeded ? "resource" : "muted"} items={FOLLOW_UP_OUTPUTS} />
        </section>

        {isSucceeded && batchId ? (
          <Link
            className="btn mt-6 h-12 w-full rounded-lg border-[#0E8779] bg-[linear-gradient(135deg,#0E8779,#006A60)] text-white shadow-[0_14px_30px_rgba(6,95,84,0.18)] hover:border-[#006A60] hover:shadow-[0_16px_34px_rgba(6,95,84,0.22)] focus:ring-[#0E8779]/30"
            to={`/projects/${process.project_id}/batches/${batchId}`}
          >
            <ArrowRight size={17} />
            查看备课资源
          </Link>
        ) : null}
      </section>
    </aside>
  );
}

function projectTitle(project?: Project, textbook?: TextbookVersion) {
  return stripKnownFileExtension(textbook?.textbook_name || project?.name || "备课资源");
}

const SUBJECT_LABELS: Record<string, string> = {
  math: "数学",
  chinese: "语文",
  english: "英语",
};

const GRADE_LABELS: Record<string, string> = {
  grade_1: "一年级",
  grade_2: "二年级",
  grade_3: "三年级",
  grade_4: "四年级",
  grade_5: "五年级",
  grade_6: "六年级",
  grade_7: "七年级",
  grade_8: "八年级",
  grade_9: "九年级",
};

function extractPublisherLabel(value: string) {
  return value.match(/([^-\s·]+出版社)/)?.[1] ?? null;
}

function extractVolumeLabel(value: string) {
  return value.match(/(上册|下册|全册)/)?.[1] ?? "";
}

function buildProcessContext(project?: Project, textbook?: TextbookVersion) {
  const sourceName = stripKnownFileExtension(textbook?.textbook_name || project?.name || "");
  const subject = SUBJECT_LABELS[textbook?.subject_code || project?.subject_code || ""] ?? "";
  const grade = GRADE_LABELS[textbook?.grade_code || project?.grade_code || ""] ?? "";
  const volume = extractVolumeLabel(sourceName);
  const publisher = extractPublisherLabel(sourceName);
  const title = subject && grade ? `${subject}${grade}${volume}` : sourceName || "备课资源";

  return {
    title,
    subtitle: `${publisher || "基于教材与学情"} · 正在生成备课资源`,
  };
}

export function ProjectWorkspacePage() {
  const queryClient = useQueryClient();
  const location = useLocation();
  const projectId = toNumberId(useParams().projectId);
  const [selectedTextbookId, setSelectedTextbookId] = useState<number | null>(null);
  const [selectedProfileFileId, setSelectedProfileFileId] = useState<number | null>(null);
  const [selectedProfileVersionId, setSelectedProfileVersionId] = useState<number | null>(null);
  const [selectedParseVersionId, setSelectedParseVersionId] = useState<number | null>(null);
  const [selectedKnowledgeVersionId, setSelectedKnowledgeVersionId] = useState<number | null>(null);
  const [currentTime, setCurrentTime] = useState(() => Date.now());
  const startRunTriggeredKeyRef = useRef<string | null>(null);
  const learnerProfileSuccessSyncKeyRef = useRef<string | null>(null);
  const [fastRefetchUntil, setFastRefetchUntil] = useState(0);
  const locationState = location.state as ProjectWorkspaceLocationState;
  const generationCourseCount = normalizeGenerationSetting(locationState?.generationSettings?.courseCount, DEFAULT_COURSE_COUNT);
  const generationSessionDurationMinutes = normalizeGenerationSetting(
    locationState?.generationSettings?.sessionDurationMinutes,
    DEFAULT_SESSION_DURATION_MINUTES,
  );
  const isFastRefetching = currentTime < fastRefetchUntil;

  useEffect(() => {
    startRunTriggeredKeyRef.current = null;
    learnerProfileSuccessSyncKeyRef.current = null;
    setFastRefetchUntil(0);
  }, [projectId]);

  useEffect(() => {
    setCurrentTime(Date.now());
    const timer = window.setInterval(() => setCurrentTime(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  const tasksQuery = useQuery({
    queryKey: ["tasks", projectId],
    queryFn: () => api.listTasks({ project_id: projectId, page: 1, page_size: 30 }),
    enabled: projectId > 0,
    refetchInterval: (query) => {
      const hasProcessingProfileTask = query.state.data?.items.some(
        (task) => isLearnerProfileTask(task) && isTaskActiveStatus(task.task_status),
      );
      return isFastRefetching || hasProcessingProfileTask ? 1_000 : 5_000;
    },
  });
  const isLearnerProfileTaskProcessing = tasksQuery.data?.items.some(
    (task) => isLearnerProfileTask(task) && isTaskActiveStatus(task.task_status),
  ) ?? false;

  const projectQuery = useQuery({
    queryKey: ["project", projectId],
    queryFn: () => api.getProject(projectId),
    enabled: projectId > 0,
    refetchInterval: isFastRefetching || isLearnerProfileTaskProcessing ? 1_000 : false,
  });

  const textbooksQuery = useQuery({
    queryKey: ["textbooks", projectId],
    queryFn: () => api.listTextbooks(projectId),
    enabled: projectId > 0,
  });

  const learnerProfilesQuery = useQuery({
    queryKey: ["learner-profiles", projectId],
    queryFn: () => api.listLearnerProfiles(projectId),
    enabled: projectId > 0,
  });

  const parseVersionsQuery = useQuery({
    queryKey: ["parse-versions", selectedTextbookId],
    queryFn: () => api.listParseVersions(selectedTextbookId!),
    enabled: Boolean(selectedTextbookId),
    refetchInterval: isFastRefetching ? 1_000 : 8_000,
  });

  const profileVersionsQuery = useQuery({
    queryKey: ["learner-profile-versions", projectId, selectedProfileFileId],
    queryFn: () => api.listLearnerProfileVersions(projectId, selectedProfileFileId!),
    enabled: Boolean(projectId && selectedProfileFileId),
    refetchInterval: isFastRefetching ? 1_000 : 8_000,
  });

  const knowledgeVersionsQuery = useQuery({
    queryKey: ["knowledge-versions", selectedParseVersionId],
    queryFn: () => api.listKnowledgeVersions(selectedParseVersionId!),
    enabled: Boolean(selectedParseVersionId),
    refetchInterval: isFastRefetching ? 1_000 : 8_000,
  });

  const generationBatchesQuery = useQuery({
    queryKey: ["generation-batches", projectId],
    queryFn: () => api.listGenerationBatches(projectId),
    enabled: projectId > 0,
    refetchInterval: isFastRefetching ? 1_000 : 8_000,
  });

  const generationProcessQuery = useQuery({
    queryKey: ["generation-process", projectId],
    queryFn: () => api.getGenerationProcess(projectId),
    enabled: projectId > 0,
    refetchInterval: (query) => {
      const process = query.state.data;
      return process?.status === "succeeded" || process?.status === "failed" ? false : isFastRefetching ? 1_000 : 5_000;
    },
  });

  const activeGenerationRunQuery = useQuery({
    queryKey: ["generation-run-active", projectId],
    queryFn: () => api.getActiveGenerationRun(projectId),
    enabled: projectId > 0,
    refetchInterval: (query) => {
      const run = query.state.data;
      return run && ["pending", "running", "waiting_user_confirm"].includes(run.run_status) ? (isFastRefetching ? 1_000 : 5_000) : false;
    },
  });

  const textbooks = textbooksQuery.data?.items ?? [];
  const learnerProfiles = learnerProfilesQuery.data?.items ?? [];
  const parseVersions = parseVersionsQuery.data?.items ?? [];
  const profileVersions = profileVersionsQuery.data?.items ?? [];
  const knowledgeVersions = knowledgeVersionsQuery.data?.items ?? [];
  const generationBatches = generationBatchesQuery.data?.items ?? [];
  const tasks = tasksQuery.data?.items ?? [];
  const generationProcess = generationProcessQuery.data;
  const activeGenerationRun = activeGenerationRunQuery.data ?? null;

  useEffect(() => {
    const preferred = textbooks.find((item) => item.is_current) ?? latestById(textbooks);
    if (!preferred) {
      setSelectedTextbookId(null);
      return;
    }
    if (!selectedTextbookId || !textbooks.some((item) => item.id === selectedTextbookId)) {
      setSelectedTextbookId(preferred.id);
    }
  }, [selectedTextbookId, textbooks]);

  useEffect(() => {
    const preferred = latestById(learnerProfiles);
    if (!preferred) {
      setSelectedProfileFileId(null);
      return;
    }
    if (!selectedProfileFileId || !learnerProfiles.some((item) => item.id === selectedProfileFileId)) {
      setSelectedProfileFileId(preferred.id);
    }
  }, [learnerProfiles, selectedProfileFileId]);

  useEffect(() => {
    const preferred = preferredParseVersion(parseVersions, tasks);
    if (!preferred) {
      setSelectedParseVersionId(null);
      setSelectedKnowledgeVersionId(null);
      return;
    }
    if (selectedParseVersionId !== preferred.id) {
      setSelectedParseVersionId(preferred.id);
      setSelectedKnowledgeVersionId(null);
    }
  }, [parseVersions, selectedParseVersionId, tasks]);

  useEffect(() => {
    const preferred = latestById(profileVersions);
    if (!preferred) {
      setSelectedProfileVersionId(null);
      return;
    }
    if (!selectedProfileVersionId || !profileVersions.some((item) => item.id === selectedProfileVersionId)) {
      setSelectedProfileVersionId(preferred.id);
    }
  }, [profileVersions, selectedProfileVersionId]);

  useEffect(() => {
    const readyVersion = knowledgeVersions.find((item) => item.version_status === READY_STATUS);
    const preferred = readyVersion ?? latestById(knowledgeVersions);
    if (!preferred) {
      setSelectedKnowledgeVersionId(null);
      return;
    }
    const selected = knowledgeVersions.find((item) => item.id === selectedKnowledgeVersionId);
    if (!selected || (readyVersion && selected.id !== readyVersion.id)) {
      setSelectedKnowledgeVersionId(preferred.id);
    }
  }, [knowledgeVersions, selectedKnowledgeVersionId]);

  const selectedTextbook = useMemo(
    () => textbooks.find((item) => item.id === selectedTextbookId) ?? latestById(textbooks),
    [selectedTextbookId, textbooks],
  );
  const selectedProfileFile = useMemo(
    () => learnerProfiles.find((item) => item.id === selectedProfileFileId) ?? latestById(learnerProfiles),
    [learnerProfiles, selectedProfileFileId],
  );
  const selectedParseVersion = useMemo(
    () => parseVersions.find((item) => item.id === selectedParseVersionId) ?? preferredParseVersion(parseVersions, tasks),
    [parseVersions, selectedParseVersionId, tasks],
  );
  const selectedProfileVersion = useMemo(
    () => profileVersions.find((item) => item.id === selectedProfileVersionId) ?? latestById(profileVersions),
    [profileVersions, selectedProfileVersionId],
  );
  const selectedKnowledgeVersion = useMemo(
    () => knowledgeVersions.find((item) => item.id === selectedKnowledgeVersionId) ?? latestById(knowledgeVersions),
    [knowledgeVersions, selectedKnowledgeVersionId],
  );
  const latestBatch = useMemo(() => latestById(generationBatches), [generationBatches]);

  const parsingTask = useMemo(
    () => latestTaskBy(tasks, isTextbookParseTask),
    [tasks],
  );
  const profileTask = useMemo(
    () => latestTaskBy(tasks, isLearnerProfileTask),
    [tasks],
  );
  const knowledgeTask = useMemo(
    () => latestTaskBy(tasks, isKnowledgeTask),
    [tasks],
  );
  const generationTask = useMemo(
    () =>
      latestTaskBy(tasks, (task) =>
        ["pipeline", "curriculum", "lesson_plan", "coverage", "assessment", "courseware"].includes(task.module_code),
      ),
    [tasks],
  );

  const materialComplete = Boolean(selectedTextbook && selectedProfileFile);
  const parseComplete = isConfirmedParseVersion(selectedParseVersion);
  const hasUnfinishedProfileTask = Boolean(profileTask && !isTaskSuccessStatus(profileTask.task_status));
  const profileComplete = isReadyProfileVersion(selectedProfileVersion) && !hasUnfinishedProfileTask;
  const hasReadyProjectBaseline = Boolean(projectQuery.data?.current_textbook_version_id && projectQuery.data?.current_learner_profile_version_id);
  const knowledgeComplete = isReadyVersion(selectedKnowledgeVersion);
  const hasSuccessfulParseVersion = parseVersions.some((item) => item.parse_status === SUCCESS_STATUS);
  const hasActiveParseTask = tasks.some((task) => isTextbookParseTask(task) && isTaskActiveStatus(task.task_status));
  const hasActiveKnowledgeTask = tasks.some((task) => isKnowledgeTask(task) && isTaskActiveStatus(task.task_status));
  const generationActive = isTaskActiveStatus(generationTask?.task_status) || isTaskActiveStatus(latestBatch?.batch_status);
  const generationComplete = isCompleteStatus(latestBatch?.batch_status);
  const parseActive = isTaskActiveStatus(parsingTask?.task_status) || Boolean(selectedParseVersion && !parseComplete);
  const profileActive = isTaskActiveStatus(profileTask?.task_status) || Boolean(selectedProfileVersion && !profileComplete);
  const knowledgeActive = isTaskActiveStatus(knowledgeTask?.task_status) || Boolean(selectedKnowledgeVersion && !knowledgeComplete);
  const parseFailed =
    isFailureStatus(parsingTask?.task_status) ||
    isFailureStatus(selectedTextbook?.parse_status) ||
    isFailureStatus(selectedParseVersion?.parse_status);
  const profileFailed =
    isFailureStatus(profileTask?.task_status) ||
    isFailureStatus(selectedProfileFile?.file_status) ||
    isFailureStatus(selectedProfileVersion?.extract_status);
  const knowledgeFailed = isFailureStatus(knowledgeTask?.task_status);
  const generationFailed = isFailureStatus(generationTask?.task_status) || isFailureStatus(latestBatch?.batch_status);

  const materialState: ProcessState = materialComplete ? "complete" : "current";
  const parseState: ProcessState = parseComplete ? "complete" : selectedTextbook ? "current" : "waiting";
  const profileState: ProcessState = profileComplete ? "complete" : selectedProfileFile ? "current" : "waiting";
  const knowledgeState: ProcessState = knowledgeComplete ? "complete" : parseComplete ? "current" : "waiting";
  const generationState: ProcessState = generationComplete ? "complete" : knowledgeComplete && profileComplete ? "current" : "waiting";

  useEffect(() => {
    if (projectId > 0 && profileComplete && !projectQuery.data?.current_learner_profile_version_id) {
      queryClient.invalidateQueries({ queryKey: ["project", projectId] });
    }
  }, [profileComplete, projectId, projectQuery.data?.current_learner_profile_version_id, queryClient]);

  const invalidateWorkspace = () => {
    queryClient.invalidateQueries({ queryKey: ["project", projectId] });
    queryClient.invalidateQueries({ queryKey: ["textbooks", projectId] });
    queryClient.invalidateQueries({ queryKey: ["learner-profiles", projectId] });
    queryClient.invalidateQueries({ queryKey: ["tasks", projectId] });
    queryClient.invalidateQueries({ queryKey: ["generation-process", projectId] });
    queryClient.invalidateQueries({ queryKey: ["generation-run-active", projectId] });
    queryClient.invalidateQueries({ queryKey: ["generation-batches", projectId] });
    if (selectedTextbookId) {
      queryClient.invalidateQueries({ queryKey: ["parse-versions", selectedTextbookId] });
    }
    if (selectedParseVersionId) {
      queryClient.invalidateQueries({ queryKey: ["knowledge-versions", selectedParseVersionId] });
    }
    if (selectedProfileFileId) {
      queryClient.invalidateQueries({ queryKey: ["learner-profile-versions", projectId, selectedProfileFileId] });
    }
    if (selectedProfileVersion?.id) {
      queryClient.invalidateQueries({ queryKey: ["learner-profile-version-detail", selectedProfileVersion.id] });
    }
  };

  const createParseTask = useMutation({
    mutationFn: () => api.createParseTask(selectedTextbook!.id),
    onSuccess: invalidateWorkspace,
  });

  const confirmParseVersion = useMutation({
    mutationFn: () => api.confirmParseVersion(selectedParseVersion!.id),
    onSuccess: (parseVersion) => {
      setSelectedParseVersionId(parseVersion.id);
      invalidateWorkspace();
    },
  });

  const createKnowledgeTask = useMutation({
    mutationFn: () => api.createKnowledgeTask(selectedParseVersion!.id, { force_regenerate: knowledgeComplete }),
    onSuccess: invalidateWorkspace,
  });

  const createBatch = useMutation({
    mutationFn: () =>
      api.createGenerationBatch({
        project_id: projectId,
        knowledge_version_id: selectedKnowledgeVersion!.id,
        learner_profile_version_id: selectedProfileVersion!.id,
        batch_name: `${projectTitle(projectQuery.data, selectedTextbook)}备课资源`,
        course_count: generationCourseCount,
        session_duration_minutes: generationSessionDurationMinutes,
      }),
    onSuccess: invalidateWorkspace,
  });

  const startGenerationRun = useMutation({
    mutationFn: () =>
      api.startGenerationRun(projectId, {
        course_count: generationCourseCount,
        session_duration_minutes: generationSessionDurationMinutes,
        auto_confirm_parse: true,
      }),
    onSuccess: invalidateWorkspace,
  });

  const learnerProfileStep = generationProcess?.steps?.find((step) => step.code === "learner_profile");
  const learnerProfileSucceeded =
    profileComplete || isTaskSuccessStatus(profileTask?.task_status) || learnerProfileStep?.status === "succeeded";
  const learnerProfileReportVersionId = selectedProfileVersion?.id ?? projectQuery.data?.current_learner_profile_version_id;
  const learnerProfileReportBatchId = generationProcess?.batch_id ?? latestBatch?.id;
  const learnerProfileReportUrl =
    learnerProfileSucceeded && learnerProfileReportVersionId
      ? learnerProfileReportBatchId
        ? `/projects/${projectId}/batches/${learnerProfileReportBatchId}/learner-profile/${learnerProfileReportVersionId}`
        : `/projects/${projectId}/learner-profile/${learnerProfileReportVersionId}`
      : null;
  const materialActions = useMemo<Partial<Record<string, StepMaterialAction>>>(() => {
    const actions: Partial<Record<string, StepMaterialAction>> = {};
    if (learnerProfileReportUrl) {
      actions.learner_profile = {
        label: "查看学情",
        href: learnerProfileReportUrl,
        state: { backTo: `/projects/${projectId}` },
      };
    }
    return actions;
  }, [
    learnerProfileReportUrl,
  ]);

  useEffect(() => {
    if (projectId <= 0 || !learnerProfileSucceeded || profileFailed) {
      return;
    }

    const syncKey = [
      projectId,
      profileTask?.id ?? "no-task",
      selectedProfileVersion?.id ?? projectQuery.data?.current_learner_profile_version_id ?? "no-version",
    ].join(":");
    if (learnerProfileSuccessSyncKeyRef.current === syncKey) {
      return;
    }

    learnerProfileSuccessSyncKeyRef.current = syncKey;
    setFastRefetchUntil(Date.now() + FAST_REFETCH_WINDOW_MS);
    queryClient.invalidateQueries({ queryKey: ["project", projectId] });
    queryClient.invalidateQueries({ queryKey: ["tasks", projectId] });
    queryClient.invalidateQueries({ queryKey: ["generation-process", projectId] });
    queryClient.invalidateQueries({ queryKey: ["generation-run-active", projectId] });
    if (selectedProfileFileId) {
      queryClient.invalidateQueries({ queryKey: ["learner-profile-versions", projectId, selectedProfileFileId] });
    }
  }, [
    learnerProfileSucceeded,
    profileFailed,
    profileTask?.id,
    projectId,
    projectQuery.data?.current_learner_profile_version_id,
    queryClient,
    selectedProfileFileId,
    selectedProfileVersion?.id,
  ]);

  useEffect(() => {
    const hasRunInBackend = Boolean(activeGenerationRun || generationProcess?.generation_run_id);
    if (
      projectId <= 0 ||
      !selectedTextbook ||
      !selectedProfileFile ||
      !learnerProfileSucceeded ||
      !hasReadyProjectBaseline ||
      hasRunInBackend ||
      hasActiveParseTask ||
      hasActiveKnowledgeTask ||
      generationComplete ||
      latestBatch ||
      startGenerationRun.isPending ||
      activeGenerationRunQuery.isLoading ||
      textbooksQuery.isLoading ||
      learnerProfilesQuery.isLoading ||
      generationBatchesQuery.isLoading
    ) {
      return;
    }

    const triggerKey = [
      "profile",
      projectId,
      projectQuery.data?.current_textbook_version_id,
      projectQuery.data?.current_learner_profile_version_id,
    ].join(":");
    if (startRunTriggeredKeyRef.current === triggerKey) {
      return;
    }

    startRunTriggeredKeyRef.current = triggerKey;
    setFastRefetchUntil(Date.now() + FAST_REFETCH_WINDOW_MS);
    startGenerationRun.reset();
    startGenerationRun.mutate(undefined, {
      onError: () => {
        startRunTriggeredKeyRef.current = null;
      },
      onSuccess: () => {
        setFastRefetchUntil(Date.now() + FAST_REFETCH_WINDOW_MS);
      },
    });
  }, [
    activeGenerationRun,
    activeGenerationRunQuery.isLoading,
    generationBatchesQuery.isLoading,
    generationComplete,
    generationProcess?.generation_run_id,
    hasActiveKnowledgeTask,
    hasActiveParseTask,
    hasReadyProjectBaseline,
    latestBatch,
    learnerProfileSucceeded,
    learnerProfilesQuery.isLoading,
    projectId,
    projectQuery.data?.current_learner_profile_version_id,
    projectQuery.data?.current_textbook_version_id,
    selectedProfileFile,
    selectedTextbook,
    startGenerationRun,
    textbooksQuery.isLoading,
  ]);

  if (projectId <= 0) {
    return <EmptyState title="地址无效" action={<Link className="btn btn-secondary" to="/">返回首页</Link>} />;
  }

  if (projectQuery.isLoading) {
    return (
      <div className="flex h-[70vh] items-center justify-center text-sm text-ink/55">
        <Loader2 className="mr-2 animate-spin" size={17} />
        加载中
      </div>
    );
  }

  if (projectQuery.error && !projectQuery.data) {
    return <ErrorNotice title="页面加载失败" message={getErrorMessage(projectQuery.error)} />;
  }

  if (!projectQuery.data) {
    return <EmptyState title="没有找到这次备课" action={<Link className="btn btn-secondary" to="/">返回首页</Link>} />;
  }

  const processContext = buildProcessContext(projectQuery.data, selectedTextbook);

  return (
    <div className="-mx-4 min-h-screen bg-[#fbfbfb] px-4 pb-10 pt-8 lg:-mx-8 lg:px-10 lg:pt-8">
      <div className="mx-auto max-w-[1500px]">
        <div className="process-layout mb-5">
          <header className="min-w-0">
            <h1 className="line-clamp-2 text-2xl font-semibold text-ink">{processContext.title}</h1>
            <p className="mt-2 text-sm leading-6 text-ink/55">{processContext.subtitle}</p>
          </header>
          <div aria-hidden="true" className="hidden md:block" />
        </div>

        <div className="process-layout">
          <main className="h-full">
            {startGenerationRun.error ? (
              <div className="mb-4">
                <ErrorNotice title="启动生成失败" message={getErrorMessage(startGenerationRun.error)} />
              </div>
            ) : null}
            {generationProcessQuery.error && !generationProcess ? (
              <ErrorNotice title="生成过程加载失败" message={getErrorMessage(generationProcessQuery.error)} />
            ) : (
              <GenerationProcessTimeline
                currentTime={currentTime}
                fallbackStartedAt={activeGenerationRun?.started_at ?? undefined}
                isLoading={generationProcessQuery.isLoading}
                materialActions={materialActions}
                process={generationProcess}
              />
            )}
          </main>

          <GenerationOutputPanel process={generationProcess} currentTime={currentTime} fallbackStartedAt={activeGenerationRun?.started_at ?? undefined} />
        </div>
      </div>
    </div>
  );
}
