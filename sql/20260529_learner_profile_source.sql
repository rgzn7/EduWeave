-- @Date: 2026-05-29
-- @Author: xisy
-- @Discription: 新增学情班级源文件表（支持一个班级挂多个学生 docx）

USE `eduweave`;

CREATE TABLE IF NOT EXISTS `learner_profile_source` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  `project_id` BIGINT UNSIGNED NOT NULL COMMENT '所属项目',
  `profile_file_id` BIGINT UNSIGNED NOT NULL COMMENT '学情文件（班级）',
  `file_object_id` BIGINT UNSIGNED NOT NULL COMMENT '学生源 docx 文件对象',
  `student_seq` INT NOT NULL COMMENT '班级内学生序号（从 1 递增）',
  `original_filename` VARCHAR(255) NOT NULL COMMENT '原始文件名',
  `student_name` VARCHAR(128) NULL COMMENT '学生姓名（解析后回填）',
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  `updated_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_profile_source_file_seq` (`profile_file_id`, `student_seq`),
  KEY `idx_profile_source_file` (`profile_file_id`),
  CONSTRAINT `fk_profile_source_project` FOREIGN KEY (`project_id`) REFERENCES `project` (`id`),
  CONSTRAINT `fk_profile_source_file` FOREIGN KEY (`profile_file_id`) REFERENCES `learner_profile_file` (`id`),
  CONSTRAINT `fk_profile_source_file_object` FOREIGN KEY (`file_object_id`) REFERENCES `file_object` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='学情班级源文件表';
