"""
@Date: 2026-05-17
@Author: xisy
@Discription: 课次教案多模态真实联调脚本（造样本图 -> 真实 gpt-5.5 读图 -> 生产函数端到端 -> 清理）

仅用于人工真实验证，会向真实 OBS 上传一张带哨兵文字的样本图并临时写入
file_object/parse_block/knowledge_evidence，结束时（无论成败）自动清理。
基线复用 generation_batch=5：project=15, knowledge_version=3, parse_version=15,
parse_page=351, knowledge_point=6, curriculum_plan=3, learner_profile_version=15。
"""

import hashlib
import os
import sys

os.environ["LLM_MULTIMODAL_ENABLED"] = "true"

from pydantic import BaseModel, Field
from sqlalchemy import text as sa_text

from app.core.database import SessionLocal
from app.core.config import get_settings
from app.modules.lesson_plan.repository import LessonPlanRepository
from app.modules.lesson_plan.schemas import LessonPlanGenerationResult
from app.modules.lesson_plan.tasks import (
    _build_lesson_plan_messages,
    _get_curriculum_lesson_sessions,
    _load_evidence_images,
)
import app.modules.auth.models  # noqa: F401  确保 sys_user 等全量表注册到 ORM 元数据
from app.modules.p0_models import FileObject, KnowledgeEvidence, ParseBlock
from app.shared.llm import ChatMessage, OpenAICompatibleLlmService, load_evidence_image_data_urls
from app.shared.storage import ObsStorageClient

SENTINEL = "EDUWEAVE-VISION-7F3A9"
PNG_PATH = "/tmp/eduweave_vision_sample.png"
PROJECT_ID = 15
PARSE_VERSION_ID = 15
PARSE_PAGE_ID = 351
KNOWLEDGE_POINT_ID = 6
CURRICULUM_PLAN_ID = 3


class SentinelProbe(BaseModel):
    """视觉链路探针：要求模型读出图片中的编号。"""

    sentinel_in_image: str = Field(description="图片中出现的编号字符串")


