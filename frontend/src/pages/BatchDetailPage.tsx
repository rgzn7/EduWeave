import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  BarChart3,
  BookOpen,
  ClipboardCheck,
  Download,
  FileText,
  Loader2,
  Presentation,
  RefreshCw,
  Sparkles,
} from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { isTaskActiveStatus } from "../hooks/useTaskPolling";
import { api } from "../lib/api";
import { useAssistantStore } from "../stores/assistant";
import type { CoursewareResult, GenerationBatch, HomeworkResult, JsonRecord, LearnerProfileFile, LessonPlan, PaperResult, Task, TextbookVersion } from "../types";
import { cn, toNumberId } from "../utils";
import { asRecord, asRecordList, formatLessonTitle, latestByUpdated, sortLessons } from "./batch-detail/helpers";

const assessmentScenes = [
  {
    scene_type: "final_exam",
  },
] as const;

type AssessmentSceneType = (typeof assessmentScenes)[number]["scene_type"];
type TextSection = {
  title: string;
  items: string[];
};

function isSuccessfulStatus(status?: string | null) {
  return ["success", "ready", "available", "confirmed"].includes(String(status ?? "").toLowerCase());
}

function isFailedStatus(status?: string | null) {
  return ["failed", "failure", "error"].includes(String(status ?? "").toLowerCase());
}

function cleanText(value: unknown) {
  const text = String(value ?? "").trim();
  if (!text || text === "-") {
    return "";
  }
  return text;
}

function numberValue(value: unknown) {
  if (typeof value === "number" && Number.isFinite(value) && value > 0) {
    return value;
  }
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
  }
  return null;
}

function fileObjectIdFrom(source: unknown, fallback?: number | null) {
  const record = asRecord(source);
  return numberValue(record?.id) ?? numberValue(record?.file_object_id) ?? numberValue(fallback);
}

function fileNameFrom(source: unknown, fallback?: string | null) {
  const record = asRecord(source);
  const candidates = [record?.original_filename, record?.filename, record?.file_name, record?.name, fallback];
  return candidates.map(cleanText).find(Boolean) ?? "已上传文件";
}

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

function extractPublisherLabel(value?: string | null) {
  return cleanText(value).match(/([\u4e00-\u9fa5A-Za-z0-9·（）()]+出版社)/u)?.[1] ?? "";
}

function textbookInfo(textbook?: TextbookVersion) {
  if (!textbook) {
    return "教材信息同步中";
  }
  const subject = subjectLabels[textbook.subject_code] ?? textbook.subject_code;
  const grade = gradeLabels[textbook.grade_code] ?? textbook.grade_code;
  const publisher = cleanText(asRecord(textbook)?.publisher) || extractPublisherLabel(textbook.textbook_name);
  return [publisher, `${subject} / ${grade}`].filter(Boolean).join(" · ");
}

function collectText(value: unknown, limit = 8): string[] {
  const items: string[] = [];

  function visit(entry: unknown) {
    if (items.length >= limit || entry === undefined || entry === null || entry === "") {
      return;
    }
    if (typeof entry === "string" || typeof entry === "number" || typeof entry === "boolean") {
      const text = cleanText(entry);
      if (text && !items.includes(text)) {
        items.push(text);
      }
      return;
    }
    if (Array.isArray(entry)) {
      entry.forEach(visit);
      return;
    }
    if (typeof entry === "object") {
      Object.values(entry as JsonRecord).forEach(visit);
    }
  }

  visit(value);
  return items;
}

const teachingDetailTerminalPunctuation = /[。！？!?；;]$/u;

function joinTeachingDetails(details: string[]) {
  const items = details.map(cleanText).filter(Boolean);

  return items
    .map((item, index) => {
      if (teachingDetailTerminalPunctuation.test(item)) {
        return item;
      }
      return `${item}${index === items.length - 1 ? "。" : "；"}`;
    })
    .join("");
}

function pickText(content: JsonRecord | null, keys: string[], limit = 6) {
  for (const key of keys) {
    const items = collectText(content?.[key], limit);
    if (items.length) {
      return items;
    }
  }
  return [];
}

function getTeachingSteps(content: JsonRecord | null) {
  const direct = asRecordList(content?.teaching_flow);
  const sessionSteps = asRecordList(content?.session_plans).flatMap((session) => asRecordList(session.teaching_steps));
  const steps = direct.length ? direct : sessionSteps;

  return steps.slice(0, 5).map((step, index) => {
    const title =
      cleanText(step.stage_name) ||
      cleanText(step.title) ||
      cleanText(step.name) ||
      cleanText(step.step_name) ||
      `教学环节 ${index + 1}`;
    const details = collectText(
      [step.teacher_actions, step.student_activities, step.activities, step.description, step.content],
      4,
    );
    return {
      title,
      details,
    };
  });
}

function buildLessonSections(lesson?: LessonPlan): TextSection[] {
  const content = asRecord(lesson?.content_json);
  const summary = cleanText(lesson?.summary_text);
  const courseOverview = asRecord(content?.course_overview);
  const afterClassPlan = asRecord(content?.after_class_plan);
  const sessionPlans = asRecordList(content?.session_plans);

  // 教案 schema 的教学目标位于 session_plans[].objectives，顶层无 objectives；保留顶层兼容键与 summary 兜底
  const directObjectives = pickText(content, ["teaching_objectives", "objectives", "lesson_objectives", "learning_objectives"], 5);
  const sessionObjectives = collectText(
    sessionPlans.flatMap((session) => collectText(session.objectives, 5)),
    5,
  );
  const objectives = directObjectives.length
    ? directObjectives
    : sessionObjectives.length
      ? sessionObjectives
      : collectText(courseOverview?.objectives, 5);
  // 重点难点：顶层 core_knowledge + 各课次 teaching_focus + 难点，去重后展示
  const focus = Array.from(
    new Set([
      ...pickText(content, ["key_points", "teaching_focus", "core_knowledge", "important_points"], 4),
      ...collectText(
        sessionPlans.flatMap((session) => collectText(session.teaching_focus, 3)),
        3,
      ),
      ...pickText(content, ["difficult_points", "learning_difficulties"], 3),
    ]),
  );
  const homework = [
    ...collectText(afterClassPlan, 5),
    ...collectText(sessionPlans.flatMap((session) => collectText(session.homework, 3)), 5),
    ...pickText(content, ["homework", "after_class_tasks"], 4),
  ];

  return [
    {
      title: "教学目标",
      items: objectives.length ? objectives : summary ? [summary] : [],
    },
    {
      title: "重点难点",
      items: focus,
    },
    {
      title: "课后安排",
      items: homework,
    },
  ];
}

