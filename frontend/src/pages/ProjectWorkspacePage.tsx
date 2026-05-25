import { type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowRight,
  BookOpen,
  Check,
  Circle,
  ExternalLink,
  FileText,
  Loader2,
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
import { cn, getErrorMessage, toNumberId } from "../utils";

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
  const paperSceneCount = new Set((paperResults?.items ?? []).map((item) => item.scene_type)).size;
  const hasCoverage = (coverageReports?.items ?? []).some((item) => isCompleteStatus(item.report_status));
  const lessonCount = lessonPlans?.pagination?.total_count ?? 0;
  const coursewareCount = coursewareResults?.pagination?.total_count ?? 0;

  const rows = [
    { label: "课程方案", value: batch?.curriculum_plan_id ? "已生成" : "准备中" },
    { label: "多课教案", value: lessonCount ? `${lessonCount} 份` : batch?.curriculum_plan_id ? "生成中" : "等待课程方案" },
    { label: "覆盖报告", value: hasCoverage ? "已完成" : lessonCount ? "准备中" : "等待教案" },
    { label: "PPT 课件", value: coursewareCount ? `${coursewareCount} 份` : "按课生成" },
    { label: "配套测练", value: paperSceneCount ? `${paperSceneCount} 类` : "按场景生成" },
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
    return <SoftNotice>整理好教学重点后，就可以生成课程方案和多课教案；PPT 课件与配套测练可在资源页按需生成。</SoftNotice>;
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

function projectTitle(project?: Project, textbook?: TextbookVersion) {
  return stripKnownFileExtension(textbook?.textbook_name || project?.name || "备课资源");
}

export function ProjectWorkspacePage() {
  const queryClient = useQueryClient();
  const projectId = toNumberId(useParams().projectId);
  const [visibleStepCount, setVisibleStepCount] = useState(1);
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
    if (!autoCoreGenerationMarker) {
      return;
    }
    setCurrentTime(Date.now());
    const timer = window.setInterval(() => setCurrentTime(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [autoCoreGenerationMarker]);

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

  const parseEvidenceSummaryQuery = useQuery({
    queryKey: ["parse-evidence-summary", selectedParseVersionId],
    queryFn: () => api.getParseEvidenceSummary(selectedParseVersionId!),
    enabled: Boolean(selectedParseVersionId),
    retry: false,
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

  const textbooks = textbooksQuery.data?.items ?? [];
  const learnerProfiles = learnerProfilesQuery.data?.items ?? [];
  const parseVersions = parseVersionsQuery.data?.items ?? [];
  const profileVersions = profileVersionsQuery.data?.items ?? [];
  const knowledgeVersions = knowledgeVersionsQuery.data?.items ?? [];
  const generationBatches = generationBatchesQuery.data?.items ?? [];
  const tasks = tasksQuery.data?.items ?? [];

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

  const knowledgeChaptersQuery = useQuery({
    queryKey: ["knowledge-chapters", selectedKnowledgeVersion?.id],
    queryFn: () => api.listKnowledgeChapters(selectedKnowledgeVersion!.id),
    enabled: Boolean(selectedKnowledgeVersion?.id && isReadyVersion(selectedKnowledgeVersion)),
    retry: false,
  });

  const knowledgePointsQuery = useQuery({
    queryKey: ["knowledge-points", selectedKnowledgeVersion?.id, "phase2"],
    queryFn: () => api.listKnowledgePoints(selectedKnowledgeVersion!.id, { page: 1, page_size: 20 }),
    enabled: Boolean(selectedKnowledgeVersion?.id && isReadyVersion(selectedKnowledgeVersion)),
    retry: false,
  });

  const lessonPlansQuery = useQuery({
    queryKey: ["lesson-plans", latestBatch?.curriculum_plan_id, "phase2"],
    queryFn: () => api.listLessonPlans(latestBatch!.curriculum_plan_id!, { page: 1, page_size: 100 }),
    enabled: Boolean(latestBatch?.curriculum_plan_id),
    retry: false,
  });

  const paperResultsQuery = useQuery({
    queryKey: ["paper-results", latestBatch?.id, "phase2"],
    queryFn: () => api.listPaperResults(latestBatch!.id, { page: 1, page_size: 100 }),
    enabled: Boolean(latestBatch?.id),
    retry: false,
  });

  const coursewareResultsQuery = useQuery({
    queryKey: ["courseware-results", latestBatch?.id, "phase2"],
    queryFn: () => api.listCoursewareResults(latestBatch!.id, { page: 1, page_size: 100 }),
    enabled: Boolean(latestBatch?.id),
    retry: false,
  });

  const coverageReportsQuery = useQuery({
    queryKey: ["coverage-reports", latestBatch?.id, "phase2"],
    queryFn: () => api.listCoverageReports(latestBatch!.id, { page: 1, page_size: 20 }),
    enabled: Boolean(latestBatch?.id),
    retry: false,
  });

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
    queryClient.invalidateQueries({ queryKey: ["generation-batches", projectId] });
    if (selectedTextbookId) {
      queryClient.invalidateQueries({ queryKey: ["parse-versions", selectedTextbookId] });
    }
    queryClient.invalidateQueries({ queryKey: ["parse-evidence-summary"] });
    if (selectedParseVersionId) {
      queryClient.invalidateQueries({ queryKey: ["knowledge-versions", selectedParseVersionId] });
    }
    if (selectedProfileFileId) {
      queryClient.invalidateQueries({ queryKey: ["learner-profile-versions", projectId, selectedProfileFileId] });
    }
    if (selectedProfileVersionId) {
      queryClient.invalidateQueries({ queryKey: ["learner-profile-version-detail", selectedProfileVersionId] });
    }
    if (selectedKnowledgeVersion?.id) {
      queryClient.invalidateQueries({ queryKey: ["knowledge-chapters", selectedKnowledgeVersion.id] });
      queryClient.invalidateQueries({ queryKey: ["knowledge-points", selectedKnowledgeVersion.id] });
    }
    if (latestBatch?.id) {
      queryClient.invalidateQueries({ queryKey: ["paper-results", latestBatch.id] });
      queryClient.invalidateQueries({ queryKey: ["courseware-results", latestBatch.id] });
      queryClient.invalidateQueries({ queryKey: ["coverage-reports", latestBatch.id] });
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
          message: "课程方案、教案和覆盖报告已准备好；PPT 可按课生成，测练可按场景生成。",
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
        message: "正在生成课程方案、多课教案和覆盖报告；PPT 课件与配套测练可在资源页按需生成。",
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
        message: "课程方案、多课教案和覆盖报告正在准备中；PPT 课件与配套测练可在资源页按需生成。",
        buttonLabel: "正在生成",
        buttonIcon: Loader2,
        disabled: true,
        loading: true,
      };
    }
    if (generationComplete && latestBatch) {
      return {
        title: "备课资源已生成",
        message: "课程方案、教案和覆盖报告已准备好；PPT 可按课生成，测练可按场景生成。",
        buttonLabel: "查看备课资源",
        buttonIcon: ExternalLink,
        onClick: () => window.location.assign(`/projects/${projectId}/batches/${latestBatch.id}`),
      };
    }
    return {
      title: latestBatch ? "可以重新生成" : "可以生成备课资源了",
      message: "将基于教材、学情和教学重点生成课程方案和多课教案；PPT 课件与配套测练可在资源页按需生成。",
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

  useEffect(() => {
    setVisibleStepCount(1);
    const timers = Array.from({ length: PROCESS_STEP_COUNT - 1 }, (_, index) =>
      window.setTimeout(() => setVisibleStepCount(index + 2), (index + 1) * 420),
    );
    return () => timers.forEach((timer) => window.clearTimeout(timer));
  }, [
    projectId,
    projectQuery.data?.id,
    selectedTextbook?.id,
    selectedProfileFile?.id,
    selectedParseVersion?.id,
    selectedKnowledgeVersion?.id,
    latestBatch?.id,
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

  const sourceTitle = projectTitle(projectQuery.data, selectedTextbook);

  return (
    <div className="-mx-4 min-h-screen bg-[#fbfbfb] px-4 pb-10 pt-10 lg:-mx-8 lg:px-10 lg:pt-12">
      <div className="mx-auto max-w-[1500px]">
        <header className="mb-10">
          <h1 className="line-clamp-2 max-w-5xl text-3xl font-semibold tracking-[-0.035em] text-ink md:text-4xl">{sourceTitle}</h1>
        </header>

        <div className="process-layout">
          <main className="space-y-6">
            <ProcessTimeline>
              {visibleStepCount >= 1 ? (
                <div className="relative md:pl-10">
                <div className="absolute left-0 top-5 hidden md:block">
                  <StepStatusIcon state={materialState} />
                </div>
                <ProcessStepCard
                  state={materialState}
                  icon={Upload}
                  title="上传材料"
                  waitingText="请上传教材 PDF 和学情分析 DOCX。"
                  currentText="请先补齐教材 PDF 和学情分析 DOCX。"
                >
                  <div className="grid gap-3 lg:grid-cols-2">
                    {selectedTextbook ? (
                      <FilePill icon={BookOpen} label="教材 PDF" fileName={fileNameFrom(selectedTextbook.source_file, selectedTextbook.textbook_name)} />
                    ) : (
                      <SoftNotice>还没有教材 PDF。</SoftNotice>
                    )}
                    {selectedProfileFile ? (
                      <FilePill icon={FileText} label="学情 DOCX" fileName={fileNameFrom(selectedProfileFile.source_file, selectedProfileFile.title)} />
                    ) : (
                      <SoftNotice>还没有学情分析 DOCX。</SoftNotice>
                    )}
                  </div>
                </ProcessStepCard>
                </div>
              ) : null}

              {visibleStepCount >= 2 ? (
                <div className="relative md:pl-10">
                <div className="absolute left-0 top-5 hidden md:block">
                  <StepStatusIcon state={parseState} />
                </div>
                <ProcessStepCard
                  state={parseState}
                  icon={BookOpen}
                  title="理解教材"
                  waitingText="上传教材后，系统会先理解教材结构。"
                  currentText={parseActive ? "正在理解教材结构，完成后会展示页数、图表、公式和证据片段。" : "可以开始理解教材。"}
                >
                  <ParseSummaryCard
                    parseVersion={selectedParseVersion}
                    summary={parseEvidenceSummaryQuery.data}
                    isLoading={parseEvidenceSummaryQuery.isLoading}
                  />
                </ProcessStepCard>
                </div>
              ) : null}

              {visibleStepCount >= 3 ? (
                <div className="relative md:pl-10">
                <div className="absolute left-0 top-5 hidden md:block">
                  <StepStatusIcon state={profileState} />
                </div>
                <ProcessStepCard
                  state={profileState}
                  icon={FileText}
                  title="分析学情"
                  waitingText="上传学情后，系统会分析学生基础、薄弱点和课时安排。"
                  currentText={profileActive ? "正在分析学情，用于调整讲解重点和练习难度。" : "等待学情分析完成。"}
                >
                  <LearnerSummaryCard detail={profileDetailQuery.data} fallback={selectedProfileVersion} isLoading={profileDetailQuery.isLoading} />
                </ProcessStepCard>
                </div>
              ) : null}

              {visibleStepCount >= 4 ? (
                <div className="relative md:pl-10">
                <div className="absolute left-0 top-5 hidden md:block">
                  <StepStatusIcon state={knowledgeState} />
                </div>
                <ProcessStepCard
                  state={knowledgeState}
                  icon={Target}
                  title="整理教学重点"
                  waitingText="教材理解完成后，系统会整理章节和知识点；学情会在生成备课包时合并使用。"
                  currentText={knowledgeActive ? "正在整理章节、知识点和重点讲解线索。" : "可以开始整理教学重点。"}
                >
                  <KnowledgeSummaryCard
                    knowledgeVersion={selectedKnowledgeVersion}
                    chapters={knowledgeChaptersQuery.data}
                    points={knowledgePointsQuery.data}
                    isLoading={knowledgeChaptersQuery.isLoading || knowledgePointsQuery.isLoading}
                  />
                </ProcessStepCard>
                </div>
              ) : null}

              {visibleStepCount >= 5 ? (
                <div className="relative md:pl-10">
                <div className="absolute left-0 top-5 hidden md:block">
                  <StepStatusIcon state={generationState} />
                </div>
                <ProcessStepCard
                  state={generationState}
                  icon={Sparkles}
                  title="生成备课资源"
                  waitingText="教学重点整理完成后，就可以生成可直接使用的备课资源。"
                  currentText={generationActive ? "正在生成课程方案、多课教案和覆盖报告。" : "可以开始生成备课资源。"}
                >
                  <GeneratedResourcesSummary
                    batch={latestBatch}
                    lessonPlans={lessonPlansQuery.data}
                    paperResults={paperResultsQuery.data}
                    coursewareResults={coursewareResultsQuery.data}
                    coverageReports={coverageReportsQuery.data}
                  />
                </ProcessStepCard>
                </div>
              ) : null}
            </ProcessTimeline>
          </main>

          <CurrentActionPanel
            action={action}
            batch={latestBatch}
            lessonPlans={lessonPlansQuery.data}
            paperResults={paperResultsQuery.data}
            coursewareResults={coursewareResultsQuery.data}
            coverageReports={coverageReportsQuery.data}
          />
        </div>
      </div>
    </div>
  );
}
