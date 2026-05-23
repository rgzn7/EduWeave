import { FormEvent, type ReactNode, useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowRight,
  BookOpen,
  Brain,
  ChevronLeft,
  CircleDot,
  ClipboardList,
  FileText,
  Layers,
  Loader2,
  Play,
  RefreshCw,
  Upload,
  Wand2,
  type LucideIcon,
} from "lucide-react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { EmptyState } from "../components/EmptyState";
import { ErrorNotice } from "../components/ErrorNotice";
import { ProgressBar } from "../components/ProgressBar";
import { StatusBadge } from "../components/StatusBadge";
import { TaskTable } from "../components/TaskTable";
import { isTaskActiveStatus } from "../hooks/useTaskPolling";
import { api } from "../lib/api";
import type { KnowledgeVersion, LearnerProfileVersion, ParseEvidenceSummary, ParseVersion, Task, TextbookVersion } from "../types";
import { cn, formatDate, getErrorMessage, toNumberId } from "../utils";

const READY_STATUS = "ready";
const SUCCESS_STATUS = "success";
const CONFIRMED_STATUS = "confirmed";

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

function isReadyVersion(item?: { version_status?: string | null }) {
  return item?.version_status === READY_STATUS;
}

function isConfirmedParseVersion(parseVersion?: ParseVersion) {
  return parseVersion?.parse_status === SUCCESS_STATUS && parseVersion.review_status === CONFIRMED_STATUS;
}

function isReadyProfileVersion(profileVersion?: LearnerProfileVersion) {
  return profileVersion?.extract_status === SUCCESS_STATUS && isReadyVersion(profileVersion);
}

function describeTask(task?: Task) {
  if (!task) {
    return "暂无任务";
  }
  return `${task.module_code} / ${task.task_type}`;
}

function QueryError({ error, title }: { error: unknown; title: string }) {
  if (!error) {
    return null;
  }
  return <ErrorNotice title={title} message={getErrorMessage(error)} />;
}

function ActionHint({ reason }: { reason?: string | null }) {
  if (!reason) {
    return null;
  }
  return (
    <div className="flex items-start gap-2 rounded-md border border-line bg-paper/70 px-3 py-2 text-xs font-semibold text-ink/55">
      <CircleDot className="mt-0.5 shrink-0" size={14} />
      <span>{reason}</span>
    </div>
  );
}

function SelectRow<T extends { id: number }>({
  items,
  selectedId,
  onChange,
  renderLabel,
}: {
  items: T[];
  selectedId: number | null;
  onChange: (id: number) => void;
  renderLabel: (item: T) => string;
}) {
  if (!items.length) {
    return null;
  }
  return (
    <select className="field" value={selectedId ?? ""} onChange={(event) => onChange(Number(event.target.value))}>
      {items.map((item) => (
        <option key={item.id} value={item.id}>
          {renderLabel(item)}
        </option>
      ))}
    </select>
  );
}

function VersionList<T extends { id: number; version_no?: number; created_at: string; updated_at: string }>({
  items,
  title,
  selectedId,
  onSelect,
  renderStatus,
  renderMeta,
  renderTitle,
}: {
  items: T[];
  title: string;
  selectedId: number | null;
  onSelect: (id: number) => void;
  renderStatus: (item: T) => string | null | undefined;
  renderMeta?: (item: T) => string;
  renderTitle?: (item: T) => string;
}) {
  if (!items.length) {
    return <EmptyState title={`暂无${title}`} />;
  }
  return (
    <div className="divide-y divide-line rounded-md border border-line">
      {items.map((item) => (
        <button
          className={cn(
            "flex w-full items-center justify-between gap-3 px-4 py-3 text-left transition hover:bg-paper",
            selectedId === item.id ? "bg-accent/10" : "bg-white",
          )}
          key={item.id}
          onClick={() => onSelect(item.id)}
          type="button"
        >
          <div className="min-w-0">
            <div className="truncate text-sm font-bold">{renderTitle?.(item) ?? `${title} #${item.version_no ?? item.id}`}</div>
            <div className="mt-1 text-xs text-ink/50">{renderMeta?.(item) ?? formatDate(item.updated_at)}</div>
          </div>
          <StatusBadge status={renderStatus(item)} />
        </button>
      ))}
    </div>
  );
}

