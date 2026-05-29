/**
 * @Date: 2026-05-29
 * @Author: xisy
 * @Discription: 小助手消息 Markdown 渲染：自定义块/行内解析 + mermaid 图表，排版对齐 thesis-viva agent 模式页（不含打字机/图片）
 */
import { Code2, Image as ImageIcon } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { loadMermaid } from "../utils/mermaid";

type MarkdownBlock =
  | { type: "heading"; depth: number; text: string }
  | { type: "paragraph"; text: string }
  | { type: "quote"; text: string }
  | { type: "hr" }
  | { type: "ul"; items: string[] }
  | { type: "ol"; items: string[]; start: number }
  | { type: "code"; language: string; code: string }
  | { type: "table"; headers: string[]; rows: string[][] };

const splitTableRow = (line: string) =>
  line
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((cell) => cell.trim());

const isTableDivider = (line: string) => {
  const cells = splitTableRow(line);
  return cells.length > 1 && cells.every((cell) => /^:?-{3,}:?$/.test(cell));
};

const isMarkdownHorizontalRule = (line: string) => /^ {0,3}(([-*_])(?:\s*\2){2,})\s*$/.test(line);

// 块级解析：标题/段落/引用/分割线/有序无序列表/代码块/表格
const parseMarkdownBlocks = (content: string): MarkdownBlock[] => {
  const blocks: MarkdownBlock[] = [];
  const lines = content.replace(/\r\n/g, "\n").split("\n");
  let paragraph: string[] = [];
  let listType: "ul" | "ol" | null = null;
  let orderedListStart = 1;
  let listItems: string[] = [];
  let quoteLines: string[] = [];
  let codeLines: string[] = [];
  let codeLanguage = "";
  let inCode = false;

  const flushParagraph = () => {
    if (!paragraph.length) return;
    blocks.push({ type: "paragraph", text: paragraph.join("\n") });
    paragraph = [];
  };
  const flushList = () => {
    if (!listType || !listItems.length) return;
    if (listType === "ol") {
      blocks.push({ type: "ol", items: listItems, start: orderedListStart });
    } else {
      blocks.push({ type: "ul", items: listItems });
    }
    listType = null;
    orderedListStart = 1;
    listItems = [];
  };
  const flushQuote = () => {
    if (!quoteLines.length) return;
    blocks.push({ type: "quote", text: quoteLines.join("\n") });
    quoteLines = [];
  };
  const flushSoftBlocks = () => {
    flushParagraph();
    flushList();
    flushQuote();
  };

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    const trimmed = line.trim();
    const fenceMatch = trimmed.match(/^```([\w-]*)/);

    if (fenceMatch) {
      if (inCode) {
        blocks.push({ type: "code", language: codeLanguage, code: codeLines.join("\n") });
        inCode = false;
        codeLanguage = "";
        codeLines = [];
      } else {
        flushSoftBlocks();
        inCode = true;
        codeLanguage = fenceMatch[1] || "";
      }
      continue;
    }

    if (inCode) {
      codeLines.push(line);
      continue;
    }

    if (!trimmed) {
      flushSoftBlocks();
      continue;
    }

    if (isMarkdownHorizontalRule(line)) {
      flushSoftBlocks();
      blocks.push({ type: "hr" });
      continue;
    }

    if (index + 1 < lines.length && line.includes("|") && isTableDivider(lines[index + 1])) {
      flushSoftBlocks();
      const headers = splitTableRow(line);
      const rows: string[][] = [];
      index += 2;
      while (index < lines.length && lines[index].includes("|") && lines[index].trim()) {
        rows.push(splitTableRow(lines[index]));
        index += 1;
      }
      index -= 1;
      blocks.push({ type: "table", headers, rows });
      continue;
    }

    const headingMatch = trimmed.match(/^(#{1,4})\s+(.+)$/);
    if (headingMatch) {
      flushSoftBlocks();
      blocks.push({ type: "heading", depth: headingMatch[1].length, text: headingMatch[2] });
      continue;
    }

    const quoteMatch = trimmed.match(/^>\s?(.*)$/);
    if (quoteMatch) {
      flushParagraph();
      flushList();
      quoteLines.push(quoteMatch[1]);
      continue;
    }

    const unorderedMatch = trimmed.match(/^[-*+]\s+(.+)$/);
    const orderedMatch = trimmed.match(/^(\d+)[.)]\s+(.+)$/);
    if (unorderedMatch || orderedMatch) {
      flushParagraph();
      flushQuote();
      const nextListType = unorderedMatch ? "ul" : "ol";
      if (listType && listType !== nextListType) flushList();
      if (!listType && orderedMatch) {
        orderedListStart = Number.parseInt(orderedMatch[1], 10) || 1;
      }
      listType = nextListType;
      listItems.push(unorderedMatch?.[1] || orderedMatch?.[2] || "");
      continue;
    }

    flushList();
    flushQuote();
    paragraph.push(line);
  }

  if (inCode) {
    blocks.push({ type: "code", language: codeLanguage, code: codeLines.join("\n") });
  }
  flushSoftBlocks();
  return blocks;
};

const renderTextWithBreaks = (text: string, keyPrefix: string): ReactNode[] =>
  text
    .split("\n")
    .flatMap((part, index, parts) =>
      index === parts.length - 1 ? [part] : [part, <br key={`${keyPrefix}-br-${index}`} />],
    );

// 行内解析：行内代码 / 加粗 / 斜体 / 链接（图片按需关闭，仅保留文本类语法）
const renderInlineMarkdown = (text: string, keyPrefix: string): ReactNode[] => {
  const nodes: ReactNode[] = [];
  const tokenPattern =
    /(`([^`]+)`)|(\*\*([^*]+)\*\*)|(__([^_]+)__)|(\*([^*\n]+)\*)|(_([^_\n]+)_)|(\[([^\]]+)\]\((https?:\/\/[^\s)]+)\))/g;
  let lastIndex = 0;
  let tokenIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = tokenPattern.exec(text)) !== null) {
    if (match.index > lastIndex) {
      nodes.push(...renderTextWithBreaks(text.slice(lastIndex, match.index), `${keyPrefix}-${tokenIndex}`));
    }
    const key = `${keyPrefix}-token-${tokenIndex}`;
    if (match[2]) {
      nodes.push(<code key={key}>{match[2]}</code>);
    } else if (match[4] || match[6]) {
      nodes.push(<strong key={key}>{match[4] || match[6]}</strong>);
    } else if (match[8] || match[10]) {
      nodes.push(<em key={key}>{match[8] || match[10]}</em>);
    } else if (match[12] && match[13]) {
      nodes.push(
        <a key={key} href={match[13]} target="_blank" rel="noreferrer">
          {match[12]}
        </a>,
      );
    }
    lastIndex = tokenPattern.lastIndex;
    tokenIndex += 1;
  }

  if (lastIndex < text.length) {
    nodes.push(...renderTextWithBreaks(text.slice(lastIndex), `${keyPrefix}-tail`));
  }
  return nodes;
};

