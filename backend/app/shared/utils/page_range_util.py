"""
@Date: 2026-04-14
@Author: xisy
@Discription: 页码范围解析工具
"""

from app.core.exceptions import AppException, BusinessErrorCode


def parse_page_range_text(page_range_text: str, total_pages: int) -> list[int]:
    """将页码范围文本解析为有序页码列表。"""
    if total_pages <= 0:
        raise AppException(BusinessErrorCode.INVALID_PAGE_RANGE, "总页数必须大于 0")

    normalized_text = page_range_text.strip()
    if not normalized_text:
        raise AppException(BusinessErrorCode.INVALID_PAGE_RANGE, "页码范围不能为空")

    page_numbers: list[int] = []
    for raw_token in normalized_text.split(","):
        token = raw_token.strip()
        if not token:
            continue
        if "-" in token:
            start_text, end_text = _split_range_token(token)
            start_page = _normalize_page_no(int(start_text), total_pages)
            end_page = _normalize_page_no(int(end_text), total_pages)
            if start_page > end_page:
                raise AppException(
                    BusinessErrorCode.INVALID_PAGE_RANGE,
                    "页码范围起始值不能大于结束值",
                    {"token": token},
                )
            page_numbers.extend(range(start_page, end_page + 1))
            continue
        page_numbers.append(_normalize_page_no(int(token), total_pages))

    if not page_numbers:
        raise AppException(BusinessErrorCode.INVALID_PAGE_RANGE, "页码范围不能为空")

    deduplicated: list[int] = []
    seen = set()
    for page_no in page_numbers:
        if page_no in seen:
            continue
        deduplicated.append(page_no)
        seen.add(page_no)
    return deduplicated


def _split_range_token(token: str) -> tuple[str, str]:
    if token.count("-") == 1:
        start_text, end_text = token.split("-", 1)
        return start_text.strip(), end_text.strip()
    if token.startswith("-") and token[1:].count("-") == 1:
        end_index = token[1:].find("-") + 1
        return token[:end_index], token[end_index + 1 :]
    raise AppException(
        BusinessErrorCode.INVALID_PAGE_RANGE,
        "页码范围格式非法",
        {"token": token},
    )


def _normalize_page_no(page_no: int, total_pages: int) -> int:
    if page_no == 0:
        raise AppException(BusinessErrorCode.INVALID_PAGE_RANGE, "页码不能为 0")
    if page_no < 0:
        normalized_page_no = total_pages + page_no + 1
    else:
        normalized_page_no = page_no
    if normalized_page_no < 1 or normalized_page_no > total_pages:
        raise AppException(
            BusinessErrorCode.INVALID_PAGE_RANGE,
            "页码超出有效范围",
            {"page_no": page_no, "total_pages": total_pages},
        )
    return normalized_page_no
