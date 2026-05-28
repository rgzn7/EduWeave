"""
@Date: 2026-05-27
@Author: xisy
@Discription: DOCX 导出标题/文件名清洗工具，保证标题与前端展示一致、文件名教师友好
"""

import re
import unicodedata

# 「第N讲 」「第N课 」前缀，N 支持阿拉伯数字与中文数字
_LESSON_PREFIX_PATTERN = re.compile(r"^\s*第\s*[一二三四五六七八九十百千零0-9]+\s*[讲课]\s*[-—:：]*\s*")

# Windows/OBS 上不允许或不友好的文件名字符
_INVALID_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')

# 文件名（不含扩展名）保留的最大 unicode 长度
_FILENAME_STEM_MAX_LEN = 100


def strip_lesson_prefix(title: str | None) -> str:
    """剥离标题中的「第N讲/第N课」前缀。

    LLM 输出的 lesson_title 经常带「第12讲 」之类前缀，与前端清洗后展示不一致；
    标题展示与文件名都应使用纯课题名。空值/无前缀时原样返回（None → ""）。
    """
    if not title:
        return ""
    cleaned = _LESSON_PREFIX_PATTERN.sub("", title).strip()
    return cleaned or title.strip()


def safe_filename_stem(stem: str | None, *, fallback: str = "导出") -> str:
    """把标题段清洗为安全的文件名主体（不含扩展名）。

    剔除非法字符与控制字符，折叠空白；空值或全为非法字符时回退 fallback；超出长度限制时截断。
    不主动添加扩展名，调用方拼接 `.docx` 等后缀。
    """
    if not stem:
        return fallback
    # 归一化全角字符，避免与半角符号产生展示差异
    normalized = unicodedata.normalize("NFKC", stem)
    cleaned = _INVALID_FILENAME_CHARS.sub("", normalized)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .-_")
    if not cleaned:
        return fallback
    if len(cleaned) > _FILENAME_STEM_MAX_LEN:
        cleaned = cleaned[:_FILENAME_STEM_MAX_LEN].rstrip(" .-_")
    return cleaned or fallback


def build_document_filename(*segments: str | None, ext: str, fallback: str = "导出") -> str:
    """以 `-` 拼接若干段并补指定扩展名，空段自动跳过。

    ext 需以 `.` 开头，如 `.docx`、`.pptx`。
    """
    parts: list[str] = []
    for segment in segments:
        if not segment:
            continue
        cleaned = safe_filename_stem(segment, fallback="")
        if cleaned:
            parts.append(cleaned)
    if not parts:
        parts = [fallback]
    return "-".join(parts) + ext


def build_docx_filename(*segments: str | None, fallback: str = "导出") -> str:
    """以 `-` 拼接若干段并补 `.docx` 扩展名，空段自动跳过。"""
    return build_document_filename(*segments, ext=".docx", fallback=fallback)


def build_pptx_filename(*segments: str | None, fallback: str = "导出") -> str:
    """以 `-` 拼接若干段并补 `.pptx` 扩展名，空段自动跳过。"""
    return build_document_filename(*segments, ext=".pptx", fallback=fallback)
