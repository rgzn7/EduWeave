import { useAuthStore } from "../stores/auth";
import type {
  AssessmentBlueprint,
  ApiEnvelope,
  AuthUser,
  CoursewareResult,
  CoverageReport,
  CreateGenerationBatchPayload,
  CreateProjectPayload,
  CurriculumPlan,
  FileDownloadUrl,
  GenerationBatch,
  HomeworkQuestionListItem,
  HomeworkResult,
  HomeworkResultDetail,
  KnowledgeChapter,
  KnowledgePoint,
  KnowledgeVersion,
  LearnerProfileFile,
  LearnerProfileVersion,
  LearnerProfileVersionDetail,
  LessonPlan,
  LoginResult,
  PageResult,
  PaperResult,
  ParseEvidenceSummary,
  ParseVersion,
  Project,
  ProjectDashboard,
  QuestionBankItem,
  Task,
  TaskDetail,
  TextbookVersion,
} from "../types";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8010";

export class EduWeaveApiError extends Error {
  status: number;
  code?: string;

  constructor(message: string, status: number, code?: string) {
    super(message);
    this.name = "EduWeaveApiError";
    this.status = status;
    this.code = code;
  }
}

function buildUrl(path: string, query?: Record<string, string | number | boolean | undefined | null>) {
  const url = new URL(path, API_BASE_URL);
  Object.entries(query ?? {}).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") {
      url.searchParams.set(key, String(value));
    }
  });
  return url.toString();
}

