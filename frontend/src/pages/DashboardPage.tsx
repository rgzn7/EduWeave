import { FormEvent, useState } from "react";
import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, CheckCircle2, FileText, Loader2, Minus, Plus, UploadCloud } from "lucide-react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { EmptyState } from "../components/EmptyState";
import { ErrorNotice } from "../components/ErrorNotice";
import {
  COURSE_COUNT_MAX,
  COURSE_COUNT_MIN,
  DEFAULT_COURSE_COUNT,
  DEFAULT_SESSION_DURATION_MINUTES,
  SESSION_DURATION_MINUTES_MAX,
  SESSION_DURATION_MINUTES_MIN,
  markAutoCoreGeneration,
} from "../lib/autoCoreGeneration";
import { api } from "../lib/api";
import { cn, formatDate } from "../utils";
import type { GenerationBatch, Project } from "../types";

type ProjectCaseState = "completed" | "processing" | "failed" | "ready_to_generate" | "incomplete";

type ProjectCase = {
  project: Project;
  state: ProjectCaseState;
  statusLabel: string;
  actionLabel: string;
  href: string;
};

const gradeNameMap: Array<[string, string]> = [
  ["一年级", "grade_1"],
  ["二年级", "grade_2"],
  ["三年级", "grade_3"],
  ["四年级", "grade_4"],
  ["五年级", "grade_5"],
  ["六年级", "grade_6"],
  ["七年级", "grade_7"],
  ["八年级", "grade_8"],
  ["九年级", "grade_9"],
  ["1年级", "grade_1"],
  ["2年级", "grade_2"],
  ["3年级", "grade_3"],
  ["4年级", "grade_4"],
  ["5年级", "grade_5"],
  ["6年级", "grade_6"],
  ["7年级", "grade_7"],
  ["8年级", "grade_8"],
  ["9年级", "grade_9"],
];

const subjectLabels: Record<string, string> = {
  math: "数学",
  chinese: "语文",
  english: "英语",
  science: "科学",
};

