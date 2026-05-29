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
  messages: AssistantChatMessage[];
  busy: boolean;

  openPanel: () => void;
  closePanel: () => void;
  togglePanel: () => void;
  setContext: (context: AssistantContext | null) => void;
  clearContext: () => void;
  setSessionId: (sessionId: number | null) => void;
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
  messages: [],
  busy: false,

  openPanel: () => set({ open: true }),
  closePanel: () => set({ open: false }),
  togglePanel: () => set((state) => ({ open: !state.open })),
  setContext: (context) => set({ context }),
  clearContext: () => set({ context: null }),
  setSessionId: (sessionId) => set({ sessionId }),
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
  // 切换所在课次/重开对话时清空会话与消息，新 run 将按切换后的上下文构建
  resetConversation: () => set({ sessionId: null, messages: [], busy: false }),
}));