export function MarkdownContent({ content }: { content: string }) {
  const blocks = useMemo(() => parseMarkdownBlocks(content), [content]);
  if (blocks.length === 0) return null;

  return (
    <div className="markdown">
      {blocks.map((block, index) => {
        const key = `md-${index}`;
        if (block.type === "heading") {
          const headingClassName = `markdown__heading markdown__heading--${Math.min(block.depth, 4)}`;
          if (block.depth <= 1) {
            return (
              <h2 className={headingClassName} key={key}>
                {renderInlineMarkdown(block.text, key)}
              </h2>
            );
          }
          if (block.depth === 2) {
            return (
              <h3 className={headingClassName} key={key}>
                {renderInlineMarkdown(block.text, key)}
              </h3>
            );
          }
          return (
            <h4 className={headingClassName} key={key}>
              {renderInlineMarkdown(block.text, key)}
            </h4>
          );
        }
        if (block.type === "paragraph") {
          return <p key={key}>{renderInlineMarkdown(block.text, key)}</p>;
        }
        if (block.type === "quote") {
          return <blockquote key={key}>{renderInlineMarkdown(block.text, key)}</blockquote>;
        }
        if (block.type === "hr") {
          return <hr className="markdown__rule" key={key} />;
        }
        if (block.type === "ul") {
          return (
            <ul key={key}>
              {block.items.map((item, itemIndex) => (
                <li key={`${key}-${itemIndex}`}>{renderInlineMarkdown(item, `${key}-${itemIndex}`)}</li>
              ))}
            </ul>
          );
        }
        if (block.type === "ol") {
          return (
            <ol key={key} start={block.start}>
              {block.items.map((item, itemIndex) => (
                <li key={`${key}-${itemIndex}`}>{renderInlineMarkdown(item, `${key}-${itemIndex}`)}</li>
              ))}
            </ol>
          );
        }
        if (block.type === "table") {
          return (
            <div className="markdown__table-wrap" key={key}>
              <table>
                <thead>
                  <tr>
                    {block.headers.map((header, cellIndex) => (
                      <th key={`${key}-h-${cellIndex}`}>{renderInlineMarkdown(header, `${key}-h-${cellIndex}`)}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {block.rows.map((row, rowIndex) => (
                    <tr key={`${key}-r-${rowIndex}`}>
                      {block.headers.map((_, cellIndex) => (
                        <td key={`${key}-r-${rowIndex}-${cellIndex}`}>
                          {renderInlineMarkdown(row[cellIndex] || "", `${key}-r-${rowIndex}-${cellIndex}`)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          );
        }
        if (block.language === "mermaid") {
          return <MermaidBlock code={block.code} key={key} />;
        }
        return (
          <pre className="markdown__code" key={key}>
            {block.language && <span>{block.language}</span>}
            <code>{block.code}</code>
          </pre>
        );
      })}
    </div>
  );
}

// Mermaid 图表块：渲染成功后提供「图表/源码」切换，失败时回落到源码
function MermaidBlock({ code }: { code: string }) {
  const [svg, setSvg] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<"svg" | "code">("svg");
  const sequenceRef = useRef(0);

  useEffect(() => {
    const trimmed = code.trim();
    if (!trimmed) {
      setSvg(null);
      setErrorMessage(null);
      return;
    }
    // 250ms 去抖 + sequence 校验，避免流式追加期间频繁渲染导致闪烁与过期覆盖
    const sequence = ++sequenceRef.current;
    const timer = window.setTimeout(async () => {
      try {
        const mermaid = await loadMermaid();
        await mermaid.parse(trimmed);
        if (sequence !== sequenceRef.current) return;
        const renderId = `ew-mermaid-${sequence}-${Math.random().toString(36).slice(2, 8)}`;
        const { svg: rendered } = await mermaid.render(renderId, trimmed);
        if (sequence !== sequenceRef.current) return;
        setSvg(rendered);
        setErrorMessage(null);
      } catch (error) {
        if (sequence !== sequenceRef.current) return;
        setSvg(null);
        setErrorMessage(error instanceof Error ? error.message : String(error));
      }
    }, 250);
    return () => window.clearTimeout(timer);
  }, [code]);

  const hasSvg = svg !== null;
  // 未渲染成功时强制回落到源码视图，避免「图表 tab 选中但内容是源码」的错位
  const showCode = !hasSvg || viewMode === "code";

  return (
    <div className={`markdown-mermaid${errorMessage ? " markdown-mermaid--error" : ""}`}>
      <div className="markdown-mermaid__toolbar">
        {hasSvg ? (
          <div className="markdown-mermaid__tabs" role="tablist" aria-label="Mermaid 视图切换">
            <button
              type="button"
              role="tab"
              aria-selected={viewMode === "svg"}
              aria-label="查看图表"
              title="查看图表"
              className={`markdown-mermaid__tab${viewMode === "svg" ? " is-active" : ""}`}
              onClick={() => setViewMode("svg")}
            >
              <ImageIcon size={14} aria-hidden="true" />
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={viewMode === "code"}
              aria-label="查看源码"
              title="查看源码"
              className={`markdown-mermaid__tab${viewMode === "code" ? " is-active" : ""}`}
              onClick={() => setViewMode("code")}
            >
              <Code2 size={14} aria-hidden="true" />
            </button>
          </div>
        ) : (
          <span className="markdown-mermaid__status">
            {errorMessage ? "mermaid 语法错误" : "mermaid 加载中"}
          </span>
        )}
      </div>
      {showCode ? (
        <pre className="markdown-mermaid__code">
          <code>{code}</code>
        </pre>
      ) : (
        <div className="markdown-mermaid__view" dangerouslySetInnerHTML={{ __html: svg! }} />
      )}
    </div>
  );
}
