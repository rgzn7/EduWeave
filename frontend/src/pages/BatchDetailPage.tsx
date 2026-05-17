import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  BookOpenCheck,
  ClipboardList,
  FileText,
  Layers3,
  ListChecks,
  Loader2,
  RotateCw,
  Target,
} from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { EmptyState } from "../components/EmptyState";
import { ErrorNotice } from "../components/ErrorNotice";
import { JsonViewer } from "../components/JsonViewer";
import { ProgressBar } from "../components/ProgressBar";
import { StatusBadge } from "../components/StatusBadge";
import { TaskTable } from "../components/TaskTable";
import { isTaskActiveStatus } from "../hooks/useTaskPolling";
import { api } from "../lib/api";
import type { CoverageReport, CurriculumPlan, GenerationBatch, LessonPlan, Task } from "../types";
import { cn, formatDate, getErrorMessage, toNumberId } from "../utils";

const tabs = [
  { id: "overview", label: "概览" },
  { id: "curriculum", label: "课程方案" },
  { id: "lesson", label: "教案" },
  { id: "assessment", label: "测评" },
  { id: "courseware", label: "课件" },
  { id: "coverage", label: "覆盖报告" },
  { id: "tasks", label: "关联任务" },
] as const;

type TabId = (typeof tabs)[number]["id"];
type JsonObject = Record<string, unknown>;

function asRecord(value: unknown): JsonObject | null {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as JsonObject) : null;
}

function asRecordList(value: unknown): JsonObject[] {
  return Array.isArray(value) ? value.map(asRecord).filter((item): item is JsonObject => Boolean(item)) : [];
}

function asStringList(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.map((item) => String(item)).filter((item) => item.trim().length > 0);
  }
  return typeof value === "string" && value.trim() ? [value] : [];
}

function asNumberList(value: unknown): number[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.map((item) => Number(item)).filter((item) => Number.isFinite(item));
}

function displayValue(value: unknown): string {
  if (value === undefined || value === null || value === "") {
    return "-";
  }
  if (Array.isArray(value)) {
    return value.length ? value.map((item) => displayValue(item)).join("、") : "-";
  }
  if (typeof value === "object") {
    try {
      return JSON.stringify(value);
    } catch {
      return String(value);
    }
  }
  return String(value);
}

function latestByUpdated<T extends { id: number; updated_at: string }>(items: T[]) {
  return [...items].sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime() || b.id - a.id)[0];
}

function sortLessons(items: LessonPlan[]) {
  return [...items].sort((a, b) => {
    const sessionDiff = (a.class_session_no ?? Number.MAX_SAFE_INTEGER) - (b.class_session_no ?? Number.MAX_SAFE_INTEGER);
    return sessionDiff || b.id - a.id;
  });
}

function taskMatches(task: Task, moduleCode: string) {
  return task.module_code === moduleCode || task.task_type.includes(moduleCode);
}

function latestTask(tasks: Task[], moduleCode: string) {
  return latestByUpdated(tasks.filter((task) => taskMatches(task, moduleCode)));
}

function hasActiveTask(batch?: GenerationBatch) {
  return (batch?.tasks ?? []).some((task) => isTaskActiveStatus(task.task_status));
}

function isBatchLive(batch?: GenerationBatch) {
  return !batch || isTaskActiveStatus(batch.batch_status) || hasActiveTask(batch);
}

function StatCard({ label, value }: { label: string; value?: string | number | null }) {
  return (
    <div className="rounded-md border border-line bg-paper/60 px-4 py-3">
      <div className="label">{label}</div>
      <div className="mt-1 break-words text-lg font-bold text-ink">{value ?? "-"}</div>
    </div>
  );
}

function ResultPlaceholder({ title, description }: { title: string; description: string }) {
  return (
    <div className="rounded-md border border-line bg-paper/60 p-5">
      <h3 className="font-bold">{title}</h3>
      <p className="mt-2 text-sm leading-6 text-ink/55">{description}</p>
    </div>
  );
}

function LoadingBlock({ text }: { text: string }) {
  return (
    <div className="flex min-h-36 items-center justify-center rounded-md border border-line bg-paper/60 text-sm font-semibold text-ink/55">
      <Loader2 className="mr-2 animate-spin" size={17} />
      {text}
    </div>
  );
}

function SectionBlock({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="rounded-md border border-line bg-paper/60 p-4">
      <h3 className="text-sm font-bold text-ink">{title}</h3>
      <div className="mt-3">{children}</div>
    </section>
  );
}

