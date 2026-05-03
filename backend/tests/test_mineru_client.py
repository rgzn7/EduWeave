"""
@Date: 2026-04-30
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


def test_mineru_document_service_should_match_real_content_list_fields() -> None:
    """归一化应匹配 MinerU 真实 content_list 字段。"""
    zip_buffer = io.BytesIO()
    with ZipFile(zip_buffer, "w") as archive:
        archive.writestr("full.md", "# 小数乘法")
        archive.writestr(
            "sample_content_list.json",
            json.dumps(
                [
                    {"page_idx": 0, "type": "text", "text": "小数乘法", "text_level": 1, "bbox": [1, 2, 3, 4]},
                    {
                        "page_idx": 0,
                        "type": "table",
                        "img_path": "images/table.jpg",
                        "table_caption": ["表 1"],
                        "table_footnote": ["说明"],
                        "table_body": "<table><tr><td>数量</td></tr></table>",
                        "bbox": [5, 6, 7, 8],
                    },
                    {
                        "page_idx": 0,
                        "type": "list",
                        "sub_type": "ordered",
                        "list_items": ["观察情境图", "列出算式"],
                        "bbox": [9, 10, 11, 12],
                    },
                    {
                        "page_idx": 0,
                        "type": "image",
                        "img_path": "images/image.jpg",
                        "image_caption": ["主题图"],
                        "image_footnote": ["图片说明"],
                        "bbox": [13, 14, 15, 16],
                    },
                    {"page_idx": 0, "type": "equation", "text": "3.5\\times3", "text_format": "latex", "bbox": [17, 18, 19, 20]},
                ],
                ensure_ascii=False,
            ),
        )
        archive.writestr("images/table.jpg", b"table-image")
        archive.writestr("images/image.jpg", b"image")

    service = MineruDocumentService()
    document = service.normalize_zip_payload(
        batch_id="batch-1",
        file_name="demo.pdf",
        data_id="data-1",
        model_version="vlm",
        full_zip_bytes=zip_buffer.getvalue(),
    )

    blocks = document.pages[0].blocks
    assert blocks[0].block_type == "heading"
    assert blocks[0].heading_level == 1
    assert blocks[0].bbox_json == {"points": [1, 2, 3, 4]}
    assert blocks[1].block_type == "table"
    assert blocks[1].asset_relative_path == "images/table.jpg"
    assert "数量" in blocks[1].text_content
    assert "表 1" in blocks[1].text_content
    assert blocks[2].text_content == "观察情境图\n列出算式"
    assert blocks[3].asset_relative_path == "images/image.jpg"
    assert blocks[3].text_content == "主题图\n图片说明"
    assert blocks[4].block_type == "equation"
    assert blocks[4].text_content == "3.5\\times3"


def test_mineru_document_service_should_normalize_content_list_v2_pages() -> None:
    """仅存在 content_list_v2 时应按页分组补齐页码。"""
    zip_buffer = io.BytesIO()
    with ZipFile(zip_buffer, "w") as archive:
        archive.writestr("full.md", "# 第一页\n\n第二页正文")
        archive.writestr(
            "content_list_v2.json",
            json.dumps(
                [
                    [
                        {
                            "type": "title",
                            "content": {"title_content": "第一页标题", "level": 1},
                            "bbox": [1, 2, 3, 4],
                        }
                    ],
                    [
                        {
                            "type": "paragraph",
                            "content": {"paragraph_content": "第二页正文"},
                            "bbox": [5, 6, 7, 8],
                        },
                        {
                            "type": "image",
                            "content": {"image_source": "images/page2.jpg", "image_caption": ["第二页图片"]},
                            "bbox": [9, 10, 11, 12],
                        },
                    ],
                ],
                ensure_ascii=False,
            ),
        )
        archive.writestr("images/page2.jpg", b"image")

    service = MineruDocumentService()
    document = service.normalize_zip_payload(
        batch_id="batch-1",
        file_name="demo.pdf",
        data_id="data-1",
        model_version="vlm",
        full_zip_bytes=zip_buffer.getvalue(),
    )

    assert [page.page_no for page in document.pages] == [1, 2]
    assert document.pages[0].blocks[0].block_type == "heading"
    assert document.pages[0].blocks[0].heading_level == 1
    assert document.pages[1].blocks[0].text_content == "第二页正文"
    assert document.pages[1].blocks[1].asset_relative_path == "images/page2.jpg"
    assert document.pages[1].blocks[1].text_content == "第二页图片"