function getTaskAssessmentScene(task: Task): AssessmentSceneType | null {
  const payloadScene = task.payload_json?.scene_type;
  if (assessmentScenes.some((scene) => scene.scene_type === payloadScene)) {
    return payloadScene as AssessmentSceneType;
  }
  const legacy = asRecord(task.payload_json?.assessment_strategy_json);
  if (assessmentScenes.some((scene) => scene.scene_type === legacy?.scene_type)) {
    return legacy?.scene_type as AssessmentSceneType;
  }
  const matched = assessmentScenes.find((scene) => task.biz_key?.endsWith(`:assessment:${scene.scene_type}`));
  return matched?.scene_type ?? null;
}

function latestTask(tasks: Task[], moduleCode: string) {
  return latestByUpdated(
    tasks.filter((task) => task.module_code === moduleCode || task.task_type.includes(moduleCode)),
  );
}

function getCoursewareTask(tasks: Task[], lessonId?: number | null) {
  if (!lessonId) {
    return undefined;
  }
  return latestByUpdated(
    tasks.filter((task) => {
      const payloadLessonId = Number(task.payload_json?.lesson_plan_id);
      return (
        (task.module_code === "courseware" || task.task_type.includes("courseware")) &&
        (payloadLessonId === lessonId || task.biz_key?.includes(`lesson_plan:${lessonId}:courseware`))
      );
    }),
  );
}

function getHomeworkTask(tasks: Task[], lessonId?: number | null) {
  if (!lessonId) {
    return undefined;
  }
  return latestByUpdated(
    tasks.filter((task) => {
      const payloadLessonId = Number(task.payload_json?.lesson_plan_id);
      return (
        (task.module_code === "homework" || task.task_type.includes("homework")) &&
        (payloadLessonId === lessonId || task.biz_key?.includes(`lesson_plan:${lessonId}:homework`))
      );
    }),
  );
}

function ResourceBadge({ children }: { children: string }) {
  return (
    <span className="inline-flex h-7 items-center rounded-full bg-[#f2f2f2] px-3 text-xs font-semibold text-ink/62">
      {children}
    </span>
  );
}

function LessonStatusChip({
  children,
  tone = "muted",
  active,
}: {
  children: string;
  tone?: "muted" | "blue" | "success" | "danger";
  active?: boolean;
}) {
  return (
    <span
      className={cn(
        "inline-flex h-8 items-center gap-1.5 rounded-full px-3 text-xs font-semibold",
        tone === "blue" && "bg-blue-50 text-blue-600",
        tone === "success" && "bg-emerald-50 text-emerald-700",
        tone === "danger" && "bg-red-50 text-red-600",
        tone === "muted" && "bg-[#f2f2f2] text-ink/58",
      )}
    >
      {children}
      {active ? <Loader2 className="animate-spin" size={13} /> : null}
    </span>
  );
}

function ResourcePanel({
  title,
  children,
  scroll,
  className,
}: {
  title?: string;
  children: ReactNode;
  scroll?: boolean;
  className?: string;
}) {
  return (
    <section className={cn("flex min-h-0 flex-col rounded-[22px] border border-line bg-white shadow-panel", className)}>
      {title ? <h2 className="shrink-0 border-b border-line px-6 py-5 text-lg font-semibold text-ink">{title}</h2> : null}
      <div className={cn("min-h-0 p-6", scroll && "overflow-y-auto")}>{children}</div>
    </section>
  );
}

function FriendlyNotice({ title, description }: { title: string; description?: string }) {
  return (
    <div className="rounded-2xl border border-dashed border-line bg-[#fafafa] px-5 py-8 text-center">
      <div className="text-sm font-semibold text-ink/72">{title}</div>
      {description ? <p className="mx-auto mt-2 max-w-xl text-sm leading-6 text-ink/45">{description}</p> : null}
    </div>
  );
}

function PageLoading({ text }: { text: string }) {
  return (
    <div className="flex h-[60vh] items-center justify-center text-sm font-medium text-ink/55">
      <Loader2 className="mr-2 animate-spin" size={18} />
      {text}
    </div>
  );
}

const sectionNumerals = ["一", "二", "三", "四", "五", "六"];

function LessonList({
  lessons,
  selectedLessonId,
  coursewareResults,
  homeworkResults,
  onSelectLesson,
}: {
  lessons: LessonPlan[];
  selectedLessonId: number | null;
  coursewareResults: CoursewareResult[];
  homeworkResults: HomeworkResult[];
  onSelectLesson: (lessonId: number) => void;
}) {
  if (!lessons.length) {
    return <FriendlyNotice title="教案正在准备" description="课程方案完成后，这里会显示每一课的教案。" />;
  }

  return (
    <div className="space-y-3">
      {lessons.map((lesson) => {
        const hasPpt = coursewareResults.some((item) => item.lesson_plan_id === lesson.id && item.export_file_id);
        const hasHomework = homeworkResults.some((item) => item.lesson_plan_id === lesson.id && isSuccessfulStatus(item.result_status));
        const selected = selectedLessonId === lesson.id;
        return (
          <button
            className={cn(
              "w-full rounded-2xl border bg-white px-4 py-4 text-left transition hover:border-ink/24 hover:bg-[#fafafa]",
              selected ? "border-ink shadow-panel" : "border-line",
            )}
            key={lesson.id}
            onClick={() => onSelectLesson(lesson.id)}
            type="button"
          >
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="text-xs font-semibold text-ink/45">第 {lesson.class_session_no ?? "-"} 课</div>
                <div className="mt-1 line-clamp-2 text-sm font-semibold leading-5 text-ink">{formatLessonTitle(lesson.lesson_title)}</div>
              </div>
              <div className="flex shrink-0 flex-col gap-1">
                {hasPpt ? <ResourceBadge>PPT</ResourceBadge> : null}
                {hasHomework ? <ResourceBadge>作业</ResourceBadge> : null}
              </div>
            </div>
          </button>
        );
      })}
    </div>
  );
}