function WorkflowSection({
  icon: Icon,
  iconTone,
  title,
  subtitle,
  status,
  task,
  children,
}: {
  icon: LucideIcon;
  iconTone: string;
  title: string;
  subtitle: string;
  status?: string | null;
  task?: Task;
  children: ReactNode;
}) {
  return (
    <section className="panel overflow-hidden">
      <div className="panel-header">
        <div className="flex min-w-0 items-center gap-3">
          <div className={cn("flex h-10 w-10 shrink-0 items-center justify-center rounded-md", iconTone)}>
            <Icon size={20} />
          </div>
          <div className="min-w-0">
            <h2 className="truncate text-lg font-bold">{title}</h2>
            <div className="truncate text-sm text-ink/55">{subtitle}</div>
          </div>
        </div>
        {status ? <StatusBadge status={status} /> : null}
      </div>
      <div className="grid gap-5 p-5 xl:grid-cols-[minmax(0,1fr)_320px]">
        <div className="space-y-5">{children}</div>
        <RecentTaskCard task={task} />
      </div>
    </section>
  );
}

function RecentTaskCard({ task }: { task?: Task }) {
  return (
    <aside className="rounded-md border border-line bg-paper/60 p-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="label">最近任务</div>
          <div className="mt-1 text-sm font-bold text-ink">{task ? `#${task.id}` : "-"}</div>
        </div>
        {task ? <StatusBadge status={task.task_status} /> : <span className="text-xs font-semibold text-ink/35">无任务</span>}
      </div>
      <div className="mt-3 text-xs text-ink/55">{describeTask(task)}</div>
      {task ? (
        <>
          <div className="mt-4">
            <ProgressBar value={task.progress_percent} />
          </div>
          {task.last_error_message ? (
            <div className="mt-3 line-clamp-3 text-xs font-semibold text-coral">{task.last_error_message}</div>
          ) : null}
          <Link className="btn btn-secondary mt-4 h-9 w-full text-xs" to={`/tasks/${task.id}`}>
            任务详情
            <ArrowRight size={14} />
          </Link>
        </>
      ) : null}
    </aside>
  );
}

function BaselineRow({
  label,
  value,
  status,
  ready,
}: {
  label: string;
  value?: string | number | null;
  status?: string | null;
  ready: boolean;
}) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-line pb-3 last:border-0 last:pb-0">
      <div className="min-w-0">
        <div className="text-xs font-semibold text-ink/45">{label}</div>
        <div className="mt-1 truncate text-sm font-bold text-ink">{value ?? "-"}</div>
      </div>
      <StatusBadge status={ready ? READY_STATUS : status ?? "pending"} />
    </div>
  );
}

function displayMetric(value: unknown) {
  if (value === undefined || value === null || value === "") {
    return "-";
  }
  if (typeof value === "boolean") {
    return value ? "是" : "否";
  }
  return String(value);
}

function recordEntries(value: unknown) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return [];
  }
  return Object.entries(value as Record<string, unknown>).filter(([, item]) => item !== undefined && item !== null && item !== "");
}

function EvidenceMetricGrid({ entries }: { entries: [string, unknown][] }) {
  if (!entries.length) {
    return <div className="text-sm text-ink/45">等待后端 evidence-summary 接口返回统计。</div>;
  }
  return (
    <div className="grid gap-3 md:grid-cols-2">
      {entries.map(([key, value]) => (
        <div className="rounded-md border border-line bg-white px-3 py-2" key={key}>
          <div className="text-xs font-semibold text-ink/45">{key}</div>
          <div className="mt-1 break-words text-sm font-bold text-ink">{displayMetric(value)}</div>
        </div>
      ))}
    </div>
  );
}

function blockTypeEntries(summary?: ParseEvidenceSummary): [string, unknown][] {
  if (summary?.block_type_counts?.length) {
    return summary.block_type_counts.map((item) => [item.block_type, item.count]);
  }
  return recordEntries(summary?.block_type_stats);
}

function mediaEntries(summary?: ParseEvidenceSummary): [string, unknown][] {
  const volume = summary?.volume;
  if (volume) {
    return [
      ["图片类 Block", volume.image_block_count],
      ["表格类 Block", volume.table_block_count],
      ["公式类 Block", volume.equation_block_count],
      ["带资源 Block", volume.asset_block_count],
      ["带坐标 Block", volume.bbox_block_count],
    ];
  }
  return recordEntries(summary?.media_stats);
}

function mineruParameterEntries(summary?: ParseEvidenceSummary): [string, unknown][] {
  const params = summary?.mineru_parameters;
  if (params) {
    return [
      ["策略编码", params.strategy_code],
      ["模型版本", params.model_version],
      ["启用 OCR", params.is_ocr],
      ["启用公式解析", params.enable_formula],
      ["启用表格解析", params.enable_table],
    ];
  }
  return recordEntries(summary?.mineru_options);
}

function evidenceSampleValue(item: Record<string, unknown>, primaryKey: string, fallbackKey?: string) {
  const value = item[primaryKey];
  if (value !== undefined && value !== null && value !== "") {
    return value;
  }
  return fallbackKey ? item[fallbackKey] : undefined;
}

