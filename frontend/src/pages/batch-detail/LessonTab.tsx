import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Download } from "lucide-react";
import { EmptyState } from "../../components/EmptyState";
import { ErrorNotice } from "../../components/ErrorNotice";
import { JsonViewer } from "../../components/JsonViewer";
import { StatusBadge } from "../../components/StatusBadge";
import { isTaskActiveStatus } from "../../hooks/useTaskPolling";
import { api } from "../../lib/api";
import type { GenerationBatch, LessonPlan, Task } from "../../types";
import { cn, formatDate, getErrorMessage } from "../../utils";
import { asNumberList, asRecord, asRecordList, asStringList, displayValue, formatLessonTitle, type JsonObject } from "./helpers";
import { KeyValueGrid, KnowledgeRefs, LoadingBlock, SectionBlock, StatCard, TaskSummaryCard, TextList } from "./shared";

function TeachingSteps({ steps }: { steps: JsonObject[] }) {
  if (!steps.length) {
    return <EmptyState description="当前结构化教案未返回 teaching_flow，原始 content_json 仍保留在页面底部。" title="暂无教学流程" />;
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
    return <EmptyState description="当前教案没有 session_plans 明细，页面会继续展示课堂流程和原始 JSON。" title="暂无课次讲解安排" />;
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

export function LessonTab({
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
  const queryClient = useQueryClient();
  const content = asRecord(lesson?.content_json);
  const downloadMutation = useMutation({
    mutationFn: async () => {
      if (!lesson) {
        throw new Error("缺少教案");
      }
      const result = lesson.export_file_id ? await api.getFileDownloadUrl(lesson.export_file_id) : await api.exportLessonPlanDocx(lesson.id);
      if (!result.signed_url) {
        throw new Error("后端未返回有效下载地址");
      }
      return result;
    },
    onSuccess: (result) => {
      if (lesson) {
        queryClient.invalidateQueries({ queryKey: ["lesson-plan", lesson.id] });
      }
      window.open(result.signed_url!, "_blank", "noopener,noreferrer");
    },
  });

  return (
    <div className="space-y-5">
      <TaskSummaryCard description="教案承接课程方案，并作为测评与课件按需生成的直接输入。" title="教案任务" task={task} />
      {!batch.curriculum_plan_id ? <EmptyState description="当前批次尚未绑定课程方案，教案列表会保持为空。" title="需要先生成课程方案" /> : null}
      {listLoading ? <LoadingBlock description="正在读取当前批次下的 ready 教案列表。" text="加载教案列表" /> : null}
      {listError ? <ErrorNotice title="教案列表获取失败" message={getErrorMessage(listError)} /> : null}
      {!listLoading && !listError && batch.curriculum_plan_id && !lessons.length ? (
        <EmptyState
          description={isTaskActiveStatus(task?.task_status) ? "教案任务仍在运行，页面会随批次轮询更新。" : "当前批次没有可展示的 ready 教案，请从关联任务查看生成结果。"}
          title={isTaskActiveStatus(task?.task_status) ? "教案生成中" : "暂未产生教案"}
        />
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
                    <div className="truncate text-sm font-bold">{formatLessonTitle(item.lesson_title)}</div>
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
            {detailLoading ? <LoadingBlock description="正在读取选中教案的课堂流程、物料和知识点引用。" text="加载教案详情" /> : null}
            {detailError ? <ErrorNotice title="教案详情获取失败" message={getErrorMessage(detailError)} /> : null}
            {lesson ? (
              <>
                <section className="rounded-md border border-line bg-paper/60 p-5">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="label">教案 #{lesson.id}</div>
                      <h2 className="mt-1 break-words text-xl font-bold text-ink">{formatLessonTitle(lesson.lesson_title)}</h2>
                      <p className="mt-2 text-sm leading-6 text-ink/60">{lesson.summary_text ?? "暂无摘要"}</p>
                    </div>
                    <div className="flex shrink-0 flex-wrap items-center gap-2">
                      <StatusBadge status={lesson.version_status} />
                      <button className="btn btn-secondary" disabled={downloadMutation.isPending} onClick={() => downloadMutation.mutate()} type="button">
                        <Download size={16} />
                        {downloadMutation.isPending ? "准备下载" : lesson.export_file_id ? "下载 DOCX" : "导出 DOCX"}
                      </button>
                    </div>
                  </div>
                  {downloadMutation.error ? <ErrorNotice title="教案 DOCX 下载失败" message={getErrorMessage(downloadMutation.error)} /> : null}
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
