-- @Date: 2026-04-30
-- @Author: xisy
-- @Discription: EduWeave MySQL 31张表初始化脚本

SET NAMES utf8mb4;
CREATE DATABASE IF NOT EXISTS `eduweave`
  DEFAULT CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;
USE `eduweave`;

SET FOREIGN_KEY_CHECKS = 0;

DROP TABLE IF EXISTS `audit_log`;
DROP TABLE IF EXISTS `generation_trace`;
DROP TABLE IF EXISTS `task_step_record`;
DROP TABLE IF EXISTS `task_record`;
DROP TABLE IF EXISTS `coverage_report`;
DROP TABLE IF EXISTS `homework_question`;
DROP TABLE IF EXISTS `homework_result`;
DROP TABLE IF EXISTS `homework_blueprint`;
DROP TABLE IF EXISTS `question_item`;
DROP TABLE IF EXISTS `paper_result`;
DROP TABLE IF EXISTS `courseware_result`;
DROP TABLE IF EXISTS `generation_batch`;
DROP TABLE IF EXISTS `assessment_blueprint`;
DROP TABLE IF EXISTS `lesson_plan`;
DROP TABLE IF EXISTS `curriculum_plan`;
DROP TABLE IF EXISTS `knowledge_evidence`;
DROP TABLE IF EXISTS `knowledge_point`;
DROP TABLE IF EXISTS `semantic_chunk`;
DROP TABLE IF EXISTS `chapter_node`;
DROP TABLE IF EXISTS `knowledge_version`;
DROP TABLE IF EXISTS `parse_issue`;
DROP TABLE IF EXISTS `parse_block`;
DROP TABLE IF EXISTS `parse_page`;
DROP TABLE IF EXISTS `parse_version`;
DROP TABLE IF EXISTS `learner_profile_record`;
DROP TABLE IF EXISTS `learner_profile_version`;
DROP TABLE IF EXISTS `learner_profile_file`;
DROP TABLE IF EXISTS `textbook_version`;
DROP TABLE IF EXISTS `file_object`;
DROP TABLE IF EXISTS `project`;
DROP TABLE IF EXISTS `sys_user`;

SET FOREIGN_KEY_CHECKS = 1;

