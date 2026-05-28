-- @Date: 2026-05-28
-- @Author: xisy
-- @Discription: 多课时教案课次级生成恢复中间表 SQL，
--               与 backend/migrations/versions/20260528_0012_lesson_plan_generation_recovery.py 对齐

CREATE TABLE IF NOT EXISTS `lesson_plan_generation_item` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  `generation_batch_id` BIGINT UNSIGNED NOT NULL COMMENT '生成批次',
  `task_record_id` BIGINT UNSIGNED NULL COMMENT '任务主表',
  `class_session_no` INT NOT NULL COMMENT '课次序号',
  `lesson_title` VARCHAR(255) NULL COMMENT '课次标题',
  `item_status` VARCHAR(32) NOT NULL DEFAULT 'pending' COMMENT '课次生成状态：pending/processing/success/failure',
  `summary_text` TEXT NULL COMMENT '摘要',
  `content_json` JSON NULL COMMENT '教案内容',
  `llm_usage_json` JSON NULL COMMENT 'LLM 用量',
  `last_error_code` VARCHAR(64) NULL COMMENT '错误码',
  `last_error_message` VARCHAR(500) NULL COMMENT '错误信息',
  `last_error_detail_json` JSON NULL COMMENT '错误详情',
  `retry_count` INT NOT NULL DEFAULT 0 COMMENT '重试次数',
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  `updated_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_lesson_plan_generation_item_session` (`generation_batch_id`, `class_session_no`),
  KEY `idx_lesson_plan_generation_item_task` (`task_record_id`, `item_status`),
  KEY `idx_lesson_plan_generation_item_batch_status` (`generation_batch_id`, `item_status`),
  CONSTRAINT `fk_lesson_plan_generation_item_batch` FOREIGN KEY (`generation_batch_id`) REFERENCES `generation_batch` (`id`),
  CONSTRAINT `fk_lesson_plan_generation_item_task` FOREIGN KEY (`task_record_id`) REFERENCES `task_record` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='教案课次生成中间结果表';
