-- @Date: 2026-05-27
-- @Author: xisy
-- @Discription: 清空 4 类资产残留的 DOCX export_file_id，配合 DOCX 模板升级
--               让前端在下次访问详情时主动触发 /export-docx，并落到新的 object_key（tv{N}）。

UPDATE curriculum_plan SET export_file_id = NULL WHERE export_file_id IS NOT NULL;
UPDATE lesson_plan SET export_file_id = NULL WHERE export_file_id IS NOT NULL;
UPDATE homework_result SET export_file_id = NULL WHERE export_file_id IS NOT NULL;
UPDATE paper_result SET export_file_id = NULL WHERE export_file_id IS NOT NULL;
