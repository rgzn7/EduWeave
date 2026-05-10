"""
@Date: 2026-05-10
@Author: xisy
@Discription: 从 FastAPI app 直接导出 OpenAPI 文档为 Markdown，无需启动服务
"""

import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BACKEND_DIR))

OUTPUT_PATH = BACKEND_DIR.parent / "docs" / "api文档.md"

# FastAPI 泛型包装层命名约定：ApiResponse_X_ / PaginatedData_X_
# 这些包装类在 OpenAPI 中不会自动生成 data/items 的 $ref，需手动推导


def _strip_generic_wrapper(schema_name: str, prefix: str) -> str | None:
    """从 `Prefix_Inner_` 格式提取 Inner。"""
    if schema_name.startswith(prefix):
        inner = schema_name[len(prefix):]
        if inner.endswith("_"):
            inner = inner[:-1]
        return inner
    return None


def _infer_prop_schema(
    prop_name: str,
    prop_schema: dict,
    parent_schema_name: str,
    components: dict,
) -> dict:
    """
    当字段 schema 没有有效类型信息时，根据父 schema 名称约定推导实际类型：
    - ApiResponse_X_  → data 字段 → X
    - PaginatedData_X_ → items 字段 → array[X]
    - 任意 ApiResponse_* → errors 字段 → array[ErrorDetail]
    """
    has_type_info = any(
        k in prop_schema for k in ("$ref", "type", "anyOf", "oneOf", "properties", "allOf", "items")
    )
    if has_type_info:
        return prop_schema

    schemas = components.get("schemas", {})

    if prop_name == "data" and parent_schema_name.startswith("ApiResponse_"):
        inner = _strip_generic_wrapper(parent_schema_name, "ApiResponse_")
        if inner and inner in schemas:
            return {"$ref": f"#/components/schemas/{inner}"}

    if prop_name == "items" and parent_schema_name.startswith("PaginatedData_"):
        inner = _strip_generic_wrapper(parent_schema_name, "PaginatedData_")
        if inner and inner in schemas:
            return {"type": "array", "items": {"$ref": f"#/components/schemas/{inner}"}}

    if prop_name == "pagination" and parent_schema_name.startswith("PaginatedData_"):
        if "PaginationMeta" in schemas:
            return {"$ref": "#/components/schemas/PaginationMeta"}

    if prop_name == "errors":
        if "ErrorDetail" in schemas:
            return {"type": "array", "items": {"$ref": "#/components/schemas/ErrorDetail"}}

    return prop_schema


def _schema_to_str(
    schema: dict,
    components: dict,
    indent: int = 0,
    schema_name: str = "",
    _visited: frozenset | None = None,
) -> str:
    """递归将 JSON Schema 渲染为可读字符串，自动处理 $ref 与泛型包装层。"""
    if _visited is None:
        _visited = frozenset()

    if not schema:
        return "any"

    # $ref 解引用，防止循环
    if "$ref" in schema:
        ref_name = schema["$ref"].split("/")[-1]
        if ref_name in _visited:
            return f"<{ref_name}>"
        ref_schema = components.get("schemas", {}).get(ref_name, {})
        return _schema_to_str(
            ref_schema, components, indent, schema_name=ref_name, _visited=_visited | {ref_name}
        )

    for key in ("anyOf", "oneOf"):
        if key in schema:
            non_null = [s for s in schema[key] if s.get("type") != "null"]
            if len(non_null) == 1:
                result = _schema_to_str(non_null[0], components, indent, schema_name, _visited)
                # 原始有 null 则标记为可选
                if len(schema[key]) > len(non_null):
                    return f"{result} | null"
                return result
            parts = [_schema_to_str(s, components, indent, schema_name, _visited) for s in schema[key]]
            return " | ".join(parts)

    if "allOf" in schema:
        merged: dict = {}
        for s in schema["allOf"]:
            resolved = components.get("schemas", {}).get(s.get("$ref", "").split("/")[-1], s)
            merged.update(resolved)
        return _schema_to_str(merged, components, indent, schema_name, _visited)

    schema_type = schema.get("type", "")

    # 没有显式 type 时，从 examples 推断基础类型（Pydantic 有时不生成 type 字段）
    if not schema_type and "properties" not in schema and "items" not in schema:
        examples = schema.get("examples", [])
        if examples:
            ex = examples[0]
            if isinstance(ex, bool):
                schema_type = "boolean"
            elif isinstance(ex, int):
                schema_type = "integer"
            elif isinstance(ex, float):
                schema_type = "number"
            elif isinstance(ex, str):
                schema_type = "string"
        if not schema_type:
            schema_type = "object"
    elif not schema_type:
        schema_type = "object"

    if schema_type == "array":
        items = schema.get("items", {})
        return f"array[{_schema_to_str(items, components, indent, schema_name, _visited)}]"

    if schema_type == "object" or "properties" in schema:
        props = schema.get("properties", {})
        required = set(schema.get("required", []))
        if not props:
            return "object"
        pad = "  " * indent
        lines = []
        for name, prop in props.items():
            prop = _infer_prop_schema(name, prop, schema_name, components)
            req_mark = "" if name in required else "?"
            prop_type = _schema_to_str(prop, components, indent + 1, schema_name, _visited)
            desc = prop.get("description", "") or prop.get("title", "")
            desc_str = f"  # {desc}" if desc else ""
            lines.append(f"{pad}  {name}{req_mark}: {prop_type}{desc_str}")
        return "{\n" + "\n".join(lines) + f"\n{pad}}}"

    if "enum" in schema:
        return " | ".join(repr(v) for v in schema["enum"])

    fmt = schema.get("format", "")
    return f"{schema_type}({fmt})" if fmt else schema_type


