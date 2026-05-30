/**
 * @Date: 2026-05-30
 * @Author: xisy
 * @Discription: Agent 运行过程时间线：将工具调用/返回成对折叠为带状态的步骤，配工具专属图标，供悬浮助手与独立助手页共用
 */
import { useMemo } from "react";
import {
  BookOpen,
  FileText,
  ListTree,
  Loader2,
  PenLine,
  RotateCw,
  Search,
  Wrench,
  type LucideIcon,
} from "lucide-react";
import type { AgentRunEvent } from "../lib/api";
import { cn } from "../utils";

// 工具 -> 友好中文名 + 图标（与后端 tools.py 的工具清单一一对应）
const TOOL_META: Record<string, { label: string; icon: LucideIcon }> = {
  search_textbook: { label: "检索教材", icon: Search },
  list_curricula: { label: "查看大纲列表", icon: ListTree },
  list_lessons: { label: "查看课次列表", icon: ListTree },
  read_lesson_plan: { label: "查阅教案", icon: BookOpen },
  write_lesson_plan: { label: "修改教案", icon: PenLine },
  read_outline: { label: "查阅大纲", icon: BookOpen },
  write_outline: { label: "修改大纲", icon: PenLine },
  read_artifact: { label: "读取资源", icon: FileText },
};

function toolMeta(toolName: string): { label: string; icon: LucideIcon } {
  return TOOL_META[toolName] ?? { label: toolName || "调用工具", icon: Wrench };
}

type StepState = "running" | "ok" | "error";

type TimelineStep = {
  key: string;
  icon: LucideIcon;
  label: string;
  detail?: string;
  state: StepState;
};

/**
 * 将原始事件序列折叠为可读步骤：
 * - tool_call / tool_result 按工具名成对合并为单个步骤（调用中=running，返回后按 ok 置 ok/error）
 * - retry 单独成警示步骤
 * - started / assistant_thinking / artifact_updated / succeeded / failed 不入时间线，避免噪音（最终结果与失败信息由气泡正文呈现）
 */
function buildSteps(events: AgentRunEvent[]): TimelineStep[] {
  const steps: TimelineStep[] = [];
  // tool_name -> 待配对 tool_call 步骤下标
  const openByTool = new Map<string, number>();

  events.forEach((event, index) => {
    const payload = event.payload ?? {};
    const toolName = (payload.tool_name as string | undefined) ?? "";
    const summary = (payload.summary as string | undefined) ?? event.message ?? "";
    const key = `${event.seq ?? `i${index}`}`;

    switch (event.event_type) {
      case "tool_call": {
        const meta = toolMeta(toolName);
        openByTool.set(toolName, steps.length);
        steps.push({ key: `c-${key}`, icon: meta.icon, label: meta.label, state: "running" });
        break;
      }
      case "tool_result": {
        const ok = payload.ok !== false;
        const detail = summary || (ok ? "完成" : "未完成");
        const idx = openByTool.get(toolName);
        if (idx != null && steps[idx]) {
          steps[idx].state = ok ? "ok" : "error";
          steps[idx].detail = detail;
          openByTool.delete(toolName);
        } else {
          // 未配到对应 tool_call（异常顺序）时单独补一条
          const meta = toolMeta(toolName);
          steps.push({ key: `r-${key}`, icon: meta.icon, label: meta.label, detail, state: ok ? "ok" : "error" });
        }
        break;
      }
      case "retry": {
        steps.push({ key: `t-${key}`, icon: RotateCw, label: "稍后重试", detail: event.message ?? undefined, state: "error" });
        break;
      }
      default:
        break;
    }
  });

  return steps;
}

export function AgentRunTimeline({ events }: { events: AgentRunEvent[] }) {
  const steps = useMemo(() => buildSteps(events), [events]);
  if (!steps.length) return null;

  return (
    <ol className="mt-2.5 space-y-2.5">
      {steps.map((step, index) => {
        const Icon = step.state === "running" ? Loader2 : step.icon;
        return (
          <li key={step.key} className="relative flex gap-2.5">
            {/* 竖线：连接到下一个节点中心 */}
            {index < steps.length - 1 ? (
              <span className="absolute left-3 top-6 -bottom-2.5 w-px bg-line" />
            ) : null}
            {/* 节点：圆形图标，竖线穿过其中心 */}
            <span
              className={cn(
                "relative z-10 flex h-6 w-6 shrink-0 items-center justify-center rounded-full border bg-paper",
                step.state === "ok" && "border-line text-ink/70",
                step.state === "running" && "border-ink/25 text-ink/50",
                step.state === "error" && "border-coral/40 text-coral",
              )}
            >
              <Icon size={12} className={cn(step.state === "running" && "animate-spin")} />
            </span>
            {/* 文本 */}
            <div className="min-w-0 flex-1 pt-0.5">
              <div className="text-xs font-medium text-ink/75">{step.label}</div>
              {step.detail ? (
                <div className={cn("mt-0.5 truncate text-xs", step.state === "error" ? "text-coral/80" : "text-ink/45")}>
                  {step.detail}
                </div>
              ) : null}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