function TextList({ items, empty = "暂无记录" }: { items: string[]; empty?: string }) {
  if (!items.length) {
    return <div className="text-sm text-ink/45">{empty}</div>;
  }
  return (
    <ul className="space-y-2 text-sm leading-6 text-ink/70">
      {items.map((item, index) => (
        <li className="flex gap-2" key={`${item}-${index}`}>
          <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-accent" />
          <span className="min-w-0 break-words">{item}</span>
        </li>
      ))}
    </ul>
  );
}

function KeyValueGrid({ record }: { record: JsonObject | null }) {
  const entries = Object.entries(record ?? {}).filter(([, value]) => value !== undefined && value !== null && value !== "");
  if (!entries.length) {
    return <div className="text-sm text-ink/45">暂无记录</div>;
  }
  return (
    <div className="grid gap-3 md:grid-cols-2">
      {entries.map(([key, value]) => (
        <div className="rounded-md border border-line bg-white px-3 py-2" key={key}>
          <div className="text-xs font-semibold text-ink/45">{key}</div>
          <div className="mt-1 break-words text-sm font-semibold text-ink/75">{displayValue(value)}</div>
        </div>
      ))}
    </div>
  );
}

function KnowledgeRefs({ ids }: { ids: number[] }) {
  if (!ids.length) {
    return <span className="text-xs font-semibold text-ink/40">暂无知识点引用</span>;
  }
  const visible = ids.slice(0, 18);
  return (
    <div className="flex flex-wrap gap-2">
      {visible.map((id) => (
        <span className="rounded-md border border-line bg-white px-2 py-1 text-xs font-semibold text-ink/65" key={id}>
          #{id}
        </span>
      ))}
      {ids.length > visible.length ? <span className="px-1 py-1 text-xs font-semibold text-ink/45">+{ids.length - visible.length}</span> : null}
    </div>
  );
}

function TaskSummaryCard({ title, task }: { title: string; task?: Task }) {
  return (
    <aside className="rounded-md border border-line bg-paper/60 p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="label">{title}</div>
          <div className="mt-1 text-sm font-bold text-ink">{task ? `任务 #${task.id}` : "暂无关联任务"}</div>
        </div>
        {task ? <StatusBadge status={task.task_status} /> : null}
      </div>
      {task ? (
        <>
          <div className="mt-3">
            <ProgressBar value={task.progress_percent} />
          </div>
          <div className="mt-3 grid gap-2 text-xs text-ink/55 md:grid-cols-2">
            <span>类型：{task.task_type}</span>
            <span>阶段：{task.current_stage ?? "-"}</span>
          </div>
          {task.last_error_message ? (
            <div className="mt-3 flex gap-2 rounded-md border border-coral/20 bg-coral/10 p-3 text-xs font-semibold text-coral">
              <AlertTriangle className="mt-0.5 shrink-0" size={14} />
              <div>
                <div>{task.last_error_code ?? "TASK_FAILED"}</div>
                <div className="mt-1 line-clamp-3">{task.last_error_message}</div>
              </div>
            </div>
          ) : null}
          <Link className="btn btn-secondary mt-4 h-9 w-full text-xs" to={`/tasks/${task.id}`}>
            任务详情
            <ArrowRight size={14} />
          </Link>
        </>
      ) : (
        <div className="mt-3 text-xs leading-5 text-ink/50">当前批次还没有产生这个模块的任务记录。</div>
      )}
    </aside>
  );
}

function CurriculumSessions({ sessions }: { sessions: JsonObject[] }) {
  if (!sessions.length) {
    return <EmptyState title="暂无课次安排" />;
  }
  return (
    <div className="space-y-3">
      {sessions.map((session, index) => (
        <div className="rounded-md border border-line bg-white p-4" key={`${session.session_no ?? index}-${session.title ?? index}`}>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="min-w-0">
              <div className="text-xs font-semibold text-ink/45">第 {displayValue(session.session_no ?? index + 1)} 课</div>
              <h4 className="mt-1 break-words font-bold text-ink">{displayValue(session.title)}</h4>
            </div>
            <span className="rounded-md bg-accent/10 px-2 py-1 text-xs font-semibold text-accent">
              {displayValue(session.duration_minutes)} 分钟
            </span>
          </div>
          <div className="mt-4 grid gap-4 xl:grid-cols-2">
            <SectionBlock title="课次目标">
              <TextList items={asStringList(session.objectives)} />
            </SectionBlock>
            <SectionBlock title="课次重点">
              <TextList items={asStringList(session.key_points)} />
            </SectionBlock>
            <SectionBlock title="教学活动">
              <TextList items={asStringList(session.activities)} />
            </SectionBlock>
            <SectionBlock title="课后任务">
              <TextList items={asStringList(session.homework)} />
            </SectionBlock>
          </div>
          <div className="mt-4">
            <KnowledgeRefs ids={asNumberList(session.knowledge_point_refs)} />
          </div>
        </div>
      ))}
    </div>
  );
}

