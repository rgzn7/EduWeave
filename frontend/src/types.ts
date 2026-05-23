export type ApiEnvelope<T> = {
  success: boolean;
  code: number;
  message: string;
  data?: T;
  timestamp: string;
  request_id: string;
  errors?: ApiErrorItem[];
};

export type ApiErrorItem = {
  code: string;
  message: string;
  details?: unknown;
  field?: unknown;
};

export type JsonRecord = Record<string, unknown>;

export type Pagination = {
  total_count: number;
  page: number;
  page_size: number;
  total_pages: number;
  has_previous: boolean;
  has_next: boolean;
};

export type PageResult<T> = {
  items: T[];
  pagination: Pagination;
};

export type AuthUser = {
  id: number;
  username: string;
  display_name: string;
  role_code: string;
  status: string;
};

export type LoginResult = {
  access_token: string;
  token_type: string;
  expires_in: number;
  user: AuthUser;
};

export type Project = {
  id: number;
  project_code?: string | null;
  name: string;
  subject_code: string;
  grade_code: string;
  applicable_target?: string | null;
  remark?: string | null;
  status: string;
  current_textbook_version_id?: number | null;
  current_learner_profile_version_id?: number | null;
  latest_generation_batch_id?: number | null;
  last_activity_at?: string | null;
  created_at: string;
  updated_at: string;
  owner_user_id?: number;
  current_textbook?: JsonRecord | null;
  current_learner_profile?: JsonRecord | null;
};

export type ProjectDashboard = {
  project: Project;
  stats: JsonRecord;
  recent_tasks: Task[];
};

export type TextbookVersion = {
  id: number;
  project_id: number;
  version_no: number;
  textbook_name: string;
  subject_code: string;
  grade_code: string;
  page_count?: number | null;
  parse_status: string;
  version_status: string;
  is_current: boolean;
  source_file?: JsonRecord;
  created_at: string;
  updated_at: string;
};

export type LearnerProfileFile = {
  id: number;
  project_id: number;
  source_file_id: number;
  title: string;
  file_status: string;
  source_file?: JsonRecord;
  latest_version?: LearnerProfileVersion | null;
  created_at: string;
  updated_at: string;
};

export type LearnerProfileVersion = {
  id: number;
  project_id: number;
  profile_file_id: number;
  version_no: number;
  grade_code?: string | null;
  subject_scope?: string | null;
  extract_status: string;
  review_status: string;
  version_status: string;
  summary_text?: string | null;
  created_at: string;
  updated_at: string;
};

export type ParseVersion = {
  id: number;
  project_id: number;
  textbook_version_id: number;
  version_no: number;
  parse_mode: string;
  strategy_code: string;
  parse_status: string;
  review_status: string;
  version_status: string;
  page_count?: number | null;
  issue_count: number;
  created_at: string;
  updated_at: string;
};

export type ParseEvidenceExample = {
  page_no?: number | null;
  block_id?: number | string | null;
  block_no?: number | string | null;
  block_type?: string | null;
  text_snippet?: string | null;
  resource_file_id?: number | null;
};

export type ParseEvidenceSummary = {
  parse_version_id: number;
  strategy_code?: string | null;
  mineru_model?: string | null;
  parse_status?: string | null;
  review_status?: string | null;
  page_count?: number | null;
  block_count?: number | null;
  issue_count?: number | null;
  block_type_stats?: JsonRecord | null;
  media_stats?: JsonRecord | null;
  mineru_options?: JsonRecord | null;
  sample_evidence?: ParseEvidenceExample[];
};

export type KnowledgeVersion = {
  id: number;
  project_id: number;
  parse_version_id: number;
  version_no: number;
  version_status: string;
  summary_json?: JsonRecord | null;
  chapter_count: number;
  point_count: number;
  created_at: string;
  updated_at: string;
};

export type GenerationBatch = {
  id: number;
  project_id: number;
  batch_no: number;
  batch_name?: string | null;
  trigger_mode: string;
  batch_status: string;
  knowledge_version_id: number;
  learner_profile_version_id: number;
  chapter_range_json?: JsonRecord | null;
  course_count?: number | null;
  session_duration_minutes?: number | null;
  template_snapshot_json?: JsonRecord | null;
  assessment_strategy_json?: JsonRecord | null;
  pipeline_options_json?: JsonRecord | null;
  curriculum_plan_id?: number | null;
  lesson_plan_id?: number | null;
  lesson_plan_ids?: number[] | null;
  tasks?: Task[];
  started_at?: string | null;
  finished_at?: string | null;
  created_by?: number | null;
  created_at: string;
  updated_at: string;
};

export type FileDownloadUrl = {
  file_object_id: number;
  bucket_name: string;
  object_key: string;
  signed_url: string | null;
  expires_in_seconds: number;
  generated_at: string;
};

