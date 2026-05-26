-- @Date: 2026-05-26
-- @Author: xisy
-- @Discription: Phase2 一键生成编排基础设施落库 SQL，
--               与 backend/migrations/versions/20260526_0010_phase2_orchestration.py 对齐
-- 主要变更：
--   1. task_record 增加心跳与执行实例 ID
--   2. 新增 generation_run 表，承载后端全权编排的一次生成运行
--   3. project 增加 active_generation_run_id 外键

ALTER TABLE `task_record`
  ADD COLUMN `last_heartbeat_at` DATETIME(3) NULL COMMENT '最近心跳时间' AFTER `finished_at`,
  ADD COLUMN `execution_attempt_id` VARCHAR(36) NULL COMMENT '本次执行实例ID' AFTER `last_heartbeat_at`;

CREATE TABLE IF NOT EXISTS `generation_run` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  `project_id` BIGINT UNSIGNED NOT NULL COMMENT '所属项目',
  `run_status` VARCHAR(32) NOT NULL DEFAULT 'pending'
    COMMENT '运行状态：pending/running/waiting_user_confirm/succeeded/failed/cancelled',
  `course_count` INT NOT NULL COMMENT '课次数',
  `session_duration_minutes` INT NOT NULL COMMENT '单次时长',
  `chapter_range_json` JSON NULL COMMENT '章节范围',
  `auto_confirm_parse` TINYINT(1) NOT NULL DEFAULT 1 COMMENT '解析自动确认开关',
  `parse_version_id` BIGINT UNSIGNED NULL COMMENT '本次运行使用的解析版本',
  `knowledge_version_id` BIGINT UNSIGNED NULL COMMENT '本次运行使用的知识版本',
  `generation_batch_id` BIGINT UNSIGNED NULL COMMENT '本次运行创建的生成批次',
  `last_error_code` VARCHAR(64) NULL COMMENT '错误码',
  `last_error_message` VARCHAR(500) NULL COMMENT '错误信息',
  `blocked_reason` VARCHAR(64) NULL COMMENT '阻塞原因编码',
  `started_at` DATETIME(3) NULL COMMENT '开始时间',
  `finished_at` DATETIME(3) NULL COMMENT '结束时间',
  `created_by` BIGINT UNSIGNED NULL COMMENT '创建人',
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  `updated_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (`id`),
  KEY `idx_generation_run_project_status` (`project_id`, `run_status`, `created_at`),
  CONSTRAINT `fk_generation_run_project` FOREIGN KEY (`project_id`) REFERENCES `project` (`id`),
  CONSTRAINT `fk_generation_run_parse_version` FOREIGN KEY (`parse_version_id`) REFERENCES `parse_version` (`id`),
  CONSTRAINT `fk_generation_run_knowledge_version` FOREIGN KEY (`knowledge_version_id`) REFERENCES `knowledge_version` (`id`),
  CONSTRAINT `fk_generation_run_generation_batch` FOREIGN KEY (`generation_batch_id`) REFERENCES `generation_batch` (`id`),
  CONSTRAINT `fk_generation_run_created_by` FOREIGN KEY (`created_by`) REFERENCES `sys_user` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='一键生成运行表';

ALTER TABLE `project`
  ADD COLUMN `active_generation_run_id` BIGINT UNSIGNED NULL COMMENT '当前活跃一键生成运行' AFTER `latest_generation_batch_id`,
  ADD CONSTRAINT `fk_project_active_generation_run` FOREIGN KEY (`active_generation_run_id`) REFERENCES `generation_run` (`id`);