CREATE TABLE `sys_user` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  `username` VARCHAR(64) NOT NULL COMMENT '登录用户名',
  `display_name` VARCHAR(64) NOT NULL COMMENT '显示名称',
  `password_hash` VARCHAR(255) NOT NULL COMMENT '密码哈希',
  `role_code` VARCHAR(32) NOT NULL DEFAULT 'teacher' COMMENT '角色编码',
  `status` VARCHAR(32) NOT NULL DEFAULT 'active' COMMENT '状态：active/disabled',
  `last_login_at` DATETIME(3) NULL COMMENT '最近登录时间',
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  `updated_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_sys_user_username` (`username`),
  KEY `idx_sys_user_role_status` (`role_code`, `status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='系统用户表';

CREATE TABLE `project` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  `owner_user_id` BIGINT UNSIGNED NOT NULL COMMENT '负责人',
  `project_code` VARCHAR(64) NULL COMMENT '项目编码',
  `name` VARCHAR(128) NOT NULL COMMENT '项目名称',
  `subject_code` VARCHAR(32) NOT NULL COMMENT '学科编码',
  `grade_code` VARCHAR(32) NOT NULL COMMENT '年级编码',
  `applicable_target` VARCHAR(255) NULL COMMENT '适用对象',
  `remark` VARCHAR(500) NULL COMMENT '备注',
  `status` VARCHAR(32) NOT NULL DEFAULT 'active' COMMENT '状态：active/archived/disabled',
  `current_textbook_version_id` BIGINT UNSIGNED NULL COMMENT '当前教材版本',
  `current_learner_profile_version_id` BIGINT UNSIGNED NULL COMMENT '当前学情版本',
  `latest_generation_batch_id` BIGINT UNSIGNED NULL COMMENT '最近生成批次',
  `last_activity_at` DATETIME(3) NULL COMMENT '最近活动时间',
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  `updated_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_project_project_code` (`project_code`),
  KEY `idx_project_owner_status` (`owner_user_id`, `status`),
  KEY `idx_project_subject_grade` (`subject_code`, `grade_code`),
  CONSTRAINT `fk_project_owner_user` FOREIGN KEY (`owner_user_id`) REFERENCES `sys_user` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='项目表';

CREATE TABLE `file_object` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  `project_id` BIGINT UNSIGNED NOT NULL COMMENT '所属项目',
  `biz_type` VARCHAR(32) NOT NULL COMMENT '文件业务类型',
  `storage_provider` VARCHAR(32) NOT NULL DEFAULT 'obs' COMMENT '存储提供商',
  `bucket_name` VARCHAR(128) NOT NULL COMMENT '存储桶',
  `object_key` VARCHAR(512) NOT NULL COMMENT '对象路径',
  `original_filename` VARCHAR(255) NOT NULL COMMENT '原始文件名',
  `file_ext` VARCHAR(32) NULL COMMENT '扩展名',
  `mime_type` VARCHAR(128) NULL COMMENT 'MIME类型',
  `file_size` BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '文件大小',
  `content_hash` VARCHAR(128) NOT NULL COMMENT '文件哈希',
  `source_type` VARCHAR(32) NOT NULL DEFAULT 'user_upload' COMMENT '来源类型',
  `upload_status` VARCHAR(32) NOT NULL DEFAULT 'uploaded' COMMENT '上传状态',
  `uploaded_by` BIGINT UNSIGNED NULL COMMENT '上传人',
  `metadata_json` JSON NULL COMMENT '附加元数据',
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  `updated_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_file_object_bucket_key` (`bucket_name`, `object_key`),
  KEY `idx_file_object_project_biz` (`project_id`, `biz_type`),
  KEY `idx_file_object_hash` (`content_hash`),
  CONSTRAINT `fk_file_object_project` FOREIGN KEY (`project_id`) REFERENCES `project` (`id`),
  CONSTRAINT `fk_file_object_uploaded_by` FOREIGN KEY (`uploaded_by`) REFERENCES `sys_user` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='统一文件对象表';

CREATE TABLE `textbook_version` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  `project_id` BIGINT UNSIGNED NOT NULL COMMENT '所属项目',
  `source_file_id` BIGINT UNSIGNED NOT NULL COMMENT '教材源文件',
  `version_no` INT NOT NULL COMMENT '版本号',
  `textbook_name` VARCHAR(255) NOT NULL COMMENT '教材名称',
  `publisher` VARCHAR(128) NULL COMMENT '出版社',
  `subject_code` VARCHAR(32) NOT NULL COMMENT '学科编码',
  `grade_code` VARCHAR(32) NOT NULL COMMENT '年级编码',
  `volume_code` VARCHAR(64) NULL COMMENT '册别',
  `edition_label` VARCHAR(64) NULL COMMENT '版本标签',
  `isbn` VARCHAR(64) NULL COMMENT 'ISBN',
  `file_hash` VARCHAR(128) NOT NULL COMMENT '文件哈希',
  `page_count` INT NULL COMMENT '页数',
  `parse_status` VARCHAR(32) NOT NULL DEFAULT 'pending' COMMENT '解析状态',
  `version_status` VARCHAR(32) NOT NULL DEFAULT 'ready' COMMENT '版本状态',
  `auto_identify_json` JSON NULL COMMENT '自动识别信息',
  `remark` VARCHAR(500) NULL COMMENT '备注',
  `uploaded_by` BIGINT UNSIGNED NULL COMMENT '上传人',
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  `updated_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_textbook_version_project_no` (`project_id`, `version_no`),
  KEY `idx_textbook_version_project_status` (`project_id`, `version_status`, `created_at`),
  KEY `idx_textbook_version_subject_grade` (`subject_code`, `grade_code`),
  CONSTRAINT `fk_textbook_version_project` FOREIGN KEY (`project_id`) REFERENCES `project` (`id`),
  CONSTRAINT `fk_textbook_version_source_file` FOREIGN KEY (`source_file_id`) REFERENCES `file_object` (`id`),
  CONSTRAINT `fk_textbook_version_uploaded_by` FOREIGN KEY (`uploaded_by`) REFERENCES `sys_user` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='教材版本表';

CREATE TABLE `learner_profile_file` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  `project_id` BIGINT UNSIGNED NOT NULL COMMENT '所属项目',
  `source_file_id` BIGINT UNSIGNED NOT NULL COMMENT '学情源文件',
  `title` VARCHAR(255) NOT NULL COMMENT '学情文档标题',
  `file_status` VARCHAR(32) NOT NULL DEFAULT 'uploaded' COMMENT '文件状态',
  `uploaded_by` BIGINT UNSIGNED NULL COMMENT '上传人',
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  `updated_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (`id`),
  KEY `idx_profile_file_project_status` (`project_id`, `file_status`, `created_at`),
  CONSTRAINT `fk_profile_file_project` FOREIGN KEY (`project_id`) REFERENCES `project` (`id`),
  CONSTRAINT `fk_profile_file_source_file` FOREIGN KEY (`source_file_id`) REFERENCES `file_object` (`id`),
  CONSTRAINT `fk_profile_file_uploaded_by` FOREIGN KEY (`uploaded_by`) REFERENCES `sys_user` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='学情文件表';

CREATE TABLE `learner_profile_version` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  `project_id` BIGINT UNSIGNED NOT NULL COMMENT '所属项目',
  `profile_file_id` BIGINT UNSIGNED NOT NULL COMMENT '学情文件',
  `parent_version_id` BIGINT UNSIGNED NULL COMMENT '父版本',
  `version_no` INT NOT NULL COMMENT '版本号',
  `textbook_version_hint_id` BIGINT UNSIGNED NULL COMMENT '教材提示版本',
  `grade_code` VARCHAR(32) NULL COMMENT '年级提示',
  `subject_scope` VARCHAR(128) NULL COMMENT '学科范围',
  `extract_status` VARCHAR(32) NOT NULL DEFAULT 'pending' COMMENT '抽取状态',
  `review_status` VARCHAR(32) NOT NULL DEFAULT 'pending' COMMENT '审核状态',
  `version_status` VARCHAR(32) NOT NULL DEFAULT 'ready' COMMENT '版本状态',
  `summary_text` TEXT NULL COMMENT '摘要',
  `raw_result_json` JSON NULL COMMENT '抽取结果JSON',
  `source_snapshot_json` JSON NULL COMMENT '输入快照',
  `created_by` BIGINT UNSIGNED NULL COMMENT '创建人',
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  `updated_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_profile_version_file_no` (`profile_file_id`, `version_no`),
  KEY `idx_profile_version_project_status` (`project_id`, `version_status`, `created_at`),
  CONSTRAINT `fk_profile_version_project` FOREIGN KEY (`project_id`) REFERENCES `project` (`id`),
  CONSTRAINT `fk_profile_version_file` FOREIGN KEY (`profile_file_id`) REFERENCES `learner_profile_file` (`id`),
  CONSTRAINT `fk_profile_version_parent` FOREIGN KEY (`parent_version_id`) REFERENCES `learner_profile_version` (`id`),
  CONSTRAINT `fk_profile_version_textbook_hint` FOREIGN KEY (`textbook_version_hint_id`) REFERENCES `textbook_version` (`id`),
  CONSTRAINT `fk_profile_version_created_by` FOREIGN KEY (`created_by`) REFERENCES `sys_user` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='学情版本表';

CREATE TABLE `learner_profile_record` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  `project_id` BIGINT UNSIGNED NOT NULL COMMENT '所属项目',
  `profile_version_id` BIGINT UNSIGNED NOT NULL COMMENT '学情版本',
  `student_key` VARCHAR(128) NOT NULL COMMENT '学生标识',
  `student_name` VARCHAR(128) NULL COMMENT '学生姓名',
  `is_anonymous` TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否匿名',
  `region_name` VARCHAR(128) NULL COMMENT '地区',
  `grade_code` VARCHAR(32) NULL COMMENT '年级',
  `subject_code` VARCHAR(32) NOT NULL COMMENT '学科',
  `textbook_version_hint_id` BIGINT UNSIGNED NULL COMMENT '教材提示版本',
  `score_value` DECIMAL(6,2) NULL COMMENT '分数',
  `advantage_tags_json` JSON NULL COMMENT '优势标签',
  `weakness_tags_json` JSON NULL COMMENT '薄弱标签',
  `ability_tags_json` JSON NULL COMMENT '能力标签',
  `habit_tags_json` JSON NULL COMMENT '学习习惯标签',
  `behavior_traits_json` JSON NULL COMMENT '行为特征',
  `time_plan_json` JSON NULL COMMENT '时间规划',
  `summary_text` TEXT NULL COMMENT '摘要',
  `evidence_json` JSON NULL COMMENT '原文依据',
  `sort_order` INT NOT NULL DEFAULT 0 COMMENT '排序',
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  `updated_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_profile_record_scope` (`profile_version_id`, `student_key`, `subject_code`),
  KEY `idx_profile_record_project_subject` (`project_id`, `subject_code`),
  CONSTRAINT `fk_profile_record_project` FOREIGN KEY (`project_id`) REFERENCES `project` (`id`),
  CONSTRAINT `fk_profile_record_version` FOREIGN KEY (`profile_version_id`) REFERENCES `learner_profile_version` (`id`),
  CONSTRAINT `fk_profile_record_textbook_hint` FOREIGN KEY (`textbook_version_hint_id`) REFERENCES `textbook_version` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='学情画像记录表';

CREATE TABLE `parse_version` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  `project_id` BIGINT UNSIGNED NOT NULL COMMENT '所属项目',
  `textbook_version_id` BIGINT UNSIGNED NOT NULL COMMENT '教材版本',
  `parent_parse_version_id` BIGINT UNSIGNED NULL COMMENT '父解析版本',
  `version_no` INT NOT NULL COMMENT '版本号',
  `parse_mode` VARCHAR(32) NOT NULL DEFAULT 'full' COMMENT '解析模式',
  `page_range_text` VARCHAR(255) NULL COMMENT '页范围',
  `strategy_code` VARCHAR(64) NOT NULL COMMENT '策略编码',
  `mineru_model` VARCHAR(64) NULL COMMENT 'MinerU模型',
  `parse_status` VARCHAR(32) NOT NULL DEFAULT 'pending' COMMENT '解析状态',
  `review_status` VARCHAR(32) NOT NULL DEFAULT 'pending' COMMENT '审核状态',
  `version_status` VARCHAR(32) NOT NULL DEFAULT 'ready' COMMENT '版本状态',
  `page_count` INT NULL COMMENT '页数',
  `source_markdown_file_id` BIGINT UNSIGNED NULL COMMENT '解析Markdown文件',
  `source_json_file_id` BIGINT UNSIGNED NULL COMMENT '解析JSON文件',
  `asset_manifest_json` JSON NULL COMMENT '解析资源清单',
  `diff_json` JSON NULL COMMENT '差异摘要',
  `error_summary` VARCHAR(500) NULL COMMENT '错误摘要',
  `started_at` DATETIME(3) NULL COMMENT '开始时间',
  `finished_at` DATETIME(3) NULL COMMENT '结束时间',
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  `updated_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_parse_version_textbook_no` (`textbook_version_id`, `version_no`),
  KEY `idx_parse_version_project_status` (`project_id`, `version_status`, `created_at`),
  CONSTRAINT `fk_parse_version_project` FOREIGN KEY (`project_id`) REFERENCES `project` (`id`),
  CONSTRAINT `fk_parse_version_textbook_version` FOREIGN KEY (`textbook_version_id`) REFERENCES `textbook_version` (`id`),
  CONSTRAINT `fk_parse_version_parent` FOREIGN KEY (`parent_parse_version_id`) REFERENCES `parse_version` (`id`),
  CONSTRAINT `fk_parse_version_markdown_file` FOREIGN KEY (`source_markdown_file_id`) REFERENCES `file_object` (`id`),
  CONSTRAINT `fk_parse_version_json_file` FOREIGN KEY (`source_json_file_id`) REFERENCES `file_object` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='解析版本表';

CREATE TABLE `parse_page` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  `parse_version_id` BIGINT UNSIGNED NOT NULL COMMENT '解析版本',
  `page_no` INT NOT NULL COMMENT '页码',
  `source_page_image_file_id` BIGINT UNSIGNED NULL COMMENT '页图文件',
  `page_status` VARCHAR(32) NOT NULL DEFAULT 'success' COMMENT '页状态',
  `has_issue` TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否有异常',
  `text_content` MEDIUMTEXT NULL COMMENT '页文本',
  `markdown_content` MEDIUMTEXT NULL COMMENT '页Markdown',
  `layout_json` JSON NULL COMMENT '页布局JSON',
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  `updated_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_parse_page_version_page_no` (`parse_version_id`, `page_no`),
  KEY `idx_parse_page_status` (`parse_version_id`, `page_status`),
  CONSTRAINT `fk_parse_page_version` FOREIGN KEY (`parse_version_id`) REFERENCES `parse_version` (`id`),
  CONSTRAINT `fk_parse_page_image_file` FOREIGN KEY (`source_page_image_file_id`) REFERENCES `file_object` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='解析页结果表';

CREATE TABLE `parse_block` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  `parse_version_id` BIGINT UNSIGNED NOT NULL COMMENT '解析版本',
  `parse_page_id` BIGINT UNSIGNED NOT NULL COMMENT '解析页',
  `block_no` INT NOT NULL COMMENT '块序号',
  `block_type` VARCHAR(32) NOT NULL COMMENT '块类型',
  `heading_level` INT NULL COMMENT '标题级别',
  `bbox_json` JSON NULL COMMENT '坐标框',
  `text_content` MEDIUMTEXT NULL COMMENT '块文本',
  `markdown_content` MEDIUMTEXT NULL COMMENT '块Markdown',
  `asset_file_id` BIGINT UNSIGNED NULL COMMENT '资源文件',
  `origin_ref_json` JSON NULL COMMENT '来源引用',
  `is_deleted` TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否删除',
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  `updated_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_parse_block_page_no` (`parse_page_id`, `block_no`),
  KEY `idx_parse_block_version_type` (`parse_version_id`, `block_type`),
  CONSTRAINT `fk_parse_block_version` FOREIGN KEY (`parse_version_id`) REFERENCES `parse_version` (`id`),
  CONSTRAINT `fk_parse_block_page` FOREIGN KEY (`parse_page_id`) REFERENCES `parse_page` (`id`),
  CONSTRAINT `fk_parse_block_asset_file` FOREIGN KEY (`asset_file_id`) REFERENCES `file_object` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='解析块结果表';

CREATE TABLE `parse_issue` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  `parse_version_id` BIGINT UNSIGNED NOT NULL COMMENT '解析版本',
  `parse_page_id` BIGINT UNSIGNED NULL COMMENT '解析页',
  `parse_block_id` BIGINT UNSIGNED NULL COMMENT '解析块',
  `related_reparse_version_id` BIGINT UNSIGNED NULL COMMENT '关联重解析版本',
  `issue_type` VARCHAR(64) NOT NULL COMMENT '异常类型',
  `severity` VARCHAR(32) NOT NULL COMMENT '严重级别',
  `issue_status` VARCHAR(32) NOT NULL DEFAULT 'open' COMMENT '异常状态',
  `detected_by` VARCHAR(32) NOT NULL DEFAULT 'system' COMMENT '发现来源',
  `description` VARCHAR(500) NULL COMMENT '异常描述',
  `resolution_note` VARCHAR(500) NULL COMMENT '处理说明',
  `created_by` BIGINT UNSIGNED NULL COMMENT '创建人',
  `resolved_by` BIGINT UNSIGNED NULL COMMENT '处理人',
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  `updated_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (`id`),
  KEY `idx_parse_issue_status` (`parse_version_id`, `issue_status`, `severity`),
  KEY `idx_parse_issue_page` (`parse_page_id`),
  CONSTRAINT `fk_parse_issue_version` FOREIGN KEY (`parse_version_id`) REFERENCES `parse_version` (`id`),
  CONSTRAINT `fk_parse_issue_page` FOREIGN KEY (`parse_page_id`) REFERENCES `parse_page` (`id`),
  CONSTRAINT `fk_parse_issue_block` FOREIGN KEY (`parse_block_id`) REFERENCES `parse_block` (`id`),
  CONSTRAINT `fk_parse_issue_reparse_version` FOREIGN KEY (`related_reparse_version_id`) REFERENCES `parse_version` (`id`),
  CONSTRAINT `fk_parse_issue_created_by` FOREIGN KEY (`created_by`) REFERENCES `sys_user` (`id`),
  CONSTRAINT `fk_parse_issue_resolved_by` FOREIGN KEY (`resolved_by`) REFERENCES `sys_user` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='解析异常表';

CREATE TABLE `knowledge_version` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  `project_id` BIGINT UNSIGNED NOT NULL COMMENT '所属项目',
  `parse_version_id` BIGINT UNSIGNED NOT NULL COMMENT '解析版本',
  `parent_knowledge_version_id` BIGINT UNSIGNED NULL COMMENT '父知识版本',
  `version_no` INT NOT NULL COMMENT '版本号',
  `version_status` VARCHAR(32) NOT NULL DEFAULT 'ready' COMMENT '版本状态',
  `summary_json` JSON NULL COMMENT '知识结构摘要',
  `created_by` BIGINT UNSIGNED NULL COMMENT '创建人',
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  `updated_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_knowledge_version_project_no` (`project_id`, `version_no`),
  KEY `idx_knowledge_version_parse` (`parse_version_id`),
  CONSTRAINT `fk_knowledge_version_project` FOREIGN KEY (`project_id`) REFERENCES `project` (`id`),
  CONSTRAINT `fk_knowledge_version_parse` FOREIGN KEY (`parse_version_id`) REFERENCES `parse_version` (`id`),
  CONSTRAINT `fk_knowledge_version_parent` FOREIGN KEY (`parent_knowledge_version_id`) REFERENCES `knowledge_version` (`id`),
  CONSTRAINT `fk_knowledge_version_created_by` FOREIGN KEY (`created_by`) REFERENCES `sys_user` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='知识版本表';

CREATE TABLE `chapter_node` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  `knowledge_version_id` BIGINT UNSIGNED NOT NULL COMMENT '知识版本',
  `parent_id` BIGINT UNSIGNED NULL COMMENT '父章节',
  `node_path` VARCHAR(255) NOT NULL COMMENT '路径编码',
  `node_no` INT NOT NULL DEFAULT 1 COMMENT '节点序号',
  `node_level` INT NOT NULL DEFAULT 1 COMMENT '层级',
  `node_type` VARCHAR(32) NOT NULL COMMENT '节点类型',
  `title` VARCHAR(255) NOT NULL COMMENT '标题',
  `summary_text` TEXT NULL COMMENT '摘要',
  `page_start` INT NULL COMMENT '起始页',
  `page_end` INT NULL COMMENT '结束页',
  `line_start` INT NULL COMMENT 'Markdown起始行号',
  `line_end` INT NULL COMMENT 'Markdown结束行号',
  `sort_order` INT NOT NULL DEFAULT 0 COMMENT '排序',
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  `updated_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_chapter_node_version_path` (`knowledge_version_id`, `node_path`),
  KEY `idx_chapter_node_parent` (`parent_id`),
  CONSTRAINT `fk_chapter_node_version` FOREIGN KEY (`knowledge_version_id`) REFERENCES `knowledge_version` (`id`),
  CONSTRAINT `fk_chapter_node_parent` FOREIGN KEY (`parent_id`) REFERENCES `chapter_node` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='章节节点表';

CREATE TABLE `semantic_chunk` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  `project_id` BIGINT UNSIGNED NOT NULL COMMENT '所属项目',
  `parse_version_id` BIGINT UNSIGNED NOT NULL COMMENT '解析版本',
  `knowledge_version_id` BIGINT UNSIGNED NULL COMMENT '知识版本',
  `chapter_node_id` BIGINT UNSIGNED NULL COMMENT '章节节点',
  `chunk_no` INT NOT NULL COMMENT '语义块序号',
  `chunk_title` VARCHAR(255) NULL COMMENT '语义块标题',
  `chunk_type` VARCHAR(32) NOT NULL DEFAULT 'semantic' COMMENT '语义块类型',
  `page_start` INT NULL COMMENT '起始页',
  `page_end` INT NULL COMMENT '结束页',
  `line_start` INT NULL COMMENT 'Markdown起始行号',
  `line_end` INT NULL COMMENT 'Markdown结束行号',
  `source_block_refs_json` JSON NULL COMMENT '来源解析块引用，保留页码、块号、坐标和资源文件',
  `source_text_hash` VARCHAR(128) NULL COMMENT '来源文本哈希',
  `chunk_text` MEDIUMTEXT NOT NULL COMMENT '语义块正文',
  `summary_text` TEXT NULL COMMENT '摘要',
  `metadata_json` JSON NULL COMMENT '附加元数据',
  `created_by` BIGINT UNSIGNED NULL COMMENT '创建人',
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  `updated_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_semantic_chunk_knowledge_no` (`knowledge_version_id`, `chunk_no`),
  KEY `idx_semantic_chunk_project` (`project_id`, `created_at`),
  KEY `idx_semantic_chunk_knowledge` (`knowledge_version_id`, `chapter_node_id`),
  KEY `idx_semantic_chunk_page_range` (`parse_version_id`, `page_start`, `page_end`),
  CONSTRAINT `fk_semantic_chunk_project` FOREIGN KEY (`project_id`) REFERENCES `project` (`id`),
  CONSTRAINT `fk_semantic_chunk_parse_version` FOREIGN KEY (`parse_version_id`) REFERENCES `parse_version` (`id`),
  CONSTRAINT `fk_semantic_chunk_knowledge_version` FOREIGN KEY (`knowledge_version_id`) REFERENCES `knowledge_version` (`id`),
  CONSTRAINT `fk_semantic_chunk_chapter` FOREIGN KEY (`chapter_node_id`) REFERENCES `chapter_node` (`id`),
  CONSTRAINT `fk_semantic_chunk_created_by` FOREIGN KEY (`created_by`) REFERENCES `sys_user` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='教材语义块表';

CREATE TABLE `knowledge_point` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  `knowledge_version_id` BIGINT UNSIGNED NOT NULL COMMENT '知识版本',
  `chapter_node_id` BIGINT UNSIGNED NULL COMMENT '章节节点',
  `point_code` VARCHAR(64) NULL COMMENT '知识点编码',
  `point_name` VARCHAR(255) NOT NULL COMMENT '知识点名称',
  `point_type` VARCHAR(32) NOT NULL DEFAULT 'knowledge' COMMENT '知识点类型',
  `importance_level` TINYINT UNSIGNED NULL COMMENT '重要度',
  `difficulty_level` TINYINT UNSIGNED NULL COMMENT '难度',
  `mastery_level_hint` VARCHAR(32) NULL COMMENT '掌握建议',
  `tags_json` JSON NULL COMMENT '标签',
  `summary_text` TEXT NULL COMMENT '摘要',
  `sort_order` INT NOT NULL DEFAULT 0 COMMENT '排序',
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  `updated_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (`id`),
  KEY `idx_knowledge_point_version_chapter` (`knowledge_version_id`, `chapter_node_id`),
  KEY `idx_knowledge_point_name` (`point_name`),
  CONSTRAINT `fk_knowledge_point_version` FOREIGN KEY (`knowledge_version_id`) REFERENCES `knowledge_version` (`id`),
  CONSTRAINT `fk_knowledge_point_chapter` FOREIGN KEY (`chapter_node_id`) REFERENCES `chapter_node` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='知识点表';

CREATE TABLE `knowledge_evidence` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  `knowledge_point_id` BIGINT UNSIGNED NOT NULL COMMENT '知识点',
  `semantic_chunk_id` BIGINT UNSIGNED NULL COMMENT '语义块',
  `parse_version_id` BIGINT UNSIGNED NOT NULL COMMENT '解析版本',
  `parse_page_id` BIGINT UNSIGNED NULL COMMENT '解析页',
  `parse_block_id` BIGINT UNSIGNED NULL COMMENT '解析块',
  `source_file_id` BIGINT UNSIGNED NULL COMMENT '来源文件',
  `evidence_type` VARCHAR(32) NOT NULL COMMENT '证据类型',
  `page_no` INT NULL COMMENT '页码',
  `excerpt_text` TEXT NULL COMMENT '原文片段',
  `bbox_json` JSON NULL COMMENT '坐标框',
  `score_value` DECIMAL(8,4) NULL COMMENT '证据分数',
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  PRIMARY KEY (`id`),
  KEY `idx_knowledge_evidence_point` (`knowledge_point_id`),
  KEY `idx_knowledge_evidence_semantic_chunk` (`semantic_chunk_id`),
  KEY `idx_knowledge_evidence_block` (`parse_block_id`),
  CONSTRAINT `fk_knowledge_evidence_point` FOREIGN KEY (`knowledge_point_id`) REFERENCES `knowledge_point` (`id`),
  CONSTRAINT `fk_knowledge_evidence_semantic_chunk` FOREIGN KEY (`semantic_chunk_id`) REFERENCES `semantic_chunk` (`id`),
  CONSTRAINT `fk_knowledge_evidence_parse_version` FOREIGN KEY (`parse_version_id`) REFERENCES `parse_version` (`id`),
  CONSTRAINT `fk_knowledge_evidence_page` FOREIGN KEY (`parse_page_id`) REFERENCES `parse_page` (`id`),
  CONSTRAINT `fk_knowledge_evidence_block` FOREIGN KEY (`parse_block_id`) REFERENCES `parse_block` (`id`),
  CONSTRAINT `fk_knowledge_evidence_source_file` FOREIGN KEY (`source_file_id`) REFERENCES `file_object` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='知识点证据表';

CREATE TABLE `curriculum_plan` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  `project_id` BIGINT UNSIGNED NOT NULL COMMENT '所属项目',
  `knowledge_version_id` BIGINT UNSIGNED NOT NULL COMMENT '知识版本',
  `learner_profile_version_id` BIGINT UNSIGNED NOT NULL COMMENT '学情版本',
  `parent_plan_id` BIGINT UNSIGNED NULL COMMENT '父课程大纲',
  `version_no` INT NOT NULL COMMENT '版本号',
  `plan_title` VARCHAR(255) NOT NULL COMMENT '课程大纲标题',
  `target_subject_code` VARCHAR(32) NOT NULL COMMENT '目标学科',
  `target_grade_code` VARCHAR(32) NULL COMMENT '目标年级',
  `chapter_range_json` JSON NULL COMMENT '章节范围',
  `course_count` INT NOT NULL COMMENT '总课次',
  `session_duration_minutes` INT NOT NULL COMMENT '单次时长',
  `generation_mode` VARCHAR(32) NOT NULL DEFAULT 'ai' COMMENT '生成模式',
  `version_status` VARCHAR(32) NOT NULL DEFAULT 'ready' COMMENT '版本状态',
  `summary_text` TEXT NULL COMMENT '摘要',
  `content_json` JSON NOT NULL COMMENT '课程大纲内容',
  `export_file_id` BIGINT UNSIGNED NULL COMMENT '导出文件',
  `created_by` BIGINT UNSIGNED NULL COMMENT '创建人',
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  `updated_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_curriculum_plan_project_no` (`project_id`, `version_no`),
  KEY `idx_curriculum_plan_project_status` (`project_id`, `version_status`, `created_at`),
  CONSTRAINT `fk_curriculum_plan_project` FOREIGN KEY (`project_id`) REFERENCES `project` (`id`),
  CONSTRAINT `fk_curriculum_plan_knowledge_version` FOREIGN KEY (`knowledge_version_id`) REFERENCES `knowledge_version` (`id`),
  CONSTRAINT `fk_curriculum_plan_profile_version` FOREIGN KEY (`learner_profile_version_id`) REFERENCES `learner_profile_version` (`id`),
  CONSTRAINT `fk_curriculum_plan_parent` FOREIGN KEY (`parent_plan_id`) REFERENCES `curriculum_plan` (`id`),
  CONSTRAINT `fk_curriculum_plan_export_file` FOREIGN KEY (`export_file_id`) REFERENCES `file_object` (`id`),
  CONSTRAINT `fk_curriculum_plan_created_by` FOREIGN KEY (`created_by`) REFERENCES `sys_user` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='课程大纲表';

CREATE TABLE `lesson_plan` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  `curriculum_plan_id` BIGINT UNSIGNED NOT NULL COMMENT '课程大纲',
  `generation_batch_id` BIGINT UNSIGNED NULL COMMENT '生成批次',
  `class_session_no` INT NULL COMMENT '课次序号',
  `version_no` INT NOT NULL COMMENT '版本号',
  `lesson_title` VARCHAR(255) NOT NULL COMMENT '教案标题',
  `style_code` VARCHAR(64) NULL COMMENT '教案风格',
  `version_status` VARCHAR(32) NOT NULL DEFAULT 'ready' COMMENT '版本状态',
  `summary_text` TEXT NULL COMMENT '摘要',
  `content_json` JSON NOT NULL COMMENT '教案内容',
  `export_file_id` BIGINT UNSIGNED NULL COMMENT '导出文件',
  `created_by` BIGINT UNSIGNED NULL COMMENT '创建人',
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  `updated_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_lesson_plan_curriculum_no` (`curriculum_plan_id`, `version_no`),
  UNIQUE KEY `uk_lesson_plan_batch_session` (`generation_batch_id`, `class_session_no`),
  KEY `idx_lesson_plan_curriculum_status` (`curriculum_plan_id`, `version_status`, `created_at`),
  KEY `idx_lesson_plan_generation_batch` (`generation_batch_id`, `class_session_no`),
  CONSTRAINT `fk_lesson_plan_curriculum` FOREIGN KEY (`curriculum_plan_id`) REFERENCES `curriculum_plan` (`id`),
  CONSTRAINT `fk_lesson_plan_export_file` FOREIGN KEY (`export_file_id`) REFERENCES `file_object` (`id`),
  CONSTRAINT `fk_lesson_plan_created_by` FOREIGN KEY (`created_by`) REFERENCES `sys_user` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='教案表';

CREATE TABLE `assessment_blueprint` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  `curriculum_plan_id` BIGINT UNSIGNED NOT NULL COMMENT '课程大纲',
  `version_no` INT NOT NULL COMMENT '版本号',
  `scenario_type` VARCHAR(32) NOT NULL COMMENT '场景类型',
  `blueprint_name` VARCHAR(255) NOT NULL COMMENT '蓝图名称',
  `version_status` VARCHAR(32) NOT NULL DEFAULT 'ready' COMMENT '版本状态',
  `strategy_json` JSON NULL COMMENT '策略配置',
  `content_json` JSON NOT NULL COMMENT '蓝图内容',
  `export_file_id` BIGINT UNSIGNED NULL COMMENT '导出文件',
  `created_by` BIGINT UNSIGNED NULL COMMENT '创建人',
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  `updated_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_assessment_blueprint_scope` (`curriculum_plan_id`, `scenario_type`, `version_no`),
  KEY `idx_assessment_blueprint_curriculum_status` (`curriculum_plan_id`, `version_status`, `created_at`),
  CONSTRAINT `fk_assessment_blueprint_curriculum` FOREIGN KEY (`curriculum_plan_id`) REFERENCES `curriculum_plan` (`id`),
  CONSTRAINT `fk_assessment_blueprint_export_file` FOREIGN KEY (`export_file_id`) REFERENCES `file_object` (`id`),
  CONSTRAINT `fk_assessment_blueprint_created_by` FOREIGN KEY (`created_by`) REFERENCES `sys_user` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='测评蓝图表';

CREATE TABLE `generation_batch` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  `project_id` BIGINT UNSIGNED NOT NULL COMMENT '所属项目',
  `batch_no` INT NOT NULL COMMENT '批次号',
  `batch_name` VARCHAR(255) NULL COMMENT '批次名称',
  `trigger_mode` VARCHAR(32) NOT NULL DEFAULT 'manual' COMMENT '触发模式',
  `batch_status` VARCHAR(32) NOT NULL DEFAULT 'pending' COMMENT '批次状态',
  `knowledge_version_id` BIGINT UNSIGNED NOT NULL COMMENT '知识版本',
  `learner_profile_version_id` BIGINT UNSIGNED NOT NULL COMMENT '学情版本',
  `chapter_range_json` JSON NULL COMMENT '章节范围快照',
  `course_count` INT NULL COMMENT '总课次快照',
  `session_duration_minutes` INT NULL COMMENT '单次时长快照',
  `template_snapshot_json` JSON NULL COMMENT '模板快照',
  `assessment_strategy_json` JSON NULL COMMENT '测评策略快照',
  `pipeline_options_json` JSON NULL COMMENT '编排选项',
  `curriculum_plan_id` BIGINT UNSIGNED NULL COMMENT '生成的大纲版本',
  `lesson_plan_id` BIGINT UNSIGNED NULL COMMENT '生成的教案版本',
  `started_at` DATETIME(3) NULL COMMENT '开始时间',
  `finished_at` DATETIME(3) NULL COMMENT '结束时间',
  `created_by` BIGINT UNSIGNED NULL COMMENT '创建人',
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  `updated_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_generation_batch_project_no` (`project_id`, `batch_no`),
  KEY `idx_generation_batch_status` (`project_id`, `batch_status`, `created_at`),
  CONSTRAINT `fk_generation_batch_project` FOREIGN KEY (`project_id`) REFERENCES `project` (`id`),
  CONSTRAINT `fk_generation_batch_knowledge_version` FOREIGN KEY (`knowledge_version_id`) REFERENCES `knowledge_version` (`id`),
  CONSTRAINT `fk_generation_batch_profile_version` FOREIGN KEY (`learner_profile_version_id`) REFERENCES `learner_profile_version` (`id`),
  CONSTRAINT `fk_generation_batch_curriculum_plan` FOREIGN KEY (`curriculum_plan_id`) REFERENCES `curriculum_plan` (`id`),
  CONSTRAINT `fk_generation_batch_lesson_plan` FOREIGN KEY (`lesson_plan_id`) REFERENCES `lesson_plan` (`id`),
  CONSTRAINT `fk_generation_batch_created_by` FOREIGN KEY (`created_by`) REFERENCES `sys_user` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='生成批次表';

CREATE TABLE `courseware_result` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  `generation_batch_id` BIGINT UNSIGNED NOT NULL COMMENT '生成批次',
  `lesson_plan_id` BIGINT UNSIGNED NOT NULL COMMENT '教案版本',
  `template_code` VARCHAR(64) NULL COMMENT '模板编码',
  `template_version` VARCHAR(64) NULL COMMENT '模板版本',
  `result_status` VARCHAR(32) NOT NULL DEFAULT 'success' COMMENT '结果状态',
  `page_count` INT NULL COMMENT '页数',
  `page_type_stats_json` JSON NULL COMMENT '页面类型统计',
  `structure_json` JSON NOT NULL COMMENT '幻灯片结构',
  `preview_json` JSON NULL COMMENT '预览信息',
  `export_file_id` BIGINT UNSIGNED NULL COMMENT '导出文件',
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  `updated_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_courseware_result_batch_lesson` (`generation_batch_id`, `lesson_plan_id`),
  KEY `idx_courseware_result_lesson` (`lesson_plan_id`, `created_at`),
  CONSTRAINT `fk_courseware_result_batch` FOREIGN KEY (`generation_batch_id`) REFERENCES `generation_batch` (`id`),
  CONSTRAINT `fk_courseware_result_lesson_plan` FOREIGN KEY (`lesson_plan_id`) REFERENCES `lesson_plan` (`id`),
  CONSTRAINT `fk_courseware_result_export_file` FOREIGN KEY (`export_file_id`) REFERENCES `file_object` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='课件结果表';

CREATE TABLE `paper_result` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  `generation_batch_id` BIGINT UNSIGNED NOT NULL COMMENT '生成批次',
  `assessment_blueprint_id` BIGINT UNSIGNED NOT NULL COMMENT '测评蓝图',
  `scene_type` VARCHAR(32) NOT NULL COMMENT '场景类型',
  `title` VARCHAR(255) NOT NULL COMMENT '标题',
  `result_status` VARCHAR(32) NOT NULL DEFAULT 'success' COMMENT '结果状态',
  `question_count` INT NOT NULL DEFAULT 0 COMMENT '题目数量',
  `difficulty_stats_json` JSON NULL COMMENT '难度统计',
  `paper_json` JSON NOT NULL COMMENT '试卷内容',
  `export_file_id` BIGINT UNSIGNED NULL COMMENT '导出文件',
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  `updated_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_paper_result_batch_scene` (`generation_batch_id`, `scene_type`),
  KEY `idx_paper_result_blueprint` (`assessment_blueprint_id`, `created_at`),
  CONSTRAINT `fk_paper_result_batch` FOREIGN KEY (`generation_batch_id`) REFERENCES `generation_batch` (`id`),
  CONSTRAINT `fk_paper_result_blueprint` FOREIGN KEY (`assessment_blueprint_id`) REFERENCES `assessment_blueprint` (`id`),
  CONSTRAINT `fk_paper_result_export_file` FOREIGN KEY (`export_file_id`) REFERENCES `file_object` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='作业试卷结果表';

CREATE TABLE `question_item` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  `generation_batch_id` BIGINT UNSIGNED NOT NULL COMMENT '生成批次',
  `paper_result_id` BIGINT UNSIGNED NOT NULL COMMENT '试卷结果',
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
  UNIQUE KEY `uk_question_item_scope` (`paper_result_id`, `question_no`),
  KEY `idx_question_item_batch_kp` (`generation_batch_id`, `knowledge_point_id`),
  KEY `idx_question_item_type_diff` (`question_type`, `difficulty_level`),
  CONSTRAINT `fk_question_item_batch` FOREIGN KEY (`generation_batch_id`) REFERENCES `generation_batch` (`id`),
  CONSTRAINT `fk_question_item_paper` FOREIGN KEY (`paper_result_id`) REFERENCES `paper_result` (`id`),
  CONSTRAINT `fk_question_item_knowledge_point` FOREIGN KEY (`knowledge_point_id`) REFERENCES `knowledge_point` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='题目明细表';

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

CREATE TABLE `coverage_report` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  `generation_batch_id` BIGINT UNSIGNED NOT NULL COMMENT '生成批次',
  `report_status` VARCHAR(32) NOT NULL DEFAULT 'success' COMMENT '报告状态',
  `coverage_rate` DECIMAL(6,2) NULL COMMENT '覆盖率',
  `warning_count` INT NOT NULL DEFAULT 0 COMMENT '告警数量',
  `coverage_summary_json` JSON NULL COMMENT '覆盖摘要',
  `report_json` JSON NOT NULL COMMENT '报告内容',
  `export_file_id` BIGINT UNSIGNED NULL COMMENT '导出文件',
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  `updated_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_coverage_report_batch` (`generation_batch_id`),
  KEY `idx_coverage_report_created_at` (`created_at`),
  CONSTRAINT `fk_coverage_report_batch` FOREIGN KEY (`generation_batch_id`) REFERENCES `generation_batch` (`id`),
  CONSTRAINT `fk_coverage_report_export_file` FOREIGN KEY (`export_file_id`) REFERENCES `file_object` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='覆盖率报告表';

CREATE TABLE `task_record` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  `project_id` BIGINT UNSIGNED NOT NULL COMMENT '所属项目',
  `generation_batch_id` BIGINT UNSIGNED NULL COMMENT '生成批次',
  `module_code` VARCHAR(32) NOT NULL COMMENT '模块编码',
  `task_type` VARCHAR(64) NOT NULL COMMENT '任务类型',
  `biz_key` VARCHAR(128) NULL COMMENT '业务键',
  `task_status` VARCHAR(32) NOT NULL DEFAULT 'pending' COMMENT '任务状态',
  `queue_name` VARCHAR(64) NULL COMMENT '队列名',
  `current_stage` VARCHAR(64) NULL COMMENT '当前阶段',
  `progress_percent` TINYINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '进度',
  `retry_count` INT NOT NULL DEFAULT 0 COMMENT '重试次数',
  `max_retry_count` INT NOT NULL DEFAULT 3 COMMENT '最大重试次数',
  `request_id` VARCHAR(64) NULL COMMENT '请求ID',
  `worker_task_id` VARCHAR(128) NULL COMMENT 'Worker任务ID',
  `operator_user_id` BIGINT UNSIGNED NULL COMMENT '操作人',
  `payload_json` JSON NULL COMMENT '任务载荷',
  `result_json` JSON NULL COMMENT '任务结果',
  `last_error_code` VARCHAR(64) NULL COMMENT '错误码',
  `last_error_message` VARCHAR(500) NULL COMMENT '错误信息',
  `started_at` DATETIME(3) NULL COMMENT '开始时间',
  `finished_at` DATETIME(3) NULL COMMENT '结束时间',
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  `updated_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (`id`),
  KEY `idx_task_record_project_status` (`project_id`, `task_status`, `created_at`),
  KEY `idx_task_record_batch_type` (`generation_batch_id`, `task_type`),
  CONSTRAINT `fk_task_record_project` FOREIGN KEY (`project_id`) REFERENCES `project` (`id`),
  CONSTRAINT `fk_task_record_batch` FOREIGN KEY (`generation_batch_id`) REFERENCES `generation_batch` (`id`),
  CONSTRAINT `fk_task_record_operator` FOREIGN KEY (`operator_user_id`) REFERENCES `sys_user` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='任务主表';

CREATE TABLE `task_step_record` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  `task_record_id` BIGINT UNSIGNED NOT NULL COMMENT '任务主表',
  `step_code` VARCHAR(64) NOT NULL COMMENT '步骤编码',
  `step_name` VARCHAR(128) NOT NULL COMMENT '步骤名称',
  `step_order` INT NOT NULL DEFAULT 0 COMMENT '步骤顺序',
  `step_status` VARCHAR(32) NOT NULL DEFAULT 'pending' COMMENT '步骤状态',
  `progress_percent` TINYINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '步骤进度',
  `detail_json` JSON NULL COMMENT '步骤明细',
  `started_at` DATETIME(3) NULL COMMENT '开始时间',
  `finished_at` DATETIME(3) NULL COMMENT '结束时间',
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  `updated_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_task_step_record_scope` (`task_record_id`, `step_code`),
  KEY `idx_task_step_status` (`task_record_id`, `step_status`),
  CONSTRAINT `fk_task_step_record_task` FOREIGN KEY (`task_record_id`) REFERENCES `task_record` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='任务步骤表';

CREATE TABLE `generation_trace` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  `generation_batch_id` BIGINT UNSIGNED NOT NULL COMMENT '生成批次',
  `trace_type` VARCHAR(32) NOT NULL COMMENT '追溯类型',
  `target_type` VARCHAR(32) NOT NULL COMMENT '目标类型',
  `target_id` BIGINT UNSIGNED NOT NULL COMMENT '目标ID',
  `source_type` VARCHAR(32) NOT NULL COMMENT '来源类型',
  `source_id` VARCHAR(64) NOT NULL COMMENT '来源ID',
  `source_rank` INT NULL COMMENT '来源排序',
  `source_score` DECIMAL(8,4) NULL COMMENT '来源分数',
  `evidence_text` TEXT NULL COMMENT '证据文本',
  `metadata_json` JSON NULL COMMENT '附加元数据',
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  PRIMARY KEY (`id`),
  KEY `idx_generation_trace_batch_target` (`generation_batch_id`, `target_type`, `target_id`),
  KEY `idx_generation_trace_source` (`source_type`, `source_id`),
  CONSTRAINT `fk_generation_trace_batch` FOREIGN KEY (`generation_batch_id`) REFERENCES `generation_batch` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='生成追溯表';

CREATE TABLE `audit_log` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  `project_id` BIGINT UNSIGNED NULL COMMENT '所属项目',
  `task_record_id` BIGINT UNSIGNED NULL COMMENT '任务',
  `operator_user_id` BIGINT UNSIGNED NULL COMMENT '操作人',
  `module_code` VARCHAR(32) NOT NULL COMMENT '模块编码',
  `action_code` VARCHAR(64) NOT NULL COMMENT '动作编码',
  `biz_type` VARCHAR(64) NULL COMMENT '业务类型',
  `biz_id` BIGINT UNSIGNED NULL COMMENT '业务主键',
  `request_id` VARCHAR(64) NULL COMMENT '请求ID',
  `action_result` VARCHAR(32) NOT NULL DEFAULT 'success' COMMENT '动作结果',
  `detail_json` JSON NULL COMMENT '明细',
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  PRIMARY KEY (`id`),
  KEY `idx_audit_log_project_created_at` (`project_id`, `created_at`),
  KEY `idx_audit_log_module_action` (`module_code`, `action_code`, `created_at`),
  CONSTRAINT `fk_audit_log_project` FOREIGN KEY (`project_id`) REFERENCES `project` (`id`),
  CONSTRAINT `fk_audit_log_task` FOREIGN KEY (`task_record_id`) REFERENCES `task_record` (`id`),
  CONSTRAINT `fk_audit_log_operator` FOREIGN KEY (`operator_user_id`) REFERENCES `sys_user` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='审计日志表';

ALTER TABLE `project`
  ADD CONSTRAINT `fk_project_current_textbook_version`
    FOREIGN KEY (`current_textbook_version_id`) REFERENCES `textbook_version` (`id`),
  ADD CONSTRAINT `fk_project_current_profile_version`
    FOREIGN KEY (`current_learner_profile_version_id`) REFERENCES `learner_profile_version` (`id`),
  ADD CONSTRAINT `fk_project_latest_generation_batch`
    FOREIGN KEY (`latest_generation_batch_id`) REFERENCES `generation_batch` (`id`);

ALTER TABLE `lesson_plan`
  ADD CONSTRAINT `fk_lesson_plan_generation_batch`
    FOREIGN KEY (`generation_batch_id`) REFERENCES `generation_batch` (`id`);
