"""
@Date: 2026-05-03
@Author: xisy
@Discription: Raccoon PPT 客户端测试
"""

from types import SimpleNamespace

import httpx
import pytest

from app.core.exceptions import AppException, BusinessErrorCode
from app.shared.ppt import RaccoonPptClient


class FakeHttpClient:
    """用于模拟 httpx 客户端。"""

    def __init__(self, responses: list[httpx.Response]) -> None:
        self.responses = responses
        self.requests: list[dict] = []

    def post(self, url: str, headers=None, json=None):  # noqa: ANN001
        self.requests.append({"method": "POST", "url": url, "headers": headers, "json": json})
        return self.responses.pop(0)

    def get(self, url: str, headers=None):  # noqa: ANN001
        self.requests.append({"method": "GET", "url": url, "headers": headers})
        return self.responses.pop(0)


def build_settings(token: str | None = "test-token"):
    """构造 Raccoon 客户端所需配置。"""
    return SimpleNamespace(
        raccoon_api_host="https://xiaohuanxiong.com",
        raccoon_api_token=token,
        raccoon_request_timeout_seconds=60,
    )


def test_raccoon_client_should_create_query_and_reply_job() -> None:
    """Raccoon 客户端应能创建、查询和回复 PPT 任务。"""
    fake_http = FakeHttpClient(
        [
            httpx.Response(200, json={"data": {"job_id": "job-1", "status": "queued"}}),
            httpx.Response(200, json={"data": {"job_id": "job-1", "status": "succeeded", "download_url": "https://file/pptx"}}),
            httpx.Response(200, json={"data": {"job_id": "job-1", "status": "running"}}),
        ]
    )
    client = RaccoonPptClient(settings=build_settings(), http_client=fake_http)

    created = client.create_ppt_job(prompt="生成课件", role="教师", scene="培训教学", audience="学生")
    queried = client.get_ppt_job("job-1")
    replied = client.reply_ppt_job(job_id="job-1", answer="补充说明")

    assert created.job_id == "job-1"
    assert queried.status == "succeeded"
    assert queried.download_url == "https://file/pptx"
    assert replied.status == "running"
    assert fake_http.requests[0]["url"].endswith("/api/open/office/v2/ppt_jobs")
    assert fake_http.requests[2]["json"] == {"answer": "补充说明"}


def test_raccoon_client_should_raise_when_token_missing() -> None:
    """缺少 Token 时应抛出系统配置异常。"""
    client = RaccoonPptClient(settings=build_settings(token=None), http_client=FakeHttpClient([]))

    with pytest.raises(AppException) as exc_info:
        client.get_ppt_job("job-1")

    assert exc_info.value.code == BusinessErrorCode.SYSTEM_CONFIG_INVALID


def test_raccoon_client_should_raise_when_api_error() -> None:
    """远程接口报错时应抛出 Raccoon 调用异常。"""
    fake_http = FakeHttpClient([httpx.Response(500, json={"message": "server error"})])
    client = RaccoonPptClient(settings=build_settings(), http_client=fake_http)

    with pytest.raises(AppException) as exc_info:
        client.get_ppt_job("job-1")

    assert exc_info.value.code == BusinessErrorCode.RACCOON_REQUEST_FAILED
