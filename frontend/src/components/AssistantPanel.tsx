import { useEffect, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Bot, Loader2, Plus, Send, Sparkles, Wrench, X } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api, streamAgentRunEvents, type AgentContext, type AgentRunEvent } from "../lib/api";
import { useAssistantStore } from "../stores/assistant";
import { cn } from "../utils";

// 事件类型 -> 中文展示标签
const EVENT_LABELS: Record<string, string> = {
  started: "开始处理",
  tool_call: "调用工具",
  tool_result: "工具返回",
  artifact_updated: "资源已更新",
  assistant_thinking: "思考中",
  retry: "稍后重试",
};

function buildContextPayload(context: AgentContext | null | undefined): AgentContext | null {
  if (!context) return null;
  const payload: AgentContext = {};
  if (context.project_id != null) payload.project_id = context.project_id;
  if (context.curriculum_plan_id != null) payload.curriculum_plan_id = context.curriculum_plan_id;
  if (context.class_session_no != null) payload.class_session_no = context.class_session_no;
  if (context.lesson_plan_id != null) payload.lesson_plan_id = context.lesson_plan_id;
  return Object.keys(payload).length ? payload : null;
}

function ToolTimeline({ events }: { events: AgentRunEvent[] }) {
  const visible = events.filter((event) => event.event_type !== "succeeded");
  if (!visible.length) return null;
  return (
    <div className="mt-2 space-y-1 border-l-2 border-line pl-3">
      {visible.map((event, index) => {
        const toolName = (event.payload?.tool_name as string | undefined) ?? "";
        const summary = (event.payload?.summary as string | undefined) ?? event.message ?? "";
        const label = EVENT_LABELS[event.event_type] ?? event.event_type;
        return (
          <div key={`${event.seq ?? index}`} className="flex items-start gap-1.5 text-xs text-ink/55">
            <Wrench size={12} className="mt-0.5 shrink-0" />
            <span className="font-medium text-ink/70">{label}</span>
            {toolName ? <span className="text-ink/45">{toolName}</span> : null}
            {summary ? <span className="truncate text-ink/45">· {summary}</span> : null}
          </div>
        );
      })}
    </div>
  );
}

