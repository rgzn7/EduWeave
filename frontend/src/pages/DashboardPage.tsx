import { FormEvent, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, CheckCircle2, FileText, Loader2, UploadCloud } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import { EmptyState } from "../components/EmptyState";
import { ErrorNotice } from "../components/ErrorNotice";
import { api } from "../lib/api";
import { cn, formatDate } from "../utils";
import type { Project } from "../types";

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

function getCaseStatus(project: Project) {
  if (project.latest_generation_batch_id) {
    return "已完成";
  }
  if (project.current_textbook_version_id && project.current_learner_profile_version_id) {
    return "生成中";
  }
  if (project.current_textbook_version_id || project.current_learner_profile_version_id) {
    return "待补充";
  }
  return "未开始";
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

function LessonPrepComposer({
  textbookFile,
  profileFile,
  isPending,
  onTextbookChange,
  onProfileChange,
}: {
  textbookFile: File | null;
  profileFile: File | null;
  isPending: boolean;
  onTextbookChange: (file: File | null) => void;
  onProfileChange: (file: File | null) => void;
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
        <div className="mx-3 flex border-t border-line/75 py-4 md:justify-end">
          <button className="btn btn-primary h-12 w-full shrink-0 rounded-full px-6 md:w-auto" disabled={isPending} type="submit">
            {isPending ? <Loader2 className="animate-spin" size={17} /> : <ArrowRight size={17} />}
            {isPending ? "正在生成" : "开始生成"}
          </button>
        </div>
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

function CaseCard({ project }: { project: Project }) {
  const status = getCaseStatus(project);

  return (
    <Link className="group block rounded-[20px] border border-line bg-white/88 p-4 shadow-panel transition hover:-translate-y-0.5 hover:border-ink/20 hover:bg-white" to={`/projects/${project.id}`}>
      <div className="flex items-start gap-3">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[#f2f2f2] text-ink/72">
          <FileText size={18} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-3">
            <h3 className="line-clamp-2 text-sm font-semibold leading-5 text-ink">{project.name}</h3>
            <CaseStatusPill label={status} />
          </div>
          <div className="mt-3 flex flex-wrap gap-1.5 text-xs font-medium text-ink/45">
            <span>{subjectLabels[project.subject_code] ?? project.subject_code}</span>
            <span>/</span>
            <span>{gradeLabels[project.grade_code] ?? project.grade_code}</span>
          </div>
          <div className="mt-5 flex items-center justify-between border-t border-line/70 pt-3 text-xs">
            <span className="text-ink/38">{formatDate(project.last_activity_at ?? project.updated_at)}</span>
            <span className="inline-flex items-center gap-1 font-semibold text-ink/72">
              查看过程
              <ArrowRight className="transition group-hover:translate-x-0.5" size={14} />
            </span>
          </div>
        </div>
      </div>
    </Link>
  );
}

function getVisibleCases(projects: Project[]) {
  if (projects.length >= 3) {
    return projects.slice(0, 3);
  }
  if (!projects.length) {
    return [];
  }

  const cases = [...projects];
  while (cases.length < 3) {
    cases.push(projects[0]);
  }
  return cases;
}

export function DashboardPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [textbookFile, setTextbookFile] = useState<File | null>(null);
  const [profileFile, setProfileFile] = useState<File | null>(null);

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
      queryClient.invalidateQueries({ queryKey: ["projects"] });
      navigate(`/projects/${project.id}`);
    },
  });

  const projects = projectsQuery.data?.items ?? [];
  const visibleCases = getVisibleCases(projects);

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

  return (
    <div className="mx-auto flex min-h-screen w-full max-w-7xl flex-col pb-16 pt-24 md:pt-32">
      <section className="mx-auto w-full max-w-[760px]">
        <div className="text-center">
          <h1 className="font-serif text-[42px] font-medium leading-tight tracking-normal text-ink md:text-[56px]">上传材料，生成备课资源</h1>
        </div>

        <form className="mt-8" onSubmit={handleSubmit}>
          <LessonPrepComposer
            isPending={startLessonPrep.isPending}
            profileFile={profileFile}
            textbookFile={textbookFile}
            onProfileChange={setProfileFile}
            onTextbookChange={handleTextbookChange}
          />
          {startLessonPrep.error ? <ErrorNotice title="暂时无法开始生成" message="请确认材料格式正确，或稍后再试。" /> : null}
        </form>
      </section>

      <section className="mx-auto mt-24 w-full max-w-5xl space-y-5" id="cases">
        <div>
          <h2 className="text-base font-semibold text-ink/82">示例备课</h2>
          <p className="mt-2 text-sm text-ink/42">打开已有记录，查看从材料到成果的完整处理过程。</p>
        </div>

        <div className="grid gap-3 md:grid-cols-3">
          {projectsQuery.isLoading ? (
            <div className="panel col-span-full flex h-28 items-center justify-center text-sm text-ink/50">
              <Loader2 className="mr-2 animate-spin" size={17} />
              正在加载
            </div>
          ) : visibleCases.length ? (
            visibleCases.map((project, index) => <CaseCard key={`${project.id}-${index}`} project={project} />)
          ) : (
            <div className="col-span-full">
              <EmptyState title="暂无示例备课" description="上传教材和学情后，可以在这里回到已有记录。" />
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
