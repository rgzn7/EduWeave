import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  BarChart3,
  BookOpen,
  ClipboardCheck,
  Download,
  FileText,
  Loader2,
  Presentation,
  Sparkles,
} from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { isTaskActiveStatus } from "../hooks/useTaskPolling";
import { api } from "../lib/api";
import type { CoursewareResult, GenerationBatch, JsonRecord, LessonPlan, PaperResult, Task } from "../types";
import { cn, formatDate, toNumberId } from "../utils";
import { asRecord, asRecordList, latestByUpdated, sortLessons } from "./batch-detail/helpers";

const assessmentScenes = [
  {
    scene_type: "homework",
    label: "课后作业",
    actionLabel: "生成作业",
    description: "围绕本套课程内容，生成课后巩固练习。",
  },
  {
    scene_type: "unit_test",
    label: "单元测评",
    actionLabel: "生成测评",
    description: "用于阶段检测，查看学生对核心知识的掌握情况。",
  },
  {
    scene_type: "final_exam",
    label: "期末综合测",
    actionLabel: "生成试卷",
    description: "生成综合测评，覆盖整套课程的重点内容。",
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

function formatLessonTitle(title?: string | null) {
  const cleaned = String(title ?? "").trim();
  return cleaned.replace(/^第\s*[一二三四五六七八九十百千万\d]+\s*[讲课节]\s*[：:、,，.\-\s]*/u, "").trim() || cleaned || "未命名课程";
}

function cleanText(value: unknown) {
  const text = String(value ?? "").trim();
  if (!text || text === "-") {
    return "";
  }
  return text;
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

  const directObjectives = pickText(content, ["teaching_objectives", "objectives", "lesson_objectives", "learning_objectives"], 5);
  const objectives = directObjectives.length ? directObjectives : collectText(courseOverview?.objectives, 5);
  const focus = [
    ...pickText(content, ["key_points", "teaching_focus", "core_knowledge", "important_points"], 4),
    ...pickText(content, ["difficult_points", "learning_difficulties"], 3),
  ];
  const practice = pickText(content, ["class_practice", "practice_items", "in_class_practice", "exercises"], 5);
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
      title: "课堂练习",
      items: practice,
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

function ResourceBadge({ children }: { children: string }) {
  return (
    <span className="inline-flex h-7 items-center rounded-full bg-[#f2f2f2] px-3 text-xs font-semibold text-ink/62">
      {children}
    </span>
  );
}

function InlineStatus({ label }: { label: string }) {
  return (
    <span className="inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap text-xs font-semibold text-ink/45">
      <span className="h-1.5 w-1.5 rounded-full bg-ink/35" />
      {label}
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

function LessonList({
  lessons,
  selectedLessonId,
  coursewareResults,
  onSelectLesson,
}: {
  lessons: LessonPlan[];
  selectedLessonId: number | null;
  coursewareResults: CoursewareResult[];
  onSelectLesson: (lessonId: number) => void;
}) {
  if (!lessons.length) {
    return <FriendlyNotice title="教案正在准备" description="课程方案完成后，这里会显示每一课的教案。" />;
  }

  return (
    <div className="space-y-3">
      {lessons.map((lesson) => {
        const hasPpt = coursewareResults.some((item) => item.lesson_plan_id === lesson.id && item.export_file_id);
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
              {hasPpt ? <ResourceBadge>PPT</ResourceBadge> : null}
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
    <div className="space-y-6">
      <div>
        <div className="text-sm font-semibold text-ink/45">第 {lesson.class_session_no ?? "-"} 课</div>
        <h2 className="mt-2 text-2xl font-semibold leading-tight text-ink">{formatLessonTitle(lesson.lesson_title)}</h2>
        {lesson.summary_text ? <p className="mt-3 text-sm leading-7 text-ink/58">{lesson.summary_text}</p> : null}
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        {sections.map((section) => (
          <section className="rounded-2xl border border-line bg-[#fafafa] p-4" key={section.title}>
            <h3 className="text-sm font-semibold text-ink">{section.title}</h3>
            {section.items.length ? (
              <ul className="mt-3 space-y-2 text-sm leading-6 text-ink/62">
                {section.items.slice(0, 5).map((item, index) => (
                  <li className="flex gap-2" key={`${section.title}-${item}-${index}`}>
                    <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-ink/32" />
                    <span className="min-w-0">{item}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <div className="mt-3 text-sm text-ink/38">等待内容同步</div>
            )}
          </section>
        ))}
      </div>

      <section className="rounded-2xl border border-line bg-white p-5">
        <h3 className="text-base font-semibold text-ink">教学流程</h3>
        {steps.length ? (
          <div className="mt-4 space-y-4">
            {steps.map((step, index) => (
              <div className="grid gap-3 border-t border-line pt-4 first:border-t-0 first:pt-0 md:grid-cols-[96px_1fr]" key={`${step.title}-${index}`}>
                <div className="text-sm font-semibold text-ink/45">环节 {index + 1}</div>
                <div>
                  <div className="font-semibold text-ink">{step.title}</div>
                  {step.details.length ? (
                    <p className="mt-2 text-sm leading-6 text-ink/58">{step.details.join("；")}</p>
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
  const [lessonDownloadId, setLessonDownloadId] = useState<number | null>(null);
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
    return sortLessons(items.filter((lesson) => lesson.generation_batch_id === batch?.id));
  }, [batch?.id, lessonPlansQuery.data?.items]);

  useEffect(() => {
    if (!lessonPlans.length) {
      setSelectedLessonId(null);
      return;
    }
    const preferred =
      lessonPlans.find((lesson) => lesson.id === batch?.lesson_plan_id) ??
      lessonPlans.find((lesson) => lesson.class_session_no === 1) ??
      lessonPlans[0];
    if (!selectedLessonId || !lessonPlans.some((lesson) => lesson.id === selectedLessonId)) {
      setSelectedLessonId(preferred.id);
    }
  }, [batch?.lesson_plan_id, lessonPlans, selectedLessonId]);

  const selectedLesson = useMemo(
    () => lessonPlans.find((lesson) => lesson.id === selectedLessonId),
    [lessonPlans, selectedLessonId],
  );

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

  const downloadCurriculum = useMutation({
    mutationFn: async () => {
      const plan = curriculumQuery.data;
      if (!plan) {
        throw new Error("课程方案暂未准备好");
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

  return (
    <div className="mx-auto w-full max-w-[1540px] space-y-6 px-2 pb-10 pt-6 text-ink">
      <section className="grid gap-6 xl:h-[calc(100vh-230px)] xl:min-h-[500px] xl:grid-cols-[310px_minmax(0,1fr)_340px]">
        <ResourcePanel title="课次" scroll>
          <LessonList
            lessons={lessonPlans}
            selectedLessonId={selectedLessonId}
            coursewareResults={coursewareResults}
            onSelectLesson={setSelectedLessonId}
          />
        </ResourcePanel>

        <ResourcePanel title="教案预览" scroll>
          <LessonPreview lesson={lessonForPreview} loading={lessonDetailQuery.isLoading} />
        </ResourcePanel>

        <ResourcePanel title="本课资源" scroll>
          <div className="space-y-4">
            <div className="rounded-2xl border border-line bg-[#fafafa] p-4">
              <div className="flex items-start gap-3">
                <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-white">
                  <FileText size={20} />
                </div>
                <div className="min-w-0">
                  <div className="font-semibold text-ink">教案 DOCX</div>
                  <p className="mt-1 text-sm leading-6 text-ink/50">下载当前课教案，直接用于备课和教研归档。</p>
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

            <div className="rounded-2xl border border-line bg-[#fafafa] p-4">
              <div className="flex items-start gap-3">
                <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-white">
                  <Presentation size={20} />
                </div>
                <div className="min-w-0">
                  <div className="font-semibold text-ink">PPT 课件</div>
                  <p className="mt-1 text-sm leading-6 text-ink/50">基于当前课教案生成这一课的 PPT。</p>
                </div>
              </div>
              {canDownloadPpt ? (
                <button className="btn btn-primary mt-4 w-full rounded-full" disabled={downloadPpt.isPending} onClick={() => downloadPpt.mutate()} type="button">
                  <Download size={16} />
                  {downloadPpt.isPending ? "准备下载" : "下载 PPT"}
                </button>
              ) : hasCoursewareResult || coursewareActive ? (
                <button className="btn btn-secondary mt-4 w-full rounded-full" disabled type="button">
                  <Loader2 className={coursewareActive ? "animate-spin" : ""} size={16} />
                  PPT 生成中
                </button>
              ) : (
                <button
                  className="btn btn-primary mt-4 w-full rounded-full"
                  disabled={!selectedLesson || createCourseware.isPending}
                  onClick={() => createCourseware.mutate()}
                  type="button"
                >
                  {createCourseware.isPending ? <Loader2 className="animate-spin" size={16} /> : <Sparkles size={16} />}
                  {coursewareFailed ? "重新生成" : "生成这一课 PPT"}
                </button>
              )}
            </div>

            {(downloadLesson.error || downloadPpt.error || createCourseware.error) ? (
              <FriendlyNotice title="操作暂时没有完成" description="请稍后再试，页面会继续同步资源状态。" />
            ) : null}
          </div>
        </ResourcePanel>
      </section>

      <ResourcePanel title="整套资源">
        <div className="grid gap-4 xl:grid-cols-[320px_1fr_320px]">
          <section className="rounded-2xl border border-line bg-[#fafafa] p-5">
            <div className="flex items-start gap-3">
              <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-white">
                <BookOpen size={20} />
              </div>
              <div>
                <h3 className="font-semibold text-ink">课程方案</h3>
                <p className="mt-2 text-sm leading-6 text-ink/50">整套课程安排、教学目标与课时规划。</p>
              </div>
            </div>
            <button
              className="btn btn-secondary mt-5 w-full rounded-full"
              disabled={!curriculumQuery.data || downloadCurriculum.isPending}
              onClick={() => downloadCurriculum.mutate()}
              type="button"
            >
              <Download size={16} />
              {downloadCurriculum.isPending ? "准备下载" : "下载课程方案"}
            </button>
          </section>

          <section className="rounded-2xl border border-line bg-[#fafafa] p-5">
            <div className="flex items-start gap-3">
              <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-white">
                <ClipboardCheck size={20} />
              </div>
              <div>
                <h3 className="font-semibold text-ink">配套测练</h3>
                <p className="mt-2 text-sm leading-6 text-ink/50">按教学场景生成作业、测评和综合试卷。</p>
              </div>
            </div>
            <div className="mt-5 grid gap-3 lg:grid-cols-3">
              {assessmentScenes.map((scene) => {
                const paper = paperResultsByScene[scene.scene_type]?.[0];
                const task = assessmentTasksByScene[scene.scene_type];
                const active = isTaskActiveStatus(task?.task_status) || isTaskActiveStatus(paper?.result_status);
                const failed = isFailedStatus(task?.task_status) || isFailedStatus(paper?.result_status);
                const hasPaper = Boolean(paper && isSuccessfulStatus(paper.result_status));
                return (
                  <div className="rounded-2xl border border-line bg-white p-4" key={scene.scene_type}>
                    <div>
                      <div className="flex min-w-0 items-center justify-between gap-3">
                        <h4 className="font-semibold text-ink">{scene.label}</h4>
                        <InlineStatus label={hasPaper ? "已生成" : active ? "生成中" : "可生成"} />
                      </div>
                      <div>
                        <p className="mt-2 min-h-12 text-sm leading-6 text-ink/48">{scene.description}</p>
                      </div>
                    </div>
                    <div className="mt-4 grid gap-2">
                      {hasPaper && paper ? (
                        <>
                          <Link className="btn btn-primary rounded-full" to={`/projects/${projectId}/batches/${batchId}/assessments/${paper.id}`}>
                            查看题目
                          </Link>
                          <button
                            className="btn btn-secondary rounded-full"
                            disabled={paperDownloadId === paper.id}
                            onClick={() => downloadPaper.mutate(paper)}
                            type="button"
                          >
                            <Download size={16} />
                            {paperDownloadId === paper.id ? "准备下载" : "下载 DOCX"}
                          </button>
                        </>
                      ) : (
                        <button
                          className="btn btn-secondary rounded-full"
                          disabled={!batch.curriculum_plan_id || active || createAssessment.isPending}
                          onClick={() => createAssessment.mutate(scene.scene_type)}
                          type="button"
                        >
                          {active || createAssessment.isPending ? <Loader2 className="animate-spin" size={16} /> : <Sparkles size={16} />}
                          {active ? "生成中" : failed ? "重新生成" : scene.actionLabel}
                        </button>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
            {(createAssessment.error || downloadPaper.error) ? (
              <div className="mt-4">
                <FriendlyNotice title="测练操作暂时没有完成" description="请稍后再试，页面会继续同步测练状态。" />
              </div>
            ) : null}
          </section>

          <section className="rounded-2xl border border-line bg-[#fafafa] p-5">
            <div className="flex items-start gap-3">
              <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-white">
                <BarChart3 size={20} />
              </div>
              <div>
                <h3 className="font-semibold text-ink">覆盖报告</h3>
                <p className="mt-2 text-sm leading-6 text-ink/50">检查知识点、题目和课件是否覆盖到位。</p>
              </div>
            </div>
            <div className="mt-5 rounded-2xl border border-line bg-white p-4">
              <div className="text-sm font-semibold text-ink/45">知识点覆盖</div>
              <div className="mt-2 text-3xl font-semibold text-ink">
                {coverageReport?.coverage_rate != null ? `${coverageReport.coverage_rate}%` : "-"}
              </div>
              <div className="mt-1 text-sm text-ink/45">
                {coverageReport ? `更新于 ${formatDate(coverageReport.updated_at)}` : "等待资源同步"}
              </div>
            </div>
            {coverageReport && isSuccessfulStatus(coverageReport.report_status) ? (
              <Link className="btn btn-primary mt-5 w-full rounded-full" to={`/projects/${projectId}/batches/${batchId}/coverage/${coverageReport.id}`}>
                查看覆盖报告
              </Link>
            ) : (
              <button className="btn btn-secondary mt-5 w-full rounded-full" disabled type="button">
                覆盖报告同步中
              </button>
            )}
          </section>
        </div>
      </ResourcePanel>

      {(downloadCurriculum.error || batchQuery.error || lessonPlansQuery.error || coverageReportsQuery.error) ? (
        <FriendlyNotice title="部分资源仍在同步" description="可以稍后刷新页面，已生成资源会继续显示在这里。" />
      ) : null}
    </div>
  );
}