const gradeLabels: Record<string, string> = {
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

function stripExtension(filename: string) {
  return filename.replace(/\.[^.]+$/u, "").trim();
}

function inferSubjectCode(filename: string) {
  if (filename.includes("语文")) {
    return "chinese";
  }
  if (filename.includes("英语")) {
    return "english";
  }
  if (filename.includes("科学")) {
    return "science";
  }
  return "math";
}

function inferGradeCode(filename: string) {
  const matched = gradeNameMap.find(([keyword]) => filename.includes(keyword));
  return matched?.[1] ?? "grade_3";
}

function clampNumber(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

function getCaseState(project: Project, batch?: GenerationBatch, hasBatchError?: boolean): ProjectCaseState {
  if (project.latest_generation_batch_id) {
    const batchStatus = String(batch?.batch_status ?? "").toLowerCase();
    if (batchStatus === "success") {
      return "completed";
    }
    if (hasBatchError || ["failure", "failed", "error"].includes(batchStatus)) {
      return "failed";
    }
    return "processing";
  }
  if (project.current_textbook_version_id && project.current_learner_profile_version_id) {
    return "ready_to_generate";
  }
  return "incomplete";
}

function getCaseStatusLabel(project: Project, state: ProjectCaseState) {
  if (state === "completed") {
    return "已完成";
  }
  if (state === "processing") {
    return "生成中";
  }
  if (state === "failed") {
    return "需要处理";
  }
  if (state === "ready_to_generate") {
    return "待生成";
  }
  if (project.current_textbook_version_id || project.current_learner_profile_version_id) {
    return "待补充";
  }
  return "未开始";
}

function getCaseActionLabel(project: Project, state: ProjectCaseState) {
  if (state === "completed") {
    return "查看资源";
  }
  if (state === "processing" || state === "ready_to_generate") {
    return "继续生成";
  }
  if (state === "failed") {
    return "需要处理";
  }
  if (project.current_textbook_version_id || project.current_learner_profile_version_id) {
    return "继续补充";
  }
  return "等待处理";
}

function getCaseLink(project: Project, state: ProjectCaseState) {
  if (state === "completed" && project.latest_generation_batch_id) {
    return `/projects/${project.id}/batches/${project.latest_generation_batch_id}`;
  }
  return `/projects/${project.id}`;
}

function buildProjectCase(project: Project, batch?: GenerationBatch, hasBatchError?: boolean): ProjectCase {
  const state = getCaseState(project, batch, hasBatchError);
  return {
    project,
    state,
    statusLabel: getCaseStatusLabel(project, state),
    actionLabel: getCaseActionLabel(project, state),
    href: getCaseLink(project, state),
  };
}

function getProjectTime(project: Project) {
  return new Date(project.last_activity_at ?? project.updated_at).getTime();
}

function getRecentPriority(item: ProjectCase) {
  if (item.state === "processing") {
    return 0;
  }
  if (item.state === "ready_to_generate") {
    return 1;
  }
  if (item.state === "failed") {
    return 2;
  }
  if (item.state === "incomplete") {
    return 3;
  }
  return 4;
}

function sortRecentCases(items: ProjectCase[]) {
  return [...items].sort((left, right) => {
    const priorityDiff = getRecentPriority(left) - getRecentPriority(right);
    if (priorityDiff !== 0) {
      return priorityDiff;
    }
    return getProjectTime(right.project) - getProjectTime(left.project);
  });
}

function ComposerMaterialRow({
  step,
  title,
  description,
  accept,
  file,
  disabled,
  onChange,
  actionLabel,
}: {
  step: 1 | 2;
  title: string;
  description: string;
  accept: string;
  file: File | null;
  disabled?: boolean;
  onChange: (file: File | null) => void;
  actionLabel: string;
}) {
  return (
    <div className={cn("flex flex-col gap-4 px-3 py-5 transition md:flex-row md:items-center md:justify-between", disabled && "opacity-45")}>
      <div className="flex min-w-0 gap-4">
        <div className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-[#f3f3f3] text-sm font-semibold text-ink/58">{step}</div>
        <div className="min-w-0">
          <h2 className="text-base font-semibold text-ink">{title}</h2>
          <p className="mt-1 text-sm leading-6 text-ink/52">{description}</p>
          {file ? (
            <div className="mt-3 flex min-w-0 items-center gap-2 text-sm font-medium text-ink">
              <CheckCircle2 className="shrink-0" size={16} />
              <span className="truncate">{file.name}</span>
            </div>
          ) : null}
        </div>
      </div>

      <label
        className={cn(
          "inline-flex h-11 shrink-0 items-center justify-center gap-2 rounded-full border border-line bg-white px-5 text-sm font-semibold text-ink transition",
          disabled ? "cursor-not-allowed" : "cursor-pointer hover:border-ink/25 hover:bg-[#f7f7f7]",
        )}
        aria-disabled={disabled}
      >
        <input
          className="sr-only"
          type="file"
          accept={accept}
          disabled={disabled}
          onChange={(event) => onChange(event.target.files?.[0] ?? null)}
        />
        <UploadCloud size={16} />
        {file ? "更换" : actionLabel}
      </label>
    </div>
  );
}

function GenerationSettingStepper({
  label,
  value,
  min,
  max,
  step,
  unit,
  disabled,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  unit: string;
  disabled?: boolean;
  onChange: (value: number) => void;
}) {
  const decrease = () => onChange(clampNumber(value - step, min, max));
  const increase = () => onChange(clampNumber(value + step, min, max));

  return (
    <div className="flex shrink-0 items-center gap-2 whitespace-nowrap">
      <span className="text-sm font-semibold text-ink">{label}</span>
      <div className="inline-flex h-10 items-center rounded-full border border-line bg-white text-sm font-semibold text-ink shadow-[0_1px_0_rgba(0,0,0,0.03)]">
        <button
          aria-label={`${label}减少`}
          className="flex h-full w-9 items-center justify-center rounded-l-full text-ink/70 transition hover:bg-[#f7f7f7] disabled:cursor-not-allowed disabled:text-ink/20 disabled:hover:bg-transparent"
          disabled={disabled || value <= min}
          type="button"
          onClick={decrease}
        >
          <Minus size={15} />
        </button>
        <span className="flex h-full min-w-10 items-center justify-center border-x border-line/70 px-2 text-center tabular-nums">{value}</span>
        <button
          aria-label={`${label}增加`}
          className="flex h-full w-9 items-center justify-center rounded-r-full text-ink/70 transition hover:bg-[#f7f7f7] disabled:cursor-not-allowed disabled:text-ink/20 disabled:hover:bg-transparent"
          disabled={disabled || value >= max}
          type="button"
          onClick={increase}
        >
          <Plus size={15} />
        </button>
      </div>
      <span className="text-sm font-medium text-ink/62">{unit}</span>
    </div>
  );
}

function LessonPrepComposer({
  textbookFile,
  profileFile,
  courseCount,
  sessionDurationMinutes,
  isPending,
  onTextbookChange,
  onProfileChange,
  onCourseCountChange,
  onSessionDurationMinutesChange,
}: {
  textbookFile: File | null;
  profileFile: File | null;
  courseCount: number;
  sessionDurationMinutes: number;
  isPending: boolean;
  onTextbookChange: (file: File | null) => void;
  onProfileChange: (file: File | null) => void;
  onCourseCountChange: (value: number) => void;
  onSessionDurationMinutesChange: (value: number) => void;
}) {
  return (
    <div className="rounded-[28px] border border-line bg-white px-4 py-2 shadow-panel">
      <ComposerMaterialRow
        accept="application/pdf,.pdf"
        actionLabel="选择教材"
        description="基于教材生成课程方案、教案、PPT 课件和配套测练。"
        file={textbookFile}
        step={1}
        title="上传教材 PDF"
        onChange={onTextbookChange}
      />
      <div className="mx-3 border-t border-line/75" />
      <ComposerMaterialRow
        accept=".doc,.docx,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        actionLabel="选择学情"
        description="根据学生基础、薄弱点和课时安排，调整讲解重点和练习难度。"
        disabled={!textbookFile}
        file={profileFile}
        step={2}
        title="补充学情分析 DOCX"
        onChange={onProfileChange}
      />
      {textbookFile && profileFile ? (
        <>
          <div className="mx-3 border-t border-line/75" />
          <div className="grid gap-4 px-3 py-5 lg:grid-cols-[auto_minmax(0,1fr)_auto] lg:items-center lg:gap-8">
            <div className="flex shrink-0 items-center gap-4">
              <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-[#f3f3f3] text-sm font-semibold text-ink/58">3</div>
              <h2 className="text-base font-semibold text-ink">生成设置</h2>
            </div>

            <div className="flex min-w-0 flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center lg:justify-start lg:gap-5 xl:flex-nowrap">
              <GenerationSettingStepper
                disabled={isPending}
                label="课次"
                max={COURSE_COUNT_MAX}
                min={COURSE_COUNT_MIN}
                step={1}
                unit="课"
                value={courseCount}
                onChange={onCourseCountChange}
              />
              <GenerationSettingStepper
                disabled={isPending}
                label="课时"
                max={SESSION_DURATION_MINUTES_MAX}
                min={SESSION_DURATION_MINUTES_MIN}
                step={5}
                unit="分钟"
                value={sessionDurationMinutes}
                onChange={onSessionDurationMinutesChange}
              />
            </div>

            <button className="btn btn-primary h-11 w-full shrink-0 rounded-full px-5 lg:w-auto" disabled={isPending} type="submit">
              {isPending ? <Loader2 className="animate-spin" size={17} /> : <ArrowRight size={17} />}
              {isPending ? "正在生成" : "开始生成"}
            </button>
          </div>
        </>
      ) : null}
    </div>
  );
}

function CaseStatusPill({ label }: { label: string }) {
  const isDone = label === "已完成";
  return (
    <span className={isDone ? "rounded-full bg-ink px-2.5 py-1 text-xs font-semibold text-white" : "rounded-full bg-[#f2f2f2] px-2.5 py-1 text-xs font-semibold text-ink/58"}>
      {label}
    </span>
  );
}

function CaseCard({ item }: { item: ProjectCase }) {
  return (
    <Link className="group block rounded-[20px] border border-line bg-white/88 p-4 shadow-panel transition hover:-translate-y-0.5 hover:border-ink/20 hover:bg-white" to={item.href}>
      <div className="flex items-start gap-3">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[#f2f2f2] text-ink/72">
          <FileText size={18} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-3">
            <h3 className="line-clamp-2 text-sm font-semibold leading-5 text-ink">{item.project.name}</h3>
            <CaseStatusPill label={item.statusLabel} />
          </div>
          <div className="mt-3 flex flex-wrap gap-1.5 text-xs font-medium text-ink/45">
            <span>{subjectLabels[item.project.subject_code] ?? item.project.subject_code}</span>
            <span>/</span>
            <span>{gradeLabels[item.project.grade_code] ?? item.project.grade_code}</span>
          </div>
          <div className="mt-5 flex items-center justify-between border-t border-line/70 pt-3 text-xs">
            <span className="text-ink/38">{formatDate(item.project.last_activity_at ?? item.project.updated_at)}</span>
            <span className="inline-flex items-center gap-1 font-semibold text-ink/72">
              {item.actionLabel}
              <ArrowRight className="transition group-hover:translate-x-0.5" size={14} />
            </span>
          </div>
        </div>
      </div>
    </Link>
  );
}

export function DashboardPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const queryClient = useQueryClient();
  const [textbookFile, setTextbookFile] = useState<File | null>(null);
  const [profileFile, setProfileFile] = useState<File | null>(null);
  const [courseCount, setCourseCount] = useState(DEFAULT_COURSE_COUNT);
  const [sessionDurationMinutes, setSessionDurationMinutes] = useState(DEFAULT_SESSION_DURATION_MINUTES);
  const isHistoryPage = location.pathname === "/history";

  const projectsQuery = useQuery({
    queryKey: ["projects"],
    queryFn: () => api.listProjects({ page: 1, page_size: 50 }),
  });

  const startLessonPrep = useMutation({
    mutationFn: async () => {
      if (!textbookFile || !profileFile) {
        throw new Error("MATERIAL_REQUIRED");
      }
      const textbookName = stripExtension(textbookFile.name);
      const project = await api.createProject({
        name: textbookName || "AI 备课",
        subject_code: inferSubjectCode(textbookFile.name),
        grade_code: inferGradeCode(textbookFile.name),
        applicable_target: "基于教材与学情生成个性化教学资源",
      });
      await api.uploadTextbook(project.id, {
        file: textbookFile,
        textbook_name: textbookName || textbookFile.name,
        set_as_current: true,
      });
      await api.uploadLearnerProfile(project.id, {
        file: profileFile,
        title: stripExtension(profileFile.name) || profileFile.name,
        auto_extract: true,
        set_as_current: true,
      });
      return project;
    },
    onSuccess: (project) => {
      markAutoCoreGeneration(project.id, { courseCount, sessionDurationMinutes });
      queryClient.invalidateQueries({ queryKey: ["projects"] });
      navigate(`/projects/${project.id}`);
    },
  });

  const projects = projectsQuery.data?.items ?? [];
  const batchQueries = useQueries({
    queries: projects.map((project) => ({
      queryKey: ["generation-batch", project.latest_generation_batch_id, "dashboard-card"],
      queryFn: () => api.getGenerationBatch(project.latest_generation_batch_id!),
      enabled: Boolean(project.latest_generation_batch_id),
      retry: false,
    })),
  });
  const projectCases = projects.map((project, index) => {
    const batchQuery = batchQueries[index];
    return buildProjectCase(project, batchQuery?.data as GenerationBatch | undefined, batchQuery?.isError);
  });
  const sortedCases = sortRecentCases(projectCases);
  const visibleCases = isHistoryPage ? sortedCases : sortedCases.slice(0, 3);

  function handleTextbookChange(file: File | null) {
    setTextbookFile(file);
    if (!file) {
      setProfileFile(null);
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (textbookFile && profileFile) {
      startLessonPrep.mutate();
    }
  }

  if (isHistoryPage) {
    return (
      <div className="mx-auto min-h-screen w-full max-w-5xl pb-16 pt-20 md:pt-28">
        <section className="space-y-5">
          <div>
            <h1 className="text-3xl font-semibold tracking-[-0.03em] text-ink md:text-4xl">备课记录</h1>
            <p className="mt-3 text-sm text-ink/45">查看所有备课，包括正在生成、待处理和已完成的记录。</p>
          </div>

          <div className="grid gap-3 md:grid-cols-3">
            {projectsQuery.isLoading ? (
              <div className="panel col-span-full flex h-28 items-center justify-center text-sm text-ink/50">
                <Loader2 className="mr-2 animate-spin" size={17} />
                正在加载
              </div>
            ) : visibleCases.length ? (
              visibleCases.map((item) => <CaseCard item={item} key={item.project.id} />)
            ) : (
              <div className="col-span-full">
                <EmptyState title="暂无备课记录" description="上传教材和学情后，备课记录会显示在这里。" />
              </div>
            )}
          </div>
        </section>
      </div>
    );
  }

  return (
    <div className="mx-auto flex min-h-screen w-full max-w-7xl flex-col pb-16 pt-24 md:pt-32">
      <section className="mx-auto w-full max-w-[900px]">
        <div className="text-center">
          <h1 className="font-serif text-[42px] font-medium leading-tight tracking-normal text-ink md:text-[56px]">上传材料，生成备课资源</h1>
        </div>

        <form className="mt-8" onSubmit={handleSubmit}>
          <LessonPrepComposer
            courseCount={courseCount}
            isPending={startLessonPrep.isPending}
            profileFile={profileFile}
            sessionDurationMinutes={sessionDurationMinutes}
            textbookFile={textbookFile}
            onCourseCountChange={setCourseCount}
            onProfileChange={setProfileFile}
            onSessionDurationMinutesChange={setSessionDurationMinutes}
            onTextbookChange={handleTextbookChange}
          />
          {startLessonPrep.error ? <ErrorNotice title="暂时无法开始生成" message="请确认材料格式正确，或稍后再试。" /> : null}
        </form>
      </section>

      <section className="mx-auto mt-24 w-full max-w-5xl space-y-5" id="recent">
        <div className="flex items-end justify-between gap-4">
          <div>
            <h2 className="text-base font-semibold text-ink/82">最近备课</h2>
            <p className="mt-2 text-sm text-ink/42">继续未完成的备课，或快速打开最近生成好的资源。</p>
          </div>
          <Link className="shrink-0 text-sm font-semibold text-ink/58 transition hover:text-ink" to="/history">
            查看更多
          </Link>
        </div>

        <div className="grid gap-3 md:grid-cols-3">
          {projectsQuery.isLoading ? (
            <div className="panel col-span-full flex h-28 items-center justify-center text-sm text-ink/50">
              <Loader2 className="mr-2 animate-spin" size={17} />
              正在加载
            </div>
          ) : visibleCases.length ? (
            visibleCases.map((item) => <CaseCard item={item} key={item.project.id} />)
          ) : (
            <div className="col-span-full">
              <EmptyState title="暂无备课记录" description="上传教材和学情后，最近备课会显示在这里。" />
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
