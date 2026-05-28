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
  publisher?: string | null;
  subject_code: string;
  grade_code: string;
  volume_code?: string | null;
  edition_label?: string | null;
  isbn?: string | null;
  page_count?: number | null;
  parse_status: string;
  version_status: string;
  remark?: string | null;
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

export type LearnerProfileSubjectOverview = {
  subject_code: string;
  student_count: number;
  score_avg: number;
  score_min: number;
  score_max: number;
  high_count: number;
  mid_count: number;
  low_count: number;
  summary: string;
};

export type LearnerProfileTieredGroup = {
  tier: "high" | "mid" | "low" | string;
  student_keys: string[];
  teaching_suggestions: string[];
};

export type LearnerClassProfile = {
  class_summary: string;
  grade_consistency?: string | null;
  region_consistency?: string | null;
  warnings?: string[];
  subject_overview?: LearnerProfileSubjectOverview[];
  common_strengths?: string[];
  common_weaknesses?: string[];
  common_habits?: string[];
  common_behaviors?: string[];
  tiered_groups?: LearnerProfileTieredGroup[];
  teaching_recommendations?: string[];
};

export type LearnerProfileVersion = {
  id: number;
  project_id: number;
  profile_file_id: number;
  parent_version_id?: number | null;
  version_no: number;
  textbook_version_hint_id?: number | null;
  grade_code?: string | null;
  subject_scope?: string | null;
  extract_status: string;
  review_status: string;
  version_status: string;
  summary_text?: string | null;
  class_profile?: LearnerClassProfile | null;
  raw_result_json?: JsonRecord | null;
  source_snapshot_json?: JsonRecord | null;
  created_by?: number | null;
  created_at: string;
  updated_at: string;
};

export type LearnerProfileRecord = {
  id: number;
  project_id: number;
  profile_version_id: number;
  student_key: string;
  student_name?: string | null;
  is_anonymous: boolean;
  region_name?: string | null;
  grade_code?: string | null;
  subject_code: string;
  textbook_version_hint_id?: number | null;
  score_value?: number | null;
  advantage_tags_json?: JsonRecord | null;
  weakness_tags_json?: JsonRecord | null;
  ability_tags_json?: JsonRecord | null;
  habit_tags_json?: JsonRecord | null;
  behavior_traits_json?: JsonRecord | null;
  time_plan_json?: JsonRecord | null;
  summary_text?: string | null;
  evidence_json?: JsonRecord | null;
  sort_order: number;
  created_at: string;
  updated_at: string;
};

