import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Download, FileQuestion, Plus, ShieldCheck } from "lucide-react";
import { EmptyState } from "../../components/EmptyState";
import { ErrorNotice } from "../../components/ErrorNotice";
import { JsonViewer } from "../../components/JsonViewer";
import { StatusBadge } from "../../components/StatusBadge";
import { isTaskActiveStatus } from "../../hooks/useTaskPolling";
import { api } from "../../lib/api";
import type { AssessmentBlueprint, GenerationBatch, PaperResult, Task } from "../../types";
import { cn, formatDate, getErrorMessage } from "../../utils";
import { asRecord, asRecordList, displayValue, type JsonObject } from "./helpers";
import { KeyValueGrid, KnowledgeRefs, LoadingBlock, SectionBlock, StatCard, TaskSummaryCard, TextList } from "./shared";

export const DEFAULT_UNIT_TEST_STRATEGY = {
  scenario_type: "unit_test",
  scene_type: "unit_test",
  question_count: 10,
  question_types: ["single_choice", "fill_blank", "short_answer"],
  difficulty_range: [1, 5],
};

const QUESTION_TYPE_LABELS: Record<string, string> = {
  single_choice: "单选题",
  fill_blank: "填空题",
  short_answer: "简答题",
};

function labelQuestionType(type: unknown) {
  const normalized = String(type ?? "");
  return QUESTION_TYPE_LABELS[normalized] ?? displayValue(type);
}

function QuestionCard({ question }: { question: JsonObject }) {
  const sourceTrace = asRecord(question.source_trace_json);
  return (
    <article className="rounded-md border border-line bg-white p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="rounded-md bg-ink px-2 py-1 text-xs font-bold text-white">第 {displayValue(question.question_no)} 题</span>
          <span className="rounded-md bg-accent/10 px-2 py-1 text-xs font-semibold text-accent">{labelQuestionType(question.question_type)}</span>
          <span className="rounded-md bg-paper px-2 py-1 text-xs font-semibold text-ink/55">难度 {displayValue(question.difficulty_level)}</span>
          <span className="rounded-md bg-paper px-2 py-1 text-xs font-semibold text-ink/55">分值 {displayValue(question.score_value)}</span>
        </div>
        {question.knowledge_point_id ? <KnowledgeRefs ids={[Number(question.knowledge_point_id)]} /> : null}
      </div>
      <p className="mt-4 whitespace-pre-wrap break-words text-sm font-semibold leading-7 text-ink">{displayValue(question.stem_text)}</p>
      {asRecord(question.options_json) ? (
        <div className="mt-4">
          <div className="label mb-2">选项</div>
          <KeyValueGrid record={asRecord(question.options_json)} />
        </div>
      ) : null}
      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <SectionBlock title="答案">
          <p className="whitespace-pre-wrap break-words text-sm leading-6 text-ink/70">{displayValue(question.answer_text)}</p>
        </SectionBlock>
        <SectionBlock title="解析">
          <p className="whitespace-pre-wrap break-words text-sm leading-6 text-ink/70">{displayValue(question.analysis_text)}</p>
        </SectionBlock>
      </div>
      <div className="mt-4">
        <SectionBlock title="来源摘要">
          <KeyValueGrid record={sourceTrace} />
        </SectionBlock>
      </div>
    </article>
  );
}

