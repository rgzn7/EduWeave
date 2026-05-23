import { useEffect, useMemo, useState } from "react";
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
import { KeyValueGrid, KnowledgeRefs, LoadingBlock, SectionBlock, StatCard, TaskSummaryCard } from "./shared";

export type AssessmentSceneType = "homework" | "unit_test" | "final_exam";

export type AssessmentSceneConfig = {
  scene_type: AssessmentSceneType;
  label: string;
  shortLabel: string;
  questionCount: number;
  difficultyRange: string;
  description: string;
};

export type AssessmentSceneSummary = {
  scene_type: AssessmentSceneType;
  label: string;
  paperCount: number;
  blueprintCount: number;
  status: string;
};

export const ASSESSMENT_SCENES: AssessmentSceneConfig[] = [
  {
    scene_type: "homework",
    label: "课后作业",
    shortLabel: "作业",
    questionCount: 6,
    difficultyRange: "1-3",
    description: "巩固当堂知识点，题量精简，偏基础应用。",
  },
  {
    scene_type: "unit_test",
    label: "单元测评",
    shortLabel: "单元",
    questionCount: 10,
    difficultyRange: "2-4",
    description: "覆盖本单元主要知识点，兼顾理解和典型应用。",
  },
  {
    scene_type: "final_exam",
    label: "期末综合测",
    shortLabel: "综合",
    questionCount: 20,
    difficultyRange: "2-5",
    description: "覆盖更广知识范围，强调综合运用和区分度。",
  },
];

const QUESTION_TYPE_LABELS: Record<string, string> = {
  single_choice: "单选题",
  fill_blank: "填空题",
  short_answer: "简答题",
};

function labelQuestionType(type: unknown) {
  const normalized = String(type ?? "");
  return QUESTION_TYPE_LABELS[normalized] ?? displayValue(type);
}

export function getAssessmentSceneConfig(sceneType: string | null | undefined) {
  return ASSESSMENT_SCENES.find((scene) => scene.scene_type === sceneType) ?? ASSESSMENT_SCENES[1];
}

function labelScene(sceneType: unknown) {
  return getAssessmentSceneConfig(String(sceneType ?? "")).label;
}

