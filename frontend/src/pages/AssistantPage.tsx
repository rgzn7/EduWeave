/**
 * @Date: 2026-05-29
 * @Author: xisy
 * @Discription: 独立小助手页：两栏布局（左=项目/会话选择，右=聊天），支持项目切换、会话列表/切换/新建与 SSE 流式回答
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Bot, FolderClosed, Loader2, MessageSquarePlus, Send, Sparkles } from "lucide-react";
import {
  api,
  streamAgentRunEvents,
  type AgentRunEvent,
  type AgentSession,
} from "../lib/api";
import { AgentRunTimeline } from "../components/AgentRunTimeline";
import { MarkdownContent } from "../components/Markdown";
import type { Project } from "../types";
import { cn, formatDate } from "../utils";

type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  status: "pending" | "done" | "error";
  events?: AgentRunEvent[];
};

export function AssistantPage() {
  const [activeProjectId, setActiveProjectId] = useState<number | null>(null);
  const [activeSessionId, setActiveSessionId] = useState<number | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);

  const bodyRef = useRef<HTMLDivElement | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  // 异步回放历史可能跨越会话切换，用 ref 锁定当前会话用于校验
  const activeSessionIdRef = useRef<number | null>(null);
  useEffect(() => {
    activeSessionIdRef.current = activeSessionId;
  }, [activeSessionId]);

  // 输入框随内容自适应高度（参考 thesis-viva composer：单行起，最高 34vh/260px）
  function resizeComposer() {
    const textarea = textareaRef.current;
    if (!textarea) return;
    textarea.style.height = "auto";
    const max = Math.min(window.innerHeight * 0.34, 260);
    const next = Math.min(textarea.scrollHeight, max);
    textarea.style.height = `${next}px`;
    textarea.style.overflowY = textarea.scrollHeight > next ? "auto" : "hidden";
  }
  useEffect(() => {
    resizeComposer();
  }, [input]);

  const projectsQuery = useQuery({
    queryKey: ["projects", "assistant"],
    queryFn: () => api.listProjects({ page: 1, page_size: 100 }),
  });
  const projects = useMemo<Project[]>(() => projectsQuery.data?.items ?? [], [projectsQuery.data?.items]);

  // 移除「全部项目」模式：项目加载后自动选中首个，保证始终锁定具体项目
  useEffect(() => {
    if (activeProjectId == null && projects.length > 0) {
      setActiveProjectId(projects[0].id);
    }
  }, [activeProjectId, projects]);

  // 会话列表随所选项目范围刷新（未选项目时拉取全部会话）
  const sessionsQuery = useQuery({
    queryKey: ["agent-sessions", activeProjectId],
    queryFn: () => api.agentListSessions({ project_id: activeProjectId, page: 1, page_size: 100 }),
  });
  const sessions = useMemo<AgentSession[]>(() => sessionsQuery.data?.items ?? [], [sessionsQuery.data?.items]);

  const activeSession = useMemo(
    () => sessions.find((session) => session.id === activeSessionId) ?? null,
    [sessions, activeSessionId],
  );

  useEffect(() => {
    bodyRef.current?.scrollTo({ top: bodyRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, busy]);

  useEffect(() => () => abortRef.current?.abort(), []);

  // 切换会话：中止流、清空消息并回放历史
  function selectSession(sessionId: number | null) {
    abortRef.current?.abort();
    setBusy(false);
    setActiveSessionId(sessionId);
    setMessages([]);
    if (sessionId != null) {
      void loadHistory(sessionId);
    }
  }

  // 切换项目范围：重置当前会话选择
  function selectProject(projectId: number) {
    if (projectId === activeProjectId) return;
    abortRef.current?.abort();
    setBusy(false);
    setActiveProjectId(projectId);
    setActiveSessionId(null);
    setMessages([]);
  }

  function startNewSession() {
    abortRef.current?.abort();
    setBusy(false);
    setActiveSessionId(null);
    setMessages([]);
    setInput("");
  }

  // 打开历史会话：拉取消息，并按 run 逐条回放工具过程事件
  async function loadHistory(sessionId: number) {
    setHistoryLoading(true);
    try {
      const history = await api.agentListMessages(sessionId, 100);
      const runIds = Array.from(
        new Set(history.map((item) => item.run_id).filter((value): value is number => typeof value === "number" && value > 0)),
      );
      const eventsByRun = new Map<number, AgentRunEvent[]>();
      await Promise.all(
        runIds.map(async (runId) => {
          try {
            eventsByRun.set(runId, await api.agentListRunEvents(runId, 0));
          } catch {
            eventsByRun.set(runId, []);
          }
        }),
      );
      // 异步期间用户可能已切走，丢弃过期结果
      if (activeSessionIdRef.current !== sessionId) return;
      setMessages(
        history.map((item) => ({
          id: `m-${item.id}`,
          role: item.role === "user" ? "user" : "assistant",
          content: item.content ?? "",
          status: "done",
          events: item.run_id ? eventsByRun.get(item.run_id) ?? [] : [],
        })),
      );
    } finally {
      if (activeSessionIdRef.current === sessionId) setHistoryLoading(false);
    }
  }

  async function handleSend() {
    const text = input.trim();
    if (!text || busy) return;
    if (activeProjectId == null) return;
    setInput("");
    setBusy(true);

    const userId = `u-${Date.now()}`;
    const assistantId = `a-${Date.now()}`;
    setMessages((prev) => [
      ...prev,
      { id: userId, role: "user", content: text, status: "done" },
      { id: assistantId, role: "assistant", content: "", status: "pending", events: [] },
    ]);

    const patchAssistant = (patch: Partial<ChatMessage>) =>
      setMessages((prev) => prev.map((message) => (message.id === assistantId ? { ...message, ...patch } : message)));

    try {
      let currentSessionId = activeSessionId;
      if (!currentSessionId) {
        const session = await api.agentCreateSession({
          project_id: activeProjectId,
          title: text.slice(0, 20),
        });
        currentSessionId = session.id;
        setActiveSessionId(currentSessionId);
        void sessionsQuery.refetch();
      }
      const run = await api.agentSubmitRun(currentSessionId, {
        content: text,
        // 独立页锁定项目范围，不携带具体课次上下文
        context: { project_id: activeProjectId },
      });

      abortRef.current?.abort();
      abortRef.current = streamAgentRunEvents(run.id, 0, {
        onEvent: (event) => {
          setMessages((prev) =>
            prev.map((message) =>
              message.id === assistantId ? { ...message, events: [...(message.events ?? []), event] } : message,
            ),
          );
          if (event.event_type === "succeeded") {
            const finalText = (event.payload?.text as string | undefined) ?? "";
            patchAssistant({ content: finalText, status: "done" });
          } else if (event.event_type === "failed") {
            patchAssistant({ content: `运行失败：${event.message ?? "未知错误"}`, status: "error" });
          }
        },
        onDone: () => {
          setBusy(false);
          patchAssistant({ status: "done" });
          void sessionsQuery.refetch();
        },
        onError: () => {
          patchAssistant({ content: "事件流连接中断，请稍后重试。", status: "error" });
          setBusy(false);
        },
      });
    } catch (error) {
      patchAssistant({ content: `请求失败：${(error as Error).message}`, status: "error" });
      setBusy(false);
    }
  }

  const projectLabel = (project: Project) => project.name || `项目 #${project.id}`;

  return (
    <div className="flex h-screen gap-4 py-4 box-border">
      {/* 左栏：项目 + 会话选择器 */}
      <aside className="flex w-72 shrink-0 flex-col gap-4 overflow-hidden">
        <div className="flex min-h-0 flex-1 flex-col rounded-2xl border border-line bg-white">
          <div className="flex items-center gap-2 border-b border-line px-4 py-3 text-xs font-semibold tracking-wide text-ink/45">
            <FolderClosed size={14} />
            项目
          </div>
          <div className="min-h-0 flex-1 space-y-1 overflow-y-auto p-2">
            {projects.map((project) => (
              <button
                type="button"
                key={project.id}
                onClick={() => selectProject(project.id)}
                className={cn(
                  "flex w-full flex-col gap-0.5 rounded-xl px-3 py-2 text-left transition hover:bg-[#f2f2f2]",
                  activeProjectId === project.id ? "bg-ink text-white hover:bg-ink" : "text-ink/65 hover:text-ink",
                )}
              >
                <span className="truncate text-sm font-medium">{projectLabel(project)}</span>
                <span className={cn("truncate text-xs", activeProjectId === project.id ? "text-white/60" : "text-ink/40")}>
                  {project.subject_code} · {project.grade_code}
                </span>
              </button>
            ))}
            {projectsQuery.isLoading ? (
              <div className="flex items-center gap-2 px-3 py-2 text-xs text-ink/40">
                <Loader2 size={12} className="animate-spin" />
                加载项目…
              </div>
            ) : null}
          </div>
        </div>

        <div className="flex min-h-0 flex-1 flex-col rounded-2xl border border-line bg-white">
          <div className="flex items-center justify-between border-b border-line px-4 py-3">
            <span className="text-xs font-semibold tracking-wide text-ink/45">会话</span>
            <button
              type="button"
              onClick={startNewSession}
              title="新建会话"
              className="flex h-7 w-7 items-center justify-center rounded-lg text-ink/55 transition hover:bg-[#f2f2f2] hover:text-ink"
            >
              <MessageSquarePlus size={15} />
            </button>
          </div>
          <div className="min-h-0 flex-1 space-y-1 overflow-y-auto p-2">
            {sessions.map((session) => (
              <button
                type="button"
                key={session.id}
                onClick={() => selectSession(session.id)}
                className={cn(
                  "flex w-full flex-col gap-0.5 rounded-xl px-3 py-2 text-left transition hover:bg-[#f2f2f2]",
                  activeSessionId === session.id ? "bg-[#f2f2f2] text-ink" : "text-ink/65 hover:text-ink",
                )}
              >
                <span className="truncate text-sm font-medium">{session.title || `会话 #${session.id}`}</span>
                <span className="truncate text-xs text-ink/40">{formatDate(session.updated_at)}</span>
              </button>
            ))}
            {sessionsQuery.isLoading ? (
              <div className="flex items-center gap-2 px-3 py-2 text-xs text-ink/40">
                <Loader2 size={12} className="animate-spin" />
                加载会话…
              </div>
            ) : sessions.length === 0 ? (
              <p className="px-3 py-6 text-center text-xs text-ink/35">还没有会话，点右上角新建</p>
            ) : null}
          </div>
        </div>
      </aside>

      {/* 右栏：聊天 */}
      <section className="relative flex min-w-0 flex-1 flex-col overflow-hidden rounded-2xl border border-line bg-white">
        <header className="flex items-center gap-2.5 border-b border-line px-5 py-3">
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-ink/10">
            <Bot size={15} className="text-ink" />
          </div>
          <div className="min-w-0">
            <div className="truncate text-sm font-semibold text-ink">
              {activeSession?.title || "EduWeave 小助手"}
            </div>
            <div className="truncate text-xs text-ink/45">
              {activeProjectId == null
                ? "请选择左侧项目"
                : projects.find((p) => p.id === activeProjectId)?.name ?? `项目 #${activeProjectId}`}
            </div>
          </div>
        </header>

        {/* 聊天区：内容居中限宽，底部留出悬浮输入框的空间 */}
        <div ref={bodyRef} className="flex-1 overflow-y-auto px-5 pt-5 pb-36">
          <div className="mx-auto w-full max-w-3xl space-y-4">
            {historyLoading ? (
              <div className="flex items-center justify-center gap-2 py-12 text-sm text-ink/45">
                <Loader2 size={16} className="animate-spin" />
                正在加载历史会话…
              </div>
            ) : messages.length === 0 ? (
              <div className="mt-16 flex flex-col items-center gap-3 text-center">
                <div className="flex h-12 w-12 items-center justify-center rounded-full border border-line bg-white">
                  <Sparkles size={22} className="text-ink/40" />
                </div>
                <p className="max-w-sm text-sm text-ink/45">
                  我可以基于教材与学情，帮你修改大纲、教案、作业与测评，或回答备课相关问题。
                </p>
                <p className="text-xs text-ink/35">已锁定左侧选中项目，直接提问即可开始</p>
              </div>
            ) : (
              messages.map((message) =>
                message.role === "user" ? (
                  <div key={message.id} className="flex justify-end">
                    <div className="max-w-[80%] rounded-2xl bg-ink px-3.5 py-2 text-sm text-white">
                      <span className="whitespace-pre-wrap break-words">{message.content}</span>
                    </div>
                  </div>
                ) : (
                  <div key={message.id} className="flex items-start gap-2.5">
                    <div className="mt-1 flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-line bg-white">
                      <Bot size={12} className="text-ink/50" />
                    </div>
                    <div className="max-w-[80%] rounded-2xl border border-line bg-white px-3.5 py-2 text-sm text-ink">
                      {message.content ? (
                        <MarkdownContent content={message.content} />
                      ) : message.status === "pending" ? (
                        <div className="flex items-center gap-2 text-ink/55">
                          <Loader2 size={14} className="animate-spin" />
                          正在处理…
                        </div>
                      ) : null}
                      {message.events && message.status !== "done" ? <AgentRunTimeline events={message.events} /> : null}
                    </div>
                  </div>
                ),
              )
            )}
          </div>
        </div>

        {/* 悬浮输入框：融入聊天区底部，限宽居中，不拦截两侧滚动 */}
        <div className="pointer-events-none absolute inset-x-0 bottom-0 px-5 pb-4">
          <div className="pointer-events-auto mx-auto w-full max-w-3xl">
            <div className="grid gap-2.5 rounded-xl border border-line bg-white/90 px-3 pb-2.5 pt-3 shadow-[0_12px_34px_-22px_rgba(20,17,11,0.5)] backdrop-blur transition focus-within:border-ink/40 focus-within:shadow-[0_0_0_3px_rgba(17,17,17,0.06),0_14px_38px_-22px_rgba(20,17,11,0.5)]">
              <textarea
                ref={textareaRef}
                value={input}
                onChange={(event) => setInput(event.target.value)}
                onInput={resizeComposer}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                    event.preventDefault();
                    void handleSend();
                  }
                }}
                rows={1}
                maxLength={4000}
                placeholder="输入你的备课需求，Enter 发送，Shift+Enter 换行"
                className="max-h-[34vh] min-h-[44px] w-full resize-none border-0 bg-transparent px-1 pt-0.5 text-sm leading-relaxed text-ink outline-none placeholder:text-ink/35"
              />
              <div className="flex items-center justify-between gap-3">
                <span className="font-mono text-[10.5px] font-bold text-ink/35">
                  {input.length.toLocaleString("zh-CN")} / 4000
                </span>
                <button
                  type="button"
                  onClick={() => void handleSend()}
                  disabled={busy || !input.trim()}
                  className="inline-flex min-h-[36px] min-w-[84px] items-center justify-center gap-1.5 self-end rounded-lg bg-ink px-3.5 text-[13px] font-bold text-white transition-all hover:-translate-y-px disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:translate-y-0"
                  title="发送"
                >
                  {busy ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} />}
                  <span>发送</span>
                </button>
              </div>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