function ParseEvidencePanel({
  parseVersion,
  summary,
  isLoading,
  error,
}: {
  parseVersion?: ParseVersion;
  summary?: ParseEvidenceSummary;
  isLoading: boolean;
  error: unknown;
}) {
  if (!parseVersion) {
    return <EmptyState title="暂无解析证据" description="选择或生成解析版本后，这里会展示 MinerU 解析证据摘要。" />;
  }

  const sampleEvidence = (summary?.sample_blocks ?? summary?.sample_evidence ?? []) as Array<Record<string, unknown>>;
  const volume = summary?.volume;
  const baseRows: [string, unknown][] = [
    ["解析版本", `#${summary?.parse_version_id ?? parseVersion.id}`],
    ["解析策略", summary?.strategy_code ?? parseVersion.strategy_code],
    ["MinerU 模型", summary?.mineru_model ?? summary?.mineru_parameters?.model_version ?? "等待后端接口"],
    ["解析状态", summary?.parse_status ?? parseVersion.parse_status],
    ["复核状态", summary?.review_status ?? parseVersion.review_status],
  ];
  const scaleRows: [string, unknown][] = [
    ["页数", volume?.page_count ?? summary?.page_count ?? parseVersion.page_count],
    ["已解析页数", volume?.parsed_page_count],
    ["Block 总数", volume?.block_count ?? summary?.block_count],
    ["Issue 数", volume?.issue_count ?? summary?.issue_count ?? parseVersion.issue_count],
  ];
  const unavailable = !isLoading && !summary;

  return (
    <section className="rounded-md border border-line bg-paper/60 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="label">解析证据摘要</div>
          <h3 className="mt-1 text-sm font-bold text-ink">MinerU 结构化能力展示</h3>
        </div>
        <StatusBadge status={summary?.parse_status ?? parseVersion.parse_status} />
      </div>
      {isLoading ? <div className="mt-3 text-xs font-semibold text-ink/45">正在读取 evidence-summary...</div> : null}
      {unavailable ? (
        <div className="mt-3 rounded-md border border-dashed border-line bg-white px-3 py-2 text-xs font-semibold leading-5 text-ink/50">
          等待后端 evidence-summary 接口；当前仅展示解析版本基础信息，不展示虚构的 block、图片、表格或公式统计。
          {error ? <span className="block text-coral">接口返回：{getErrorMessage(error)}</span> : null}
        </div>
      ) : null}
      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <div>
          <div className="mb-2 text-xs font-semibold text-ink/45">版本基础信息</div>
          <EvidenceMetricGrid entries={baseRows} />
        </div>
        <div>
          <div className="mb-2 text-xs font-semibold text-ink/45">规模统计</div>
          <EvidenceMetricGrid entries={scaleRows} />
        </div>
        <div>
          <div className="mb-2 text-xs font-semibold text-ink/45">Block 类型统计</div>
          <EvidenceMetricGrid entries={blockTypeEntries(summary)} />
        </div>
        <div>
          <div className="mb-2 text-xs font-semibold text-ink/45">多媒体与资源统计</div>
          <EvidenceMetricGrid entries={mediaEntries(summary)} />
        </div>
      </div>
      <div className="mt-4">
        <div className="mb-2 text-xs font-semibold text-ink/45">MinerU 参数摘要</div>
        <EvidenceMetricGrid entries={mineruParameterEntries(summary)} />
      </div>
      <div className="mt-4">
        <div className="mb-2 text-xs font-semibold text-ink/45">示例证据</div>
        {sampleEvidence.length ? (
          <div className="space-y-2">
            {sampleEvidence.slice(0, 5).map((item, index) => (
              <div
                className="rounded-md border border-line bg-white px-3 py-2 text-sm"
                key={`${evidenceSampleValue(item, "parse_block_id", "block_id") ?? evidenceSampleValue(item, "block_no") ?? index}`}
              >
                <div className="flex flex-wrap gap-2 text-xs font-semibold text-ink/50">
                  <span>页码 {displayMetric(evidenceSampleValue(item, "page_no"))}</span>
                  <span>Block {displayMetric(evidenceSampleValue(item, "block_no", "parse_block_id"))}</span>
                  <span>类型 {displayMetric(evidenceSampleValue(item, "block_type"))}</span>
                  <span>资源 {displayMetric(evidenceSampleValue(item, "asset_file_id", "resource_file_id"))}</span>
                </div>
                <div className="mt-1 line-clamp-2 break-words text-ink/70">
                  {displayMetric(evidenceSampleValue(item, "text_excerpt", "text_snippet"))}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="text-sm text-ink/45">等待后端返回页码、block 编号、文本片段与资源文件 ID。</div>
        )}
      </div>
    </section>
  );
}

function UploadError({ error, title }: { error: unknown; title: string }) {
  if (!error) {
    return null;
  }
  return <ErrorNotice title={title} message={getErrorMessage(error)} />;
}

export function ProjectWorkspacePage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const projectId = toNumberId(useParams().projectId);
  const [textbookFile, setTextbookFile] = useState<File | null>(null);
  const [textbookName, setTextbookName] = useState("");
  const [profileFile, setProfileFile] = useState<File | null>(null);
  const [profileTitle, setProfileTitle] = useState("");
  const [batchName, setBatchName] = useState("第一轮课程规划");
  const [courseCount, setCourseCount] = useState(12);
  const [duration, setDuration] = useState(90);
  const [selectedTextbookId, setSelectedTextbookId] = useState<number | null>(null);
  const [selectedProfileFileId, setSelectedProfileFileId] = useState<number | null>(null);
  const [selectedProfileVersionId, setSelectedProfileVersionId] = useState<number | null>(null);
  const [selectedParseVersionId, setSelectedParseVersionId] = useState<number | null>(null);
  const [selectedKnowledgeVersionId, setSelectedKnowledgeVersionId] = useState<number | null>(null);

  const projectQuery = useQuery({
    queryKey: ["project", projectId],
    queryFn: () => api.getProject(projectId),
    enabled: projectId > 0,
  });

  const dashboardQuery = useQuery({
    queryKey: ["project-dashboard", projectId],
    queryFn: () => api.getProjectDashboard(projectId),
    enabled: projectId > 0,
    refetchInterval: 10_000,
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
    const preferred = latestById(parseVersions);
    if (!preferred) {
      setSelectedParseVersionId(null);
      setSelectedKnowledgeVersionId(null);
      return;
    }
    if (!selectedParseVersionId || !parseVersions.some((item) => item.id === selectedParseVersionId)) {
      setSelectedParseVersionId(preferred.id);
      setSelectedKnowledgeVersionId(null);
    }
  }, [parseVersions, selectedParseVersionId]);

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
  }, [knowledgeVersions]);

  const selectedTextbook = useMemo(
    () => textbooks.find((item) => item.id === selectedTextbookId) ?? latestById(textbooks),
    [selectedTextbookId, textbooks],
  );
  const selectedParseVersion = useMemo(
    () => parseVersions.find((item) => item.id === selectedParseVersionId) ?? latestById(parseVersions),
    [parseVersions, selectedParseVersionId],
  );
  const selectedProfileVersion = useMemo(
    () => profileVersions.find((item) => item.id === selectedProfileVersionId) ?? latestById(profileVersions),
    [profileVersions, selectedProfileVersionId],
  );
  const selectedKnowledgeVersion = useMemo(
    () => knowledgeVersions.find((item) => item.id === selectedKnowledgeVersionId) ?? latestById(knowledgeVersions),
    [knowledgeVersions, selectedKnowledgeVersionId],
  );
  const hasKnowledgeVersion = knowledgeVersions.length > 0;
  const hasReadyKnowledgeVersion = knowledgeVersions.some(isReadyVersion);

  const parsingTask = useMemo(
    () => latestTaskBy(tasks, (task) => task.module_code === "parsing" || task.task_type === "textbook_parse"),
    [tasks],
  );
  const profileTask = useMemo(
    () => latestTaskBy(tasks, (task) => task.module_code === "learner_profile" || task.task_type === "learner_profile_extract"),
    [tasks],
  );
  const knowledgeTask = useMemo(
    () => latestTaskBy(tasks, (task) => task.module_code === "knowledge" || task.task_type === "knowledge_extract"),
    [tasks],
  );
  const knowledgeTaskActive = isTaskActiveStatus(knowledgeTask?.task_status);
  const knowledgeActionLabel = hasKnowledgeVersion ? "重新抽取知识" : "抽取知识";
  const generationTask = useMemo(
    () =>
      latestTaskBy(tasks, (task) =>
        ["pipeline", "curriculum", "lesson_plan", "coverage", "assessment", "courseware"].includes(task.module_code),
      ),
    [tasks],
  );

  const invalidateWorkspace = () => {
    queryClient.invalidateQueries({ queryKey: ["project", projectId] });
    queryClient.invalidateQueries({ queryKey: ["project-dashboard", projectId] });
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
  };

  const uploadTextbook = useMutation({
    mutationFn: () =>
      api.uploadTextbook(projectId, {
        file: textbookFile!,
        textbook_name: textbookName || textbookFile?.name,
        set_as_current: true,
      }),
    onSuccess: (textbook) => {
      setTextbookFile(null);
      setTextbookName("");
      setSelectedTextbookId(textbook.id);
      setSelectedParseVersionId(null);
      setSelectedKnowledgeVersionId(null);
      invalidateWorkspace();
    },
  });

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

  const uploadProfile = useMutation({
    mutationFn: () =>
      api.uploadLearnerProfile(projectId, {
        file: profileFile!,
        title: profileTitle || profileFile?.name,
        auto_extract: true,
        set_as_current: true,
      }),
    onSuccess: (profile) => {
      setProfileFile(null);
      setProfileTitle("");
      setSelectedProfileFileId(profile.id);
      setSelectedProfileVersionId(null);
      invalidateWorkspace();
    },
  });

  const createKnowledgeTask = useMutation({
    mutationFn: () => api.createKnowledgeTask(selectedParseVersion!.id, { force_regenerate: hasReadyKnowledgeVersion }),
    onSuccess: invalidateWorkspace,
  });

  const createBatch = useMutation({
    mutationFn: () =>
      api.createGenerationBatch({
        project_id: projectId,
        knowledge_version_id: selectedKnowledgeVersion!.id,
        learner_profile_version_id: selectedProfileVersion!.id,
        batch_name: batchName.trim(),
        course_count: courseCount,
        session_duration_minutes: duration,
      }),
    onSuccess: (batch) => {
      invalidateWorkspace();
      navigate(`/projects/${projectId}/batches/${batch.id}`);
    },
  });

  const uploadTextbookReason = !textbookFile ? "请选择 PDF 教材文件" : uploadTextbook.isPending ? "正在上传教材" : null;
  const parseReason = !selectedTextbook ? "缺少教材版本" : createParseTask.isPending ? "正在创建解析任务" : null;
  const confirmParseReason = !selectedParseVersion
    ? "缺少解析版本"
    : selectedParseVersion.parse_status !== SUCCESS_STATUS
      ? `解析状态为 ${selectedParseVersion.parse_status}`
      : selectedParseVersion.review_status === CONFIRMED_STATUS
        ? "解析版本已确认"
        : confirmParseVersion.isPending
          ? "正在确认解析版本"
          : null;
  const uploadProfileReason = !profileFile ? "请选择学情 doc/docx 文件" : uploadProfile.isPending ? "正在上传学情" : null;
  const knowledgeReason = !selectedParseVersion
    ? "缺少解析版本"
    : selectedParseVersion.parse_status !== SUCCESS_STATUS
      ? `解析状态为 ${selectedParseVersion.parse_status}`
      : selectedParseVersion.review_status !== CONFIRMED_STATUS
        ? "请先确认解析版本"
        : knowledgeTaskActive
          ? "知识抽取任务运行中"
          : createKnowledgeTask.isPending
            ? "正在创建知识抽取任务"
            : null;
  const batchReason = !selectedKnowledgeVersion
    ? "缺少知识版本"
    : !isReadyVersion(selectedKnowledgeVersion)
      ? "知识版本未就绪"
      : !selectedProfileVersion
        ? "缺少学情版本"
        : !isReadyProfileVersion(selectedProfileVersion)
          ? "学情版本未成功抽取"
          : !batchName.trim()
            ? "请输入批次名称"
            : courseCount <= 0
              ? "课次必须大于 0"
              : duration <= 0
                ? "课时分钟必须大于 0"
                : createBatch.isPending
                  ? "正在创建生成批次"
                  : null;

  function handleTextbookSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!uploadTextbookReason) {
      uploadTextbook.mutate();
    }
  }

  function handleProfileSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!uploadProfileReason) {
      uploadProfile.mutate();
    }
  }

  function handleBatchSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!batchReason) {
      createBatch.mutate();
    }
  }

  const stats = dashboardQuery.data?.stats ?? {};
  const statEntries = Object.entries(stats).slice(0, 4);

  if (projectId <= 0) {
    return <EmptyState title="项目地址无效" action={<Link className="btn btn-secondary" to="/">返回总览</Link>} />;
  }

  if (projectQuery.isLoading) {
    return (
      <div className="flex h-[60vh] items-center justify-center text-sm text-ink/55">
        <Loader2 className="mr-2 animate-spin" size={17} />
        加载中
      </div>
    );
  }

  if (projectQuery.error && !projectQuery.data) {
    return <ErrorNotice title="项目详情获取失败" message={getErrorMessage(projectQuery.error)} />;
  }

  if (!projectQuery.data) {
    return <EmptyState title="项目不存在" action={<Link className="btn btn-secondary" to="/">返回总览</Link>} />;
  }

  return (
    <div className="space-y-6">
      <section className="flex flex-col justify-between gap-4 xl:flex-row xl:items-end">
        <div>
          <Link className="mb-4 inline-flex items-center gap-2 text-sm font-semibold text-ink/55 hover:text-ink" to="/">
            <ChevronLeft size={16} />
            项目总览
          </Link>
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-3xl font-bold">{projectQuery.data.name}</h1>
            <StatusBadge status={projectQuery.data.status} />
          </div>
          <div className="mt-2 flex flex-wrap gap-2 text-sm text-ink/55">
            <span>{projectQuery.data.subject_code}</span>
            <span>/</span>
            <span>{projectQuery.data.grade_code}</span>
            <span>/</span>
            <span>{formatDate(projectQuery.data.updated_at)}</span>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          {statEntries.length ? (
            statEntries.map(([key, value]) => (
              <div className="min-w-28 rounded-lg border border-line bg-white px-4 py-3" key={key}>
                <div className="label">{key}</div>
                <div className="mt-1 text-xl font-bold">{String(value ?? "-")}</div>
              </div>
            ))
          ) : (
            <div className="min-w-28 rounded-lg border border-line bg-white px-4 py-3">
              <div className="label">任务数</div>
              <div className="mt-1 text-xl font-bold">{tasks.length}</div>
            </div>
          )}
          <button className="btn btn-secondary" disabled={tasksQuery.isFetching} onClick={invalidateWorkspace} type="button">
            <RefreshCw className={tasksQuery.isFetching ? "animate-spin" : ""} size={16} />
            刷新
          </button>
        </div>
      </section>

      <QueryError error={dashboardQuery.error} title="项目看板获取失败" />

      <div className="space-y-6">
        <WorkflowSection
          icon={BookOpen}
          iconTone="bg-accent/10 text-accent"
          title="教材上传与解析"
          subtitle={selectedTextbook?.textbook_name ?? "未选择教材版本"}
          status={selectedParseVersion?.review_status ?? selectedTextbook?.parse_status}
          task={parsingTask}
        >
          <QueryError error={textbooksQuery.error} title="教材列表获取失败" />
          <QueryError error={parseVersionsQuery.error} title="解析版本获取失败" />
          <form className="grid gap-3 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto]" onSubmit={handleTextbookSubmit}>
            <input className="field" placeholder="教材名称" value={textbookName} onChange={(event) => setTextbookName(event.target.value)} />
            <input
              className="file-field"
              type="file"
              accept="application/pdf,.pdf"
              onChange={(event) => setTextbookFile(event.target.files?.[0] ?? null)}
            />
            <button className="btn btn-primary" disabled={Boolean(uploadTextbookReason)} type="submit">
              {uploadTextbook.isPending ? <Loader2 className="animate-spin" size={17} /> : <Upload size={17} />}
              上传教材
            </button>
          </form>
          <ActionHint reason={uploadTextbookReason} />
          <UploadError error={uploadTextbook.error} title="教材上传失败" />

          <div className="grid gap-4 2xl:grid-cols-[280px_1fr]">
            <div className="space-y-3">
              <div className="label">教材版本</div>
              <SelectRow<TextbookVersion>
                items={textbooks}
                selectedId={selectedTextbookId}
                onChange={(id) => {
                  setSelectedTextbookId(id);
                  setSelectedParseVersionId(null);
                  setSelectedKnowledgeVersionId(null);
                }}
                renderLabel={(item) => `v${item.version_no} ${item.textbook_name}`}
              />
              <button
                className="btn btn-secondary w-full"
                disabled={Boolean(parseReason)}
                onClick={() => {
                  if (!parseReason) {
                    createParseTask.mutate();
                  }
                }}
                type="button"
              >
                {createParseTask.isPending ? <Loader2 className="animate-spin" size={17} /> : <Play size={17} />}
                发起解析
              </button>
              <ActionHint reason={parseReason} />
              <UploadError error={createParseTask.error} title="解析任务创建失败" />
            </div>
            <div className="space-y-3">
              <div className="flex items-center justify-between gap-3">
                <div className="label">解析版本</div>
                <button
                  className="btn btn-secondary h-8 px-3 text-xs"
                  disabled={Boolean(confirmParseReason)}
                  onClick={() => {
                    if (!confirmParseReason) {
                      confirmParseVersion.mutate();
                    }
                  }}
                  type="button"
                >
                  {confirmParseVersion.isPending ? <Loader2 className="animate-spin" size={14} /> : null}
                  确认解析
                </button>
              </div>
              <VersionList<ParseVersion>
                items={parseVersions}
                title="解析"
                selectedId={selectedParseVersionId}
                onSelect={(id) => {
                  setSelectedParseVersionId(id);
                  setSelectedKnowledgeVersionId(null);
                }}
                renderStatus={(item) => item.review_status || item.parse_status}
                renderMeta={(item) => `${item.strategy_code} / ${item.page_count ?? "-"} 页 / ${formatDate(item.updated_at)}`}
              />
              <ActionHint reason={confirmParseReason} />
              <UploadError error={confirmParseVersion.error} title="解析版本确认失败" />
            </div>
          </div>
          <ParseEvidencePanel
            parseVersion={selectedParseVersion}
            summary={parseEvidenceSummaryQuery.data}
            isLoading={parseEvidenceSummaryQuery.isLoading}
            error={parseEvidenceSummaryQuery.error}
          />
        </WorkflowSection>

        <WorkflowSection
          icon={FileText}
          iconTone="bg-coral/10 text-coral"
          title="学情上传与抽取"
          subtitle={selectedProfileVersion ? `学情版本 #${selectedProfileVersion.id}` : "未选择学情版本"}
          status={selectedProfileVersion?.extract_status}
          task={profileTask}
        >
          <QueryError error={learnerProfilesQuery.error} title="学情文件获取失败" />
          <QueryError error={profileVersionsQuery.error} title="学情版本获取失败" />
          <form className="grid gap-3 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto]" onSubmit={handleProfileSubmit}>
            <input className="field" placeholder="学情标题" value={profileTitle} onChange={(event) => setProfileTitle(event.target.value)} />
            <input
              className="file-field"
              type="file"
              accept=".doc,.docx,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
              onChange={(event) => setProfileFile(event.target.files?.[0] ?? null)}
            />
            <button className="btn btn-primary" disabled={Boolean(uploadProfileReason)} type="submit">
              {uploadProfile.isPending ? <Loader2 className="animate-spin" size={17} /> : <Upload size={17} />}
              上传学情
            </button>
          </form>
          <ActionHint reason={uploadProfileReason} />
          <UploadError error={uploadProfile.error} title="学情上传失败" />
          <div className="grid gap-4 2xl:grid-cols-[280px_1fr]">
            <div className="space-y-3">
              <div className="label">学情文件</div>
              <SelectRow
                items={learnerProfiles}
                selectedId={selectedProfileFileId}
                onChange={(id) => {
                  setSelectedProfileFileId(id);
                  setSelectedProfileVersionId(null);
                }}
                renderLabel={(item) => `${item.id} ${item.title}`}
              />
              <div className="rounded-md border border-line bg-paper/60 px-4 py-3 text-sm">
                <div className="text-xs font-semibold text-ink/45">当前文件状态</div>
                <div className="mt-2">
                  {learnerProfiles.find((item) => item.id === selectedProfileFileId)?.file_status ? (
                    <StatusBadge status={learnerProfiles.find((item) => item.id === selectedProfileFileId)?.file_status} />
                  ) : (
                    <span className="text-sm font-semibold text-ink/40">-</span>
                  )}
                </div>
              </div>
            </div>
            <div className="space-y-3">
              <div className="label">学情版本</div>
              <VersionList<LearnerProfileVersion>
                items={profileVersions}
                title="学情"
                selectedId={selectedProfileVersionId}
                onSelect={setSelectedProfileVersionId}
                renderStatus={(item) => item.extract_status || item.review_status}
                renderMeta={(item) => `${item.subject_scope ?? "-"} / ${formatDate(item.updated_at)}`}
              />
            </div>
          </div>
        </WorkflowSection>

        <WorkflowSection
          icon={Brain}
          iconTone="bg-leaf/10 text-leaf"
          title="知识抽取"
          subtitle={selectedKnowledgeVersion ? `${selectedKnowledgeVersion.point_count} 个知识点` : "未选择知识版本"}
          status={selectedKnowledgeVersion?.version_status}
          task={knowledgeTask}
        >
          <QueryError error={knowledgeVersionsQuery.error} title="知识版本获取失败" />
          <div className="grid gap-4 2xl:grid-cols-[280px_1fr]">
            <div className="space-y-3">
              <div className="rounded-md border border-line bg-paper/60 px-4 py-3 text-sm">
                <div className="label">输入解析版本</div>
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  <strong>{selectedParseVersion ? `#${selectedParseVersion.id}` : "-"}</strong>
                  {selectedParseVersion ? <StatusBadge status={selectedParseVersion.review_status ?? selectedParseVersion.parse_status} /> : null}
                </div>
              </div>
              <button
                className="btn btn-secondary w-full"
                disabled={Boolean(knowledgeReason)}
                onClick={() => {
                  if (!knowledgeReason) {
                    createKnowledgeTask.mutate();
                  }
                }}
                type="button"
              >
                {createKnowledgeTask.isPending ? <Loader2 className="animate-spin" size={17} /> : <Wand2 size={17} />}
                {knowledgeActionLabel}
              </button>
              <ActionHint reason={knowledgeReason} />
              <UploadError error={createKnowledgeTask.error} title="知识抽取任务创建失败" />
            </div>
            <div className="space-y-3">
              <div className="label">知识版本</div>
              <VersionList<KnowledgeVersion>
                items={knowledgeVersions}
                title="知识"
                selectedId={selectedKnowledgeVersionId}
                onSelect={setSelectedKnowledgeVersionId}
                renderStatus={(item) => item.version_status}
                renderMeta={(item) => `${item.chapter_count} 章 / ${item.point_count} 点 / ${formatDate(item.updated_at)}`}
              />
            </div>
          </div>
        </WorkflowSection>

        <WorkflowSection
          icon={ClipboardList}
          iconTone="bg-ink/10 text-ink"
          title="生成批次"
          subtitle={generationBatches.length ? `${generationBatches.length} 个批次` : "暂无批次"}
          status={generationBatches[0]?.batch_status}
          task={generationTask}
        >
          <QueryError error={generationBatchesQuery.error} title="生成批次获取失败" />
          <div className="grid gap-5 xl:grid-cols-[340px_1fr]">
            <form className="space-y-4" onSubmit={handleBatchSubmit}>
              <div className="rounded-md border border-line bg-paper/60 p-4">
                <div className="label">基线状态</div>
                <div className="mt-4 space-y-3">
                  <BaselineRow
                    label="知识版本"
                    value={selectedKnowledgeVersion ? `#${selectedKnowledgeVersion.id}` : null}
                    status={selectedKnowledgeVersion?.version_status}
                    ready={isReadyVersion(selectedKnowledgeVersion)}
                  />
                  <BaselineRow
                    label="学情版本"
                    value={selectedProfileVersion ? `#${selectedProfileVersion.id}` : null}
                    status={selectedProfileVersion?.extract_status}
                    ready={isReadyProfileVersion(selectedProfileVersion)}
                  />
                </div>
              </div>
              <label className="block">
                <span className="label">批次名称</span>
                <input className="field mt-2" value={batchName} onChange={(event) => setBatchName(event.target.value)} />
              </label>
              <div className="grid grid-cols-2 gap-3">
                <label className="block">
                  <span className="label">课次</span>
                  <input
                    className="field mt-2"
                    min={1}
                    type="number"
                    value={courseCount}
                    onChange={(event) => setCourseCount(Number(event.target.value))}
                  />
                </label>
                <label className="block">
                  <span className="label">分钟</span>
                  <input className="field mt-2" min={1} type="number" value={duration} onChange={(event) => setDuration(Number(event.target.value))} />
                </label>
              </div>
              <button className="btn btn-primary w-full" disabled={Boolean(batchReason)} type="submit">
                {createBatch.isPending ? <Loader2 className="animate-spin" size={17} /> : <Play size={17} />}
                创建批次
              </button>
              <ActionHint reason={batchReason} />
              <UploadError error={createBatch.error} title="生成批次创建失败" />
            </form>

            {generationBatches.length ? (
              <div className="divide-y divide-line rounded-md border border-line">
                {generationBatches.map((batch) => (
                  <Link
                    className="flex flex-col gap-3 bg-white px-4 py-3 transition hover:bg-paper md:flex-row md:items-center md:justify-between"
                    key={batch.id}
                    to={`/projects/${projectId}/batches/${batch.id}`}
                  >
                    <div className="min-w-0">
                      <div className="truncate text-sm font-bold">{batch.batch_name ?? `批次 #${batch.batch_no}`}</div>
                      <div className="mt-1 text-xs text-ink/50">
                        {batch.course_count ?? "-"} 课次 / {batch.session_duration_minutes ?? "-"} 分钟 / {formatDate(batch.updated_at)}
                      </div>
                    </div>
                    <div className="flex items-center gap-3">
                      <StatusBadge status={batch.batch_status} />
                      <ArrowRight className="text-ink/35" size={16} />
                    </div>
                  </Link>
                ))}
              </div>
            ) : (
              <EmptyState title="暂无生成批次" />
            )}
          </div>
        </WorkflowSection>
      </div>

      <section className="panel overflow-hidden">
        <div className="panel-header">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-md bg-gold/10 text-gold">
              <Layers size={20} />
            </div>
            <div>
              <h2 className="text-lg font-bold">任务中心</h2>
              <div className="text-sm text-ink/55">{tasks.length} 条记录</div>
            </div>
          </div>
          <button className="btn btn-secondary" disabled={tasksQuery.isFetching} onClick={() => tasksQuery.refetch()} type="button">
            <RefreshCw className={tasksQuery.isFetching ? "animate-spin" : ""} size={16} />
            刷新
          </button>
        </div>
        <QueryError error={tasksQuery.error} title="任务列表获取失败" />
        {tasks.length ? (
          <TaskTable tasks={tasks} />
        ) : (
          <div className="p-5">
            <EmptyState title="暂无任务" />
          </div>
        )}
      </section>
    </div>
  );
}
