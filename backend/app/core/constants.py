"""
@Date: 2026-05-03
@Author: xisy
@Discription: 输入链路公共常量定义
"""

TEXTBOOK_SOURCE_BIZ_TYPE = "textbook_source"
LEARNER_PROFILE_SOURCE_BIZ_TYPE = "learner_profile_source"
COURSEWARE_EXPORT_BIZ_TYPE = "courseware_export"
CURRICULUM_EXPORT_BIZ_TYPE = "curriculum_export"
LESSON_PLAN_EXPORT_BIZ_TYPE = "lesson_plan_export"
PAPER_EXPORT_BIZ_TYPE = "paper_export"

PROJECT_MODULE_CODE = "project"
TEXTBOOK_MODULE_CODE = "textbook"
LEARNER_PROFILE_MODULE_CODE = "learner_profile"
PARSING_MODULE_CODE = "parsing"
KNOWLEDGE_MODULE_CODE = "knowledge"
TASK_CENTER_MODULE_CODE = "task_center"
FILE_ASSET_MODULE_CODE = "file_asset"
PIPELINE_MODULE_CODE = "pipeline"
CURRICULUM_MODULE_CODE = "curriculum"
LESSON_PLAN_MODULE_CODE = "lesson_plan"
ASSESSMENT_MODULE_CODE = "assessment"
COURSEWARE_MODULE_CODE = "courseware"
COVERAGE_MODULE_CODE = "coverage"

TASK_STATUS_PENDING = "pending"
TASK_STATUS_PROCESSING = "processing"
TASK_STATUS_SUCCESS = "success"
TASK_STATUS_PARTIAL_SUCCESS = "partial_success"
TASK_STATUS_FAILURE = "failure"
TASK_STATUS_CANCELLED = "cancelled"

PROFILE_EXTRACT_TASK_TYPE = "learner_profile_extract"
TEXTBOOK_PARSE_TASK_TYPE = "textbook_parse"
TEXTBOOK_REPARSE_TASK_TYPE = "textbook_reparse"
KNOWLEDGE_EXTRACT_TASK_TYPE = "knowledge_extract"
CURRICULUM_GENERATE_TASK_TYPE = "curriculum_generate"
LESSON_PLAN_GENERATE_TASK_TYPE = "lesson_plan_generate"
ASSESSMENT_GENERATE_TASK_TYPE = "assessment_generate"
COURSEWARE_GENERATE_TASK_TYPE = "courseware_generate"
COVERAGE_ANALYZE_TASK_TYPE = "coverage_analyze"

PROFILE_QUEUE_NAME = "profile_queue"
PARSING_QUEUE_NAME = "parsing_queue"
KNOWLEDGE_QUEUE_NAME = "knowledge_queue"
GENERATION_QUEUE_NAME = "generation_queue"

PARSE_MODE_FULL = "full"
PARSE_STATUS_PENDING = "pending"
PARSE_STATUS_PROCESSING = "processing"
PARSE_STATUS_SUCCESS = "success"
PARSE_STATUS_FAILURE = "failure"

REVIEW_STATUS_PENDING = "pending"
REVIEW_STATUS_CONFIRMED = "confirmed"
VERSION_STATUS_READY = "ready"
VERSION_STATUS_ARCHIVED = "archived"

MINERU_STRATEGY_VLM_DEFAULT = "mineru_vlm_default"
MINERU_STRATEGY_VLM_OCR = "mineru_vlm_ocr"
MINERU_STRATEGY_DOC_DEFAULT = "mineru_doc_default"
SUPPORTED_MINERU_STRATEGIES = {
    MINERU_STRATEGY_VLM_DEFAULT,
    MINERU_STRATEGY_VLM_OCR,
    MINERU_STRATEGY_DOC_DEFAULT,
}
