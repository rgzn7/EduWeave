-- @Date: 2026-05-26
-- @Author: xisy
-- @Discription: 为 question_item / homework_question 增加 question_basis_json 列，
--               用于持久化"题目考查依据"，与 backend/migrations/versions/20260526_0009_add_question_basis_json.py 对齐
-- 历史行（迁移前已存在的题目）该列为 NULL，由后端接口层在响应时回退到实时聚合

ALTER TABLE `question_item`
  ADD COLUMN `question_basis_json` JSON NULL COMMENT '题目考查依据' AFTER `source_trace_json`;

ALTER TABLE `homework_question`
  ADD COLUMN `question_basis_json` JSON NULL COMMENT '题目考查依据' AFTER `source_trace_json`;