def main() -> int:
    settings = get_settings()
    print(f"[cfg] multimodal_enabled={settings.llm_multimodal_enabled} "
          f"model={settings.llm_model} api_format={settings.llm_api_format} "
          f"max_images={settings.llm_multimodal_max_images}")
    assert settings.llm_multimodal_enabled, "多模态开关未生效"

    image_bytes = open(PNG_PATH, "rb").read()
    content_hash = hashlib.sha256(image_bytes).hexdigest()

    storage = ObsStorageClient()
    # build_object_key 内部已自动前置 obs_base_prefix（projects），此处不再重复传 "projects"
    object_key = storage.build_object_key(
        str(PROJECT_ID), "manual-test", "vision", filename="sample.png"
    )
    storage.upload_bytes(object_key, image_bytes, content_type="image/png")
    print(f"[obs] uploaded -> {object_key} ({len(image_bytes)} bytes)")

    session = SessionLocal()
    fo_id = pb_id = ke_id = None
    try:
        next_block_no = session.execute(
            sa_text("SELECT COALESCE(MAX(block_no),0)+1 FROM parse_block WHERE parse_page_id=:p"),
            {"p": PARSE_PAGE_ID},
        ).scalar()

        file_object = FileObject(
            project_id=PROJECT_ID,
            biz_type="parse_asset",
            storage_provider="obs",
            bucket_name=settings.obs_bucket,
            object_key=object_key,
            original_filename="sample.png",
            file_ext="png",
            mime_type="image/png",
            file_size=len(image_bytes),
            content_hash=content_hash,
        )
        session.add(file_object)
        session.flush()
        fo_id = file_object.id

        parse_block = ParseBlock(
            parse_version_id=PARSE_VERSION_ID,
            parse_page_id=PARSE_PAGE_ID,
            block_no=next_block_no,
            block_type="image",
            text_content="[MANUAL TEST IMAGE]",
            asset_file_id=fo_id,
        )
        session.add(parse_block)
        session.flush()
        pb_id = parse_block.id

        evidence = KnowledgeEvidence(
            knowledge_point_id=KNOWLEDGE_POINT_ID,
            parse_version_id=PARSE_VERSION_ID,
            parse_page_id=PARSE_PAGE_ID,
            parse_block_id=pb_id,
            evidence_type="image",
        )
        session.add(evidence)
        session.commit()
        ke_id = evidence.id
        print(f"[db] seeded file_object={fo_id} parse_block={pb_id} knowledge_evidence={ke_id}")

        repo = LessonPlanRepository(session)
        assets = repo.list_evidence_image_assets([KNOWLEDGE_POINT_ID, 7, 8])
        print(f"[repo] list_evidence_image_assets -> {len(assets)} 行: {assets}")
        assert any(a[0] == fo_id for a in assets), "证据图片查询未命中样本"

        data_urls = load_evidence_image_data_urls(assets=assets, max_images=6)
        assert len(data_urls) >= 1 and data_urls[0].startswith("data:image/png;base64,")
        print(f"[loader] data_urls={len(data_urls)} 首图前缀={data_urls[0][:40]}...")

        # --- 真实视觉链路证明：真 gpt-5.5 必须读出图片哨兵 ---
        llm = OpenAICompatibleLlmService()
        probe_messages = [
            ChatMessage(role="system", content="你是图像识别助手，只输出 json。"),
            ChatMessage(
                role="user",
                content=[
                    {"type": "text", "text": "读出图片中最显著的英文编号字符串，原样返回 json。"},
                    {"type": "image", "data_url": data_urls[0]},
                ],
            ),
        ]
        probe = llm.generate_structured_output(
            messages=probe_messages, response_model=SentinelProbe
        )
        print(f"[vision-probe] 模型回读 = {probe.sentinel_in_image!r} 期望含 {SENTINEL!r}")
        assert SENTINEL in probe.sentinel_in_image.replace(" ", ""), "模型未读到图片哨兵，多模态链路未真正生效"
        print("[vision-probe] PASS：真实 gpt-5.5 确实接收并识别了图片内容")

        # --- 生产函数端到端：真实 _load_evidence_images + _build_lesson_plan_messages ---
        project = repo.get_project(PROJECT_ID)
        curriculum_plan = repo.get_curriculum_plan(CURRICULUM_PLAN_ID)
        profile_version = repo.get_learner_profile_version(curriculum_plan.learner_profile_version_id)
        generation_batch = repo.get_generation_batch(5)
        knowledge_points = repo.list_knowledge_points(curriculum_plan.knowledge_version_id)
        profile_records = repo.list_profile_records(curriculum_plan.learner_profile_version_id)
        lesson_sessions = _get_curriculum_lesson_sessions(curriculum_plan)

        prod_images = _load_evidence_images(repo, knowledge_points)
        print(f"[prod] _load_evidence_images -> {len(prod_images)} 张（知识点 {len(knowledge_points)} 个）")
        assert len(prod_images) >= 1, "生产路径未加载到证据图片"

        messages = _build_lesson_plan_messages(
            project=project,
            generation_batch=generation_batch,
            curriculum_plan=curriculum_plan,
            target_lesson_session=lesson_sessions[0],
            profile_version=profile_version,
            knowledge_points=knowledge_points,
            profile_records=profile_records,
            evidence_images=prod_images,
        )
        user_msg = messages[-1]
        assert isinstance(user_msg.content, list), "含图时 user 消息应为多模态 part 列表"
        image_parts = [p for p in user_msg.content if p.get("type") == "image"]
        print(f"[prod] user 消息 part 数={len(user_msg.content)} 其中图片 part={len(image_parts)}")

        result = llm.generate_structured_output(
            messages=messages, response_model=LessonPlanGenerationResult
        )
        print(f"[prod] 真实教案生成成功：lesson_title={result.lesson_title!r} "
              f"core_knowledge={len(result.core_knowledge)} 条 "
              f"teaching_flow={len(result.teaching_flow)} 步")
        print("\n=== 全部真实测试通过 ===")
        return 0
    finally:
        cleanup_session = SessionLocal()
        try:
            if ke_id:
                cleanup_session.execute(sa_text("DELETE FROM knowledge_evidence WHERE id=:i"), {"i": ke_id})
            if pb_id:
                cleanup_session.execute(sa_text("DELETE FROM parse_block WHERE id=:i"), {"i": pb_id})
            if fo_id:
                cleanup_session.execute(sa_text("DELETE FROM file_object WHERE id=:i"), {"i": fo_id})
            cleanup_session.commit()
            print(f"[cleanup] 已删除 ke={ke_id} pb={pb_id} fo={fo_id}")
        finally:
            cleanup_session.close()
        try:
            storage.delete_object(object_key)
            print(f"[cleanup] 已删除 OBS 对象 {object_key}")
        except Exception as exc:  # noqa: BLE001
            print(f"[cleanup] OBS 删除失败（需手动确认）: {exc}")
        session.close()


if __name__ == "__main__":
    sys.exit(main())
