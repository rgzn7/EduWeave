import { create } from "zustand";
import type { AgentContext, AgentRunEvent } from "../lib/api";

// 所在课次教案上下文标签（用于面板顶部展示）
export type AssistantContextLabels = {
  projectName?: string;
  curriculumTitle?: string;
  lessonTitle?: string;
};

export type AssistantContext = AgentContext & { labels?: AssistantContextLabels };

export type AssistantChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  status: "pending" | "done" | "error";
  // 助手消息进行中的工具调用过程事件
  events?: AgentRunEvent[];
};

type AssistantState = {
  open: boolean;
  context: AssistantContext | null;
  sessionId: number | null;
  // 当前会话所属项目：跨项目切换时据此丢弃上一个项目残留的会话
  sessionProjectId: number | null;
  messages: AssistantChatMessage[];
  busy: boolean;

  openPanel: () => void;
  closePanel: () => void;
  togglePanel: () => void;
  setContext: (context: AssistantContext | null) => void;
  clearContext: () => void;
  setSessionId: (sessionId: number | null, projectId?: number | null) => void;
  setBusy: (busy: boolean) => void;
  addMessage: (message: AssistantChatMessage) => void;
  updateMessage: (id: string, patch: Partial<AssistantChatMessage>) => void;
  appendMessageEvent: (id: string, event: AgentRunEvent) => void;
  resetConversation: () => void;
};

export const useAssistantStore = create<AssistantState>((set) => ({
  open: false,
  context: null,
  sessionId: null,
  sessionProjectId: null,
  messages: [],
  busy: false,

  openPanel: () => set({ open: true }),
  closePanel: () => set({ open: false }),
  togglePanel: () => set((state) => ({ open: !state.open })),
  setContext: (context) =>
    set((state) => {
      const nextProjectId = context?.project_id ?? null;
      // 切换到不同项目时，清空上一个项目残留的会话与消息，避免跨项目串台；
      // 同项目内切换课次、离开后再回到同项目则保留会话
      if (nextProjectId != null && state.sessionProjectId != null && nextProjectId !== state.sessionProjectId) {
        return { context, sessionId: null, sessionProjectId: null, messages: [], busy: false };
      }
      return { context };
    }),
  clearContext: () => set({ context: null }),
  setSessionId: (sessionId, projectId) =>
    set({ sessionId, sessionProjectId: sessionId == null ? null : projectId ?? null }),
  setBusy: (busy) => set({ busy }),
  addMessage: (message) => set((state) => ({ messages: [...state.messages, message] })),
  updateMessage: (id, patch) =>
    set((state) => ({
      messages: state.messages.map((message) => (message.id === id ? { ...message, ...patch } : message)),
    })),
  appendMessageEvent: (id, event) =>
    set((state) => ({
      messages: state.messages.map((message) =>
        message.id === id ? { ...message, events: [...(message.events ?? []), event] } : message,
      ),
    })),
  // 重开对话时清空会话与消息，新 run 将按当前上下文构建
  resetConversation: () => set({ sessionId: null, sessionProjectId: null, messages: [], busy: false }),
}));