function LessonPreview({ lesson, loading }: { lesson?: LessonPlan; loading: boolean }) {
  const content = asRecord(lesson?.content_json);
  const steps = getTeachingSteps(content);
  const sections = buildLessonSections(lesson);

  if (loading) {
    return <PageLoading text="正在读取教案" />;
  }

  if (!lesson) {
    return <FriendlyNotice title="请选择一课" description="选择左侧课次后，可以预览本课教案。" />;
  }

  return (
    <div>
      <h3 className="text-lg font-semibold text-ink">教案预览</h3>
      <div className="mt-6 divide-y divide-line">
        {sections.map((section, index) => (
          <section className="py-5 first:pt-0 last:pb-0" key={section.title}>
            <h4 className="text-base font-semibold text-ink">
              {sectionNumerals[index] ?? index + 1}、{section.title}
            </h4>
            {section.items.length ? (
              <div className="mt-4 space-y-3 text-sm leading-7 text-ink/68">
                {section.items.slice(0, 5).map((item, index) => (
                  <p key={`${section.title}-${item}-${index}`}>{item}</p>
                ))}
              </div>
            ) : (
              <div className="mt-3 text-sm text-ink/38">等待内容同步</div>
            )}
          </section>
        ))}
      </div>

      <section className="mt-6 border-t border-line pt-5">
        <h4 className="text-base font-semibold text-ink">
          {sectionNumerals[sections.length] ?? sections.length + 1}、教学流程
        </h4>
        {steps.length ? (
          <div className="mt-4 space-y-4">
            {steps.map((step, index) => (
              <div className="grid gap-3 border-t border-line pt-4 first:border-t-0 first:pt-0 md:grid-cols-[96px_1fr]" key={`${step.title}-${index}`}>
                <div className="text-sm font-semibold text-ink/45">环节 {index + 1}</div>
                <div>
                  <div className="font-semibold text-ink">{step.title}</div>
                  {step.details.length ? (
                    <p className="mt-2 text-sm leading-6 text-ink/58">{joinTeachingDetails(step.details)}</p>
                  ) : null}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="mt-3 text-sm text-ink/42">教学流程正在同步。</div>
        )}
      </section>
    </div>
  );
}

export function BatchDetailPage() {
  const projectId = toNumberId(useParams().projectId);
  const batchId = toNumberId(useParams().batchId);
  const queryClient = useQueryClient();
  const [selectedLessonId, setSelectedLessonId] = useState<number | null>(null);
  // 记住最后一次有效选中的课次序号；列表刷新（如 Agent 新建版本换了 id）后据此按课次保持选中
  const lastSelectedSessionRef = useRef<number | null>(null);
  const [lessonDownloadId, setLessonDownloadId] = useState<number | null>(null);
  const [homeworkDownloadId, setHomeworkDownloadId] = useState<number | null>(null);
  const [paperDownloadId, setPaperDownloadId] = useState<number | null>(null);

  const batchQuery = useQuery({
    queryKey: ["generation-batch", batchId],
    queryFn: () => api.getGenerationBatch(batchId),
    enabled: batchId > 0,
    refetchInterval: (query) => {
      const batch = query.state.data as GenerationBatch | undefined;
      return isTaskActiveStatus(batch?.batch_status) || (batch?.tasks ?? []).some((task) => isTaskActiveStatus(task.task_status)) ? 5_000 : false;
    },
  });

  const batch = batchQuery.data;
  const tasks = useMemo(() => batch?.tasks ?? [], [batch?.tasks]);

  const projectQuery = useQuery({
    queryKey: ["project", projectId],
    queryFn: () => api.getProject(projectId),
    enabled: projectId > 0,
  });

  const textbooksQuery = useQuery({
    queryKey: ["textbooks", projectId, "batch-detail"],
    queryFn: () => api.listTextbooks(projectId),
    enabled: projectId > 0,
  });

  const learnerProfilesQuery = useQuery({
    queryKey: ["learner-profiles", projectId, "batch-detail"],
    queryFn: () => api.listLearnerProfiles(projectId),
    enabled: projectId > 0,
  });

  const textbookMaterial = useMemo(() => {
    const items = textbooksQuery.data?.items ?? [];
    return (
      items.find((item) => item.id === projectQuery.data?.current_textbook_version_id) ??
      items.find((item) => item.is_current) ??
      latestByUpdated(items)
    );
  }, [projectQuery.data?.current_textbook_version_id, textbooksQuery.data?.items]);

  const learnerProfileMaterial = useMemo(() => {
    const items = learnerProfilesQuery.data?.items ?? [];
    return (
      items.find((item) => item.latest_version?.id === projectQuery.data?.current_learner_profile_version_id) ??
      latestByUpdated(items)
    );
  }, [learnerProfilesQuery.data?.items, projectQuery.data?.current_learner_profile_version_id]);

  const curriculumQuery = useQuery({
    queryKey: ["curriculum-plan", batch?.curriculum_plan_id],
    queryFn: () => api.getCurriculumPlan(batch!.curriculum_plan_id!),
    enabled: Boolean(batch?.curriculum_plan_id),
  });

  const lessonPlansQuery = useQuery({
    queryKey: ["lesson-plans", batch?.id, batch?.curriculum_plan_id],
    queryFn: () => api.listLessonPlans(batch!.curriculum_plan_id!, { page: 1, page_size: 100 }),
    enabled: Boolean(batch?.id && batch?.curriculum_plan_id),
  });

  const lessonPlans = useMemo(() => {
    const items = lessonPlansQuery.data?.items ?? [];
    // 纳入本批次教案与 Agent 新建版本（脱离批次，generation_batch_id 为空）；每课次取最新 ready 版本
    const relevant = items.filter(
      (lesson) => lesson.generation_batch_id === batch?.id || lesson.generation_batch_id == null,
    );
    const latestBySession = new Map<number, LessonPlan>();
    for (const lesson of relevant) {
      const key = lesson.class_session_no ?? -1;
      const existing = latestBySession.get(key);
      if (!existing) {
        latestBySession.set(key, lesson);
        continue;
      }
      const lessonReady = lesson.version_status === "ready";
      const existingReady = existing.version_status === "ready";
      if (lessonReady !== existingReady) {
        if (lessonReady) latestBySession.set(key, lesson);
        continue;
      }
      if ((lesson.version_no ?? 0) > (existing.version_no ?? 0)) {
        latestBySession.set(key, lesson);
      }
    }
    return sortLessons(Array.from(latestBySession.values()));
  }, [batch?.id, lessonPlansQuery.data?.items]);

  useEffect(() => {
    if (!lessonPlans.length) {
      setSelectedLessonId(null);
      return;
    }
    // 当前选中仍有效则保持不动
    if (selectedLessonId && lessonPlans.some((lesson) => lesson.id === selectedLessonId)) {
      return;
    }
    // 选中失效（如 Agent 新建版本换了 id）：优先按上次课次序号找回对应的新版本，避免回退到第一课
    const bySession =
      lastSelectedSessionRef.current != null
        ? lessonPlans.find((lesson) => lesson.class_session_no === lastSelectedSessionRef.current)
        : undefined;
    const preferred =
      bySession ??
      lessonPlans.find((lesson) => lesson.id === batch?.lesson_plan_id) ??
      lessonPlans.find((lesson) => lesson.class_session_no === 1) ??
      lessonPlans[0];
    setSelectedLessonId(preferred.id);
  }, [batch?.lesson_plan_id, lessonPlans, selectedLessonId]);

  const selectedLesson = useMemo(
    () => lessonPlans.find((lesson) => lesson.id === selectedLessonId),
    [lessonPlans, selectedLessonId],
  );

  // 选中有效时持续记录课次序号；失效后不更新，从而保留失效前的课次用于按课次找回
  useEffect(() => {
    if (selectedLesson?.class_session_no != null) {
      lastSelectedSessionRef.current = selectedLesson.class_session_no;
    }
  }, [selectedLesson?.class_session_no]);

  // 向智能助手发布「所在课次教案」上下文，贯穿本页 run；离开本页时清空回到单页形态
  const setAssistantContext = useAssistantStore((state) => state.setContext);
  const clearAssistantContext = useAssistantStore((state) => state.clearContext);
  useEffect(() => {
    if (!batch?.curriculum_plan_id) return;
    setAssistantContext({
      project_id: projectId || undefined,
      curriculum_plan_id: batch.curriculum_plan_id ?? undefined,
      class_session_no: selectedLesson?.class_session_no ?? undefined,
      lesson_plan_id: selectedLesson?.id ?? undefined,
      labels: {
        projectName: projectQuery.data?.name,
        curriculumTitle: curriculumQuery.data?.plan_title,
        lessonTitle: selectedLesson?.lesson_title,
      },
    });
  }, [
    projectId,
    batch?.curriculum_plan_id,
    selectedLesson?.id,
    selectedLesson?.class_session_no,
    selectedLesson?.lesson_title,
    projectQuery.data?.name,
    curriculumQuery.data?.plan_title,
    setAssistantContext,
  ]);
  useEffect(() => () => clearAssistantContext(), [clearAssistantContext]);

  const lessonDetailQuery = useQuery({
    queryKey: ["lesson-plan", selectedLessonId],
    queryFn: () => api.getLessonPlan(selectedLessonId!),
    enabled: Boolean(selectedLessonId),
  });

  const coursewareResultsQuery = useQuery({
    queryKey: ["courseware-results", batch?.id],
    queryFn: () => api.listCoursewareResults(batch!.id, { page: 1, page_size: 100 }),
    enabled: Boolean(batch?.id),
    refetchInterval: (query) => {
      const hasActive = (query.state.data?.items ?? []).some((item) => isTaskActiveStatus(item.result_status));
      return hasActive ? 5_000 : false;
    },
  });

  const coursewareResults = useMemo(
    () => [...(coursewareResultsQuery.data?.items ?? [])].sort((a, b) => b.id - a.id),
    [coursewareResultsQuery.data?.items],
  );

  const selectedCoursewareResult = useMemo(() => {
    if (!selectedLessonId) {
      return undefined;
    }
    return coursewareResults.find((result) => result.lesson_plan_id === selectedLessonId);
  }, [coursewareResults, selectedLessonId]);

  const selectedCoursewareTask = useMemo(() => getCoursewareTask(tasks, selectedLessonId), [selectedLessonId, tasks]);

  const selectedHomeworkTask = useMemo(() => getHomeworkTask(tasks, selectedLessonId), [selectedLessonId, tasks]);

  const homeworkResultsQuery = useQuery({
    queryKey: ["homework-results", batch?.id],
    queryFn: () => api.listHomeworkResults({ generation_batch_id: batch!.id, page: 1, page_size: 100 }),
    enabled: Boolean(batch?.id),
    refetchInterval: isTaskActiveStatus(selectedHomeworkTask?.task_status) ? 5_000 : false,
  });

  const homeworkResults = useMemo(
    () => [...(homeworkResultsQuery.data?.items ?? [])].sort((a, b) => b.id - a.id),
    [homeworkResultsQuery.data?.items],
  );

  const selectedHomeworkResult = useMemo(() => {
    if (!selectedLessonId) {
      return undefined;
    }
    return homeworkResults.find((result) => result.lesson_plan_id === selectedLessonId);
  }, [homeworkResults, selectedLessonId]);

  const assessmentTasksByScene = useMemo(() => {
    return Object.fromEntries(
      assessmentScenes.map((scene) => [
        scene.scene_type,
        latestByUpdated(
          tasks.filter((task) => {
            if (!(task.module_code === "assessment" || task.task_type.includes("assessment"))) {
              return false;
            }
            return getTaskAssessmentScene(task) === scene.scene_type;
          }),
        ),
      ]),
    ) as Record<AssessmentSceneType, Task | undefined>;
  }, [tasks]);

  const paperResultQueries = useQueries({
    queries: assessmentScenes.map((scene) => ({
      queryKey: ["paper-results", batch?.id, scene.scene_type],
      queryFn: () =>
        api.listPaperResults(batch!.id, {
          scene_type: scene.scene_type,
          page: 1,
          page_size: 100,
        }),
      enabled: Boolean(batch?.id),
      refetchInterval: isTaskActiveStatus(assessmentTasksByScene[scene.scene_type]?.task_status) ? 5_000 : false,
    })),
  });

  const paperResultsByScene = useMemo(() => {
    return Object.fromEntries(
      assessmentScenes.map((scene, index) => [
        scene.scene_type,
        [...(paperResultQueries[index]?.data?.items ?? [])].sort((a, b) => b.id - a.id),
      ]),
    ) as Record<AssessmentSceneType, PaperResult[]>;
  }, [paperResultQueries]);

  const coverageTask = useMemo(() => latestTask(tasks, "coverage"), [tasks]);
  const coverageReportsQuery = useQuery({
    queryKey: ["coverage-reports", batch?.id],
    queryFn: () => api.listCoverageReports(batch!.id, { page: 1, page_size: 100 }),
    enabled: Boolean(batch?.id),
    refetchInterval: isTaskActiveStatus(coverageTask?.task_status) ? 5_000 : false,
  });

  const coverageReport = useMemo(() => {
    return [...(coverageReportsQuery.data?.items ?? [])].sort((a, b) => b.id - a.id)[0];
  }, [coverageReportsQuery.data?.items]);

  const createCourseware = useMutation({
    mutationFn: () => {
      if (!selectedLesson) {
        throw new Error("请选择一课教案");
      }
      return api.createCoursewareTask(selectedLesson.id);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["generation-batch", batchId] });
      queryClient.invalidateQueries({ queryKey: ["courseware-results", batch?.id] });
    },
  });

  const retryCourseware = useMutation({
    mutationFn: () => {
      if (!selectedCoursewareResult) {
        throw new Error("请选择需要重试的 PPT 结果");
      }
      return api.regenerateCoursewareResult(selectedCoursewareResult.id);
    },
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ["generation-batch", batchId] });
      queryClient.invalidateQueries({ queryKey: ["courseware-results", batch?.id] });
      queryClient.invalidateQueries({ queryKey: ["courseware-result", result.id] });
    },
  });

  const createHomework = useMutation({
    mutationFn: () => {
      if (!selectedLesson) {
        throw new Error("请选择一课教案");
      }
      return api.createHomeworkTask(selectedLesson.id);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["generation-batch", batchId] });
      queryClient.invalidateQueries({ queryKey: ["homework-results", batch?.id] });
      queryClient.invalidateQueries({ queryKey: ["coverage-reports", batch?.id] });
    },
  });

  const downloadLesson = useMutation({
    mutationFn: async (lesson: LessonPlan) => {
      setLessonDownloadId(lesson.id);
      const result = lesson.export_file_id ? await api.getFileDownloadUrl(lesson.export_file_id) : await api.exportLessonPlanDocx(lesson.id);
      if (!result.signed_url) {
        throw new Error("下载地址暂未准备好");
      }
      return result.signed_url;
    },
    onSuccess: (url, lesson) => {
      queryClient.invalidateQueries({ queryKey: ["lesson-plan", lesson.id] });
      window.open(url, "_blank", "noopener,noreferrer");
    },
    onSettled: () => setLessonDownloadId(null),
  });

  const downloadHomework = useMutation({
    mutationFn: async (homework: HomeworkResult) => {
      setHomeworkDownloadId(homework.id);
      const result = homework.export_file_id ? await api.getFileDownloadUrl(homework.export_file_id) : await api.exportHomeworkResultDocx(homework.id);
      if (!result.signed_url) {
        throw new Error("下载地址暂未准备好");
      }
      return result.signed_url;
    },
    onSuccess: (url, homework) => {
      queryClient.invalidateQueries({ queryKey: ["homework-result", homework.id] });
      queryClient.invalidateQueries({ queryKey: ["homework-results", batch?.id] });
      window.open(url, "_blank", "noopener,noreferrer");
    },
    onSettled: () => setHomeworkDownloadId(null),
  });

  const downloadCurriculum = useMutation({
    mutationFn: async () => {
      const plan = curriculumQuery.data;
      if (!plan) {
        throw new Error("课程总纲暂未准备好");
      }
      const result = plan.export_file_id ? await api.getFileDownloadUrl(plan.export_file_id) : await api.exportCurriculumPlanDocx(plan.id);
      if (!result.signed_url) {
        throw new Error("下载地址暂未准备好");
      }
      return result.signed_url;
    },
    onSuccess: (url) => {
      queryClient.invalidateQueries({ queryKey: ["curriculum-plan", batch?.curriculum_plan_id] });
      window.open(url, "_blank", "noopener,noreferrer");
    },
  });

  const downloadPpt = useMutation({
    mutationFn: async () => {
      if (!selectedCoursewareResult?.export_file_id) {
        throw new Error("PPT 暂未准备好");
      }
      const result = await api.getFileDownloadUrl(selectedCoursewareResult.export_file_id);
      if (!result.signed_url) {
        throw new Error("下载地址暂未准备好");
      }
      return result.signed_url;
    },
    onSuccess: (url) => window.open(url, "_blank", "noopener,noreferrer"),
  });

  const createAssessment = useMutation({
    mutationFn: (sceneType: AssessmentSceneType) =>
      api.createAssessmentTask(batch!.curriculum_plan_id!, {
        scene_type: sceneType,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["generation-batch", batchId] });
      queryClient.invalidateQueries({ queryKey: ["paper-results", batch?.id] });
      queryClient.invalidateQueries({ queryKey: ["question-items", batch?.id] });
    },
  });

  const downloadPaper = useMutation({
    mutationFn: async (paper: PaperResult) => {
      setPaperDownloadId(paper.id);
      const result = paper.export_file_id ? await api.getFileDownloadUrl(paper.export_file_id) : await api.exportPaperResultDocx(paper.id);
      if (!result.signed_url) {
        throw new Error("下载地址暂未准备好");
      }
      return result.signed_url;
    },
    onSuccess: (url, paper) => {
      queryClient.invalidateQueries({ queryKey: ["paper-result", paper.id] });
      window.open(url, "_blank", "noopener,noreferrer");
    },
    onSettled: () => setPaperDownloadId(null),
  });

  const openMaterialFile = useMutation({
    mutationFn: async ({ fileObjectId }: { fileObjectId: number; kind: "textbook" | "profile" }) => {
      const result = await api.getFileDownloadUrl(fileObjectId);
      if (!result.signed_url) {
        throw new Error("材料打开地址暂未准备好");
      }
      return result.signed_url;
    },
    onSuccess: (url) => window.open(url, "_blank", "noopener,noreferrer"),
  });

  if (projectId <= 0 || batchId <= 0) {
    return <FriendlyNotice title="备课资源地址无效" description="请从备课记录重新打开。" />;
  }

  if (batchQuery.isLoading && !batch) {
    return <PageLoading text="正在打开备课资源" />;
  }

  if (!batch) {
    return <FriendlyNotice title="暂时无法打开备课资源" description="请稍后刷新，或从备课记录重新进入。" />;
  }

  const lessonForPreview = lessonDetailQuery.data ?? selectedLesson;
  const coursewareActive = isTaskActiveStatus(selectedCoursewareTask?.task_status) || isTaskActiveStatus(selectedCoursewareResult?.result_status);
  const coursewareFailed = isFailedStatus(selectedCoursewareResult?.result_status) || isFailedStatus(selectedCoursewareTask?.task_status);
  const canDownloadPpt = Boolean(selectedCoursewareResult?.export_file_id);
  const hasCoursewareResult = Boolean(selectedCoursewareResult);
  const homeworkActive = isTaskActiveStatus(selectedHomeworkTask?.task_status) || isTaskActiveStatus(selectedHomeworkResult?.result_status);
  const homeworkFailed = isFailedStatus(selectedHomeworkTask?.task_status) || isFailedStatus(selectedHomeworkResult?.result_status);
  const hasHomework = Boolean(selectedHomeworkResult && isSuccessfulStatus(selectedHomeworkResult.result_status));
  const homeworkStatusUnavailable = homeworkResultsQuery.isError;
  const finalExamPaper = paperResultsByScene.final_exam?.[0];
  const finalExamTask = assessmentTasksByScene.final_exam;
  const finalExamActive = isTaskActiveStatus(finalExamTask?.task_status) || isTaskActiveStatus(finalExamPaper?.result_status);
  const finalExamFailed = isFailedStatus(finalExamTask?.task_status) || isFailedStatus(finalExamPaper?.result_status);
  const hasFinalExam = Boolean(finalExamPaper && isSuccessfulStatus(finalExamPaper.result_status));
  const hasCoverageReport = Boolean(coverageReport && isSuccessfulStatus(coverageReport.report_status));
  const lessonCount = lessonPlans.length || batch.course_count;
  const courseOutlineMeta = [
    lessonCount ? `共 ${lessonCount} 课` : "课次数待同步",
    batch.session_duration_minutes ? `每课 ${batch.session_duration_minutes} 分钟` : null,
  ]
    .filter(Boolean)
    .join("，");
  const textbookFileObjectId = fileObjectIdFrom(textbookMaterial?.source_file);
  const textbookMaterialInfo = textbookInfo(textbookMaterial);
  const learnerProfileMaterialInfo = learnerProfileMaterial
    ? cleanText(learnerProfileMaterial.title) || fileNameFrom(learnerProfileMaterial.source_file, "学生学情记录")
    : "学情材料同步中";
  const learnerProfileVersionId = batch.learner_profile_version_id;
  const coursewareGenerating = coursewareActive || createCourseware.isPending || retryCourseware.isPending;
  const homeworkGenerating = homeworkActive || createHomework.isPending;
  const coursewareStatusLabel = canDownloadPpt ? "PPT 已生成" : coursewareGenerating ? "PPT 生成中" : coursewareFailed ? "PPT 需重试" : "PPT 待生成";
  const homeworkStatusLabel = hasHomework ? "作业已生成" : homeworkGenerating ? "作业生成中" : homeworkFailed ? "作业需重试" : "作业待生成";
  const coursewareStatusTone: "muted" | "blue" | "success" | "danger" = canDownloadPpt
    ? "success"
    : coursewareGenerating
      ? "blue"
      : coursewareFailed
        ? "danger"
        : "muted";
  const homeworkStatusTone: "muted" | "blue" | "success" | "danger" = hasHomework
    ? "success"
    : homeworkGenerating
      ? "blue"
      : homeworkFailed
        ? "danger"
        : "muted";

  return (
    <div className="mx-auto w-full max-w-[1540px] space-y-6 px-2 pb-10 pt-6 text-ink">
      <section className="grid gap-6 xl:h-[calc(100vh-230px)] xl:min-h-[560px] xl:grid-cols-[310px_minmax(0,1fr)]">
        <ResourcePanel title="课次" scroll>
          <LessonList
            lessons={lessonPlans}
            selectedLessonId={selectedLessonId}
            coursewareResults={coursewareResults}
            homeworkResults={homeworkResults}
            onSelectLesson={setSelectedLessonId}
          />
        </ResourcePanel>

        <section className="flex min-h-0 flex-col rounded-[22px] border border-line bg-white shadow-panel">
          <div className="shrink-0 border-b border-line px-7 py-6">
            <div className="text-sm font-semibold text-ink/45">第 {lessonForPreview?.class_session_no ?? "-"} 课</div>
            <div className="mt-2 flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
              <h2 className="text-3xl font-semibold leading-tight text-ink">{lessonForPreview ? formatLessonTitle(lessonForPreview.lesson_title) : "请选择一课"}</h2>
              <div className="flex shrink-0 flex-wrap items-center gap-2">
                <LessonStatusChip active={homeworkGenerating} tone={homeworkStatusTone}>
                  {homeworkStatusLabel}
                </LessonStatusChip>
                <LessonStatusChip active={coursewareGenerating} tone={coursewareStatusTone}>
                  {coursewareStatusLabel}
                </LessonStatusChip>
              </div>
            </div>
            {lessonForPreview?.summary_text ? <p className="mt-4 max-w-4xl text-sm leading-7 text-ink/64">{lessonForPreview.summary_text}</p> : null}
          </div>

          <div className="grid min-h-0 flex-1 xl:grid-cols-[minmax(0,1fr)_330px]">
            <div className="min-h-0 overflow-y-auto px-7 py-6">
              <LessonPreview lesson={lessonForPreview} loading={lessonDetailQuery.isLoading} />
            </div>

            <aside className="min-h-0 overflow-y-auto border-t border-line px-7 py-6 xl:border-l xl:border-t-0">
              <div>
                <h3 className="text-lg font-semibold text-ink">本课资源</h3>
              </div>

              <div className="mt-6 divide-y divide-line">
                <div className="pb-6">
                  <div className="flex items-center gap-3">
                    <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[#f6f6f6]">
                      <FileText size={19} />
                    </div>
                    <div className="min-w-0">
                      <div className="font-semibold text-ink">教案 DOCX</div>
                    </div>
                  </div>
                  <button
                    className="btn btn-secondary mt-4 w-full rounded-full"
                    disabled={!lessonForPreview || lessonDownloadId === lessonForPreview.id}
                    onClick={() => lessonForPreview && downloadLesson.mutate(lessonForPreview)}
                    type="button"
                  >
                    <Download size={16} />
                    {lessonForPreview && lessonDownloadId === lessonForPreview.id ? "准备下载" : "下载教案"}
                  </button>
                </div>

                <div className="py-6">
                  <div className="flex items-center gap-3">
                    <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[#f6f6f6]">
                      <Presentation size={19} />
                    </div>
                    <div className="min-w-0">
                      <div className="font-semibold text-ink">PPT 课件</div>
                    </div>
                  </div>
                  {canDownloadPpt ? (
                    <button className="btn btn-primary mt-4 w-full rounded-full" disabled={downloadPpt.isPending} onClick={() => downloadPpt.mutate()} type="button">
                      <Download size={16} />
                      {downloadPpt.isPending ? "准备下载" : "下载 PPT"}
                    </button>
                  ) : coursewareGenerating ? (
                    <button className="btn btn-secondary mt-4 w-full rounded-full" disabled type="button">
                      <Loader2 className="animate-spin" size={16} />
                      PPT 生成中
                    </button>
                  ) : coursewareFailed ? (
                    <button
                      className="btn btn-primary mt-4 w-full rounded-full"
                      disabled={!selectedCoursewareResult || retryCourseware.isPending}
                      onClick={() => retryCourseware.mutate()}
                      type="button"
                    >
                      {retryCourseware.isPending ? <Loader2 className="animate-spin" size={16} /> : <RefreshCw size={16} />}
                      重试 PPT
                    </button>
                  ) : hasCoursewareResult ? (
                    <button className="btn btn-secondary mt-4 w-full rounded-full" disabled type="button">
                      PPT 状态同步中
                    </button>
                  ) : (
                    <button
                      className="btn btn-primary mt-4 w-full rounded-full"
                      disabled={!selectedLesson || createCourseware.isPending}
                      onClick={() => createCourseware.mutate()}
                      type="button"
                    >
                      {createCourseware.isPending ? <Loader2 className="animate-spin" size={16} /> : <Sparkles size={16} />}
                      生成这一课 PPT
                    </button>
                  )}
                </div>

                <div className="pt-6">
                  <div className="flex items-center gap-3">
                    <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[#f6f6f6]">
                      <ClipboardCheck size={19} />
                    </div>
                    <div className="min-w-0">
                      <div className="font-semibold text-ink">课后作业</div>
                    </div>
                  </div>
                  {homeworkStatusUnavailable ? (
                    <button className="btn btn-secondary mt-4 w-full rounded-full" disabled type="button">
                      作业状态同步中
                    </button>
                  ) : hasHomework && selectedHomeworkResult ? (
                    <div className="mt-4 grid gap-2">
                      <Link className="btn btn-secondary rounded-full" to={`/projects/${projectId}/batches/${batchId}/homework/${selectedHomeworkResult.id}`}>
                        查看题目
                      </Link>
                      <button
                        className="btn btn-secondary rounded-full"
                        disabled={homeworkDownloadId === selectedHomeworkResult.id}
                        onClick={() => downloadHomework.mutate(selectedHomeworkResult)}
                        type="button"
                      >
                        <Download size={16} />
                        {homeworkDownloadId === selectedHomeworkResult.id ? "准备下载" : "下载 DOCX"}
                      </button>
                    </div>
                  ) : (
                    <button
                      className="btn btn-primary mt-4 w-full rounded-full"
                      disabled={!selectedLesson || homeworkGenerating}
                      onClick={() => createHomework.mutate()}
                      type="button"
                    >
                      {homeworkGenerating ? <Loader2 className="animate-spin" size={16} /> : <Sparkles size={16} />}
                      {homeworkActive ? "生成中" : homeworkFailed ? "重新生成" : "生成这一课作业"}
                    </button>
                  )}
                </div>
              </div>

              {(downloadLesson.error || downloadPpt.error || createCourseware.error || retryCourseware.error || createHomework.error || downloadHomework.error) ? (
                <div className="mt-5">
                  <FriendlyNotice title="操作暂时没有完成" description="请稍后再试，页面会继续同步资源状态。" />
                </div>
              ) : null}
            </aside>
          </div>
        </section>
      </section>

      <ResourcePanel>
        <div className="flex flex-col gap-3 border-b border-line pb-5 md:flex-row md:items-end md:justify-between">
          <h2 className="text-2xl font-semibold tracking-normal text-ink">整套资源</h2>
        </div>

        <div className="hidden grid-cols-[minmax(220px,1.05fr)_minmax(250px,1.25fr)_minmax(240px,1fr)_minmax(180px,auto)] gap-6 border-b border-line py-4 text-sm font-semibold text-ink/45 xl:grid">
          <div>资源</div>
          <div>内容说明</div>
          <div>相关信息</div>
          <div className="text-center">操作</div>
        </div>

        <div className="divide-y divide-line">
          <div className="grid gap-4 py-5 xl:grid-cols-[minmax(220px,1.05fr)_minmax(250px,1.25fr)_minmax(240px,1fr)_minmax(180px,auto)] xl:items-center xl:gap-6">
            <div className="flex min-w-0 items-center gap-4">
              <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-[#f3f3f3] text-ink">
                <BookOpen size={21} />
              </div>
              <div className="min-w-0">
                <h3 className="text-lg font-semibold text-ink">课程总纲</h3>
              </div>
            </div>
            <p className="text-sm leading-6 text-ink/58">整套课程安排、教学目标与课时规划。</p>
            <div className="text-sm font-medium text-ink/58">{courseOutlineMeta}</div>
            <div className="flex xl:justify-center">
              <button
                className="btn btn-secondary min-w-[152px] rounded-full px-5"
                disabled={!curriculumQuery.data || downloadCurriculum.isPending}
                onClick={() => downloadCurriculum.mutate()}
                type="button"
              >
                <Download size={16} />
                {downloadCurriculum.isPending ? "准备下载" : "下载总纲"}
              </button>
            </div>
          </div>

          <div className="grid gap-4 py-5 xl:grid-cols-[minmax(220px,1.05fr)_minmax(250px,1.25fr)_minmax(240px,1fr)_minmax(180px,auto)] xl:items-center xl:gap-6">
            <div className="flex min-w-0 items-center gap-4">
              <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-[#f3f3f3] text-ink">
                <ClipboardCheck size={21} />
              </div>
              <div className="min-w-0">
                <h3 className="text-lg font-semibold text-ink">期末综合测</h3>
              </div>
            </div>
            <p className="text-sm leading-6 text-ink/58">覆盖整套课程重点内容。</p>
            <div className="text-sm font-medium text-ink/58">{hasFinalExam ? "综合测评" : "等待生成"}</div>
            <div className="flex xl:justify-center">
              {hasFinalExam && finalExamPaper ? (
                <button
                  className="btn btn-secondary min-w-[152px] rounded-full px-5"
                  disabled={paperDownloadId === finalExamPaper.id}
                  onClick={() => downloadPaper.mutate(finalExamPaper)}
                  type="button"
                >
                  <Download size={16} />
                  {paperDownloadId === finalExamPaper.id ? "准备下载" : "下载 DOCX"}
                </button>
              ) : (
                <button
                  className="btn btn-secondary min-w-[152px] rounded-full px-5"
                  disabled={!batch.curriculum_plan_id || finalExamActive || createAssessment.isPending}
                  onClick={() => createAssessment.mutate("final_exam")}
                  type="button"
                >
                  {finalExamActive || createAssessment.isPending ? <Loader2 className="animate-spin" size={16} /> : <Sparkles size={16} />}
                  {finalExamActive ? "生成中" : finalExamFailed ? "重新生成" : "生成试卷"}
                </button>
              )}
            </div>
          </div>

          <div className="grid gap-4 py-5 xl:grid-cols-[minmax(220px,1.05fr)_minmax(250px,1.25fr)_minmax(240px,1fr)_minmax(180px,auto)] xl:items-center xl:gap-6">
            <div className="flex min-w-0 items-center gap-4">
              <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-[#f3f3f3] text-ink">
                <FileText size={21} />
              </div>
              <div className="min-w-0">
                <h3 className="text-lg font-semibold text-ink">教材 PDF</h3>
              </div>
            </div>
            <p className="text-sm leading-6 text-ink/58">本次备课使用的教材。</p>
            <div className="min-w-0 truncate text-sm font-medium text-ink/58">{textbookMaterialInfo}</div>
            <div className="flex xl:justify-center">
              <button
                className="btn btn-secondary min-w-[152px] rounded-full px-5"
                disabled={!textbookFileObjectId || (openMaterialFile.isPending && openMaterialFile.variables?.kind === "textbook")}
                onClick={() => textbookFileObjectId && openMaterialFile.mutate({ fileObjectId: textbookFileObjectId, kind: "textbook" })}
                type="button"
              >
                {openMaterialFile.isPending && openMaterialFile.variables?.kind === "textbook" ? <Loader2 className="animate-spin" size={16} /> : <Download size={16} />}
                下载教材
              </button>
            </div>
          </div>

          <div className="grid gap-4 py-5 xl:grid-cols-[minmax(220px,1.05fr)_minmax(250px,1.25fr)_minmax(240px,1fr)_minmax(180px,auto)] xl:items-center xl:gap-6">
            <div className="flex min-w-0 items-center gap-4">
              <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-[#f3f3f3] text-ink">
                <ClipboardCheck size={21} />
              </div>
              <div className="min-w-0">
                <h3 className="text-lg font-semibold text-ink">学情画像</h3>
              </div>
            </div>
            <p className="text-sm leading-6 text-ink/58">本次备课使用的学情画像分析。</p>
            <div className="min-w-0 truncate text-sm font-medium text-ink/58">{learnerProfileMaterialInfo}</div>
            <div className="flex xl:justify-center">
              {learnerProfileVersionId ? (
                <Link className="btn btn-secondary min-w-[152px] rounded-full px-5" to={`/projects/${projectId}/batches/${batchId}/learner-profile/${learnerProfileVersionId}`}>
                  <ClipboardCheck size={16} />
                  查看画像
                </Link>
              ) : (
                <button className="btn btn-secondary min-w-[152px] rounded-full px-5" disabled type="button">
                  画像同步中
                </button>
              )}
            </div>
          </div>

          <div className="grid gap-4 py-5 xl:grid-cols-[minmax(220px,1.05fr)_minmax(250px,1.25fr)_minmax(240px,1fr)_minmax(180px,auto)] xl:items-center xl:gap-6">
            <div className="flex min-w-0 items-center gap-4">
              <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-[#f3f3f3] text-ink">
                <BarChart3 size={21} />
              </div>
              <div className="min-w-0">
                <h3 className="text-lg font-semibold text-ink">覆盖报告</h3>
              </div>
            </div>
            <p className="text-sm leading-6 text-ink/58">知识点、题目和课件覆盖检查。</p>
            <div className="text-sm font-medium text-ink/58">
              {coverageReport?.coverage_rate != null ? `${coverageReport.coverage_rate}% 知识点覆盖` : "知识点覆盖同步中"}
            </div>
            <div className="flex xl:justify-center">
              {hasCoverageReport && coverageReport ? (
                <Link className="btn btn-secondary min-w-[170px] rounded-full px-5" to={`/projects/${projectId}/batches/${batchId}/coverage/${coverageReport.id}`}>
                  <BarChart3 size={16} />
                  查看覆盖报告
                </Link>
              ) : (
                <button className="btn btn-secondary min-w-[170px] rounded-full px-5" disabled type="button">
                  覆盖报告同步中
                </button>
              )}
            </div>
          </div>
        </div>

        {(createAssessment.error || downloadPaper.error || openMaterialFile.error) ? (
          <div className="mt-4">
            <FriendlyNotice title="操作暂时没有完成" description="请稍后再试，页面会继续同步资源状态。" />
          </div>
        ) : null}
      </ResourcePanel>

      {(downloadCurriculum.error || batchQuery.error || lessonPlansQuery.error || coverageReportsQuery.error) ? (
        <FriendlyNotice title="部分资源仍在同步" description="可以稍后刷新页面，已有资源会继续显示在这里。" />
      ) : null}
    </div>
  );
}