export type CurriculumPlan = {
  id: number;
  project_id: number;
  knowledge_version_id: number;
  learner_profile_version_id: number;
  parent_plan_id?: number | null;
  version_no: number;
  plan_title: string;
  target_subject_code: string;
  target_grade_code?: string | null;
  chapter_range_json?: JsonRecord | null;
  course_count: number;
  session_duration_minutes: number;
  generation_mode: string;
  version_status: string;
  summary_text?: string | null;
  content_json: JsonRecord | null;
  export_file_id?: number | null;
  created_by?: number | null;
  created_at: string;
  updated_at: string;
};

export type LessonPlan = {
  id: number;
  curriculum_plan_id: number;
  generation_batch_id?: number | null;
  class_session_no?: number | null;
  version_no: number;
  lesson_title: string;
  style_code?: string | null;
  version_status: string;
  summary_text?: string | null;
  content_json: JsonRecord | null;
  export_file_id?: number | null;
  created_by?: number | null;
  created_at: string;
  updated_at: string;
};

export type AssessmentBlueprint = {
  id: number;
  curriculum_plan_id: number;
  version_no: number;
  scenario_type: string;
  blueprint_name: string;
  version_status: string;
  strategy_json?: JsonRecord | null;
  content_json: JsonRecord | null;
  export_file_id?: number | null;
  created_by?: number | null;
  created_at: string;
  updated_at: string;
};

export type QuestionItem = {
  id: number;
  generation_batch_id: number;
  paper_result_id: number;
  knowledge_point_id?: number | null;
  question_no: number;
  question_type: string;
  difficulty_level?: number | null;
  score_value?: number | null;
  stem_text: string;
  options_json?: JsonRecord | null;
  answer_text?: string | null;
  analysis_text?: string | null;
  source_trace_json?: JsonRecord | null;
  created_at: string;
  updated_at: string;
};

export type QuestionBankItem = QuestionItem & {
  scene_type?: string | null;
  paper_title?: string | null;
  knowledge_point_name?: string | null;
};

export type PaperResult = {
  id: number;
  generation_batch_id: number;
  assessment_blueprint_id: number;
  scene_type: string;
  title: string;
  result_status: string;
  question_count: number;
  difficulty_stats_json?: JsonRecord | null;
  paper_json: JsonRecord | null;
  export_file_id?: number | null;
  questions?: QuestionItem[];
  created_at: string;
  updated_at: string;
};

export type CoursewareResult = {
  id: number;
  generation_batch_id: number;
  lesson_plan_id: number;
  template_code?: string | null;
  template_version?: string | null;
  result_status: string;
  page_count?: number | null;
  page_type_stats_json?: JsonRecord | null;
  structure_json: JsonRecord | null;
  preview_json?: JsonRecord | null;
  export_file_id?: number | null;
  created_at: string;
  updated_at: string;
};

export type CoverageReport = {
  id: number;
  generation_batch_id: number;
  report_status: string;
  coverage_rate?: number | null;
  warning_count: number;
  coverage_summary_json?: JsonRecord | null;
  report_json: JsonRecord | null;
  export_file_id?: number | null;
  created_at: string;
  updated_at: string;
};

export type TaskStep = {
  id: number;
  step_code: string;
  step_name: string;
  step_order: number;
  step_status: string;
  progress_percent: number;
  detail_json?: JsonRecord | null;
  started_at?: string | null;
  finished_at?: string | null;
  created_at: string;
  updated_at: string;
};

export type Task = {
  id: number;
  project_id: number;
  generation_batch_id?: number | null;
  module_code: string;
  task_type: string;
  biz_key?: string | null;
  task_status: "pending" | "running" | "processing" | "success" | "failed" | "failure" | "error" | "cancelled" | string;
  queue_name?: string | null;
  current_stage?: string | null;
  progress_percent: number;
  retry_count: number;
  max_retry_count: number;
  worker_task_id?: string | null;
  last_error_code?: string | null;
  last_error_message?: string | null;
  payload_json?: JsonRecord | null;
  result_json?: JsonRecord | null;
  started_at?: string | null;
  finished_at?: string | null;
  created_at: string;
  updated_at: string;
};

export type TaskDetail = Task & {
  steps: TaskStep[];
};

export type CreateProjectPayload = {
  name: string;
  subject_code: string;
  grade_code: string;
  applicable_target?: string;
  remark?: string;
};

export type CreateGenerationBatchPayload = {
  project_id: number;
  knowledge_version_id: number;
  learner_profile_version_id: number;
  batch_name?: string;
  chapter_range_json?: JsonRecord | null;
  course_count: number;
  session_duration_minutes: number;
};
