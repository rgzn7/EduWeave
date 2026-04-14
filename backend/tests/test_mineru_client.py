"""
@Date: 2026-04-14
@Author: xisy
@Discription: MinerU 客户端与结果归一化测试
"""

import io
import json
import time
from zipfile import ZipFile

import httpx
import pytest

from app.core.config import get_settings
from app.core.exceptions import AppException, BusinessErrorCode
from app.shared.mineru import MineruClient, MineruDocumentService


def build_settings():
    """构造带 MinerU Token 的测试配置。"""
    return get_settings().model_copy(
        update={
            "mineru_api_base_url": "https://mineru.test",
            "mineru_api_token": "test-token",
            "mineru_poll_interval_seconds": 1,
            "mineru_poll_timeout_seconds": 5,
        }
    )


def test_mineru_client_should_request_upload_urls_successfully() -> None:
    """上传地址申请应兼容对象形式的 file_urls。"""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v4/file-urls/batch"
        return httpx.Response(
            status_code=200,
            json={
                "code": 0,
                "msg": "ok",
                "data": {
                    "batch_id": "batch-1",
                    "file_urls": [{"url": "https://upload.test/file-1"}],
                },
            },
        )

    client = MineruClient(settings=build_settings(), http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    result = client.request_upload_urls(
        files=[{"name": "demo.pdf", "data_id": "data-1", "is_ocr": False}],
        model_version="vlm",
    )

    assert result.batch_id == "batch-1"
    assert result.file_urls == ["https://upload.test/file-1"]


def test_mineru_client_should_raise_when_batch_failed() -> None:
    """任务失败状态应抛出受控异常。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=200,
            json={
                "code": 0,
                "msg": "ok",
                "data": {
                    "extract_result": [
                        {
                            "file_name": "demo.pdf",
                            "data_id": "data-1",
                            "state": "failed",
                            "err_msg": "parse failed",
                            "full_zip_url": None,
                        }
                    ]
                },
            },
        )

    client = MineruClient(settings=build_settings(), http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(AppException) as exc_info:
        client.poll_batch_result(batch_id="batch-1", data_id="data-1", file_name="demo.pdf")

    assert exc_info.value.code == BusinessErrorCode.MINERU_TASK_FAILED


def test_mineru_client_should_raise_when_poll_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """轮询超时应抛出超时异常。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=200,
            json={
                "code": 0,
                "msg": "ok",
                "data": {
                    "extract_result": [
                        {
                            "file_name": "demo.pdf",
                            "data_id": "data-1",
                            "state": "running",
                            "err_msg": None,
                            "full_zip_url": None,
                        }
                    ]
                },
            },
        )

    monotonic_values = iter([0.0, 0.1, 1.5])
    monkeypatch.setattr(time, "monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)

    settings = build_settings().model_copy(update={"mineru_poll_timeout_seconds": 1})
    client = MineruClient(settings=settings, http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(AppException) as exc_info:
        client.poll_batch_result(batch_id="batch-1", data_id="data-1", file_name="demo.pdf")

    assert exc_info.value.code == BusinessErrorCode.MINERU_POLL_TIMEOUT


def test_mineru_document_service_should_normalize_zip_payload() -> None:
    """压缩包归一化应正确识别根目录和资源路径。"""
    zip_buffer = io.BytesIO()
    with ZipFile(zip_buffer, "w") as archive:
        archive.writestr("job-1/full.md", "# 标题\n\n第一页内容")
        archive.writestr(
            "job-1/content_list.json",
            json.dumps(
                [
                    {"page_idx": 0, "type": "heading", "text": "标题"},
                    {"page_idx": 0, "type": "paragraph", "text": "第一页内容", "img_path": "images/1.png"},
                ],
                ensure_ascii=False,
            ),
        )
        archive.writestr("job-1/images/1.png", b"fake-image")

    service = MineruDocumentService()
    document = service.normalize_zip_payload(
        batch_id="batch-1",
        file_name="demo.pdf",
        data_id="data-1",
        model_version="vlm",
        full_zip_bytes=zip_buffer.getvalue(),
    )

    assert document.pages[0].page_no == 1
    assert document.pages[0].blocks[0].block_type == "heading"
    assert "images/1.png" in document.asset_files
