-- @Date: 2026-05-25
-- @Author: xisy
-- @Discription: 课后作业按 lesson_plan_id 拆分重构所需的 3 张新表 DDL
-- 与 Alembic 迁移 20260525_0008_split_homework_tables 一致

SET NAMES utf8mb4;
USE `eduweave`;

SET FOREIGN_KEY_CHECKS = 0;

DROP TABLE IF EXISTS `homework_question`;
DROP TABLE IF EXISTS `homework_result`;
DROP TABLE IF EXISTS `homework_blueprint`;

CREATE TABLE `homework_blueprint` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  `lesson_plan_id` BIGINT UNSIGNED NOT NULL COMMENT '所属教案',
  `generation_batch_id` BIGINT UNSIGNED NOT NULL COMMENT '生成批次',
  `version_no` INT NOT NULL COMMENT '版本号',
  `blueprint_name` VARCHAR(255) NOT NULL COMMENT '蓝图名称',
  `version_status` VARCHAR(32) NOT NULL DEFAULT 'ready' COMMENT '版本状态',
  `strategy_json` JSON NULL COMMENT '策略配置',
  `content_json` JSON NOT NULL COMMENT '蓝图内容',
  `export_file_id` BIGINT UNSIGNED NULL COMMENT '导出文件',
  `created_by` BIGINT UNSIGNED NULL COMMENT '创建人',
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  `updated_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_homework_blueprint_lesson_version` (`lesson_plan_id`, `version_no`),
  KEY `idx_homework_blueprint_batch` (`generation_batch_id`),
  KEY `idx_homework_blueprint_lesson_status` (`lesson_plan_id`, `version_status`, `created_at`),
  CONSTRAINT `fk_homework_blueprint_lesson_plan` FOREIGN KEY (`lesson_plan_id`) REFERENCES `lesson_plan` (`id`),
  CONSTRAINT `fk_homework_blueprint_batch` FOREIGN KEY (`generation_batch_id`) REFERENCES `generation_batch` (`id`),
  CONSTRAINT `fk_homework_blueprint_export_file` FOREIGN KEY (`export_file_id`) REFERENCES `file_object` (`id`),
  CONSTRAINT `fk_homework_blueprint_created_by` FOREIGN KEY (`created_by`) REFERENCES `sys_user` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='课后作业蓝图表';

CREATE TABLE `homework_result` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  `generation_batch_id` BIGINT UNSIGNED NOT NULL COMMENT '生成批次',
  `lesson_plan_id` BIGINT UNSIGNED NOT NULL COMMENT '所属教案',
  `homework_blueprint_id` BIGINT UNSIGNED NOT NULL COMMENT '作业蓝图',
  `title` VARCHAR(255) NOT NULL COMMENT '作业标题',
  `result_status` VARCHAR(32) NOT NULL DEFAULT 'success' COMMENT '结果状态',
  `question_count` INT NOT NULL DEFAULT 0 COMMENT '题目数量',
  `difficulty_stats_json` JSON NULL COMMENT '难度统计',
  `content_json` JSON NOT NULL COMMENT '作业内容',
  `export_file_id` BIGINT UNSIGNED NULL COMMENT '导出文件',
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  `updated_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_homework_result_lesson` (`lesson_plan_id`),
  KEY `idx_homework_result_batch` (`generation_batch_id`, `lesson_plan_id`),
  KEY `idx_homework_result_blueprint` (`homework_blueprint_id`, `created_at`),
  CONSTRAINT `fk_homework_result_batch` FOREIGN KEY (`generation_batch_id`) REFERENCES `generation_batch` (`id`),
  CONSTRAINT `fk_homework_result_lesson_plan` FOREIGN KEY (`lesson_plan_id`) REFERENCES `lesson_plan` (`id`),
  CONSTRAINT `fk_homework_result_blueprint` FOREIGN KEY (`homework_blueprint_id`) REFERENCES `homework_blueprint` (`id`),
  CONSTRAINT `fk_homework_result_export_file` FOREIGN KEY (`export_file_id`) REFERENCES `file_object` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='课后作业结果表';

CREATE TABLE `homework_question` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  `generation_batch_id` BIGINT UNSIGNED NOT NULL COMMENT '生成批次',
  `homework_result_id` BIGINT UNSIGNED NOT NULL COMMENT '作业结果',
  `lesson_plan_id` BIGINT UNSIGNED NOT NULL COMMENT '所属教案',
  `knowledge_point_id` BIGINT UNSIGNED NULL COMMENT '知识点',
  `question_no` INT NOT NULL COMMENT '题号',
  `question_type` VARCHAR(32) NOT NULL COMMENT '题型',
  `difficulty_level` TINYINT UNSIGNED NULL COMMENT '难度',
  `score_value` DECIMAL(6,2) NULL COMMENT '分值',
  `stem_text` MEDIUMTEXT NOT NULL COMMENT '题干',
  `options_json` JSON NULL COMMENT '选项',
  `answer_text` TEXT NULL COMMENT '答案',
  `analysis_text` TEXT NULL COMMENT '解析',
  `source_trace_json` JSON NULL COMMENT '题目来源摘要',
  `question_basis_json` JSON NULL COMMENT '题目考查依据',
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  `updated_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_homework_question_scope` (`homework_result_id`, `question_no`),
  KEY `idx_homework_question_lesson_kp` (`lesson_plan_id`, `knowledge_point_id`),
  KEY `idx_homework_question_batch_kp` (`generation_batch_id`, `knowledge_point_id`),
  KEY `idx_homework_question_type_diff` (`question_type`, `difficulty_level`),
  CONSTRAINT `fk_homework_question_batch` FOREIGN KEY (`generation_batch_id`) REFERENCES `generation_batch` (`id`),
  CONSTRAINT `fk_homework_question_result` FOREIGN KEY (`homework_result_id`) REFERENCES `homework_result` (`id`),
  CONSTRAINT `fk_homework_question_lesson_plan` FOREIGN KEY (`lesson_plan_id`) REFERENCES `lesson_plan` (`id`),
  CONSTRAINT `fk_homework_question_knowledge_point` FOREIGN KEY (`knowledge_point_id`) REFERENCES `knowledge_point` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='课后作业题目明细表';

SET FOREIGN_KEY_CHECKS = 1;