def _resolve_request_body(op: dict, components: dict) -> str | None:
    rb = op.get("requestBody", {})
    if not rb:
        return None
    for _, media in rb.get("content", {}).items():
        s = media.get("schema")
        if s:
            return _schema_to_str(s, components)
    return None


def _resolve_response_schema(resp: dict, components: dict) -> str:
    for _, media in resp.get("content", {}).items():
        s = media.get("schema")
        if s:
            return _schema_to_str(s, components)
    return ""


def build_markdown(spec: dict) -> str:
    info = spec.get("info", {})
    components = spec.get("components", {})
    paths = spec.get("paths", {})

    lines: list[str] = []

    lines += [
        f"# {info.get('title', 'API 文档')}",
        "",
        f"**版本**: {info.get('version', '')}",
        "",
    ]
    if info.get("description"):
        lines += [info["description"], ""]

    # 按 Tag 分组
    tag_ops: dict[str, list[tuple[str, str, dict]]] = {}
    for path, methods in paths.items():
        for method, op in methods.items():
            if method in ("get", "post", "put", "patch", "delete", "head", "options"):
                tags = op.get("tags") or ["其他"]
                for tag in tags:
                    tag_ops.setdefault(tag, []).append((method.upper(), path, op))

    # 目录
    lines += ["## 目录", ""]
    for tag in tag_ops:
        anchor = tag.lower().replace(" ", "-")
        lines.append(f"- [{tag}](#{anchor})")
    lines.append("")

    for tag, ops in tag_ops.items():
        lines += [f"## {tag}", ""]

        for method, path, op in ops:
            summary = op.get("summary", path)
            deprecated = " *(已废弃)*" if op.get("deprecated") else ""

            lines += [f"### {method} `{path}`{deprecated}", ""]
            if summary:
                lines += [f"**{summary}**", ""]
            if op.get("description"):
                lines += [op["description"], ""]

            # Path / Query 参数
            params = op.get("parameters", [])
            if params:
                lines += [
                    "**参数**",
                    "",
                    "| 位置 | 名称 | 类型 | 必填 | 说明 |",
                    "| --- | --- | --- | --- | --- |",
                ]
                for p in params:
                    p_in = p.get("in", "")
                    p_name = p.get("name", "")
                    p_required = "是" if p.get("required") else "否"
                    p_desc = p.get("description", "")
                    p_schema = p.get("schema", {})
                    p_type = p_schema.get("format") or p_schema.get("type", "string")
                    lines.append(f"| {p_in} | `{p_name}` | {p_type} | {p_required} | {p_desc} |")
                lines.append("")

            # 请求体
            body_str = _resolve_request_body(op, components)
            if body_str:
                lines += ["**请求体**", "", f"```json\n{body_str}\n```", ""]

            # 响应（只展示 200/201，忽略 422 通用校验错误）
            responses = op.get("responses", {})
            success_codes = [c for c in responses if c.startswith("2")]
            if success_codes:
                lines += ["**响应**", ""]
                for code in success_codes:
                    resp = responses[code]
                    desc = resp.get("description", "")
                    schema_str = _resolve_response_schema(resp, components)
                    lines.append(f"`{code}` {desc}")
                    if schema_str:
                        lines += ["", f"```json\n{schema_str}\n```"]
                lines.append("")

            lines += ["---", ""]

    return "\n".join(lines)


def main() -> None:
    import os

    os.environ.setdefault("APP_LOAD_DOTENV", "0")
    os.environ.setdefault("APP_NAME", "EduWeave")
    os.environ.setdefault("APP_VERSION", "0.1.0")
    os.environ.setdefault("APP_ENV", "local")
    os.environ.setdefault("MYSQL_HOST", "localhost")
    os.environ.setdefault("MYSQL_USER", "dummy")
    os.environ.setdefault("MYSQL_PASSWORD", "dummy")
    os.environ.setdefault("JWT_SECRET", "dummy-secret-key-for-doc-export-only")
    os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
    os.environ.setdefault("MILVUS_URI", "http://localhost:19530")
    os.environ.setdefault("MILVUS_EMBEDDING_DIM", "1536")
    os.environ.setdefault("OBS_ENDPOINT", "https://obs.example.com")
    os.environ.setdefault("OBS_AK", "dummy")
    os.environ.setdefault("OBS_SK", "dummy")
    os.environ.setdefault("OBS_BUCKET", "dummy")
    os.environ.setdefault("LLM_API_BASE_URL", "https://api.openai.com/v1")
    os.environ.setdefault("LLM_API_KEY", "dummy")
    os.environ.setdefault("LLM_MODEL", "gpt-4o")
    os.environ.setdefault("EMBEDDING_API_BASE_URL", "https://api.openai.com/v1")
    os.environ.setdefault("EMBEDDING_API_KEY", "dummy")
    os.environ.setdefault("EMBEDDING_MODEL", "text-embedding-3-small")
    os.environ.setdefault("MINERU_API_BASE_URL", "https://mineru.example.com")
    os.environ.setdefault("MINERU_API_TOKEN", "dummy")
    os.environ.setdefault("RACCOON_API_HOST", "https://raccoon.example.com")
    os.environ.setdefault("RACCOON_API_TOKEN", "dummy")
    os.environ.setdefault("CORS_ALLOWED_ORIGINS", '["*"]')

    from app.main import app

    spec = app.openapi()

    md = build_markdown(spec)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(md, encoding="utf-8")
    print(f"✅ 已导出到 {OUTPUT_PATH}")

    json_path = OUTPUT_PATH.with_suffix(".json")
    json_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ OpenAPI JSON 已保存到 {json_path}")


if __name__ == "__main__":
    main()