function BlueprintDetail({ blueprint }: { blueprint?: AssessmentBlueprint }) {
  const content = asRecord(blueprint?.content_json);
  const strategySummary = asRecord(content?.strategy_summary) ?? asRecord(blueprint?.strategy_json);
  const knowledgeWeights = asRecordList(content?.knowledge_weights);

  if (!blueprint) {
    return null;
  }

  return (
    <div className="space-y-5">
      <section className="rounded-md border border-line bg-paper/60 p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="label">测评蓝图 #{blueprint.id}</div>
            <h2 className="mt-1 break-words text-xl font-bold text-ink">{blueprint.blueprint_name}</h2>
            <p className="mt-2 text-sm text-ink/55">
              {blueprint.scenario_type} / 版本 {blueprint.version_no} / {formatDate(blueprint.updated_at)}
            </p>
          </div>
          <StatusBadge status={blueprint.version_status} />
        </div>
      </section>

      <div className="grid gap-4 xl:grid-cols-3">
        <SectionBlock title="策略摘要">
          <KeyValueGrid record={strategySummary} />
        </SectionBlock>
        <SectionBlock title="题型分布">
          <KeyValueGrid record={asRecord(content?.question_type_distribution)} />
        </SectionBlock>
        <SectionBlock title="难度分布">
          <KeyValueGrid record={asRecord(content?.difficulty_distribution)} />
        </SectionBlock>
      </div>

      <SectionBlock title="知识点考查权重">
        {knowledgeWeights.length ? (
          <div className="space-y-3">
            {knowledgeWeights.map((item, index) => (
              <div className="rounded-md border border-line bg-white p-3" key={`${item.knowledge_point_id ?? index}`}>
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <KnowledgeRefs ids={item.knowledge_point_id ? [Number(item.knowledge_point_id)] : []} />
                  <span className="text-xs font-semibold text-ink/50">建议 {displayValue(item.suggested_question_count)} 题</span>
                </div>
                <div className="mt-3 grid gap-3 md:grid-cols-3">
                  <StatCard label="权重" value={item.weight_percent != null ? `${displayValue(item.weight_percent)}%` : "-"} />
                  <StatCard label="题型" value={displayValue(item.question_types)} />
                  <StatCard label="难度" value={displayValue(item.difficulty_range)} />
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="text-sm text-ink/45">暂无知识点权重</div>
        )}
      </SectionBlock>

      <JsonViewer title="content_json" value={blueprint.content_json} />
    </div>
  );
}

function PaperDetail({ paper }: { paper?: PaperResult }) {
  const paperJson = asRecord(paper?.paper_json);
  const questionRecords = paper?.questions?.length
    ? paper.questions.map((question) => question as unknown as JsonObject)
    : asRecordList(paperJson?.questions);

  if (!paper) {
    return null;
  }

  return (
    <div className="space-y-5">
      <section className="rounded-md border border-line bg-paper/60 p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="label">试卷 #{paper.id}</div>
            <h2 className="mt-1 break-words text-xl font-bold text-ink">{paper.title}</h2>
            <p className="mt-2 text-sm text-ink/55">
              {paper.scene_type} / {paper.question_count} 题 / {formatDate(paper.updated_at)}
            </p>
          </div>
          <StatusBadge status={paper.result_status} />
        </div>
        <div className="mt-4 grid gap-3 md:grid-cols-3">
          <StatCard label="题量" value={paper.question_count} />
          <StatCard label="蓝图" value={`#${paper.assessment_blueprint_id}`} />
          <StatCard label="导出文件" value={paper.export_file_id ? `#${paper.export_file_id}` : "未导出"} />
        </div>
      </section>

      <div className="grid gap-4 xl:grid-cols-2">
        <SectionBlock title="题型分布">
          <KeyValueGrid record={asRecord(paperJson?.question_type_distribution)} />
        </SectionBlock>
        <SectionBlock title="难度统计">
          <KeyValueGrid record={asRecord(paper.difficulty_stats_json) ?? asRecord(paperJson?.difficulty_distribution)} />
        </SectionBlock>
      </div>

      <SectionBlock title="题目列表">
        {questionRecords.length ? (
          <div className="space-y-3">
            {questionRecords.map((question, index) => (
              <QuestionCard question={question} key={`${question.question_no ?? index}-${question.stem_text ?? index}`} />
            ))}
          </div>
        ) : (
          <EmptyState description="试卷结果中没有 questions 明细，仍可展开 paper_json 查看后端原始结构。" title="暂无题目明细" />
        )}
      </SectionBlock>

      <JsonViewer title="paper_json" value={paper.paper_json} />
    </div>
  );
}

export function AssessmentTab({
  batch,
  hasLessonPlans,
  task,
  blueprints,
  selectedBlueprintId,
  onSelectBlueprint,
  blueprint,
  blueprintListLoading,
  blueprintDetailLoading,
  blueprintListError,
  blueprintDetailError,
  papers,
  selectedPaperId,
  onSelectPaper,
  paper,
  paperListLoading,
  paperDetailLoading,
  paperListError,
  paperDetailError,
  onCreateAssessment,
  createPending,
  createError,
}: {
  batch: GenerationBatch;
  hasLessonPlans: boolean;
  task?: Task;
  blueprints: AssessmentBlueprint[];
  selectedBlueprintId: number | null;
  onSelectBlueprint: (id: number) => void;
  blueprint?: AssessmentBlueprint;
  blueprintListLoading: boolean;
  blueprintDetailLoading: boolean;
  blueprintListError: unknown;
  blueprintDetailError: unknown;
  papers: PaperResult[];
  selectedPaperId: number | null;
  onSelectPaper: (id: number) => void;
  paper?: PaperResult;
  paperListLoading: boolean;
  paperDetailLoading: boolean;
  paperListError: unknown;
  paperDetailError: unknown;
  onCreateAssessment: () => void;
  createPending: boolean;
  createError: unknown;
}) {
  const queryClient = useQueryClient();
  const activeTask = isTaskActiveStatus(task?.task_status);
  const hasSuccessPaper = papers.some((item) => ["success", "ready"].includes(item.result_status));
  const createDisabledReason = !batch.curriculum_plan_id
    ? "需要先生成课程方案"
    : !hasLessonPlans
      ? "需要先生成至少一份教案"
      : activeTask
        ? "测评任务运行中"
        : hasSuccessPaper
          ? "当前批次已生成单元测评"
          : createPending
            ? "正在创建测评任务"
            : null;

  const downloadMutation = useMutation({
    mutationFn: async () => {
      if (!paper) {
        throw new Error("缺少试卷结果");
      }
      const result = paper.export_file_id ? await api.getFileDownloadUrl(paper.export_file_id) : await api.exportPaperResultDocx(paper.id);
      if (!result.signed_url) {
        throw new Error("后端未返回有效下载地址");
      }
      return result;
    },
    onSuccess: (result) => {
      if (paper) {
        queryClient.invalidateQueries({ queryKey: ["paper-result", paper.id] });
      }
      window.open(result.signed_url!, "_blank", "noopener,noreferrer");
    },
  });

  return (
    <div className="space-y-5">
      <TaskSummaryCard description="测评是按需生成成果；任务成功后会同时产生蓝图和试卷结果。" title="测评任务" task={task} />

      <section className="rounded-md border border-line bg-paper/60 p-5">
        <div className="flex flex-col justify-between gap-4 xl:flex-row xl:items-center">
          <div>
            <div className="label">默认策略</div>
            <h3 className="mt-1 text-lg font-bold text-ink">单元测评 unit_test</h3>
            <p className="mt-2 text-sm leading-6 text-ink/55">10 题，覆盖单选、填空、简答，难度范围 1-5。</p>
          </div>
          <button className="btn btn-primary" disabled={Boolean(createDisabledReason)} onClick={onCreateAssessment} type="button">
            <Plus size={16} />
            生成单元测评
          </button>
        </div>
        {createDisabledReason ? <div className="mt-3 text-xs font-semibold text-ink/45">{createDisabledReason}</div> : null}
        {createError ? <ErrorNotice title="测评任务创建失败" message={getErrorMessage(createError)} /> : null}
      </section>

      <div className="grid gap-5 xl:grid-cols-2">
        <section className="space-y-3">
          <div className="flex items-center gap-2 text-sm font-bold">
            <ShieldCheck size={16} />
            测评蓝图
          </div>
          {blueprintListLoading ? <LoadingBlock description="正在读取当前课程方案下的 unit_test 蓝图。" text="加载测评蓝图" /> : null}
          {blueprintListError ? <ErrorNotice title="测评蓝图列表获取失败" message={getErrorMessage(blueprintListError)} /> : null}
          {!blueprintListLoading && !blueprintListError && !blueprints.length ? (
            <EmptyState
              description={activeTask ? "测评任务仍在运行，蓝图会在后端持久化后出现。" : "当前批次还没有蓝图结果，可在依赖满足后生成单元测评。"}
              title={activeTask ? "测评蓝图生成中" : "暂未产生测评蓝图"}
            />
          ) : null}
          {blueprints.length ? (
            <div className="divide-y divide-line rounded-md border border-line">
              {blueprints.map((item) => (
                <button
                  className={cn(
                    "flex w-full items-center justify-between gap-3 bg-white px-4 py-3 text-left transition hover:bg-paper",
                    selectedBlueprintId === item.id && "bg-accent/10",
                  )}
                  key={item.id}
                  onClick={() => onSelectBlueprint(item.id)}
                  type="button"
                >
                  <div className="min-w-0">
                    <div className="truncate text-sm font-bold">{item.blueprint_name}</div>
                    <div className="mt-1 text-xs text-ink/50">
                      #{item.id} / {item.scenario_type} / {formatDate(item.updated_at)}
                    </div>
                  </div>
                  <StatusBadge status={item.version_status} />
                </button>
              ))}
            </div>
          ) : null}
        </section>

        <section className="space-y-3">
          <div className="flex items-center gap-2 text-sm font-bold">
            <FileQuestion size={16} />
            试卷结果
          </div>
          {paperListLoading ? <LoadingBlock description="正在读取当前批次下的试卷结果和导出状态。" text="加载试卷结果" /> : null}
          {paperListError ? <ErrorNotice title="试卷列表获取失败" message={getErrorMessage(paperListError)} /> : null}
          {!paperListLoading && !paperListError && !papers.length ? (
            <EmptyState
              description={activeTask ? "试卷会在测评任务完成后出现，页面会随轮询刷新。" : "当前批次还没有单元试卷结果。"}
              title={activeTask ? "试卷生成中" : "暂未产生试卷"}
            />
          ) : null}
          {papers.length ? (
            <div className="divide-y divide-line rounded-md border border-line">
              {papers.map((item) => (
                <button
                  className={cn(
                    "flex w-full items-center justify-between gap-3 bg-white px-4 py-3 text-left transition hover:bg-paper",
                    selectedPaperId === item.id && "bg-accent/10",
                  )}
                  key={item.id}
                  onClick={() => onSelectPaper(item.id)}
                  type="button"
                >
                  <div className="min-w-0">
                    <div className="truncate text-sm font-bold">{item.title}</div>
                    <div className="mt-1 text-xs text-ink/50">
                      #{item.id} / {item.question_count} 题 / {formatDate(item.updated_at)}
                    </div>
                  </div>
                  <StatusBadge status={item.result_status} />
                </button>
              ))}
            </div>
          ) : null}
        </section>
      </div>

      {blueprintDetailLoading ? <LoadingBlock description="正在读取题型、难度和知识点权重。" text="加载蓝图详情" /> : null}
      {blueprintDetailError ? <ErrorNotice title="蓝图详情获取失败" message={getErrorMessage(blueprintDetailError)} /> : null}
      <BlueprintDetail blueprint={blueprint} />

      <section className="space-y-4">
        <div className="flex flex-col justify-between gap-3 rounded-md border border-line bg-paper/60 p-4 xl:flex-row xl:items-center">
          <div>
            <div className="label">DOCX 导出</div>
            <div className="mt-1 text-sm font-bold text-ink">{paper ? `试卷 #${paper.id}` : "请选择试卷结果"}</div>
          </div>
          <button className="btn btn-secondary" disabled={!paper || downloadMutation.isPending} onClick={() => downloadMutation.mutate()} type="button">
            <Download size={16} />
            {downloadMutation.isPending ? "准备下载" : paper?.export_file_id ? "下载 DOCX" : "导出 DOCX"}
          </button>
        </div>
        {downloadMutation.error ? <ErrorNotice title="DOCX 下载失败" message={getErrorMessage(downloadMutation.error)} /> : null}
      </section>

      {paperDetailLoading ? <LoadingBlock description="正在读取题目、答案解析和知识点来源。" text="加载试卷详情" /> : null}
      {paperDetailError ? <ErrorNotice title="试卷详情获取失败" message={getErrorMessage(paperDetailError)} /> : null}
      <PaperDetail paper={paper} />
    </div>
  );
}
