import { useEffect, useMemo, useState } from "react";
import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Loader2, RotateCw } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { EmptyState } from "../components/EmptyState";
import { ErrorNotice } from "../components/ErrorNotice";
import { StatusBadge } from "../components/StatusBadge";
import { TaskTable } from "../components/TaskTable";
import { isTaskActiveStatus } from "../hooks/useTaskPolling";
import { api } from "../lib/api";
import type { AssessmentBlueprint, GenerationBatch, JsonRecord, PaperResult, Task } from "../types";
import { cn, formatDate, getErrorMessage, toNumberId } from "../utils";
import { ASSESSMENT_SCENES, AssessmentTab, type AssessmentSceneSummary, type AssessmentSceneType } from "./batch-detail/AssessmentTab";
import { CoursewareTab } from "./batch-detail/CoursewareTab";
import { CoverageTab } from "./batch-detail/CoverageTab";
import { CurriculumTab } from "./batch-detail/CurriculumTab";
import { isBatchLive, latestTask, sortLessons } from "./batch-detail/helpers";
import { LessonTab } from "./batch-detail/LessonTab";
import { OverviewTab } from "./batch-detail/OverviewTab";
import { StatCard } from "./batch-detail/shared";

const tabs = [
  { id: "overview", label: "概览" },
  { id: "curriculum", label: "课程方案" },
  { id: "lesson", label: "教案" },
  { id: "assessment", label: "测练" },
  { id: "courseware", label: "课件" },
  { id: "coverage", label: "覆盖报告" },
  { id: "tasks", label: "关联任务" },
] as const;

type TabId = (typeof tabs)[number]["id"];

function isSuccessfulResultStatus(status: string) {
  return status === "success" || status === "ready";
}

function isAssessmentSceneType(value: unknown): value is AssessmentSceneType {
  return ASSESSMENT_SCENES.some((scene) => scene.scene_type === value);
}

function getTaskAssessmentScene(task: Task): AssessmentSceneType | null {
  const payload = task.payload_json;
  const directScene = payload?.scene_type;
  if (isAssessmentSceneType(directScene)) {
    return directScene;
  }
  const legacyStrategy = payload?.assessment_strategy_json as JsonRecord | undefined;
  if (isAssessmentSceneType(legacyStrategy?.scene_type)) {
    return legacyStrategy.scene_type as AssessmentSceneType;
  }
  if (task.biz_key) {
    const matchedScene = ASSESSMENT_SCENES.find((scene) => task.biz_key?.endsWith(`:assessment:${scene.scene_type}`));
    return matchedScene?.scene_type ?? null;
  }
  return null;
}