function getPaperQuestionRecords(paper?: PaperResult) {
  const paperJson = asRecord(paper?.paper_json);
  return paper?.questions?.length ? paper.questions.map((question) => question as unknown as JsonObject) : asRecordList(paperJson?.questions);
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
  const sceneConfig = getAssessmentSceneConfig(blueprint?.scenario_type);

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
              {sceneConfig.label} / {blueprint.scenario_type} / 版本 {blueprint.version_no} / {formatDate(blueprint.updated_at)}
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
  const sceneName = String(paperJson?.scene_label ?? labelScene(paper?.scene_type));
  const questionRecords = getPaperQuestionRecords(paper);

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
              {sceneName} / {paper.scene_type} / {paper.question_count} 题 / {formatDate(paper.updated_at)}
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

function QuestionBankPreview({ paper }: { paper?: PaperResult }) {
  const [typeFilter, setTypeFilter] = useState("");
  const [difficultyFilter, setDifficultyFilter] = useState("");
  const [knowledgeFilter, setKnowledgeFilter] = useState("");

  useEffect(() => {
    setTypeFilter("");
    setDifficultyFilter("");
    setKnowledgeFilter("");
  }, [paper?.id]);

  const questionRecords = useMemo(() => getPaperQuestionRecords(paper), [paper]);
  const questionTypes = useMemo(
    () => Array.from(new Set(questionRecords.map((item) => String(item.question_type ?? "")).filter(Boolean))).sort(),
    [questionRecords],
  );
  const difficultyLevels = useMemo(
    () => Array.from(new Set(questionRecords.map((item) => String(item.difficulty_level ?? "")).filter(Boolean))).sort(),
    [questionRecords],
  );
  const knowledgePointIds = useMemo(
    () => Array.from(new Set(questionRecords.map((item) => String(item.knowledge_point_id ?? "")).filter(Boolean))).sort(),
    [questionRecords],
  );
  const filteredQuestions = useMemo(
    () =>
      questionRecords.filter((item) => {
        const matchesType = !typeFilter || String(item.question_type ?? "") === typeFilter;
        const matchesDifficulty = !difficultyFilter || String(item.difficulty_level ?? "") === difficultyFilter;
        const matchesKnowledge = !knowledgeFilter || String(item.knowledge_point_id ?? "") === knowledgeFilter;
        return matchesType && matchesDifficulty && matchesKnowledge;
      }),
    [difficultyFilter, knowledgeFilter, questionRecords, typeFilter],
  );

  return (
    <section className="space-y-4 rounded-md border border-line bg-paper/60 p-4">
      <div className="flex flex-col justify-between gap-3 xl:flex-row xl:items-start">
        <div>
          <div className="label">题目沉淀</div>
          <h3 className="mt-1 text-sm font-bold text-ink">{paper ? `当前试卷 #${paper.id}` : "请选择试卷结果"}</h3>
          <p className="mt-2 max-w-2xl text-xs leading-5 text-ink/50">
            当前基于试卷详情中的题目明细展示；全批次题库查询等待后端 question-items 接口，不展示虚构沉淀数据。
          </p>
        </div>
        <StatusBadge status={paper?.result_status ?? "pending"} />
      </div>
      {paper && questionRecords.length ? (
        <>
          <div className="grid gap-3 md:grid-cols-3">
            <label className="block">
              <span className="label">题型</span>
              <select className="field mt-2" value={typeFilter} onChange={(event) => setTypeFilter(event.target.value)}>
                <option value="">全部题型</option>
                {questionTypes.map((type) => (
                  <option key={type} value={type}>
                    {labelQuestionType(type)}
                  </option>
                ))}
              </select>
            </label>
            <label className="block">
              <span className="label">难度</span>
              <select className="field mt-2" value={difficultyFilter} onChange={(event) => setDifficultyFilter(event.target.value)}>
                <option value="">全部难度</option>
                {difficultyLevels.map((level) => (
                  <option key={level} value={level}>
                    难度 {level}
                  </option>
                ))}
              </select>
            </label>
            <label className="block">
              <span className="label">知识点</span>
              <select className="field mt-2" value={knowledgeFilter} onChange={(event) => setKnowledgeFilter(event.target.value)}>
                <option value="">全部知识点</option>
                {knowledgePointIds.map((id) => (
                  <option key={id} value={id}>
                    #{id}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <div className="grid gap-3 md:grid-cols-3">
            <StatCard label="当前试卷题目" value={questionRecords.length} />
            <StatCard label="筛选结果" value={filteredQuestions.length} />
            <StatCard label="测练场景" value={labelScene(paper.scene_type)} />
          </div>
          {filteredQuestions.length ? (
            <div className="space-y-2">
              {filteredQuestions.map((question, index) => (
                <article className="rounded-md border border-line bg-white px-3 py-3" key={`${question.id ?? question.question_no ?? index}`}>
                  <div className="flex flex-wrap items-center gap-2 text-xs font-semibold">
                    <span className="rounded-md bg-ink px-2 py-1 text-white">第 {displayValue(question.question_no)} 题</span>
                    <span className="rounded-md bg-accent/10 px-2 py-1 text-accent">{labelQuestionType(question.question_type)}</span>
                    <span className="rounded-md bg-paper px-2 py-1 text-ink/55">难度 {displayValue(question.difficulty_level)}</span>
                    <span className="rounded-md bg-paper px-2 py-1 text-ink/55">知识点 {displayValue(question.knowledge_point_id)}</span>
                  </div>
                  <p className="mt-3 line-clamp-2 break-words text-sm font-semibold leading-6 text-ink">{displayValue(question.stem_text)}</p>
                  <div className="mt-2 grid gap-2 text-xs leading-5 text-ink/55 xl:grid-cols-2">
                    <span className="break-words">答案：{displayValue(question.answer_text)}</span>
                    <span className="break-words">解析：{displayValue(question.analysis_text)}</span>
                  </div>
                </article>
              ))}
            </div>
          ) : (
            <EmptyState description="当前筛选条件没有匹配题目，请调整题型、难度或知识点。" title="暂无匹配题目" />
          )}
        </>
      ) : (
        <EmptyState
          description={paper ? "当前试卷详情没有 questions 明细，等待后端返回题目沉淀数据。" : "选择试卷后展示题干、答案、解析、题型、难度和知识点。"}
          title="暂无题目沉淀"
        />
      )}
    </section>
  );
}

export function AssessmentTab({
  batch,
  hasLessonPlans,
  task,
  selectedScene,
  sceneSummaries,
  onSelectScene,
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
  selectedScene: AssessmentSceneType;
  sceneSummaries: AssessmentSceneSummary[];
  onSelectScene: (scene: AssessmentSceneType) => void;
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
  onCreateAssessment: (scene: AssessmentSceneType) => void;
  createPending: boolean;
  createError: unknown;
}) {
  const queryClient = useQueryClient();
  const selectedSceneConfig = getAssessmentSceneConfig(selectedScene);
  const activeTask = isTaskActiveStatus(task?.task_status);
  const hasSuccessPaper = papers.some((item) => ["success", "ready"].includes(item.result_status));
  const sceneSummaryMap = Object.fromEntries(sceneSummaries.map((summary) => [summary.scene_type, summary]));
  const createDisabledReason = !batch.curriculum_plan_id
    ? "需要先生成课程方案"
    : !hasLessonPlans
      ? "需要先生成至少一份教案"
      : activeTask
        ? `${selectedSceneConfig.label}任务运行中`
        : hasSuccessPaper
          ? `当前批次已生成${selectedSceneConfig.label}`
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
      <TaskSummaryCard description={`${selectedSceneConfig.label}按需生成；任务成功后会同时产生蓝图和试卷结果。`} title="测练任务" task={task} />

      <section className="rounded-md border border-line bg-paper/60 p-5">
        <div className="flex flex-col justify-between gap-4 xl:flex-row xl:items-start">
          <div>
            <div className="label">测练体系</div>
            <h3 className="mt-1 text-lg font-bold text-ink">{selectedSceneConfig.label}</h3>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-ink/55">
              {selectedSceneConfig.questionCount} 题，覆盖单选、填空、简答，难度范围 {selectedSceneConfig.difficultyRange}。{selectedSceneConfig.description}
            </p>
          </div>
          <button className="btn btn-primary" disabled={Boolean(createDisabledReason)} onClick={() => onCreateAssessment(selectedScene)} type="button">
            <Plus size={16} />
            生成{selectedSceneConfig.label}
          </button>
        </div>
        <div className="mt-5 grid gap-3 lg:grid-cols-3">
          {ASSESSMENT_SCENES.map((scene) => {
            const summary = sceneSummaryMap[scene.scene_type];
            const isSelected = scene.scene_type === selectedScene;
            return (
              <button
                className={cn(
                  "rounded-md border border-line bg-white p-4 text-left transition hover:border-accent/40 hover:bg-accent/5",
                  isSelected && "border-accent bg-accent/10",
                )}
                key={scene.scene_type}
                onClick={() => onSelectScene(scene.scene_type)}
                type="button"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="text-sm font-bold text-ink">{scene.label}</div>
                    <div className="mt-1 text-xs font-semibold text-ink/50">{scene.scene_type}</div>
                  </div>
                  <StatusBadge status={summary?.status ?? "pending"} />
                </div>
                <div className="mt-3 grid grid-cols-2 gap-2 text-xs font-semibold text-ink/55">
                  <span>试卷 {summary?.paperCount ?? 0} 份</span>
                  <span>蓝图 {summary?.blueprintCount ?? 0} 份</span>
                </div>
              </button>
            );
          })}
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
          {blueprintListLoading ? <LoadingBlock description={`正在读取当前课程方案下的 ${selectedSceneConfig.label} 蓝图。`} text="加载测评蓝图" /> : null}
          {blueprintListError ? <ErrorNotice title="测评蓝图列表获取失败" message={getErrorMessage(blueprintListError)} /> : null}
          {!blueprintListLoading && !blueprintListError && !blueprints.length ? (
            <EmptyState
              description={activeTask ? "测评任务仍在运行，蓝图会在后端持久化后出现。" : `当前批次还没有${selectedSceneConfig.label}蓝图，可在依赖满足后生成。`}
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
                      #{item.id} / {labelScene(item.scenario_type)} / {formatDate(item.updated_at)}
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
              description={activeTask ? "试卷会在测评任务完成后出现，页面会随轮询刷新。" : `当前批次还没有${selectedSceneConfig.label}结果。`}
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
                      #{item.id} / {labelScene(item.scene_type)} / {item.question_count} 题 / {formatDate(item.updated_at)}
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
      <QuestionBankPreview paper={paper} />
      <PaperDetail paper={paper} />
    </div>
  );
}
