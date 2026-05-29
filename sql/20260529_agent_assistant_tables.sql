-- @Date: 2026-05-29
-- @Author: xisy
-- @Discription: 项目级智能助手（EduWeave Agent）相关表：会话/消息/运行/运行事件/运行工件

SET NAMES utf8mb4;

-- 智能助手会话表
CREATE TABLE IF NOT EXISTS `agent_session` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  `user_id` BIGINT UNSIGNED NOT NULL COMMENT '所属教师',
  `project_id` BIGINT UNSIGNED NULL COMMENT '所属项目（项目级助手范围；单页全局会话可为空）',
  `title` VARCHAR(255) NULL COMMENT '会话标题',
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  `updated_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (`id`),
  KEY `idx_agent_session_user` (`user_id`, `updated_at`),
  KEY `idx_agent_session_project` (`project_id`, `updated_at`),
  CONSTRAINT `fk_agent_session_user` FOREIGN KEY (`user_id`) REFERENCES `sys_user` (`id`),
  CONSTRAINT `fk_agent_session_project` FOREIGN KEY (`project_id`) REFERENCES `project` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='智能助手会话表';

-- 智能助手消息表
CREATE TABLE IF NOT EXISTS `agent_message` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  `session_id` BIGINT UNSIGNED NOT NULL COMMENT '所属会话',
  `user_id` BIGINT UNSIGNED NOT NULL COMMENT '所属教师',
  `run_id` BIGINT UNSIGNED NULL COMMENT '产出该消息的运行',
  `role` VARCHAR(32) NOT NULL COMMENT '消息角色：user/assistant',
  `content` MEDIUMTEXT NULL COMMENT '消息内容',
  `metadata_json` JSON NULL COMMENT '附加元数据',
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  PRIMARY KEY (`id`),
  KEY `idx_agent_message_session` (`session_id`, `id`),
  KEY `idx_agent_message_run` (`run_id`),
  CONSTRAINT `fk_agent_message_session` FOREIGN KEY (`session_id`) REFERENCES `agent_session` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='智能助手消息表';

-- 智能助手运行表
CREATE TABLE IF NOT EXISTS `agent_run` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  `session_id` BIGINT UNSIGNED NOT NULL COMMENT '所属会话',
  `project_id` BIGINT UNSIGNED NULL COMMENT '所属项目',
  `user_id` BIGINT UNSIGNED NOT NULL COMMENT '所属教师',
  `user_message_id` BIGINT UNSIGNED NULL COMMENT '触发运行的用户消息',
  `assistant_message_id` BIGINT UNSIGNED NULL COMMENT '运行成功落库的助手消息',
  `status` VARCHAR(32) NOT NULL DEFAULT 'pending' COMMENT '运行状态：pending/running/succeeded/failed/cancelled',
  `context_json` JSON NULL COMMENT '所在课次教案上下文：{project_id,curriculum_plan_id,class_session_no,lesson_plan_id}',
  `attempt_count` INT NOT NULL DEFAULT 0 COMMENT '已尝试次数',
  `max_attempts` INT NOT NULL DEFAULT 3 COMMENT '最大尝试次数',
  `available_at` DATETIME(3) NOT NULL COMMENT '可被抢占的时间',
  `locked_by` VARCHAR(64) NOT NULL DEFAULT '' COMMENT '持锁 worker',
  `lease_expires_at` DATETIME(3) NULL COMMENT '租约过期时间',
  `last_error_code` VARCHAR(64) NULL COMMENT '最近错误码',
  `error_message` TEXT NULL COMMENT '最近错误信息',
  `final_response` MEDIUMTEXT NULL COMMENT '最终回答文本',
  `started_at` DATETIME(3) NULL COMMENT '开始执行时间',
  `completed_at` DATETIME(3) NULL COMMENT '结束时间',
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  `updated_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (`id`),
  KEY `idx_agent_run_queue` (`status`, `available_at`),
  KEY `idx_agent_run_session` (`session_id`, `id`),
  CONSTRAINT `fk_agent_run_session` FOREIGN KEY (`session_id`) REFERENCES `agent_session` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='智能助手运行表';

-- 智能助手运行事件表
CREATE TABLE IF NOT EXISTS `agent_run_event` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  `run_id` BIGINT UNSIGNED NOT NULL COMMENT '所属运行',
  `session_id` BIGINT UNSIGNED NOT NULL COMMENT '所属会话',
  `seq` INT NOT NULL COMMENT '运行内自增序号',
  `event_type` VARCHAR(32) NOT NULL COMMENT '事件类型',
  `title` VARCHAR(255) NULL COMMENT '事件标题',
  `message` TEXT NULL COMMENT '事件描述',
  `payload_json` JSON NULL COMMENT '事件载荷',
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_agent_run_event_seq` (`run_id`, `seq`),
  CONSTRAINT `fk_agent_run_event_run` FOREIGN KEY (`run_id`) REFERENCES `agent_run` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='智能助手运行事件表';

-- 智能助手运行工件表
CREATE TABLE IF NOT EXISTS `agent_artifact` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  `session_id` BIGINT UNSIGNED NOT NULL COMMENT '所属会话',
  `source_tool` VARCHAR(64) NOT NULL COMMENT '来源工具名',
  `content_hash` VARCHAR(64) NOT NULL COMMENT '内容哈希（去重）',
  `title` VARCHAR(255) NULL COMMENT '工件标题',
  `summary` TEXT NULL COMMENT '工件摘要预览',
  `content_text` MEDIUMTEXT NOT NULL COMMENT '工件全文',
  `superseded_at` DATETIME(3) NULL COMMENT '失效时间',
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  `updated_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_agent_artifact_hash` (`session_id`, `source_tool`, `content_hash`),
  KEY `idx_agent_artifact_session` (`session_id`, `id`),
  CONSTRAINT `fk_agent_artifact_session` FOREIGN KEY (`session_id`) REFERENCES `agent_session` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='智能助手运行工件表';