export function BatchDetailPage() {
  const routeProjectId = toNumberId(useParams().projectId);
  const batchId = toNumberId(useParams().batchId);
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState<TabId>("overview");
  const [selectedLessonId, setSelectedLessonId] = useState<number | null>(null);
  const [selectedCoverageReportId, setSelectedCoverageReportId] = useState<number | null>(null);
  const [selectedAssessmentScene, setSelectedAssessmentScene] = useState<AssessmentSceneType>("unit_test");
  const [selectedBlueprintId, setSelectedBlueprintId] = useState<number | null>(null);
  const [selectedPaperId, setSelectedPaperId] = useState<number | null>(null);
  const [selectedCoursewareResultId, setSelectedCoursewareResultId] = useState<number | null>(null);
  const [coursewareAutoSelectedBatchId, setCoursewareAutoSelectedBatchId] = useState<number | null>(null);

  const batchQuery = useQuery({
    queryKey: ["generation-batch", batchId],
    queryFn: () => api.getGenerationBatch(batchId),
    enabled: batchId > 0,
    refetchInterval: (query) => (isBatchLive(query.state.data as GenerationBatch | undefined) ? 5_000 : false),
  });

  const batch = batchQuery.data;
  const projectId = batch?.project_id ?? routeProjectId;
  const tasks = useMemo(() => batch?.tasks ?? [], [batch?.tasks]);
  const curriculumTask = useMemo(() => latestTask(tasks, "curriculum"), [tasks]);
  const lessonTask = useMemo(() => latestTask(tasks, "lesson_plan"), [tasks]);
  const coverageTask = useMemo(() => latestTask(tasks, "coverage"), [tasks]);
  const assessmentTasksByScene = useMemo(() => {
    return Object.fromEntries(
      ASSESSMENT_SCENES.map((scene) => [
        scene.scene_type,
        latestTask(
          tasks.filter((task) => {
            if (!(task.module_code === "assessment" || task.task_type.includes("assessment"))) {
              return false;
            }
            return getTaskAssessmentScene(task) === scene.scene_type;
          }),
          "assessment",
        ),
      ]),
    ) as Record<AssessmentSceneType, Task | undefined>;
  }, [tasks]);
  const assessmentTask = assessmentTasksByScene[selectedAssessmentScene];
  const coursewareTask = useMemo(() => latestTask(tasks, "courseware"), [tasks]);
  const selectedCoursewareTask = useMemo(() => {
    if (!selectedLessonId) {
      return undefined;
    }
    return latestTask(
      tasks.filter((task) => {
        const payloadLessonId = Number(task.payload_json?.lesson_plan_id);
        return (
          (task.module_code === "courseware" || task.task_type.includes("courseware")) &&
          (payloadLessonId === selectedLessonId || task.biz_key?.includes(`lesson_plan:${selectedLessonId}:courseware`))
        );
      }),
      "courseware",
    );
  }, [selectedLessonId, tasks]);

  const projectQuery = useQuery({
    queryKey: ["project", projectId],
    queryFn: () => api.getProject(projectId),
    enabled: projectId > 0,
  });

  const curriculumQuery = useQuery({
    queryKey: ["curriculum-plan", batch?.curriculum_plan_id],
    queryFn: () => api.getCurriculumPlan(batch!.curriculum_plan_id!),
    enabled: Boolean(batch?.curriculum_plan_id),
    refetchInterval: isTaskActiveStatus(curriculumTask?.task_status) || isBatchLive(batch) ? 5_000 : false,
  });

  const lessonPlansQuery = useQuery({
    queryKey: ["lesson-plans", batch?.id, batch?.curriculum_plan_id],
    queryFn: () => api.listLessonPlans(batch!.curriculum_plan_id!, { page: 1, page_size: 100 }),
    enabled: Boolean(batch?.id && batch?.curriculum_plan_id),
    refetchInterval: isTaskActiveStatus(lessonTask?.task_status) || isBatchLive(batch) ? 5_000 : false,
  });

  const allLessonPlans = lessonPlansQuery.data?.items ?? [];
  const lessonPlans = useMemo(
    () => sortLessons(allLessonPlans.filter((lessonPlan) => lessonPlan.generation_batch_id === batch?.id)),
    [allLessonPlans, batch?.id],
  );

  useEffect(() => {
    if (!lessonPlans.length) {
      setSelectedLessonId(null);
      return;
    }
    const preferred =
      lessonPlans.find((item) => item.id === batch?.lesson_plan_id) ??
      lessonPlans.find((item) => item.class_session_no === 1) ??
      lessonPlans[0];
    if (!selectedLessonId || !lessonPlans.some((item) => item.id === selectedLessonId)) {
      setSelectedLessonId(preferred.id);
    }
  }, [batch?.lesson_plan_id, lessonPlans, selectedLessonId]);

  const lessonDetailQuery = useQuery({
    queryKey: ["lesson-plan", selectedLessonId],
    queryFn: () => api.getLessonPlan(selectedLessonId!),
    enabled: Boolean(selectedLessonId),
    refetchInterval: isTaskActiveStatus(lessonTask?.task_status) ? 5_000 : false,
  });

  const coverageReportsQuery = useQuery({
    queryKey: ["coverage-reports", batch?.id],
    queryFn: () => api.listCoverageReports(batch!.id, { page: 1, page_size: 100 }),
    enabled: Boolean(batch?.id),
    refetchInterval: isTaskActiveStatus(coverageTask?.task_status) || isBatchLive(batch) ? 5_000 : false,
  });

  const coverageReports = useMemo(() => {
    return [...(coverageReportsQuery.data?.items ?? [])].sort((a, b) => b.id - a.id);
  }, [coverageReportsQuery.data?.items]);

  useEffect(() => {
    if (!coverageReports.length) {
      setSelectedCoverageReportId(null);
      return;
    }
    if (!selectedCoverageReportId || !coverageReports.some((item) => item.id === selectedCoverageReportId)) {
      setSelectedCoverageReportId(coverageReports[0].id);
    }
  }, [coverageReports, selectedCoverageReportId]);

  const coverageDetailQuery = useQuery({
    queryKey: ["coverage-report", selectedCoverageReportId],
    queryFn: () => api.getCoverageReport(selectedCoverageReportId!),
    enabled: Boolean(selectedCoverageReportId),
    refetchInterval: isTaskActiveStatus(coverageTask?.task_status) ? 5_000 : false,
  });

  const assessmentBlueprintQueries = useQueries({
    queries: ASSESSMENT_SCENES.map((scene) => ({
      queryKey: ["assessment-blueprints", batch?.curriculum_plan_id, scene.scene_type],
      queryFn: () =>
        api.listAssessmentBlueprints(batch!.curriculum_plan_id!, {
          scenario_type: scene.scene_type,
          page: 1,
          page_size: 100,
        }),
      enabled: Boolean(batch?.curriculum_plan_id),
      refetchInterval: isTaskActiveStatus(assessmentTasksByScene[scene.scene_type]?.task_status) || isBatchLive(batch) ? 5_000 : false,
    })),
  });

  const assessmentBlueprintsByScene = useMemo(() => {
    return Object.fromEntries(
      ASSESSMENT_SCENES.map((scene, index) => [
        scene.scene_type,
        [...(assessmentBlueprintQueries[index]?.data?.items ?? [])].sort((a, b) => b.id - a.id),
      ]),
    ) as Record<AssessmentSceneType, AssessmentBlueprint[]>;
  }, [assessmentBlueprintQueries]);

  const assessmentBlueprints = assessmentBlueprintsByScene[selectedAssessmentScene] ?? [];
  const selectedAssessmentSceneIndex = Math.max(
    ASSESSMENT_SCENES.findIndex((scene) => scene.scene_type === selectedAssessmentScene),
    0,
  );
  const selectedAssessmentBlueprintsQuery = assessmentBlueprintQueries[selectedAssessmentSceneIndex];

  useEffect(() => {
    if (!assessmentBlueprints.length) {
      setSelectedBlueprintId(null);
      return;
    }
    if (!selectedBlueprintId || !assessmentBlueprints.some((item) => item.id === selectedBlueprintId)) {
      setSelectedBlueprintId(assessmentBlueprints[0].id);
    }
  }, [assessmentBlueprints, selectedAssessmentScene, selectedBlueprintId]);

  const assessmentBlueprintDetailQuery = useQuery({
    queryKey: ["assessment-blueprint", selectedBlueprintId],
    queryFn: () => api.getAssessmentBlueprint(selectedBlueprintId!),
    enabled: Boolean(selectedBlueprintId),
    refetchInterval: isTaskActiveStatus(assessmentTask?.task_status) ? 5_000 : false,
  });

  const paperResultQueries = useQueries({
    queries: ASSESSMENT_SCENES.map((scene) => ({
      queryKey: ["paper-results", batch?.id, scene.scene_type],
      queryFn: () =>
        api.listPaperResults(batch!.id, {
          scene_type: scene.scene_type,
          page: 1,
          page_size: 100,
        }),
      enabled: Boolean(batch?.id),
      refetchInterval: isTaskActiveStatus(assessmentTasksByScene[scene.scene_type]?.task_status) || isBatchLive(batch) ? 5_000 : false,
    })),
  });

  const paperResultsByScene = useMemo(() => {
    return Object.fromEntries(
      ASSESSMENT_SCENES.map((scene, index) => [
        scene.scene_type,
        [...(paperResultQueries[index]?.data?.items ?? [])].sort((a, b) => b.id - a.id),
      ]),
    ) as Record<AssessmentSceneType, PaperResult[]>;
  }, [paperResultQueries]);

  const paperResults = paperResultsByScene[selectedAssessmentScene] ?? [];
  const selectedPaperResultsQuery = paperResultQueries[selectedAssessmentSceneIndex];

  useEffect(() => {
    if (!paperResults.length) {
      setSelectedPaperId(null);
      return;
    }
    if (!selectedPaperId || !paperResults.some((item) => item.id === selectedPaperId)) {
      setSelectedPaperId(paperResults[0].id);
    }
  }, [paperResults, selectedAssessmentScene, selectedPaperId]);

  const paperDetailQuery = useQuery({
    queryKey: ["paper-result", selectedPaperId],
    queryFn: () => api.getPaperResult(selectedPaperId!),
    enabled: Boolean(selectedPaperId),
    refetchInterval: isTaskActiveStatus(assessmentTask?.task_status) ? 5_000 : false,
  });

  const assessmentSceneSummaries = useMemo<AssessmentSceneSummary[]>(() => {
    return ASSESSMENT_SCENES.map((scene) => {
      const scenePapers = paperResultsByScene[scene.scene_type] ?? [];
      const sceneBlueprints = assessmentBlueprintsByScene[scene.scene_type] ?? [];
      const sceneTask = assessmentTasksByScene[scene.scene_type];
      return {
        scene_type: scene.scene_type,
        label: scene.label,
        paperCount: scenePapers.length,
        blueprintCount: sceneBlueprints.length,
        status: scenePapers[0]?.result_status ?? sceneTask?.task_status ?? "pending",
      };
    });
  }, [assessmentBlueprintsByScene, assessmentTasksByScene, paperResultsByScene]);

  const coursewareResultsQuery = useQuery({
    queryKey: ["courseware-results", batch?.id],
    queryFn: () => api.listCoursewareResults(batch!.id, { page: 1, page_size: 100 }),
    enabled: Boolean(batch?.id),
    refetchInterval: (query) => {
      const hasLiveResult = (query.state.data?.items ?? []).some((item) => isTaskActiveStatus(item.result_status));
      return isTaskActiveStatus(coursewareTask?.task_status) || isBatchLive(batch) || hasLiveResult ? 5_000 : false;
    },
  });

  const coursewareResults = useMemo(() => {
    return [...(coursewareResultsQuery.data?.items ?? [])].sort((a, b) => b.id - a.id);
  }, [coursewareResultsQuery.data?.items]);

  const selectedLesson = useMemo(() => {
    return lessonPlans.find((lesson) => lesson.id === selectedLessonId);
  }, [lessonPlans, selectedLessonId]);

  useEffect(() => {
    if (!selectedLessonId) {
      setSelectedCoursewareResultId(null);
      return;
    }
    const matchingResult = coursewareResults.find((item) => item.lesson_plan_id === selectedLessonId);
    if (matchingResult) {
      if (selectedCoursewareResultId !== matchingResult.id) {
        setSelectedCoursewareResultId(matchingResult.id);
      }
      return;
    }
    if (selectedCoursewareResultId !== null) {
      setSelectedCoursewareResultId(null);
    }
  }, [coursewareResults, selectedCoursewareResultId, selectedLessonId]);

  useEffect(() => {
    if (activeTab !== "courseware" || !batch?.id || coursewareAutoSelectedBatchId === batch.id || !coursewareResults.length) {
      return;
    }

    const selectedLessonHasResult = selectedLessonId ? coursewareResults.some((item) => item.lesson_plan_id === selectedLessonId) : false;
    if (!selectedLessonHasResult) {
      const preferredResult = coursewareResults.find((item) => isSuccessfulResultStatus(item.result_status)) ?? coursewareResults[0];
      setSelectedLessonId(preferredResult.lesson_plan_id);
      setSelectedCoursewareResultId(preferredResult.id);
    }
    setCoursewareAutoSelectedBatchId(batch.id);
  }, [activeTab, batch?.id, coursewareAutoSelectedBatchId, coursewareResults, selectedLessonId]);

  const coursewareDetailQuery = useQuery({
    queryKey: ["courseware-result", selectedCoursewareResultId],
    queryFn: () => api.getCoursewareResult(selectedCoursewareResultId!),
    enabled: Boolean(selectedCoursewareResultId),
    refetchInterval: (query) =>
      isTaskActiveStatus(query.state.data?.result_status) || isTaskActiveStatus(selectedCoursewareTask?.task_status) ? 5_000 : false,
  });

  const coursewareOverviewStatus =
    coursewareResults.find((item) => isSuccessfulResultStatus(item.result_status))?.result_status ??
    coursewareResults[0]?.result_status ??
    coursewareTask?.task_status ??
    "pending";
  const coverageOverviewStatus = coverageReports[0]?.report_status ?? coverageTask?.task_status ?? "pending";

  const createAssessment = useMutation({
    mutationFn: (sceneType: AssessmentSceneType) =>
      api.createAssessmentTask(batch!.curriculum_plan_id!, {
        scene_type: sceneType,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["generation-batch", batchId] });
      queryClient.invalidateQueries({ queryKey: ["assessment-blueprints", batch?.curriculum_plan_id] });
      queryClient.invalidateQueries({ queryKey: ["paper-results", batch?.id] });
      queryClient.invalidateQueries({ queryKey: ["question-items", batch?.id] });
    },
  });

  const refreshCoverage = useMutation({
    mutationFn: () => api.refreshCoverageReport(batch!.id),
    onSuccess: (report) => {
      setSelectedCoverageReportId(report.id);
      queryClient.setQueryData(["coverage-report", report.id], report);
      queryClient.invalidateQueries({ queryKey: ["coverage-reports", report.generation_batch_id] });
      queryClient.invalidateQueries({ queryKey: ["generation-batch", batchId] });
    },
  });

  if (routeProjectId <= 0 || batchId <= 0) {
    return <ErrorNotice title="批次地址无效" message="请从项目工作台进入一个真实生成批次。" />;
  }

  if (batchQuery.isLoading && !batch) {
    return (
      <div className="flex h-[60vh] items-center justify-center text-sm text-ink/55">
        <Loader2 className="mr-2 animate-spin" size={17} />
        加载批次详情
      </div>
    );
  }

  if (batchQuery.error && !batch) {
    return <ErrorNotice title="批次详情获取失败" message={getErrorMessage(batchQuery.error)} />;
  }

  if (!batch) {
    return <EmptyState title="批次不存在" action={<Link className="btn btn-secondary" to={`/projects/${projectId}`}>返回项目</Link>} />;
  }

  return (
    <div className="space-y-6">
      <section className="flex flex-col justify-between gap-4 xl:flex-row xl:items-end">
        <div>
          <Link className="mb-4 inline-flex items-center gap-2 text-sm font-semibold text-ink/55 hover:text-ink" to={`/projects/${projectId}`}>
            <ArrowLeft size={16} />
            项目工作台
          </Link>
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-3xl font-bold">{batch.batch_name ?? `生成批次 #${batch.batch_no}`}</h1>
            <StatusBadge status={batch.batch_status} />
          </div>
          <div className="mt-2 flex flex-wrap gap-2 text-sm text-ink/55">
            <span>{projectQuery.data?.name ?? `项目 #${projectId}`}</span>
            <span>/</span>
            <span>批次 ID {batch.id}</span>
            <span>/</span>
            <span>{formatDate(batch.updated_at)}</span>
          </div>
        </div>
        <button className="btn btn-secondary" disabled={batchQuery.isFetching} onClick={() => batchQuery.refetch()} type="button">
          <RotateCw className={batchQuery.isFetching ? "animate-spin" : ""} size={16} />
          刷新
        </button>
      </section>

      <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <StatCard label="知识版本" value={batch.knowledge_version_id} />
        <StatCard label="学情版本" value={batch.learner_profile_version_id} />
        <StatCard label="课次" value={batch.course_count} />
        <StatCard label="课时分钟" value={batch.session_duration_minutes} />
      </section>

      <section className="panel overflow-hidden">
        <div className="border-b border-line px-3 py-3">
          <div className="flex gap-2 overflow-x-auto">
            {tabs.map((tab) => (
              <button
                className={cn(
                  "h-9 shrink-0 rounded-md px-3 text-sm font-semibold text-ink/60 transition hover:bg-paper hover:text-ink",
                  activeTab === tab.id && "bg-ink text-white hover:bg-ink hover:text-white",
                )}
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                type="button"
              >
                {tab.label}
              </button>
            ))}
          </div>
        </div>
        <div className="p-5">
          {activeTab === "overview" ? (
            <OverviewTab
              assessmentScenes={assessmentSceneSummaries}
              batch={batch}
              coursewareCount={coursewareResults.length}
              coursewareStatus={coursewareOverviewStatus}
              coverageCount={coverageReports.length}
              coverageStatus={coverageOverviewStatus}
              lessonCount={lessonPlans.length}
            />
          ) : null}
          {activeTab === "curriculum" ? (
            <CurriculumTab
              plan={curriculumQuery.data}
              isLoading={curriculumQuery.isLoading}
              error={curriculumQuery.error}
              task={curriculumTask}
            />
          ) : null}
          {activeTab === "lesson" ? (
            <LessonTab
              batch={batch}
              lessons={lessonPlans}
              selectedLessonId={selectedLessonId}
              onSelectLesson={setSelectedLessonId}
              lesson={lessonDetailQuery.data}
              listLoading={lessonPlansQuery.isLoading}
              detailLoading={lessonDetailQuery.isLoading}
              listError={lessonPlansQuery.error}
              detailError={lessonDetailQuery.error}
              task={lessonTask}
            />
          ) : null}
          {activeTab === "assessment" ? (
            <AssessmentTab
              batch={batch}
              hasLessonPlans={lessonPlans.length > 0}
              task={assessmentTask}
              selectedScene={selectedAssessmentScene}
              sceneSummaries={assessmentSceneSummaries}
              onSelectScene={setSelectedAssessmentScene}
              blueprints={assessmentBlueprints}
              selectedBlueprintId={selectedBlueprintId}
              onSelectBlueprint={setSelectedBlueprintId}
              blueprint={assessmentBlueprintDetailQuery.data}
              blueprintListLoading={selectedAssessmentBlueprintsQuery?.isLoading ?? false}
              blueprintDetailLoading={assessmentBlueprintDetailQuery.isLoading}
              blueprintListError={selectedAssessmentBlueprintsQuery?.error}
              blueprintDetailError={assessmentBlueprintDetailQuery.error}
              papers={paperResults}
              selectedPaperId={selectedPaperId}
              onSelectPaper={setSelectedPaperId}
              paper={paperDetailQuery.data}
              paperListLoading={selectedPaperResultsQuery?.isLoading ?? false}
              paperDetailLoading={paperDetailQuery.isLoading}
              paperListError={selectedPaperResultsQuery?.error}
              paperDetailError={paperDetailQuery.error}
              onCreateAssessment={(sceneType) => createAssessment.mutate(sceneType)}
              createPending={createAssessment.isPending}
              createError={createAssessment.error}
            />
          ) : null}
          {activeTab === "courseware" ? (
            <CoursewareTab
              batch={batch}
              lessons={lessonPlans}
              selectedLessonId={selectedLessonId}
              selectedLesson={selectedLesson}
              onSelectLesson={setSelectedLessonId}
              task={selectedCoursewareTask}
              results={coursewareResults}
              selectedResultId={selectedCoursewareResultId}
              onSelectResult={setSelectedCoursewareResultId}
              result={coursewareDetailQuery.data}
              listLoading={coursewareResultsQuery.isLoading}
              detailLoading={coursewareDetailQuery.isLoading}
              listError={coursewareResultsQuery.error}
              detailError={coursewareDetailQuery.error}
            />
          ) : null}
          {activeTab === "coverage" ? (
            <CoverageTab
              reports={coverageReports}
              selectedReportId={selectedCoverageReportId}
              onSelectReport={setSelectedCoverageReportId}
              report={coverageDetailQuery.data}
              listLoading={coverageReportsQuery.isLoading}
              detailLoading={coverageDetailQuery.isLoading}
              listError={coverageReportsQuery.error}
              detailError={coverageDetailQuery.error}
              task={coverageTask}
              onRefreshCoverage={() => refreshCoverage.mutate()}
              refreshPending={refreshCoverage.isPending}
              refreshError={refreshCoverage.error}
            />
          ) : null}
          {activeTab === "tasks" ? (
            tasks.length ? (
              <TaskTable tasks={tasks} />
            ) : (
              <EmptyState description="当前批次没有任务记录，通常表示生成尚未触发或批次数据异常。" title="暂无关联任务" />
            )
          ) : null}
        </div>
      </section>
    </div>
  );
}
