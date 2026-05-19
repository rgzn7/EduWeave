import { EmptyState } from "../../components/EmptyState";
import { ErrorNotice } from "../../components/ErrorNotice";
import { JsonViewer } from "../../components/JsonViewer";
import { StatusBadge } from "../../components/StatusBadge";
import { isTaskActiveStatus } from "../../hooks/useTaskPolling";
import type { CurriculumPlan, Task } from "../../types";
import { getErrorMessage } from "../../utils";
import { asNumberList, asRecord, asRecordList, asStringList, displayValue, type JsonObject } from "./helpers";
import { KeyValueGrid, KnowledgeRefs, LoadingBlock, SectionBlock, StatCard, TaskSummaryCard, TextList } from "./shared";

function CurriculumSessions({ sessions }: { sessions: JsonObject[] }) {
  if (!sessions.length) {
    return <EmptyState description="后端返回的课程方案中没有可展示的 lesson_sessions，下面仍保留原始 JSON 兜底。" title="暂无课次安排" />;
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

export function CurriculumTab({
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
      <TaskSummaryCard description="课程方案是后续教案、测评和课件的上游成果；失败时可进入任务详情查看真实后端步骤。" title="课程方案任务" task={task} />
      {isLoading ? <LoadingBlock description="正在读取课程方案详情和结构化 content_json。" text="加载课程方案" /> : null}
      {error ? <ErrorNotice title="课程方案获取失败" message={getErrorMessage(error)} /> : null}
      {!isLoading && !error && !plan ? (
        <EmptyState
          description={isTaskActiveStatus(task?.task_status) ? "任务仍在运行，请等待轮询刷新；也可以进入任务详情查看当前阶段。" : "当前批次没有课程方案结果，请先确认生成批次任务是否成功。"}
          title={isTaskActiveStatus(task?.task_status) ? "课程方案生成中" : "暂未产生课程方案"}
        />
      ) : null}
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