export function AssistantPanel() {
  const queryClient = useQueryClient();
  const {
    open,
    context,
    sessionId,
    messages,
    busy,
    openPanel,
    closePanel,
    setSessionId,
    setBusy,
    addMessage,
    updateMessage,
    appendMessageEvent,
    resetConversation,
  } = useAssistantStore();

  const [input, setInput] = useState("");
  const bodyRef = useRef<HTMLDivElement | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    bodyRef.current?.scrollTo({ top: bodyRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, busy]);

  useEffect(() => () => abortRef.current?.abort(), []);

  const contextChip = useMemo(() => {
    if (context?.curriculum_plan_id != null && context?.class_session_no != null) {
      return `当前：第 ${context.class_session_no} 课次${context.labels?.lessonTitle ? `《${context.labels.lessonTitle}》` : ""}`;
    }
    if (context?.curriculum_plan_id != null) {
      return `当前：大纲${context.labels?.curriculumTitle ? `《${context.labels.curriculumTitle}》` : ""}`;
    }
    return "单页模式（未锁定具体课次）";
  }, [context]);

  function invalidateResourceQueries() {
    queryClient.invalidateQueries({ queryKey: ["lesson-plans"] });
    queryClient.invalidateQueries({ queryKey: ["lesson-plan"] });
    queryClient.invalidateQueries({ queryKey: ["curriculum-plan"] });
    queryClient.invalidateQueries({ queryKey: ["generation-batch"] });
  }

  async function handleSend() {
    const text = input.trim();
    if (!text || busy) return;
    setInput("");
    setBusy(true);

    const userId = `u-${Date.now()}`;
    const assistantId = `a-${Date.now()}`;
    addMessage({ id: userId, role: "user", content: text, status: "done" });
    addMessage({ id: assistantId, role: "assistant", content: "", status: "pending", events: [] });

    try {
      let currentSessionId = sessionId;
      if (!currentSessionId) {
        const session = await api.agentCreateSession({
          project_id: context?.project_id ?? null,
          title: text.slice(0, 20),
        });
        currentSessionId = session.id;
        setSessionId(currentSessionId);
      }
      const run = await api.agentSubmitRun(currentSessionId, {
        content: text,
        context: buildContextPayload(context),
      });

      abortRef.current?.abort();
      abortRef.current = streamAgentRunEvents(run.id, 0, {
        onEvent: (event) => {
          appendMessageEvent(assistantId, event);
          if (event.event_type === "succeeded") {
            const finalText = (event.payload?.text as string | undefined) ?? "";
            updateMessage(assistantId, { content: finalText, status: "done" });
          } else if (event.event_type === "failed") {
            updateMessage(assistantId, {
              content: `运行失败：${event.message ?? "未知错误"}`,
              status: "error",
            });
          } else if (event.event_type === "artifact_updated") {
            invalidateResourceQueries();
          }
        },
        onDone: () => {
          setBusy(false);
          updateMessage(assistantId, { status: "done" });
        },
        onError: () => {
          updateMessage(assistantId, { content: "事件流连接中断，请稍后重试。", status: "error" });
          setBusy(false);
        },
      });
    } catch (error) {
      updateMessage(assistantId, {
        content: `请求失败：${(error as Error).message}`,
        status: "error",
      });
      setBusy(false);
    }
  }

  function handleReset() {
    abortRef.current?.abort();
    resetConversation();
  }

  return (
    <>
      {/* 悬浮入口按钮：跨页常驻 */}
      {!open ? (
        <button
          type="button"
          onClick={openPanel}
          title="EduWeave 小助手"
          className="fixed bottom-6 right-6 z-30 flex items-center gap-2 rounded-full bg-ink px-4 py-3 text-sm font-semibold text-white shadow-panel transition-all hover:opacity-90 active:scale-95"
        >
          <Sparkles size={18} />
          小助手
        </button>
      ) : null}

      {/* 右侧抽屉面板：整层不拦截点击，仅抽屉本身可交互，保证打开时仍可操作页面（如切换课次） */}
      {open ? (
        <div className="pointer-events-none fixed inset-0 z-40 flex justify-end">
          <div className="pointer-events-auto flex h-full w-full max-w-[420px] flex-col border-l border-line bg-paper shadow-panel">
            {/* 头部 */}
            <div className="flex items-center justify-between border-b border-line px-4 py-3">
              <div className="flex items-center gap-2.5">
                <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-ink/10">
                  <Bot size={15} className="text-ink" />
                </div>
                <span className="text-sm font-semibold text-ink">EduWeave 小助手</span>
              </div>
              <div className="flex items-center gap-1">
                <button
                  type="button"
                  onClick={handleReset}
                  title="开启新对话"
                  className="flex h-8 w-8 items-center justify-center rounded-lg text-ink/55 transition hover:bg-[#f2f2f2] hover:text-ink"
                >
                  <Plus size={16} />
                </button>
                <button
                  type="button"
                  onClick={closePanel}
                  title="收起"
                  className="flex h-8 w-8 items-center justify-center rounded-lg text-ink/55 transition hover:bg-[#f2f2f2] hover:text-ink"
                >
                  <X size={16} />
                </button>
              </div>
            </div>

            {/* 上下文提示 */}
            <div className="border-b border-line bg-white/60 px-4 py-2">
              <div className="flex items-center gap-1.5 text-xs text-ink/55">
                <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-ink/30" />
                {contextChip}
              </div>
            </div>

            {/* 消息区 */}
            <div ref={bodyRef} className="flex-1 space-y-4 overflow-y-auto px-4 py-4">
              {messages.length === 0 ? (
                <div className="mt-12 flex flex-col items-center gap-3 text-center">
                  <div className="flex h-12 w-12 items-center justify-center rounded-full border border-line bg-white">
                    <Bot size={22} className="text-ink/40" />
                  </div>
                  <p className="text-sm text-ink/45">
                    你好，我可以帮你修改当前课次的教案、联动更新大纲，或基于教材回答问题。
                  </p>
                  <p className="text-xs text-ink/35">试试：「把本课导入环节改得更有趣」</p>
                </div>
              ) : null}
              {messages.map((message) =>
                message.role === "user" ? (
                  <div key={message.id} className="flex justify-end">
                    <div className="max-w-[88%] rounded-2xl bg-ink px-3 py-2 text-sm text-white">
                      <span className="whitespace-pre-wrap break-words">{message.content}</span>
                    </div>
                  </div>
                ) : (
                  <div key={message.id} className="flex items-start gap-2">
                    <div className="mt-1 flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-line bg-white">
                      <Bot size={12} className="text-ink/50" />
                    </div>
                    <div className="max-w-[82%] rounded-2xl border border-line bg-white px-3 py-2 text-sm text-ink">
                      {message.content ? (
                        <div className="markdown-body prose prose-sm max-w-none break-words text-ink">
                          <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
                        </div>
                      ) : message.status === "pending" ? (
                        <div className="flex items-center gap-2 text-ink/55">
                          <Loader2 size={14} className="animate-spin" />
                          正在处理…
                        </div>
                      ) : null}
                      {message.events && message.status !== "done" ? (
                        <ToolTimeline events={message.events} />
                      ) : null}
                    </div>
                  </div>
                ),
              )}
            </div>

            {/* 输入区 */}
            <div className="border-t border-line p-3">
              <div className="flex items-center gap-2">
                <textarea
                  value={input}
                  onChange={(event) => setInput(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" && !event.shiftKey) {
                      event.preventDefault();
                      void handleSend();
                    }
                  }}
                  rows={2}
                  placeholder="输入你的备课需求，Enter 发送，Shift+Enter 换行"
                  className="flex-1 resize-none rounded-xl border border-line bg-white px-3 py-2 text-sm text-ink outline-none focus:border-ink/40"
                />
                <button
                  type="button"
                  onClick={() => void handleSend()}
                  disabled={busy || !input.trim()}
                  className="flex h-10 w-10 items-center justify-center rounded-xl bg-ink text-white transition-all hover:opacity-90 disabled:opacity-40 active:scale-95"
                  title="发送"
                >
                  {busy ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} />}
                </button>
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}