async function request<T>(
  path: string,
  init: RequestInit = {},
  query?: Record<string, string | number | boolean | undefined | null>,
) {
  const token = useAuthStore.getState().token;
  const headers = new Headers(init.headers);
  const isFormData = init.body instanceof FormData;

  if (!isFormData && init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  const response = await fetch(buildUrl(path, query), {
    ...init,
    headers,
  });

  let envelope: ApiEnvelope<T> | undefined;
  try {
    envelope = (await response.json()) as ApiEnvelope<T>;
  } catch {
    envelope = undefined;
  }

  if (!response.ok || envelope?.success === false) {
    const firstError = envelope?.errors?.[0];
    if (firstError?.code === "TOKEN_EXPIRED" || response.status === 401) {
      useAuthStore.getState().clearSession();
    }
    throw new EduWeaveApiError(firstError?.message ?? envelope?.message ?? "请求失败", response.status, firstError?.code);
  }

  return envelope?.data as T;
}

export const api = {
  login(payload: { username: string; password: string }) {
    return request<LoginResult>("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  me() {
    return request<AuthUser>("/api/v1/auth/me");
  },
  listProjects(query?: { page?: number; page_size?: number; status?: string; subject_code?: string }) {
    return request<PageResult<Project>>("/api/v1/projects", {}, query);
  },
  createProject(payload: CreateProjectPayload) {
    return request<Project>("/api/v1/projects", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  getProject(projectId: number) {
    return request<Project>(`/api/v1/projects/${projectId}`);
  },
  getProjectDashboard(projectId: number) {
    return request<ProjectDashboard>(`/api/v1/projects/${projectId}/dashboard`);
  },
  listTasks(query?: {
    project_id?: number;
    module_code?: string;
    task_type?: string;
    task_status?: string;
    page?: number;
    page_size?: number;
  }) {
    return request<PageResult<Task>>("/api/v1/tasks", {}, query);
  },
  getTask(taskId: number) {
    return request<TaskDetail>(`/api/v1/tasks/${taskId}`);
  },
  uploadTextbook(
    projectId: number,
    payload: {
      file: File;
      textbook_name?: string;
      set_as_current?: boolean;
    },
  ) {
    const formData = new FormData();
    formData.append("file", payload.file);
    if (payload.textbook_name) {
      formData.append("textbook_name", payload.textbook_name);
    }
    formData.append("set_as_current", String(payload.set_as_current ?? true));
    return request<TextbookVersion>(`/api/v1/projects/${projectId}/textbooks`, {
      method: "POST",
      body: formData,
    });
  },
  listTextbooks(projectId: number) {
    return request<PageResult<TextbookVersion>>(`/api/v1/projects/${projectId}/textbooks`, {}, { page: 1, page_size: 20 });
  },
  createParseTask(textbookVersionId: number) {
    return request<Task>(`/api/v1/textbook-versions/${textbookVersionId}/parse-tasks`, {
      method: "POST",
      body: JSON.stringify({
        strategy_code: "mineru_vlm_default",
        set_as_current_on_success: true,
      }),
    });
  },
  listParseVersions(textbookVersionId: number) {
    return request<PageResult<ParseVersion>>(
      `/api/v1/textbook-versions/${textbookVersionId}/parse-versions`,
      {},
      { page: 1, page_size: 20 },
    );
  },
  confirmParseVersion(parseVersionId: number) {
    return request<ParseVersion>(`/api/v1/parse-versions/${parseVersionId}/confirm`, {
      method: "POST",
    });
  },
  getParseEvidenceSummary(parseVersionId: number) {
    return request<ParseEvidenceSummary>(`/api/v1/parse-versions/${parseVersionId}/evidence-summary`);
  },
  uploadLearnerProfile(
    projectId: number,
    payload: {
      file: File;
      title?: string;
      auto_extract?: boolean;
      set_as_current?: boolean;
    },
  ) {
    const formData = new FormData();
    formData.append("file", payload.file);
    if (payload.title) {
      formData.append("title", payload.title);
    }
    formData.append("auto_extract", String(payload.auto_extract ?? true));
    formData.append("set_as_current", String(payload.set_as_current ?? true));
    return request<LearnerProfileFile>(`/api/v1/projects/${projectId}/learner-profiles`, {
      method: "POST",
      body: formData,
    });
  },
  listLearnerProfiles(projectId: number) {
    return request<PageResult<LearnerProfileFile>>(
      `/api/v1/projects/${projectId}/learner-profiles`,
      {},
      { page: 1, page_size: 20 },
    );
  },
  listLearnerProfileVersions(projectId: number, profileFileId: number) {
    return request<PageResult<LearnerProfileVersion>>(
      `/api/v1/projects/${projectId}/learner-profiles/${profileFileId}/versions`,
      {},
      { page: 1, page_size: 20 },
    );
  },
  getLearnerProfileVersion(profileVersionId: number) {
    return request<LearnerProfileVersionDetail>(`/api/v1/learner-profile-versions/${profileVersionId}`);
  },
  createKnowledgeTask(parseVersionId: number, payload: { force_regenerate?: boolean } = {}) {
    return request<Task>(`/api/v1/parse-versions/${parseVersionId}/knowledge-tasks`, {
      method: "POST",
      body: JSON.stringify({ force_regenerate: payload.force_regenerate ?? false }),
    });
  },
  listKnowledgeVersions(parseVersionId: number) {
    return request<PageResult<KnowledgeVersion>>(
      `/api/v1/parse-versions/${parseVersionId}/knowledge-versions`,
      {},
      { page: 1, page_size: 20 },
    );
  },
  listKnowledgeChapters(knowledgeVersionId: number) {
    return request<KnowledgeChapter[]>(`/api/v1/knowledge-versions/${knowledgeVersionId}/chapters`);
  },
  listKnowledgePoints(knowledgeVersionId: number, query?: { chapter_node_id?: number; keyword?: string; page?: number; page_size?: number }) {
    return request<PageResult<KnowledgePoint>>(
      `/api/v1/knowledge-versions/${knowledgeVersionId}/points`,
      {},
      { page: 1, page_size: 20, ...query },
    );
  },
  createGenerationBatch(payload: CreateGenerationBatchPayload) {
    return request<GenerationBatch>("/api/v1/generation-batches", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  listGenerationBatches(projectId: number) {
    return request<PageResult<GenerationBatch>>(
      "/api/v1/generation-batches",
      {},
      { project_id: projectId, page: 1, page_size: 20 },
    );
  },
  getGenerationBatch(generationBatchId: number) {
    return request<GenerationBatch>(`/api/v1/generation-batches/${generationBatchId}`);
  },
  listCurriculumPlans(query: { project_id: number; knowledge_version_id?: number; page?: number; page_size?: number }) {
    return request<PageResult<CurriculumPlan>>("/api/v1/curriculum-plans", {}, { page: 1, page_size: 20, ...query });
  },
  getCurriculumPlan(curriculumPlanId: number) {
    return request<CurriculumPlan>(`/api/v1/curriculum-plans/${curriculumPlanId}`);
  },
  exportCurriculumPlanDocx(curriculumPlanId: number) {
    return request<FileDownloadUrl>(`/api/v1/curriculum-plans/${curriculumPlanId}/export-docx`, {
      method: "POST",
    });
  },
  listLessonPlans(curriculumPlanId: number, query?: { page?: number; page_size?: number }) {
    return request<PageResult<LessonPlan>>(
      "/api/v1/lesson-plans",
      {},
      { curriculum_plan_id: curriculumPlanId, page: 1, page_size: 20, ...query },
    );
  },
  getLessonPlan(lessonPlanId: number) {
    return request<LessonPlan>(`/api/v1/lesson-plans/${lessonPlanId}`);
  },
  exportLessonPlanDocx(lessonPlanId: number) {
    return request<FileDownloadUrl>(`/api/v1/lesson-plans/${lessonPlanId}/export-docx`, {
      method: "POST",
    });
  },
  createAssessmentTask(curriculumPlanId: number, payload?: { scene_type?: "unit_test" | "final_exam" }) {
    return request<Task>(`/api/v1/curriculum-plans/${curriculumPlanId}/assessment-tasks`, {
      method: "POST",
      body: JSON.stringify(payload ?? {}),
    });
  },
  createHomeworkTask(lessonPlanId: number) {
    return request<Task>(`/api/v1/lesson-plans/${lessonPlanId}/homework-tasks`, {
      method: "POST",
    });
  },
  getHomeworkResultByLesson(lessonPlanId: number) {
    return request<HomeworkResultDetail>(`/api/v1/lesson-plans/${lessonPlanId}/homework-result`);
  },
  listHomeworkResults(query?: { curriculum_plan_id?: number; generation_batch_id?: number; page?: number; page_size?: number }) {
    return request<PageResult<HomeworkResult>>("/api/v1/homework-results", {}, { page: 1, page_size: 20, ...query });
  },
  getHomeworkResult(homeworkResultId: number) {
    return request<HomeworkResultDetail>(`/api/v1/homework-results/${homeworkResultId}`);
  },
  exportHomeworkResultDocx(homeworkResultId: number) {
    return request<FileDownloadUrl>(`/api/v1/homework-results/${homeworkResultId}/export-docx`, {
      method: "POST",
    });
  },
  listHomeworkQuestions(query?: {
    lesson_plan_id?: number;
    homework_result_id?: number;
    knowledge_point_id?: number;
    question_type?: string;
    difficulty_level?: number;
    page?: number;
    page_size?: number;
  }) {
    return request<PageResult<HomeworkQuestionListItem>>("/api/v1/homework-questions", {}, { page: 1, page_size: 20, ...query });
  },
  listAssessmentBlueprints(
    curriculumPlanId: number,
    query?: { scenario_type?: string; page?: number; page_size?: number },
  ) {
    return request<PageResult<AssessmentBlueprint>>(
      "/api/v1/assessment-blueprints",
      {},
      { curriculum_plan_id: curriculumPlanId, page: 1, page_size: 20, ...query },
    );
  },
  getAssessmentBlueprint(assessmentBlueprintId: number) {
    return request<AssessmentBlueprint>(`/api/v1/assessment-blueprints/${assessmentBlueprintId}`);
  },
  listPaperResults(generationBatchId: number, query?: { scene_type?: string; page?: number; page_size?: number }) {
    return request<PageResult<PaperResult>>(
      "/api/v1/paper-results",
      {},
      { generation_batch_id: generationBatchId, page: 1, page_size: 20, ...query },
    );
  },
  getPaperResult(paperResultId: number) {
    return request<PaperResult>(`/api/v1/paper-results/${paperResultId}`);
  },
  exportPaperResultDocx(paperResultId: number) {
    return request<FileDownloadUrl>(`/api/v1/paper-results/${paperResultId}/export-docx`, {
      method: "POST",
    });
  },
  listQuestionItems(query?: {
    generation_batch_id?: number;
    paper_result_id?: number;
    knowledge_point_id?: number;
    question_type?: string;
    difficulty_level?: number;
    scene_type?: string;
    page?: number;
    page_size?: number;
  }) {
    return request<PageResult<QuestionBankItem>>("/api/v1/question-items", {}, { page: 1, page_size: 20, ...query });
  },
  createCoursewareTask(lessonPlanId: number) {
    return request<Task>(`/api/v1/lesson-plans/${lessonPlanId}/courseware-tasks`, {
      method: "POST",
    });
  },
  listCoursewareResults(generationBatchId: number, query?: { page?: number; page_size?: number }) {
    return request<PageResult<CoursewareResult>>(
      "/api/v1/courseware-results",
      {},
      { generation_batch_id: generationBatchId, page: 1, page_size: 20, ...query },
    );
  },
  getCoursewareResult(coursewareResultId: number) {
    return request<CoursewareResult>(`/api/v1/courseware-results/${coursewareResultId}`);
  },
  refreshCoursewareResult(coursewareResultId: number) {
    return request<CoursewareResult>(`/api/v1/courseware-results/${coursewareResultId}/refresh`, {
      method: "POST",
    });
  },
  replyCoursewareResult(coursewareResultId: number, payload: { answer: string }) {
    return request<CoursewareResult>(`/api/v1/courseware-results/${coursewareResultId}/reply`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  listCoverageReports(generationBatchId: number, query?: { page?: number; page_size?: number }) {
    return request<PageResult<CoverageReport>>(
      "/api/v1/coverage-reports",
      {},
      { generation_batch_id: generationBatchId, page: 1, page_size: 20, ...query },
    );
  },
  getCoverageReport(coverageReportId: number) {
    return request<CoverageReport>(`/api/v1/coverage-reports/${coverageReportId}`);
  },
  refreshCoverageReport(generationBatchId: number) {
    return request<CoverageReport>(`/api/v1/generation-batches/${generationBatchId}/coverage-reports/refresh`, {
      method: "POST",
    });
  },
  getFileDownloadUrl(fileObjectId: number) {
    return request<FileDownloadUrl>(`/api/v1/files/${fileObjectId}/download-url`);
  },
};