export type LearnerProfileVersionDetail = LearnerProfileVersion & {
  records: LearnerProfileRecord[];
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

export type ParseEvidenceVolume = {
  page_count: number;
  parsed_page_count: number;
  block_count: number;
  issue_count: number;
  asset_block_count: number;
  bbox_block_count: number;
  image_block_count: number;
  table_block_count: number;
  equation_block_count: number;
};

export type ParseEvidenceBlockTypeCount = {
  block_type: string;
  count: number;
};

export type ParseEvidenceMineruParameters = {
  strategy_code: string;
  model_version?: string | null;
  is_ocr: boolean;
  enable_formula: boolean;
  enable_table: boolean;
};

export type ParseEvidenceSampleBlock = {
  parse_page_id: number;
  parse_block_id: number;
  page_no: number;
  block_no: number;
  block_type: string;
  heading_level?: number | null;
  text_excerpt?: string | null;
  bbox_json?: JsonRecord | null;
  asset_file_id?: number | null;
};

export type ParseEvidenceSummary = {
  parse_version_id: number;
  textbook_version_id?: number;
  strategy_code?: string | null;
  mineru_model?: string | null;
  parse_status?: string | null;
  review_status?: string | null;
  version_status?: string | null;
  volume?: ParseEvidenceVolume;
  block_type_counts?: ParseEvidenceBlockTypeCount[];
  mineru_parameters?: ParseEvidenceMineruParameters;
  sample_blocks?: ParseEvidenceSampleBlock[];
  /** Legacy placeholder shape kept so older mocked/dev responses do not break the page. */
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

export type KnowledgeChapter = {
  id: number;
  knowledge_version_id: number;
  parent_id?: number | null;
  node_path: string;
  node_no: number;
  node_level: number;
  node_type: string;
  title: string;
  summary_text?: string | null;
  page_start?: number | null;
  page_end?: number | null;
  line_start?: number | null;
  line_end?: number | null;
  sort_order: number;
  created_at: string;
  updated_at: string;
};

export type KnowledgePoint = {
  id: number;
  knowledge_version_id: number;
  chapter_node_id?: number | null;
  chapter_title?: string | null;
  point_code?: string | null;
  point_name: string;
  point_type: string;
  importance_level?: number | null;
  difficulty_level?: number | null;
  mastery_level_hint?: string | null;
  tags_json?: JsonRecord | null;
  summary_text?: string | null;
  sort_order: number;
  evidence_count: number;
  created_at: string;
  updated_at: string;
};

export type KnowledgeEvidence = {
  id: number;
  knowledge_point_id: number;
  semantic_chunk_id?: number | null;
  parse_version_id: number;
  parse_page_id?: number | null;
  parse_block_id?: number | null;
  source_file_id?: number | null;
  evidence_type: string;
  page_no?: number | null;
  excerpt_text?: string | null;
  bbox_json?: JsonRecord | null;
  score_value?: number | null;
  created_at: string;
};

export type KnowledgePointDetail = KnowledgePoint & {
  evidences: KnowledgeEvidence[];
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

export type GenerationRunStatus = "pending" | "running" | "waiting_user_confirm" | "succeeded" | "failed" | "cancelled";

export type GenerationRunCreatePayload = {
  course_count: number;
  session_duration_minutes: number;
  chapter_range_json?: JsonRecord | null;
  auto_confirm_parse?: boolean;
};

export type GenerationRun = {
  id: number;
  project_id: number;
  run_status: GenerationRunStatus;
  course_count: number;
  session_duration_minutes: number;
  chapter_range_json?: JsonRecord | null;
  auto_confirm_parse: boolean;
  parse_version_id?: number | null;
  knowledge_version_id?: number | null;
  generation_batch_id?: number | null;
  blocked_reason?: string | null;
  last_error_code?: string | null;
  last_error_message?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  created_at: string;
  updated_at: string;
};

export type GenerationProcessStatus = "pending" | "running" | "succeeded" | "failed";
export type GenerationProcessStatusDetail = "waiting_dispatch" | "waiting_user_confirm" | "retrying" | "blocked";
export type GenerationProcessStepStatusDetail = "retrying" | "waiting_dispatch";

export type GenerationProcessStep = {
  code: string;
  display_name: string;
  description: string;
  status: GenerationProcessStatus;
  status_detail?: GenerationProcessStepStatusDetail | null;
  progress_percent: number;
  current_stage?: string | null;
  progress_detail?: JsonRecord | null;
  result_detail?: JsonRecord | null;
  summary?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  error_message?: string | null;
};

export type GenerationProcess = {
  project_id: number;
  batch_id?: number | null;
  generation_run_id?: number | null;
  status: GenerationProcessStatus;
  status_detail?: GenerationProcessStatusDetail | null;
  blocked_reason?: string | null;
  current_step_code?: string | null;
  steps: GenerationProcessStep[];
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

export type QuestionBasisSource = JsonRecord & {
  blueprint_type?: string | null;
  blueprint_id?: number | null;
  weight_percent?: number | string | null;
  suggested_question_count?: number | string | null;
};

export type QuestionBasis = JsonRecord & {
  knowledge_point_id?: number | null;
  knowledge_point_name?: string | null;
  knowledge_point_summary?: string | null;
  chapter_title?: string | null;
  lesson_no?: number | null;
  lesson_title?: string | null;
  teaching_goal?: string | null;
  assessment_position?: string | null;
  basis_summary?: string | null;
  source?: QuestionBasisSource | null;
};

export type QuestionItem = {
  id: number;
  generation_batch_id: number;
  paper_result_id: number;
  knowledge_point_id?: number | null;
  knowledge_point_name?: string | null;
  question_no: number;
  question_type: string;
  difficulty_level?: number | null;
  score_value?: number | null;
  stem_text: string;
  options_json?: JsonRecord | null;
  answer_text?: string | null;
  analysis_text?: string | null;
  source_trace_json?: JsonRecord | null;
  question_basis_json?: QuestionBasis | null;
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

export type HomeworkQuestion = {
  id: number;
  generation_batch_id: number;
  homework_result_id: number;
  lesson_plan_id: number;
  knowledge_point_id?: number | null;
  knowledge_point_name?: string | null;
  question_no: number;
  question_type: string;
  difficulty_level?: number | null;
  score_value?: number | null;
  stem_text: string;
  options_json?: JsonRecord | null;
  answer_text?: string | null;
  analysis_text?: string | null;
  source_trace_json?: JsonRecord | null;
  question_basis_json?: QuestionBasis | null;
  created_at: string;
  updated_at: string;
};

export type HomeworkResult = {
  id: number;
  generation_batch_id: number;
  lesson_plan_id: number;
  homework_blueprint_id: number;
  title: string;
  result_status: string;
  question_count: number;
  difficulty_stats_json?: JsonRecord | null;
  content_json: JsonRecord | null;
  export_file_id?: number | null;
  class_session_no?: number | null;
  lesson_title?: string | null;
  created_at: string;
  updated_at: string;
};

export type HomeworkResultDetail = HomeworkResult & {
  questions: HomeworkQuestion[];
};

export type HomeworkQuestionListItem = HomeworkQuestion & {
  homework_title: string;
  class_session_no?: number | null;
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