function TeachingSteps({ steps }: { steps: JsonObject[] }) {
  if (!steps.length) {
    return <EmptyState title="暂无教学流程" />;
  }
  return (
    <div className="space-y-3">
      {steps.map((step, index) => (
        <div className="rounded-md border border-line bg-white p-4" key={`${step.step_no ?? index}-${step.stage_name ?? index}`}>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h4 className="font-bold text-ink">
              {displayValue(step.step_no ?? index + 1)}. {displayValue(step.stage_name)}
            </h4>
            <span className="rounded-md bg-leaf/10 px-2 py-1 text-xs font-semibold text-leaf">{displayValue(step.duration_minutes)} 分钟</span>
          </div>
          <div className="mt-4 grid gap-4 md:grid-cols-2">
            <SectionBlock title="教师动作">
              <TextList items={asStringList(step.teacher_actions)} />
            </SectionBlock>
            <SectionBlock title="学生活动">
              <TextList items={asStringList(step.student_activities)} />
            </SectionBlock>
          </div>
          <div className="mt-4">
            <KnowledgeRefs ids={asNumberList(step.knowledge_point_refs)} />
          </div>
        </div>
      ))}
    </div>
  );
}

function LessonSessions({ sessions }: { sessions: JsonObject[] }) {
  if (!sessions.length) {
    return <EmptyState title="暂无课次讲解安排" />;
  }
  return (
    <div className="space-y-3">
      {sessions.map((session, index) => (
        <div className="rounded-md border border-line bg-white p-4" key={`${session.session_no ?? index}-${session.title ?? index}`}>
          <div className="mb-4">
            <div className="text-xs font-semibold text-ink/45">第 {displayValue(session.session_no ?? index + 1)} 课</div>
            <h4 className="mt-1 break-words font-bold text-ink">{displayValue(session.title)}</h4>
          </div>
          <div className="grid gap-4 xl:grid-cols-2">
            <SectionBlock title="课次目标">
              <TextList items={asStringList(session.objectives)} />
            </SectionBlock>
            <SectionBlock title="教学重点">
              <TextList items={asStringList(session.teaching_focus)} />
            </SectionBlock>
          </div>
          <div className="mt-4">
            <SectionBlock title="教学步骤">
              <TeachingSteps steps={asRecordList(session.teaching_steps)} />
            </SectionBlock>
          </div>
          <div className="mt-4 grid gap-4 xl:grid-cols-[1fr_auto]">
            <SectionBlock title="课后任务">
              <TextList items={asStringList(session.homework)} />
            </SectionBlock>
            <SectionBlock title="知识点引用">
              <KnowledgeRefs ids={asNumberList(session.knowledge_point_refs)} />
            </SectionBlock>
          </div>
        </div>
      ))}
    </div>
  );
}

function CurriculumTab({
  plan,
  isLoading,
  error,
  task,
}: {
  plan?: CurriculumPlan;
  isLoading: boolean;
  error: unknown;
  task?: Task;
}) {
  const content = asRecord(plan?.content_json);
  const sessions = asRecordList(content?.lesson_sessions);

  return (
    <div className="space-y-5">
      <TaskSummaryCard title="课程方案任务" task={task} />
      {isLoading ? <LoadingBlock text="加载课程方案" /> : null}
      {error ? <ErrorNotice title="课程方案获取失败" message={getErrorMessage(error)} /> : null}
      {!isLoading && !error && !plan ? <EmptyState title={isTaskActiveStatus(task?.task_status) ? "课程方案生成中" : "暂未产生课程方案"} /> : null}
      {plan ? (
        <>
          <section className="rounded-md border border-line bg-paper/60 p-5">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="label">课程方案 #{plan.id}</div>
                <h2 className="mt-1 break-words text-xl font-bold text-ink">{plan.plan_title}</h2>
                <p className="mt-2 text-sm leading-6 text-ink/60">{plan.summary_text ?? "暂无摘要"}</p>
              </div>
              <StatusBadge status={plan.version_status} />
            </div>
            <div className="mt-4 grid gap-3 md:grid-cols-4">
              <StatCard label="课程数" value={plan.course_count} />
              <StatCard label="课时分钟" value={plan.session_duration_minutes} />
              <StatCard label="学科" value={plan.target_subject_code} />
              <StatCard label="年级" value={plan.target_grade_code} />
            </div>
          </section>

          <div className="grid gap-4 xl:grid-cols-2">
            <SectionBlock title="课程概览">
              <KeyValueGrid record={asRecord(content?.course_overview)} />
            </SectionBlock>
            <SectionBlock title="阶段目标">
              <TextList items={asStringList(content?.stage_goals)} />
            </SectionBlock>
            <SectionBlock title="课程重点">
              <TextList items={asStringList(content?.key_points)} />
            </SectionBlock>
            <SectionBlock title="课程难点">
              <TextList items={asStringList(content?.difficult_points)} />
            </SectionBlock>
          </div>

          <SectionBlock title="学情适配">
            <TextList items={asStringList(content?.learner_adjustments)} />
          </SectionBlock>

          <SectionBlock title="课次安排">
            <CurriculumSessions sessions={sessions} />
          </SectionBlock>

          <SectionBlock title="覆盖知识点引用">
            <KnowledgeRefs ids={asNumberList(content?.coverage_knowledge_points)} />
          </SectionBlock>

          <JsonViewer title="content_json" value={plan.content_json} />
        </>
      ) : null}
    </div>
  );
}

