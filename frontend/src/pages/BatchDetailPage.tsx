import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Loader2, RotateCw } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { EmptyState } from "../components/EmptyState";
import { ErrorNotice } from "../components/ErrorNotice";
import { StatusBadge } from "../components/StatusBadge";
import { TaskTable } from "../components/TaskTable";
import { isTaskActiveStatus } from "../hooks/useTaskPolling";
import { api } from "../lib/api";
import type { GenerationBatch } from "../types";
import { cn, formatDate, getErrorMessage, toNumberId } from "../utils";
import { AssessmentTab, DEFAULT_UNIT_TEST_STRATEGY } from "./batch-detail/AssessmentTab";
import { CoverageTab } from "./batch-detail/CoverageTab";
import { CurriculumTab } from "./batch-detail/CurriculumTab";
import { isBatchLive, latestTask, sortLessons } from "./batch-detail/helpers";
import { LessonTab } from "./batch-detail/LessonTab";
import { OverviewTab } from "./batch-detail/OverviewTab";
import { ResultPlaceholder, StatCard } from "./batch-detail/shared";

const tabs = [
  { id: "overview", label: "概览" },
  { id: "curriculum", label: "课程方案" },
  { id: "lesson", label: "教案" },
  { id: "assessment", label: "测评" },
  { id: "courseware", label: "课件" },
  { id: "coverage", label: "覆盖报告" },
  { id: "tasks", label: "关联任务" },
] as const;

type TabId = (typeof tabs)[number]["id"];

export function BatchDetailPage() {
  const routeProjectId = toNumberId(useParams().projectId);
  const batchId = toNumberId(useParams().batchId);
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState<TabId>("overview");
  const [selectedLessonId, setSelectedLessonId] = useState<number | null>(null);
  const [selectedCoverageReportId, setSelectedCoverageReportId] = useState<number | null>(null);
  const [selectedBlueprintId, setSelectedBlueprintId] = useState<number | null>(null);
  const [selectedPaperId, setSelectedPaperId] = useState<number | null>(null);

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
  const assessmentTask = useMemo(() => latestTask(tasks, "assessment"), [tasks]);

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

  const assessmentBlueprintsQuery = useQuery({
    queryKey: ["assessment-blueprints", batch?.curriculum_plan_id, "unit_test"],
    queryFn: () => api.listAssessmentBlueprints(batch!.curriculum_plan_id!, { scenario_type: "unit_test", page: 1, page_size: 100 }),
    enabled: Boolean(batch?.curriculum_plan_id),
    refetchInterval: isTaskActiveStatus(assessmentTask?.task_status) || isBatchLive(batch) ? 5_000 : false,
  });

  const assessmentBlueprints = useMemo(() => {
    return [...(assessmentBlueprintsQuery.data?.items ?? [])].sort((a, b) => b.id - a.id);
  }, [assessmentBlueprintsQuery.data?.items]);

  useEffect(() => {
    if (!assessmentBlueprints.length) {
      setSelectedBlueprintId(null);
      return;
    }
    if (!selectedBlueprintId || !assessmentBlueprints.some((item) => item.id === selectedBlueprintId)) {
      setSelectedBlueprintId(assessmentBlueprints[0].id);
    }
  }, [assessmentBlueprints, selectedBlueprintId]);

  const assessmentBlueprintDetailQuery = useQuery({
    queryKey: ["assessment-blueprint", selectedBlueprintId],
    queryFn: () => api.getAssessmentBlueprint(selectedBlueprintId!),
    enabled: Boolean(selectedBlueprintId),
    refetchInterval: isTaskActiveStatus(assessmentTask?.task_status) ? 5_000 : false,
  });

  const paperResultsQuery = useQuery({
    queryKey: ["paper-results", batch?.id, "unit_test"],
    queryFn: () => api.listPaperResults(batch!.id, { scene_type: "unit_test", page: 1, page_size: 100 }),
    enabled: Boolean(batch?.id),
    refetchInterval: isTaskActiveStatus(assessmentTask?.task_status) || isBatchLive(batch) ? 5_000 : false,
  });

  const paperResults = useMemo(() => {
    return [...(paperResultsQuery.data?.items ?? [])].sort((a, b) => b.id - a.id);
  }, [paperResultsQuery.data?.items]);

  useEffect(() => {
    if (!paperResults.length) {
      setSelectedPaperId(null);
      return;
    }
    if (!selectedPaperId || !paperResults.some((item) => item.id === selectedPaperId)) {
      setSelectedPaperId(paperResults[0].id);
    }
  }, [paperResults, selectedPaperId]);

  const paperDetailQuery = useQuery({
    queryKey: ["paper-result", selectedPaperId],
    queryFn: () => api.getPaperResult(selectedPaperId!),
    enabled: Boolean(selectedPaperId),
    refetchInterval: isTaskActiveStatus(assessmentTask?.task_status) ? 5_000 : false,
  });

  const createAssessment = useMutation({
    mutationFn: () =>
      api.createAssessmentTask(batch!.curriculum_plan_id!, {
        assessment_strategy_json: DEFAULT_UNIT_TEST_STRATEGY,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["generation-batch", batchId] });
      queryClient.invalidateQueries({ queryKey: ["assessment-blueprints", batch?.curriculum_plan_id, "unit_test"] });
      queryClient.invalidateQueries({ queryKey: ["paper-results", batch?.id, "unit_test"] });
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
          {activeTab === "overview" ? <OverviewTab batch={batch} /> : null}
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
              blueprints={assessmentBlueprints}
              selectedBlueprintId={selectedBlueprintId}
              onSelectBlueprint={setSelectedBlueprintId}
              blueprint={assessmentBlueprintDetailQuery.data}
              blueprintListLoading={assessmentBlueprintsQuery.isLoading}
              blueprintDetailLoading={assessmentBlueprintDetailQuery.isLoading}
              blueprintListError={assessmentBlueprintsQuery.error}
              blueprintDetailError={assessmentBlueprintDetailQuery.error}
              papers={paperResults}
              selectedPaperId={selectedPaperId}
              onSelectPaper={setSelectedPaperId}
              paper={paperDetailQuery.data}
              paperListLoading={paperResultsQuery.isLoading}
              paperDetailLoading={paperDetailQuery.isLoading}
              paperListError={paperResultsQuery.error}
              paperDetailError={paperDetailQuery.error}
              onCreateAssessment={() => createAssessment.mutate()}
              createPending={createAssessment.isPending}
              createError={createAssessment.error}
            />
          ) : null}
          {activeTab === "courseware" ? (
            <ResultPlaceholder title="课件结果入口" description="Phase3-B 暂不实现课件链路。课件任务、刷新、回复和 PPTX 下载将在 Phase3-C 接入。" />
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
            />
          ) : null}
          {activeTab === "tasks" ? (
            tasks.length ? <TaskTable tasks={tasks} /> : <EmptyState title="暂无关联任务" />
          ) : null}
        </div>
      </section>
    </div>
  );
}
