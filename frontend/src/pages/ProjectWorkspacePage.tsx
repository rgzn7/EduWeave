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
import { Link, useParams } from "react-router-dom";
import { EmptyState } from "../components/EmptyState";
import { ErrorNotice } from "../components/ErrorNotice";
import { isTaskActiveStatus } from "../hooks/useTaskPolling";
import {
  clearAutoCoreGenerationMarker,
  DEFAULT_COURSE_COUNT,
  DEFAULT_SESSION_DURATION_MINUTES,
  readAutoCoreGenerationMarker,
  type AutoCoreGenerationMarker,
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
  LearnerProfileFile,
  LearnerProfileVersion,
  LearnerProfileVersionDetail,
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
const FAILURE_STATUSES = new Set(["failed", "failure", "error", "cancelled"]);

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
  fileName: string;
  metaItems: string[];
  openLabel: string;
  opening?: boolean;
  disabled?: boolean;
  onOpen: () => void;
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

function isReadyProfileVersion(profileVersion?: LearnerProfileVersion | LearnerProfileVersionDetail) {
  return profileVersion?.extract_status === SUCCESS_STATUS && isReadyVersion(profileVersion);
}

function isCompleteStatus(status?: string | null) {
  return ["success", "completed", "complete", "ready", "done"].includes(String(status ?? "").toLowerCase());
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

function scoreLabel(score?: number | null) {
  if (score === undefined || score === null) {
    return "已完成分析";
  }
  if (score >= 85) {
    return `基础扎实，约 ${score} 分`;
  }
  if (score >= 70) {
    return `中等偏上，约 ${score} 分`;
  }
  if (score >= 60) {
    return `基础待稳固，约 ${score} 分`;
  }
  return `需要重点帮扶，约 ${score} 分`;
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

function LearnerSummaryCard({
  detail,
  fallback,
  isLoading,
}: {
  detail?: LearnerProfileVersionDetail;
  fallback?: LearnerProfileVersion;
  isLoading: boolean;
}) {
  const records = detail?.records ?? [];
  const targetRecord = records[0];
  const weaknesses = uniqueItems(records.flatMap((record) => extractTagItems(record.weakness_tags_json)), 4);
  const habits = uniqueItems(records.flatMap((record) => [...extractTagItems(record.habit_tags_json), ...extractTagItems(record.behavior_traits_json)]), 4);
  const timePlans = uniqueItems(records.flatMap((record) => extractTagItems(record.time_plan_json)), 3);

  if (!detail && fallback?.summary_text) {
    return <SoftNotice>{fallback.summary_text}</SoftNotice>;
  }

  if (!detail) {
    return <SoftNotice>{isLoading ? "正在读取学情分析结果。" : "学情分析已完成，摘要正在同步。"}</SoftNotice>;
  }

  return (
    <div className="grid gap-3 md:grid-cols-2">
      <div className="rounded-2xl border border-line bg-[#fbfbfb] p-4">
        <div className="text-xs font-medium text-ink/42">学生基础</div>
        <div className="mt-2 text-sm font-semibold text-ink">{scoreLabel(targetRecord?.score_value)}</div>
      </div>
      <div className="rounded-2xl border border-line bg-[#fbfbfb] p-4">
        <div className="text-xs font-medium text-ink/42">薄弱点</div>
        <div className="mt-2">
          <ChipList items={weaknesses} emptyText="未识别到明确薄弱点" />
        </div>
      </div>
      <div className="rounded-2xl border border-line bg-[#fbfbfb] p-4">
        <div className="text-xs font-medium text-ink/42">学习习惯</div>
        <div className="mt-2">
          <ChipList items={habits} emptyText="暂无学习习惯摘要" />
        </div>
      </div>
      <div className="rounded-2xl border border-line bg-[#fbfbfb] p-4">
        <div className="text-xs font-medium text-ink/42">课时安排</div>
        <div className="mt-2">
          <ChipList items={timePlans} emptyText="暂无课时安排摘要" />
        </div>
      </div>
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
  "mineru_parse",
  "learner_profile",
  "knowledge_structure",
  "curriculum_plan",
  "lesson_plan_generate",
  "coverage_check",
] as const;

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
    toolName: "MinerU 教材解析工具",
    description: "识别教材章节、页码、图表、题目和知识点。",
    icon: FileText,
  },
  learner_profile: {
    title: "学情信息分析",
    toolName: "学情理解工具",
    description: "分析学生基础、薄弱点、学习习惯和班级画像。",
    icon: BookOpen,
  },
  knowledge_structure: {
    title: "重组教学内容",
    toolName: "知识点梳理工具",
    description: "整理课程知识点、能力目标、重点难点和关联关系。",
    icon: ListChecks,
  },
  curriculum_plan: {
    title: "整套课程规划",
    toolName: "课程规划工具",
    description: "生成整套课程课次安排、教学目标和课时规划。",
    icon: Clock3,
  },
  lesson_plan_generate: {
    title: "多课时教案生成",
    toolName: "教案生成工具",
    description: "为每一课生成教学目标、重点难点、教学流程和课后安排。",
    icon: BookOpen,
  },
  coverage_check: {
    title: "校验知识覆盖",
    toolName: "覆盖检查工具",
    description: "检查课程、教案、题目和课件的知识点覆盖情况。",
    icon: Target,
  },
};

const CORE_OUTPUTS = [
  { label: "课程总纲", stepCode: "curriculum_plan", icon: FileText },
  { label: "多课时教案", stepCode: "lesson_plan_generate", icon: BookOpen },
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
  return status === "running" || status === "pending" || status === "waiting";
}

function timestampMs(value?: string | null) {
  if (!value) {
    return null;
  }
  const time = new Date(value).getTime();
  return Number.isFinite(time) ? time : null;
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

  if (fallbackStart && isActive) {
    return formatDurationMs(currentTime - fallbackStart);
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

function extractNumberBefore(value: string | null | undefined, unit: string) {
  if (!value) {
    return null;
  }
  const match = value.match(new RegExp(`(\\d+)\\s*${unit}`));
  return match?.[1] ?? null;
}

function formatPhase2StepSummary(step: GenerationProcessStep) {
  if (step.status === "failed") {
    return step.error_message || "生成失败，请稍后重试。";
  }
  if (step.status === "pending" || step.status === "waiting") {
    if (step.code === "lesson_plan_generate") {
      return "等待课程规划完成后自动开始。";
    }
    if (step.code === "coverage_check") {
      return "等待核心资源生成后自动开始。";
    }
    return "等待前置步骤完成后自动开始。";
  }
  if (step.status === "running") {
    const runningSummaries: Record<string, string> = {
      mineru_parse: "正在解析教材结构、页码与内容。",
      learner_profile: "正在分析学生基础、薄弱点与学习特征。",
      knowledge_structure: "正在提取章节、知识点与教学线索。",
      curriculum_plan: "正在规划课次安排、教学目标与课时节奏。",
      lesson_plan_generate: "正在生成多课时教案与课堂流程。",
      coverage_check: "正在检查课程、教案与资源的知识覆盖。",
    };
    return runningSummaries[step.code] ?? getPhase2StepMeta(step).description;
  }
  if (step.status === "succeeded") {
    if (step.code === "mineru_parse") {
      const pageCount = extractNumberBefore(step.summary, "页");
      return pageCount ? `已完成教材结构、页码与内容识别，共 ${pageCount} 页。` : "已完成教材结构、页码与内容识别。";
    }
    if (step.code === "learner_profile") {
      return "已完成学生基础、薄弱点与学习特征分析。";
    }
    if (step.code === "knowledge_structure") {
      const chapterCount = extractNumberBefore(step.summary, "个章节");
      const pointCount = extractNumberBefore(step.summary, "个知识点");
      return chapterCount && pointCount
        ? `已完成教学重点整理，识别 ${chapterCount} 个章节、${pointCount} 个知识点。`
        : "已完成章节结构与教学重点整理。";
    }
    if (step.code === "curriculum_plan") {
      return "已完成整套课程的课次安排与教学目标。";
    }
    if (step.code === "lesson_plan_generate") {
      return "已完成多课时教案生成。";
    }
    if (step.code === "coverage_check") {
      return "已完成核心资源覆盖检查。";
    }
  }
  return step.summary || getPhase2StepMeta(step).description;
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
  isLast,
  materialAction,
  step,
}: {
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
  const isPending = step.status === "pending" || step.status === "waiting";
  const isExpandable = isSucceeded;
  const [manualExpanded, setManualExpanded] = useState(false);
  const [materialOpen, setMaterialOpen] = useState(false);
  const materialPopoverRef = useRef<HTMLDivElement | null>(null);
  const isExpanded = isRunning || isFailed || (isSucceeded && manualExpanded);

  useEffect(() => {
    if (!isSucceeded) {
      setManualExpanded(false);
    }
  }, [isSucceeded]);

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
      {!isLast ? <div className="absolute left-3 top-8 bottom-[-1rem] hidden w-px bg-line md:block" /> : null}
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
            <p className={cn("mt-1 text-sm leading-6", isPending ? "text-ink/36" : isFailed ? "font-medium text-[#9f1f16]" : "text-ink/58")}>
              {formatPhase2StepSummary(step)}
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-1.5">
            {materialAction ? (
              <div className="relative" ref={materialPopoverRef}>
                <button
                  className="rounded-md px-2 py-1 text-sm font-semibold text-[#2563eb] transition hover:bg-[#eff6ff] hover:text-[#1d4ed8]"
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
                        {materialAction.metaItems.length ? (
                          <div className="mt-2 text-sm leading-5 text-ink/50">{materialAction.metaItems.join(" · ")}</div>
                        ) : null}
                      </div>
                    </div>
                    <button
                      className="mt-4 inline-flex h-11 w-full items-center justify-center gap-2 rounded-lg bg-ink text-sm font-semibold text-white transition hover:bg-ink/88 disabled:cursor-not-allowed disabled:bg-ink/20"
                      disabled={materialAction.disabled || materialAction.opening}
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
          </div>
        ) : null}
      </section>
    </article>
  );
}

function GenerationProcessTimeline({
  materialActions,
  process,
  isLoading,
}: {
  materialActions?: Partial<Record<string, StepMaterialAction>>;
  process?: GenerationProcess;
  isLoading: boolean;
}) {
  const steps = process?.steps?.length ? process.steps : fallbackGenerationSteps();

  return (
    <div className="relative space-y-4">
      {isLoading && !process ? (
        <div className="mb-2 flex items-center gap-2 text-sm text-ink/45">
          <Loader2 className="animate-spin" size={15} />
          正在同步生成过程
        </div>
      ) : null}
      {steps.map((step, index) => (
        <GenerationStepCard isLast={index === steps.length - 1} key={step.code} materialAction={materialActions?.[step.code]} step={step} />
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

  return (
    <aside className="sticky top-8 space-y-4">
      <section className="rounded-lg border border-line bg-white p-6 shadow-[0_16px_42px_rgba(17,17,17,0.06)]">
        <h2 className="text-xl font-semibold text-ink">本次备课</h2>
        <div className="mt-5 grid gap-4">
          <ProcessStat icon={Clock3} label="已运行" value={formatGenerationRuntime(process, currentTime, fallbackStartedAt)} />
          <ProcessStat icon={Check} label="已完成" value={`${completedCount} / ${totalCount} 步`} />
          <ProcessStat icon={Loader2} iconClassName={runningCount > 0 ? "animate-spin" : undefined} label="正在处理" value={`${runningCount} 项`} />
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
          <Link className="btn btn-primary mt-6 h-12 w-full rounded-lg" to={`/projects/${process.project_id}/batches/${batchId}`}>
            <ExternalLink size={17} />
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
  const projectId = toNumberId(useParams().projectId);
  const [selectedTextbookId, setSelectedTextbookId] = useState<number | null>(null);
  const [selectedProfileFileId, setSelectedProfileFileId] = useState<number | null>(null);
  const [selectedProfileVersionId, setSelectedProfileVersionId] = useState<number | null>(null);
  const [selectedParseVersionId, setSelectedParseVersionId] = useState<number | null>(null);
  const [selectedKnowledgeVersionId, setSelectedKnowledgeVersionId] = useState<number | null>(null);
  const [autoCoreGenerationMarker, setAutoCoreGenerationMarker] = useState<AutoCoreGenerationMarker | null>(() =>
    readAutoCoreGenerationMarker(projectId),
  );
  const [currentTime, setCurrentTime] = useState(() => Date.now());
  const autoTriggeredStepKeys = useRef<Set<string>>(new Set());

  useEffect(() => {
    setAutoCoreGenerationMarker(readAutoCoreGenerationMarker(projectId));
    autoTriggeredStepKeys.current.clear();
  }, [projectId]);

  useEffect(() => {
    setCurrentTime(Date.now());
    const timer = window.setInterval(() => setCurrentTime(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  const projectQuery = useQuery({
    queryKey: ["project", projectId],
    queryFn: () => api.getProject(projectId),
    enabled: projectId > 0,
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
    refetchInterval: 8_000,
  });

  const profileVersionsQuery = useQuery({
    queryKey: ["learner-profile-versions", projectId, selectedProfileFileId],
    queryFn: () => api.listLearnerProfileVersions(projectId, selectedProfileFileId!),
    enabled: Boolean(projectId && selectedProfileFileId),
    refetchInterval: 8_000,
  });

  const profileDetailQuery = useQuery({
    queryKey: ["learner-profile-version-detail", selectedProfileVersionId],
    queryFn: () => api.getLearnerProfileVersion(selectedProfileVersionId!),
    enabled: Boolean(selectedProfileVersionId),
    retry: false,
  });

  const knowledgeVersionsQuery = useQuery({
    queryKey: ["knowledge-versions", selectedParseVersionId],
    queryFn: () => api.listKnowledgeVersions(selectedParseVersionId!),
    enabled: Boolean(selectedParseVersionId),
    refetchInterval: 8_000,
  });

  const generationBatchesQuery = useQuery({
    queryKey: ["generation-batches", projectId],
    queryFn: () => api.listGenerationBatches(projectId),
    enabled: projectId > 0,
    refetchInterval: 8_000,
  });

  const tasksQuery = useQuery({
    queryKey: ["tasks", projectId],
    queryFn: () => api.listTasks({ project_id: projectId, page: 1, page_size: 30 }),
    enabled: projectId > 0,
    refetchInterval: 5_000,
  });

  const generationProcessQuery = useQuery({
    queryKey: ["generation-process", projectId],
    queryFn: () => api.getGenerationProcess(projectId),
    enabled: projectId > 0,
    refetchInterval: (query) => {
      const process = query.state.data;
      return process?.status === "succeeded" || process?.status === "failed" ? false : 5_000;
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
    () => latestTaskBy(tasks, (task) => task.module_code === "learner_profile" || task.task_type === "learner_profile_extract"),
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
  const profileComplete = isReadyProfileVersion(profileDetailQuery.data ?? selectedProfileVersion);
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
  const autoCoreGenerationEnabled = Boolean(autoCoreGenerationMarker);
  const generationCourseCount = autoCoreGenerationMarker?.courseCount ?? DEFAULT_COURSE_COUNT;
  const generationSessionDurationMinutes = autoCoreGenerationMarker?.sessionDurationMinutes ?? DEFAULT_SESSION_DURATION_MINUTES;

  const materialState: ProcessState = materialComplete ? "complete" : "current";
  const parseState: ProcessState = parseComplete ? "complete" : selectedTextbook ? "current" : "waiting";
  const profileState: ProcessState = profileComplete ? "complete" : selectedProfileFile ? "current" : "waiting";
  const knowledgeState: ProcessState = knowledgeComplete ? "complete" : parseComplete ? "current" : "waiting";
  const generationState: ProcessState = generationComplete ? "complete" : knowledgeComplete && profileComplete ? "current" : "waiting";

  const invalidateWorkspace = () => {
    queryClient.invalidateQueries({ queryKey: ["project", projectId] });
    queryClient.invalidateQueries({ queryKey: ["textbooks", projectId] });
    queryClient.invalidateQueries({ queryKey: ["learner-profiles", projectId] });
    queryClient.invalidateQueries({ queryKey: ["tasks", projectId] });
    queryClient.invalidateQueries({ queryKey: ["generation-process", projectId] });
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
    if (selectedProfileVersionId) {
      queryClient.invalidateQueries({ queryKey: ["learner-profile-version-detail", selectedProfileVersionId] });
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

  const openMaterialFile = useMutation({
    mutationFn: async ({ fileObjectId }: { fileObjectId: number; kind: "textbook" | "profile" }) => {
      const result = await api.getFileDownloadUrl(fileObjectId);
      if (!result.signed_url) {
        throw new Error("暂时无法打开材料，请稍后重试。");
      }
      return result.signed_url;
    },
    onSuccess: (url) => window.open(url, "_blank", "noopener,noreferrer"),
  });

  const selectedTextbookSource = valueAsRecord(selectedTextbook?.source_file);
  const selectedProfileSource = valueAsRecord(selectedProfileFile?.source_file);
  const selectedTextbookFileObjectId = fileObjectIdFrom(selectedTextbook?.source_file);
  const selectedProfileFileObjectId = fileObjectIdFrom(selectedProfileFile?.source_file, selectedProfileFile?.source_file_id);
  const materialActions = useMemo<Partial<Record<string, StepMaterialAction>>>(() => {
    const actions: Partial<Record<string, StepMaterialAction>> = {};
    if (selectedTextbook) {
      actions.mineru_parse = {
        label: "查看教材",
        fileName: fileNameFrom(selectedTextbook.source_file, selectedTextbook.textbook_name),
        metaItems: [
          selectedTextbook.page_count ? `${selectedTextbook.page_count} 页` : "",
          formatDate(stringValue(selectedTextbookSource?.created_at) || selectedTextbook.created_at),
        ].filter(Boolean),
        openLabel: "打开教材",
        opening: openMaterialFile.isPending && openMaterialFile.variables?.kind === "textbook",
        disabled: !selectedTextbookFileObjectId,
        onOpen: () => selectedTextbookFileObjectId && openMaterialFile.mutate({ fileObjectId: selectedTextbookFileObjectId, kind: "textbook" }),
      };
    }
    if (selectedProfileFile) {
      const recordCount = profileDetailQuery.data?.records?.length;
      actions.learner_profile = {
        label: "查看学情",
        fileName: fileNameFrom(selectedProfileFile.source_file, selectedProfileFile.title),
        metaItems: [
          recordCount ? `${recordCount} 份学情记录` : "",
          formatDate(stringValue(selectedProfileSource?.created_at) || selectedProfileFile.created_at),
        ].filter(Boolean),
        openLabel: "打开学情",
        opening: openMaterialFile.isPending && openMaterialFile.variables?.kind === "profile",
        disabled: !selectedProfileFileObjectId,
        onOpen: () => selectedProfileFileObjectId && openMaterialFile.mutate({ fileObjectId: selectedProfileFileObjectId, kind: "profile" }),
      };
    }
    return actions;
  }, [
    openMaterialFile,
    profileDetailQuery.data?.records?.length,
    selectedProfileFile,
    selectedProfileFileObjectId,
    selectedProfileSource?.created_at,
    selectedTextbook,
    selectedTextbookFileObjectId,
    selectedTextbookSource?.created_at,
  ]);

  const autoMutationError = createParseTask.error ?? confirmParseVersion.error ?? createKnowledgeTask.error ?? createBatch.error;
  const hasAutoBlockingFailure =
    parseFailed || profileFailed || knowledgeFailed || generationFailed || Boolean(autoMutationError);
  const hasAutoMutationPending =
    createParseTask.isPending || confirmParseVersion.isPending || createKnowledgeTask.isPending || createBatch.isPending;
  const autoElapsedText = autoCoreGenerationMarker
    ? `已运行 ${formatElapsedTime(autoCoreGenerationMarker.createdAt, currentTime)}`
    : undefined;

  const triggerAutoStep = (stepKey: string, action: () => void) => {
    if (autoTriggeredStepKeys.current.has(stepKey)) {
      return;
    }
    autoTriggeredStepKeys.current.add(stepKey);
    action();
  };

  useEffect(() => {
    if (autoCoreGenerationEnabled && generationComplete && latestBatch) {
      clearAutoCoreGenerationMarker(projectId);
      setAutoCoreGenerationMarker(null);
    }
  }, [autoCoreGenerationEnabled, generationComplete, latestBatch, projectId]);

  useEffect(() => {
    if (
      !autoCoreGenerationEnabled ||
      projectId <= 0 ||
      !selectedTextbook ||
      !selectedProfileFile ||
      hasAutoBlockingFailure ||
      hasAutoMutationPending ||
      textbooksQuery.isLoading ||
      learnerProfilesQuery.isLoading ||
      parseVersionsQuery.isLoading ||
      profileVersionsQuery.isLoading ||
      knowledgeVersionsQuery.isLoading ||
      generationBatchesQuery.isLoading ||
      tasksQuery.isLoading
    ) {
      return;
    }

    if (!selectedParseVersion && !parseActive && !hasSuccessfulParseVersion && !hasActiveParseTask) {
      triggerAutoStep(`parse:${selectedTextbook.id}`, () => createParseTask.mutate());
      return;
    }

    if (selectedParseVersion?.parse_status === SUCCESS_STATUS && selectedParseVersion.review_status !== CONFIRMED_STATUS) {
      triggerAutoStep(`confirm-parse:${selectedParseVersion.id}`, () => confirmParseVersion.mutate());
      return;
    }

    if (parseComplete && !knowledgeComplete && !knowledgeActive && !hasActiveKnowledgeTask && selectedParseVersion) {
      triggerAutoStep(`knowledge:${selectedParseVersion.id}`, () => createKnowledgeTask.mutate());
      return;
    }

    if (parseComplete && profileComplete && knowledgeComplete && !latestBatch && !generationActive) {
      triggerAutoStep(`batch:${selectedKnowledgeVersion?.id}:${selectedProfileVersion?.id}`, () => createBatch.mutate());
    }
  }, [
    autoCoreGenerationEnabled,
    confirmParseVersion,
    createBatch,
    createKnowledgeTask,
    createParseTask,
    generationActive,
    generationBatchesQuery.isLoading,
    hasAutoBlockingFailure,
    hasAutoMutationPending,
    hasActiveKnowledgeTask,
    hasActiveParseTask,
    hasSuccessfulParseVersion,
    knowledgeActive,
    knowledgeComplete,
    knowledgeVersionsQuery.isLoading,
    latestBatch,
    learnerProfilesQuery.isLoading,
    parseActive,
    parseComplete,
    parseVersionsQuery.isLoading,
    profileComplete,
    profileVersionsQuery.isLoading,
    projectId,
    selectedKnowledgeVersion?.id,
    selectedParseVersion,
    selectedProfileFile,
    selectedProfileVersion?.id,
    selectedTextbook,
    tasksQuery.isLoading,
    textbooksQuery.isLoading,
  ]);

  const action: ActionConfig = useMemo(() => {
    if (autoCoreGenerationEnabled) {
      if (autoMutationError) {
        return {
          title: "自动生成遇到问题",
          message: getErrorMessage(autoMutationError),
          meta: autoElapsedText,
        };
      }
      if (parseFailed) {
        return {
          title: "教材理解失败",
          message: taskErrorMessage(parsingTask, "教材解析没有成功，请查看任务详情或重新创建备课。"),
          meta: autoElapsedText,
        };
      }
      if (profileFailed) {
        return {
          title: "学情分析失败",
          message: taskErrorMessage(profileTask, "学情分析没有成功，当前接口不支持对已上传学情重新抽取。"),
          meta: autoElapsedText,
        };
      }
      if (knowledgeFailed) {
        return {
          title: "教学重点整理失败",
          message: taskErrorMessage(knowledgeTask, "知识点抽取没有成功，请查看任务详情或重新创建备课。"),
          meta: autoElapsedText,
        };
      }
      if (generationFailed) {
        return {
          title: "核心备课包生成失败",
          message: taskErrorMessage(generationTask, "课程方案、教案或覆盖报告生成没有成功，请查看任务详情。"),
          meta: autoElapsedText,
        };
      }
      if (generationComplete && latestBatch) {
        return {
          title: "备课资源已生成",
          message: "课程方案、教案和覆盖报告已准备好；PPT 与课后作业可按课生成，期末综合测可按整套生成。",
          meta: autoElapsedText,
          buttonLabel: "查看备课资源",
          buttonIcon: ExternalLink,
          onClick: () => window.location.assign(`/projects/${projectId}/batches/${latestBatch.id}`),
        };
      }
      if (!selectedParseVersion || selectedParseVersion.parse_status !== SUCCESS_STATUS || selectedParseVersion.review_status !== CONFIRMED_STATUS) {
        return {
          title: "自动生成中",
          message: "正在理解教材，完成后会自动确认结果并整理教学重点。",
          meta: autoElapsedText,
          buttonLabel: "正在自动处理",
          buttonIcon: Loader2,
          disabled: true,
          loading: true,
        };
      }
      if (profileActive && knowledgeActive && !profileComplete && !knowledgeComplete) {
        return {
          title: "自动生成中",
          message: "正在并行分析学情和整理教学重点，完成后会自动生成核心备课包。",
          meta: autoElapsedText,
          buttonLabel: "正在自动处理",
          buttonIcon: Loader2,
          disabled: true,
          loading: true,
        };
      }
      if (!profileComplete) {
        return {
          title: "自动生成中",
          message: "正在分析学情，完成后会和教材知识点一起用于生成核心备课包。",
          meta: autoElapsedText,
          buttonLabel: "正在自动处理",
          buttonIcon: Loader2,
          disabled: true,
          loading: true,
        };
      }
      if (!knowledgeComplete) {
        return {
          title: "自动生成中",
          message: "正在整理章节、知识点和重点讲解线索，完成后会自动生成核心备课包。",
          meta: autoElapsedText,
          buttonLabel: "正在自动处理",
          buttonIcon: Loader2,
          disabled: true,
          loading: true,
        };
      }
      return {
        title: "自动生成中",
        message: "正在生成课程方案、多课教案和覆盖报告；PPT 与课后作业可按课生成，期末综合测可按整套生成。",
        meta: autoElapsedText,
        buttonLabel: "正在自动处理",
        buttonIcon: Loader2,
        disabled: true,
        loading: true,
      };
    }

    if (!selectedTextbook || !selectedProfileFile) {
      return {
        title: "请先补齐材料",
        message: "上传教材 PDF 和学情分析 DOCX 后，EduWeave 会开始理解教材和分析学情。",
      };
    }
    if (!selectedParseVersion || selectedParseVersion.parse_status !== SUCCESS_STATUS) {
      return {
        title: parseActive ? "正在理解教材" : "可以理解教材了",
        message: parseActive ? "教材结构正在识别，完成后会展示页数、图表、公式和证据片段。" : "先让系统读懂教材结构，再继续整理知识点。",
        buttonLabel: parseActive ? "正在理解教材" : "理解教材",
        buttonIcon: parseActive ? Loader2 : BookOpen,
        disabled: parseActive || createParseTask.isPending,
        loading: createParseTask.isPending || parseActive,
        onClick: () => createParseTask.mutate(),
      };
    }
    if (selectedParseVersion.review_status !== CONFIRMED_STATUS) {
      return {
        title: "请确认教材理解结果",
        message: "确认后，系统会基于这份教材理解结果整理教学重点。",
        buttonLabel: "确认教材理解结果",
        buttonIcon: Check,
        disabled: confirmParseVersion.isPending,
        loading: confirmParseVersion.isPending,
        onClick: () => confirmParseVersion.mutate(),
      };
    }
    if (profileActive && knowledgeActive && !profileComplete && !knowledgeComplete) {
      return {
        title: "并行处理中",
        message: "正在并行分析学情和整理教学重点，完成后会自动生成核心备课包。",
        buttonLabel: "正在处理",
        buttonIcon: Loader2,
        disabled: true,
        loading: true,
      };
    }
    if (!profileComplete) {
      return {
        title: profileActive ? "正在分析学情" : "等待学情分析",
        message: "学情会用于调整讲解重点和练习难度，完成后继续整理教学重点。",
        buttonLabel: profileActive ? "正在分析学情" : undefined,
        buttonIcon: Loader2,
        disabled: true,
        loading: profileActive,
      };
    }
    if (!knowledgeComplete) {
      return {
        title: knowledgeActive ? "正在整理教学重点" : "可以整理教学重点了",
        message: "系统会把教材内容整理成章节、知识点和重点讲解线索。",
        buttonLabel: knowledgeActive ? "正在整理教学重点" : "整理教学重点",
        buttonIcon: knowledgeActive ? Loader2 : Target,
        disabled: knowledgeActive || createKnowledgeTask.isPending,
        loading: knowledgeActive || createKnowledgeTask.isPending,
        onClick: () => createKnowledgeTask.mutate(),
      };
    }
    if (generationActive) {
      return {
        title: "正在生成备课资源",
        message: "课程方案、多课教案和覆盖报告正在准备中；PPT 与课后作业可按课生成，期末综合测可按整套生成。",
        buttonLabel: "正在生成",
        buttonIcon: Loader2,
        disabled: true,
        loading: true,
      };
    }
    if (generationComplete && latestBatch) {
      return {
        title: "备课资源已生成",
        message: "课程方案、教案和覆盖报告已准备好；PPT 与课后作业可按课生成，期末综合测可按整套生成。",
        buttonLabel: "查看备课资源",
        buttonIcon: ExternalLink,
        onClick: () => window.location.assign(`/projects/${projectId}/batches/${latestBatch.id}`),
      };
    }
    return {
      title: latestBatch ? "可以重新生成" : "可以生成备课资源了",
      message: "将基于教材、学情和教学重点生成课程方案和多课教案；PPT 与课后作业可按课生成，期末综合测可按整套生成。",
      buttonLabel: "生成备课资源",
      buttonIcon: Wand2,
      disabled: createBatch.isPending,
      loading: createBatch.isPending,
      onClick: () => createBatch.mutate(),
    };
  }, [
    autoCoreGenerationEnabled,
    autoElapsedText,
    autoMutationError,
    confirmParseVersion,
    createBatch,
    createKnowledgeTask,
    createParseTask,
    generationActive,
    generationComplete,
    generationFailed,
    generationTask,
    knowledgeActive,
    knowledgeComplete,
    knowledgeFailed,
    knowledgeTask,
    latestBatch,
    parseActive,
    parseFailed,
    parsingTask,
    profileFailed,
    profileActive,
    profileComplete,
    profileTask,
    projectId,
    selectedParseVersion,
    selectedProfileFile,
    selectedTextbook,
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
          <main>
            {openMaterialFile.error ? (
              <div className="mb-4">
                <ErrorNotice title="材料暂时无法打开" message={getErrorMessage(openMaterialFile.error)} />
              </div>
            ) : null}
            {generationProcessQuery.error && !generationProcess ? (
              <ErrorNotice title="生成过程加载失败" message={getErrorMessage(generationProcessQuery.error)} />
            ) : (
              <GenerationProcessTimeline materialActions={materialActions} process={generationProcess} isLoading={generationProcessQuery.isLoading} />
            )}
          </main>

          <GenerationOutputPanel process={generationProcess} currentTime={currentTime} fallbackStartedAt={autoCoreGenerationMarker?.createdAt} />
        </div>
      </div>
    </div>
  );
}