function LessonTab({
  batch,
  lessons,
  selectedLessonId,
  onSelectLesson,
  lesson,
  listLoading,
  detailLoading,
  listError,
  detailError,
  task,
}: {
  batch: GenerationBatch;
  lessons: LessonPlan[];
  selectedLessonId: number | null;
  onSelectLesson: (id: number) => void;
  lesson?: LessonPlan;
  listLoading: boolean;
  detailLoading: boolean;
  listError: unknown;
  detailError: unknown;
  task?: Task;
}) {
  const content = asRecord(lesson?.content_json);

  return (
    <div className="space-y-5">
      <TaskSummaryCard title="教案任务" task={task} />
      {!batch.curriculum_plan_id ? <EmptyState title="需要先生成课程方案" /> : null}
      {listLoading ? <LoadingBlock text="加载教案列表" /> : null}
      {listError ? <ErrorNotice title="教案列表获取失败" message={getErrorMessage(listError)} /> : null}
      {!listLoading && !listError && batch.curriculum_plan_id && !lessons.length ? (
        <EmptyState title={isTaskActiveStatus(task?.task_status) ? "教案生成中" : "暂未产生教案"} />
      ) : null}
      {lessons.length ? (
        <div className="grid gap-5 xl:grid-cols-[300px_1fr]">
          <aside className="space-y-2">
            <div className="label">教案列表</div>
            <div className="divide-y divide-line rounded-md border border-line">
              {lessons.map((item) => (
                <button
                  className={cn(
                    "flex w-full items-center justify-between gap-3 bg-white px-4 py-3 text-left transition hover:bg-paper",
                    selectedLessonId === item.id && "bg-accent/10",
                  )}
                  key={item.id}
                  onClick={() => onSelectLesson(item.id)}
                  type="button"
                >
                  <div className="min-w-0">
                    <div className="truncate text-sm font-bold">{item.lesson_title}</div>
                    <div className="mt-1 text-xs text-ink/50">
                      第 {item.class_session_no ?? "-"} 课 / {formatDate(item.updated_at)}
                    </div>
                  </div>
                  <StatusBadge status={item.version_status} />
                </button>
              ))}
            </div>
          </aside>
          <div className="space-y-5">
            {detailLoading ? <LoadingBlock text="加载教案详情" /> : null}
            {detailError ? <ErrorNotice title="教案详情获取失败" message={getErrorMessage(detailError)} /> : null}
            {lesson ? (
              <>
                <section className="rounded-md border border-line bg-paper/60 p-5">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="label">教案 #{lesson.id}</div>
                      <h2 className="mt-1 break-words text-xl font-bold text-ink">{lesson.lesson_title}</h2>
                      <p className="mt-2 text-sm leading-6 text-ink/60">{lesson.summary_text ?? "暂无摘要"}</p>
                    </div>
                    <StatusBadge status={lesson.version_status} />
                  </div>
                  <div className="mt-4 grid gap-3 md:grid-cols-3">
                    <StatCard label="课次" value={lesson.class_session_no} />
                    <StatCard label="版本" value={lesson.version_no} />
                    <StatCard label="风格" value={lesson.style_code} />
                  </div>
                </section>

                <div className="grid gap-4 xl:grid-cols-2">
                  <SectionBlock title="课程概述">
                    <KeyValueGrid record={asRecord(content?.course_overview)} />
                  </SectionBlock>
                  <SectionBlock title="课后安排">
                    <KeyValueGrid record={asRecord(content?.after_class_plan)} />
                  </SectionBlock>
                  <SectionBlock title="物料清单">
                    <TextList items={asStringList(content?.material_list)} />
                  </SectionBlock>
                  <SectionBlock title="核心知识">
                    <TextList items={asStringList(content?.core_knowledge)} />
                  </SectionBlock>
                </div>

                <SectionBlock title="标准行课流程">
                  <TeachingSteps steps={asRecordList(content?.teaching_flow)} />
                </SectionBlock>

                <SectionBlock title="课次讲解安排">
                  <LessonSessions sessions={asRecordList(content?.session_plans)} />
                </SectionBlock>

                <div className="grid gap-4 xl:grid-cols-2">
                  <SectionBlock title="学情适配">
                    <TextList items={asStringList(content?.learner_adjustments)} />
                  </SectionBlock>
                  <SectionBlock title="教案整体知识点引用">
                    <KnowledgeRefs ids={asNumberList(content?.knowledge_point_refs)} />
                  </SectionBlock>
                </div>

                <JsonViewer title="content_json" value={lesson.content_json} />
              </>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function CoverageTab({
  reports,
  selectedReportId,
  onSelectReport,
  report,
  listLoading,
  detailLoading,
  listError,
  detailError,
  task,
}: {
  reports: CoverageReport[];
  selectedReportId: number | null;
  onSelectReport: (id: number) => void;
  report?: CoverageReport;
  listLoading: boolean;
  detailLoading: boolean;
  listError: unknown;
  detailError: unknown;
  task?: Task;
}) {
  const summary = asRecord(report?.coverage_summary_json);
  const reportJson = asRecord(report?.report_json);
  const importantCoverage = asRecord(reportJson?.important_knowledge_point_coverage);
  const artifactCoverage = asRecord(reportJson?.artifact_coverage);
  const warnings = asRecordList(reportJson?.warnings);

  return (
    <div className="space-y-5">
      <TaskSummaryCard title="覆盖报告任务" task={task} />
      {listLoading ? <LoadingBlock text="加载覆盖报告" /> : null}
      {listError ? <ErrorNotice title="覆盖报告列表获取失败" message={getErrorMessage(listError)} /> : null}
      {!listLoading && !listError && !reports.length ? (
        <EmptyState title={isTaskActiveStatus(task?.task_status) ? "覆盖报告生成中" : "暂未产生覆盖报告"} />
      ) : null}
      {reports.length ? (
        <div className="grid gap-5 xl:grid-cols-[300px_1fr]">
          <aside className="space-y-2">
            <div className="label">报告列表</div>
            <div className="divide-y divide-line rounded-md border border-line">
              {reports.map((item) => (
                <button
                  className={cn(
                    "flex w-full items-center justify-between gap-3 bg-white px-4 py-3 text-left transition hover:bg-paper",
                    selectedReportId === item.id && "bg-accent/10",
                  )}
                  key={item.id}
                  onClick={() => onSelectReport(item.id)}
                  type="button"
                >
                  <div className="min-w-0">
                    <div className="truncate text-sm font-bold">覆盖报告 #{item.id}</div>
                    <div className="mt-1 text-xs text-ink/50">
                      {item.coverage_rate ?? "-"}% / {formatDate(item.updated_at)}
                    </div>
                  </div>
                  <StatusBadge status={item.report_status} />
                </button>
              ))}
            </div>
          </aside>
          <div className="space-y-5">
            {detailLoading ? <LoadingBlock text="加载覆盖报告详情" /> : null}
            {detailError ? <ErrorNotice title="覆盖报告详情获取失败" message={getErrorMessage(detailError)} /> : null}
            {report ? (
              <>
                <section className="rounded-md border border-line bg-paper/60 p-5">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <div className="label">覆盖报告 #{report.id}</div>
                      <h2 className="mt-1 text-xl font-bold text-ink">知识点覆盖率 {report.coverage_rate ?? "-"}%</h2>
                    </div>
                    <StatusBadge status={report.report_status} />
                  </div>
                  <div className="mt-4 grid gap-3 md:grid-cols-3">
                    <StatCard label="覆盖率" value={report.coverage_rate != null ? `${report.coverage_rate}%` : "-"} />
                    <StatCard label="告警数" value={report.warning_count} />
                    <StatCard label="更新时间" value={formatDate(report.updated_at)} />
                  </div>
                </section>

                <div className="grid gap-4 xl:grid-cols-2">
                  <SectionBlock title="覆盖摘要">
                    <KeyValueGrid record={summary} />
                  </SectionBlock>
                  <SectionBlock title="重点知识点覆盖">
                    <KeyValueGrid record={importantCoverage} />
                  </SectionBlock>
                </div>

                <SectionBlock title="成果物覆盖摘要">
                  {artifactCoverage && Object.keys(artifactCoverage).length ? (
                    <div className="space-y-3">
                      {Object.entries(artifactCoverage).map(([key, value]) => {
                        const item = asRecord(value);
                        return (
                          <div className="rounded-md border border-line bg-white p-3" key={key}>
                            <div className="flex flex-wrap items-center justify-between gap-3">
                              <div className="font-bold text-ink">{key}</div>
                              <span className="text-xs font-semibold text-ink/50">引用 {displayValue(item?.reference_count)} 个</span>
                            </div>
                            <div className="mt-3">
                              <KnowledgeRefs ids={asNumberList(item?.valid_knowledge_point_ids)} />
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  ) : (
                    <div className="text-sm text-ink/45">暂无成果物覆盖记录</div>
                  )}
                </SectionBlock>

                <SectionBlock title="告警列表">
                  {warnings.length ? (
                    <div className="space-y-3">
                      {warnings.map((warning, index) => (
                        <div className="rounded-md border border-coral/20 bg-coral/10 p-3 text-sm text-coral" key={`${warning.code ?? index}`}>
                          <div className="font-bold">{displayValue(warning.code)}</div>
                          <div className="mt-1 leading-6">{displayValue(warning.message)}</div>
                          <div className="mt-3">
                            <KnowledgeRefs ids={asNumberList(warning.knowledge_point_ids)} />
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="text-sm text-ink/45">暂无告警</div>
                  )}
                </SectionBlock>

                <JsonViewer title="report_json" value={report.report_json} />
              </>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}

export function BatchDetailPage() {
  const routeProjectId = toNumberId(useParams().projectId);
  const batchId = toNumberId(useParams().batchId);
  const [activeTab, setActiveTab] = useState<TabId>("overview");
  const [selectedLessonId, setSelectedLessonId] = useState<number | null>(null);
  const [selectedCoverageReportId, setSelectedCoverageReportId] = useState<number | null>(null);

  const batchQuery = useQuery({
    queryKey: ["generation-batch", batchId],
    queryFn: () => api.getGenerationBatch(batchId),
    enabled: batchId > 0,
    refetchInterval: (query) => (isBatchLive(query.state.data as GenerationBatch | undefined) ? 5_000 : false),
  });

  const batch = batchQuery.data;
  const projectId = batch?.project_id ?? routeProjectId;
  const tasks = useMemo(() => batch?.tasks ?? [], [batch?.tasks]);
  const curriculumTask = useMemo(() => latestTask(tasks, "curriculum"), [tasks]);
  const lessonTask = useMemo(() => latestTask(tasks, "lesson_plan"), [tasks]);
  const coverageTask = useMemo(() => latestTask(tasks, "coverage"), [tasks]);

  const projectQuery = useQuery({
    queryKey: ["project", projectId],
    queryFn: () => api.getProject(projectId),
    enabled: projectId > 0,
  });

  const curriculumQuery = useQuery({
    queryKey: ["curriculum-plan", batch?.curriculum_plan_id],
    queryFn: () => api.getCurriculumPlan(batch!.curriculum_plan_id!),
    enabled: Boolean(batch?.curriculum_plan_id),
    refetchInterval: isTaskActiveStatus(curriculumTask?.task_status) || isBatchLive(batch) ? 5_000 : false,
  });

  const lessonPlansQuery = useQuery({
    queryKey: ["lesson-plans", batch?.id, batch?.curriculum_plan_id],
    queryFn: () => api.listLessonPlans(batch!.curriculum_plan_id!, { page: 1, page_size: 100 }),
    enabled: Boolean(batch?.id && batch?.curriculum_plan_id),
    refetchInterval: isTaskActiveStatus(lessonTask?.task_status) || isBatchLive(batch) ? 5_000 : false,
  });

  const allLessonPlans = lessonPlansQuery.data?.items ?? [];
  const lessonPlans = useMemo(
    () => sortLessons(allLessonPlans.filter((lessonPlan) => lessonPlan.generation_batch_id === batch?.id)),
    [allLessonPlans, batch?.id],
  );

  useEffect(() => {
    if (!lessonPlans.length) {
      setSelectedLessonId(null);
      return;
    }
    const preferred =
      lessonPlans.find((item) => item.id === batch?.lesson_plan_id) ??
      lessonPlans.find((item) => item.class_session_no === 1) ??
      lessonPlans[0];
    if (!selectedLessonId || !lessonPlans.some((item) => item.id === selectedLessonId)) {
      setSelectedLessonId(preferred.id);
    }
  }, [batch?.lesson_plan_id, lessonPlans, selectedLessonId]);

  const lessonDetailQuery = useQuery({
    queryKey: ["lesson-plan", selectedLessonId],
    queryFn: () => api.getLessonPlan(selectedLessonId!),
    enabled: Boolean(selectedLessonId),
    refetchInterval: isTaskActiveStatus(lessonTask?.task_status) ? 5_000 : false,
  });

  const coverageReportsQuery = useQuery({
    queryKey: ["coverage-reports", batch?.id],
    queryFn: () => api.listCoverageReports(batch!.id, { page: 1, page_size: 100 }),
    enabled: Boolean(batch?.id),
    refetchInterval: isTaskActiveStatus(coverageTask?.task_status) || isBatchLive(batch) ? 5_000 : false,
  });

  const coverageReports = useMemo(() => {
    return [...(coverageReportsQuery.data?.items ?? [])].sort((a, b) => b.id - a.id);
  }, [coverageReportsQuery.data?.items]);

  useEffect(() => {
    if (!coverageReports.length) {
      setSelectedCoverageReportId(null);
      return;
    }
    if (!selectedCoverageReportId || !coverageReports.some((item) => item.id === selectedCoverageReportId)) {
      setSelectedCoverageReportId(coverageReports[0].id);
    }
  }, [coverageReports, selectedCoverageReportId]);

  const coverageDetailQuery = useQuery({
    queryKey: ["coverage-report", selectedCoverageReportId],
    queryFn: () => api.getCoverageReport(selectedCoverageReportId!),
    enabled: Boolean(selectedCoverageReportId),
    refetchInterval: isTaskActiveStatus(coverageTask?.task_status) ? 5_000 : false,
  });

  if (routeProjectId <= 0 || batchId <= 0) {
    return <ErrorNotice title="批次地址无效" message="请从项目工作台进入一个真实生成批次。" />;
  }

  if (batchQuery.isLoading && !batch) {
    return (
      <div className="flex h-[60vh] items-center justify-center text-sm text-ink/55">
        <Loader2 className="mr-2 animate-spin" size={17} />
        加载批次详情
      </div>
    );
  }

  if (batchQuery.error && !batch) {
    return <ErrorNotice title="批次详情获取失败" message={getErrorMessage(batchQuery.error)} />;
  }

  if (!batch) {
    return <EmptyState title="批次不存在" action={<Link className="btn btn-secondary" to={`/projects/${projectId}`}>返回项目</Link>} />;
  }

  return (
    <div className="space-y-6">
      <section className="flex flex-col justify-between gap-4 xl:flex-row xl:items-end">
        <div>
          <Link className="mb-4 inline-flex items-center gap-2 text-sm font-semibold text-ink/55 hover:text-ink" to={`/projects/${projectId}`}>
            <ArrowLeft size={16} />
            项目工作台
          </Link>
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-3xl font-bold">{batch.batch_name ?? `生成批次 #${batch.batch_no}`}</h1>
            <StatusBadge status={batch.batch_status} />
          </div>
          <div className="mt-2 flex flex-wrap gap-2 text-sm text-ink/55">
            <span>{projectQuery.data?.name ?? `项目 #${projectId}`}</span>
            <span>/</span>
            <span>批次 ID {batch.id}</span>
            <span>/</span>
            <span>{formatDate(batch.updated_at)}</span>
          </div>
        </div>
        <button className="btn btn-secondary" disabled={batchQuery.isFetching} onClick={() => batchQuery.refetch()} type="button">
          <RotateCw className={batchQuery.isFetching ? "animate-spin" : ""} size={16} />
          刷新
        </button>
      </section>

      <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <StatCard label="知识版本" value={batch.knowledge_version_id} />
        <StatCard label="学情版本" value={batch.learner_profile_version_id} />
        <StatCard label="课次" value={batch.course_count} />
        <StatCard label="课时分钟" value={batch.session_duration_minutes} />
      </section>

      <section className="panel overflow-hidden">
        <div className="border-b border-line px-3 py-3">
          <div className="flex gap-2 overflow-x-auto">
            {tabs.map((tab) => (
              <button
                className={cn(
                  "h-9 shrink-0 rounded-md px-3 text-sm font-semibold text-ink/60 transition hover:bg-paper hover:text-ink",
                  activeTab === tab.id && "bg-ink text-white hover:bg-ink hover:text-white",
                )}
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                type="button"
              >
                {tab.label}
              </button>
            ))}
          </div>
        </div>
        <div className="p-5">
          {activeTab === "overview" ? <OverviewTab batch={batch} /> : null}
          {activeTab === "curriculum" ? (
            <CurriculumTab
              plan={curriculumQuery.data}
              isLoading={curriculumQuery.isLoading}
              error={curriculumQuery.error}
              task={curriculumTask}
            />
          ) : null}
          {activeTab === "lesson" ? (
            <LessonTab
              batch={batch}
              lessons={lessonPlans}
              selectedLessonId={selectedLessonId}
              onSelectLesson={setSelectedLessonId}
              lesson={lessonDetailQuery.data}
              listLoading={lessonPlansQuery.isLoading}
              detailLoading={lessonDetailQuery.isLoading}
              listError={lessonPlansQuery.error}
              detailError={lessonDetailQuery.error}
              task={lessonTask}
            />
          ) : null}
          {activeTab === "assessment" ? (
            <ResultPlaceholder title="测评结果入口" description="Phase3-A 暂不实现测评链路。测评蓝图、试卷和题目详情将在 Phase3-B 接入。" />
          ) : null}
          {activeTab === "courseware" ? (
            <ResultPlaceholder title="课件结果入口" description="Phase3-A 暂不实现课件链路。课件任务、刷新、回复和 PPTX 下载将在 Phase3-C 接入。" />
          ) : null}
          {activeTab === "coverage" ? (
            <CoverageTab
              reports={coverageReports}
              selectedReportId={selectedCoverageReportId}
              onSelectReport={setSelectedCoverageReportId}
              report={coverageDetailQuery.data}
              listLoading={coverageReportsQuery.isLoading}
              detailLoading={coverageDetailQuery.isLoading}
              listError={coverageReportsQuery.error}
              detailError={coverageDetailQuery.error}
              task={coverageTask}
            />
          ) : null}
          {activeTab === "tasks" ? (
            tasks.length ? <TaskTable tasks={tasks} /> : <EmptyState title="暂无关联任务" />
          ) : null}
        </div>
      </section>
    </div>
  );
}

function OverviewTab({ batch }: { batch: GenerationBatch }) {
  const taskProgress = batch.tasks?.length
    ? Math.round(batch.tasks.reduce((sum, task) => sum + (task.progress_percent ?? 0), 0) / batch.tasks.length)
    : 0;

  return (
    <div className="space-y-5">
      <div className="grid gap-4 xl:grid-cols-[1fr_360px]">
        <div className="space-y-4">
          <div className="grid gap-3 md:grid-cols-3">
            <StatCard label="课程方案" value={batch.curriculum_plan_id ? `#${batch.curriculum_plan_id}` : "未生成"} />
            <StatCard label="首份教案" value={batch.lesson_plan_id ? `#${batch.lesson_plan_id}` : "未生成"} />
            <StatCard label="关联任务" value={batch.tasks?.length ?? 0} />
          </div>
          <div className="rounded-md border border-line bg-paper/60 p-4">
            <div className="mb-3 flex items-center gap-2 text-sm font-bold">
              <ClipboardList size={16} />
              任务平均进度
            </div>
            <ProgressBar value={taskProgress} />
          </div>
        </div>
        <div className="grid gap-3">
          <div className="flex items-center gap-3 rounded-md border border-line bg-paper/60 p-4">
            <BookOpenCheck className="text-accent" size={22} />
            <div>
              <div className="text-sm font-bold">创建时间</div>
              <div className="text-sm text-ink/55">{formatDate(batch.created_at)}</div>
            </div>
          </div>
          <div className="flex items-center gap-3 rounded-md border border-line bg-paper/60 p-4">
            <Layers3 className="text-leaf" size={22} />
            <div>
              <div className="text-sm font-bold">完成时间</div>
              <div className="text-sm text-ink/55">{formatDate(batch.finished_at)}</div>
            </div>
          </div>
        </div>
      </div>
      <div className="grid gap-4 xl:grid-cols-2">
        <JsonViewer title="chapter_range_json" value={batch.chapter_range_json} />
        <JsonViewer title="assessment_strategy_json" value={batch.assessment_strategy_json} />
      </div>
      <div className="grid gap-4 xl:grid-cols-3">
        <section className="rounded-md border border-line bg-paper/60 p-4">
          <div className="mb-3 flex items-center gap-2 text-sm font-bold">
            <Target size={16} />
            课程方案
          </div>
          <StatusBadge status={batch.curriculum_plan_id ? "ready" : "pending"} />
        </section>
        <section className="rounded-md border border-line bg-paper/60 p-4">
          <div className="mb-3 flex items-center gap-2 text-sm font-bold">
            <FileText size={16} />
            教案
          </div>
          <StatusBadge status={batch.lesson_plan_ids?.length ? "ready" : "pending"} />
        </section>
        <section className="rounded-md border border-line bg-paper/60 p-4">
          <div className="mb-3 flex items-center gap-2 text-sm font-bold">
            <ListChecks size={16} />
            覆盖报告
          </div>
          <StatusBadge status={batch.batch_status} />
        </section>
      </div>
    </div>
  );
}
