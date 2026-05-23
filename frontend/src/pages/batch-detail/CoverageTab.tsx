import { RotateCw } from "lucide-react";
import { EmptyState } from "../../components/EmptyState";
import { ErrorNotice } from "../../components/ErrorNotice";
import { JsonViewer } from "../../components/JsonViewer";
import { StatusBadge } from "../../components/StatusBadge";
import { isTaskActiveStatus } from "../../hooks/useTaskPolling";
import type { CoverageReport, Task } from "../../types";
import { cn, formatDate, getErrorMessage } from "../../utils";
import { asNumberList, asRecord, asRecordList, displayValue, type JsonObject } from "./helpers";
import { KeyValueGrid, KnowledgeRefs, LoadingBlock, SectionBlock, StatCard, TaskSummaryCard } from "./shared";

const ARTIFACT_BUCKETS = [
  { type: "curriculum_plan", label: "课程大纲" },
  { type: "lesson_plan", label: "教案" },
  { type: "question_item", label: "试卷题目" },
  { type: "courseware_slide", label: "课件页面" },
] as const;

const ARTIFACT_LABELS: Record<string, string> = Object.fromEntries(ARTIFACT_BUCKETS.map((item) => [item.type, item.label]));

const QUESTION_TYPE_LABELS: Record<string, string> = {
  single_choice: "单选题",
  fill_blank: "填空题",
  short_answer: "简答题",
  unknown: "未知题型",
};

const SCENE_LABELS: Record<string, string> = {
  homework: "课后作业",
  unit_test: "单元测评",
  final_exam: "期末综合测",
};

const WARNING_LABELS: Record<string, string> = {
  INVALID_KNOWLEDGE_POINT_REF: "范围外知识点引用",
  QUESTION_DIFFICULTY_OUT_OF_RANGE: "题目难度越界",
  UNCOVERED_KNOWLEDGE_POINTS: "存在未覆盖知识点",
  IMPORTANT_KNOWLEDGE_POINTS_UNCOVERED: "重点知识点未覆盖",
};

function numberValue(value: unknown) {
  const valueAsNumber = Number(value);
  return Number.isFinite(valueAsNumber) ? valueAsNumber : null;
}

function countValue(value: unknown) {
  return numberValue(value) ?? 0;
}

function textValue(value: unknown) {
  const displayed = displayValue(value);
  return displayed === "-" ? "" : displayed;
}

function formatScene(value: unknown) {
  const key = String(value ?? "");
  return SCENE_LABELS[key] ?? displayValue(value);
}

function formatQuestionType(value: unknown) {
  const key = String(value ?? "");
  return QUESTION_TYPE_LABELS[key] ?? displayValue(value);
}

function formatDifficultyRange(value: unknown) {
  if (Array.isArray(value) && value.length === 2) {
    return `${displayValue(value[0])}-${displayValue(value[1])} 级`;
  }
  return displayValue(value);
}

function orderedRecordEntries(record: JsonObject | null, preferredOrder: string[], labels: Record<string, string>) {
  const seen = new Set<string>();
  const entries = preferredOrder.map((key) => {
    seen.add(key);
    return {
      key,
      label: labels[key] ?? key,
      value: countValue(record?.[key]),
    };
  });

  Object.entries(record ?? {}).forEach(([key, value]) => {
    if (!seen.has(key)) {
      entries.push({
        key,
        label: labels[key] ?? key,
        value: countValue(value),
      });
    }
  });

  return entries.filter((item) => item.value > 0 || preferredOrder.includes(item.key));
}

function DistributionList({
  record,
  preferredOrder,
  labels,
  empty,
}: {
  record: JsonObject | null;
  preferredOrder: string[];
  labels: Record<string, string>;
  empty: string;
}) {
  const entries = orderedRecordEntries(record, preferredOrder, labels);
  const total = entries.reduce((sum, item) => sum + item.value, 0);

  if (!entries.length) {
    return <div className="text-sm text-ink/45">{empty}</div>;
  }

  return (
    <div className="space-y-3">
      {entries.map((item) => {
        const width = total > 0 && item.value > 0 ? `${Math.max((item.value / total) * 100, 5)}%` : "0%";
        return (
          <div key={item.key}>
            <div className="flex items-center justify-between gap-3 text-xs font-semibold text-ink/55">
              <span>{item.label}</span>
              <span>{item.value}</span>
            </div>
            <div className="mt-1 h-2 overflow-hidden rounded-full bg-line">
              <div className="h-full rounded-full bg-accent" style={{ width }} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

function InvalidKnowledgeRefs({ ids }: { ids: number[] }) {
  if (!ids.length) {
    return null;
  }
  const visible = ids.slice(0, 18);
  return (
    <div className="flex flex-wrap gap-2">
      {visible.map((id) => (
        <span className="rounded-md border border-coral/25 bg-coral/10 px-2 py-1 text-xs font-semibold text-coral" key={id}>
          #{id}
        </span>
      ))}
      {ids.length > visible.length ? <span className="px-1 py-1 text-xs font-semibold text-coral/70">+{ids.length - visible.length}</span> : null}
    </div>
  );
}

function getArtifactTitle(artifactType: string, item: JsonObject, index: number) {
  if (artifactType === "curriculum_plan") {
    return textValue(item.title) || `课程大纲 #${displayValue(item.curriculum_plan_id ?? item.artifact_id ?? index + 1)}`;
  }
  if (artifactType === "lesson_plan") {
    const session = textValue(item.class_session_no);
    const title = textValue(item.title);
    return `${session ? `第 ${session} 课` : "教案"}${title ? ` · ${title}` : ""}`;
  }
  if (artifactType === "question_item") {
    const questionNo = textValue(item.question_no);
    const questionType = formatQuestionType(item.question_type);
    const difficulty = textValue(item.difficulty_level);
    return `题目 ${questionNo || index + 1} · ${questionType}${difficulty ? ` · 难度 ${difficulty}` : ""}`;
  }
  if (artifactType === "courseware_slide") {
    const slideNo = textValue(item.slide_no);
    const title = textValue(item.title);
    return `第 ${slideNo || index + 1} 页${title ? ` · ${title}` : ""}`;
  }
  return `${ARTIFACT_LABELS[artifactType] ?? artifactType} #${displayValue(item.artifact_id ?? index + 1)}`;
}

function getArtifactMeta(artifactType: string, item: JsonObject) {
  if (artifactType === "curriculum_plan") {
    return [`大纲 #${displayValue(item.curriculum_plan_id ?? item.artifact_id)}`];
  }
  if (artifactType === "lesson_plan") {
    return [`教案 #${displayValue(item.lesson_plan_id ?? item.artifact_id)}`, `课次 ${displayValue(item.class_session_no)}`];
  }
  if (artifactType === "question_item") {
    return [
      `题目 #${displayValue(item.question_item_id ?? item.artifact_id)}`,
      `试卷 #${displayValue(item.paper_result_id)}`,
      formatScene(item.scene_type),
      `策略 ${formatDifficultyRange(item.difficulty_range)}`,
    ];
  }
  if (artifactType === "courseware_slide") {
    return [
      `课件 #${displayValue(item.courseware_result_id ?? item.artifact_id)}`,
      `教案 #${displayValue(item.lesson_plan_id)}`,
      `页型 ${displayValue(item.slide_type)}`,
    ];
  }
  return [`成果物 #${displayValue(item.artifact_id)}`];
}

function ArtifactCoverageMatrix({ artifactCoverage }: { artifactCoverage: JsonObject | null }) {
  const buckets = ARTIFACT_BUCKETS.map((item) => ({ type: item.type, fallbackLabel: item.label }));

  if (!artifactCoverage || !buckets.length) {
    return <div className="text-sm text-ink/45">暂无成果物覆盖记录</div>;
  }

  return (
    <div className="divide-y divide-line overflow-hidden rounded-md border border-line bg-white">
      {buckets.map((config) => {
        const bucket = asRecord(artifactCoverage[config.type]);
        const items = asRecordList(bucket?.items);
        const displayName = textValue(bucket?.display_name) || config.fallbackLabel;
        const coveredIds = asNumberList(bucket?.covered_knowledge_point_ids);
        const invalidIds = asNumberList(bucket?.invalid_knowledge_point_ids);

        return (
          <section className="p-4" key={config.type}>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h4 className="text-sm font-bold text-ink">{displayName}</h4>
                <div className="mt-1 text-xs font-semibold text-ink/45">{config.type}</div>
              </div>
              <div className="grid grid-cols-2 gap-2 text-right text-xs font-semibold text-ink/55 sm:grid-cols-4">
                <span>成果 {displayValue(bucket?.item_count)}</span>
                <span>引用 {displayValue(bucket?.reference_count)}</span>
                <span>覆盖 {coveredIds.length}</span>
                <span className={invalidIds.length ? "text-coral" : ""}>越界 {invalidIds.length}</span>
              </div>
            </div>

            <div className="mt-3 grid gap-3 xl:grid-cols-2">
              <div>
                <div className="mb-2 text-xs font-semibold text-ink/45">覆盖知识点</div>
                <KnowledgeRefs ids={coveredIds} />
              </div>
              <div>
                <div className="mb-2 text-xs font-semibold text-ink/45">范围外引用</div>
                {invalidIds.length ? <InvalidKnowledgeRefs ids={invalidIds} /> : <span className="text-xs font-semibold text-ink/40">暂无范围外引用</span>}
              </div>
            </div>

            <div className="mt-4 max-h-[480px] divide-y divide-line overflow-y-auto border-t border-line">
              {items.length ? (
                items.map((item, index) => {
                  const validIds = asNumberList(item.valid_knowledge_point_ids);
                  const itemInvalidIds = asNumberList(item.invalid_knowledge_point_ids);
                  return (
                    <div className="py-3" key={`${config.type}-${displayValue(item.artifact_id)}-${index}`}>
                      <div className="flex flex-wrap items-start justify-between gap-2">
                        <div className="min-w-0">
                          <div className="break-words text-sm font-semibold text-ink">{getArtifactTitle(config.type, item, index)}</div>
                          <div className="mt-1 flex flex-wrap gap-2 text-xs text-ink/45">
                            {getArtifactMeta(config.type, item).map((meta) => (
                              <span key={meta}>{meta}</span>
                            ))}
                          </div>
                        </div>
                        <span className={cn("text-xs font-bold", itemInvalidIds.length ? "text-coral" : "text-ink/45")}>
                          引用 {displayValue(item.reference_count)}
                        </span>
                      </div>
                      <div className="mt-3 grid gap-3 xl:grid-cols-2">
                        <KnowledgeRefs ids={validIds} />
                        {itemInvalidIds.length ? <InvalidKnowledgeRefs ids={itemInvalidIds} /> : null}
                      </div>
                    </div>
                  );
                })
              ) : (
                <div className="py-3 text-sm text-ink/45">暂无明细</div>
              )}
            </div>
          </section>
        );
      })}
    </div>
  );
}

function AssessmentQuality({ assessmentQuality }: { assessmentQuality: JsonObject | null }) {
  const questionTypeDistribution = asRecord(assessmentQuality?.question_type_distribution);
  const difficultyDistribution = asRecord(assessmentQuality?.difficulty_distribution);
  const strategyChecks = asRecordList(assessmentQuality?.strategy_checks);

  return (
    <div className="space-y-4">
      <div className="grid gap-3 md:grid-cols-3">
        <StatCard label="题目总数" value={displayValue(assessmentQuality?.question_count)} />
        <StatCard label="策略校验" value={`${strategyChecks.filter((item) => item.passed === true).length}/${strategyChecks.length || 0}`} />
        <StatCard label="越界题目" value={strategyChecks.reduce((sum, item) => sum + asNumberList(item.out_of_range_question_item_ids).length, 0)} />
      </div>
      <div className="grid gap-4 xl:grid-cols-2">
        <div>
          <h4 className="mb-3 text-xs font-bold text-ink/55">题型分布</h4>
          <DistributionList
            empty="暂无题型统计"
            labels={QUESTION_TYPE_LABELS}
            preferredOrder={["single_choice", "fill_blank", "short_answer"]}
            record={questionTypeDistribution}
          />
        </div>
        <div>
          <h4 className="mb-3 text-xs font-bold text-ink/55">难度分布</h4>
          <DistributionList
            empty="暂无难度统计"
            labels={{ "1": "1 级", "2": "2 级", "3": "3 级", "4": "4 级", "5": "5 级", unknown: "未知" }}
            preferredOrder={["1", "2", "3", "4", "5"]}
            record={difficultyDistribution}
          />
        </div>
      </div>
      <div className="divide-y divide-line overflow-hidden rounded-md border border-line bg-white">
        {strategyChecks.length ? (
          strategyChecks.map((check, index) => {
            const outOfRangeIds = asNumberList(check.out_of_range_question_item_ids);
            return (
              <div className="p-3" key={`${displayValue(check.paper_result_id)}-${displayValue(check.scene_type)}-${index}`}>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="text-sm font-bold text-ink">
                    {formatScene(check.scene_type)} / 试卷 #{displayValue(check.paper_result_id)}
                  </div>
                  <span className={cn("text-xs font-bold", check.passed ? "text-mint" : "text-coral")}>
                    {check.passed ? "通过" : "有越界"}
                  </span>
                </div>
                <div className="mt-2 flex flex-wrap gap-3 text-xs text-ink/50">
                  <span>题目 {displayValue(check.question_count)}</span>
                  <span>难度范围 {formatDifficultyRange(check.difficulty_range)}</span>
                  <span>越界 {outOfRangeIds.length}</span>
                </div>
                {outOfRangeIds.length ? (
                  <div className="mt-3">
                    <InvalidKnowledgeRefs ids={outOfRangeIds} />
                  </div>
                ) : null}
              </div>
            );
          })
        ) : (
          <div className="p-3 text-sm text-ink/45">暂无策略校验记录</div>
        )}
      </div>
    </div>
  );
}

function WarningList({ warnings }: { warnings: JsonObject[] }) {
  if (!warnings.length) {
    return <div className="text-sm text-ink/45">暂无告警</div>;
  }

  return (
    <div className="space-y-3">
      {warnings.map((warning, index) => {
        const code = String(warning.code ?? "");
        const knowledgePointIds = asNumberList(warning.knowledge_point_ids);
        const questionItemIds = asNumberList(warning.question_item_ids);
        return (
          <div className="rounded-md border border-coral/20 bg-coral/10 p-3 text-sm text-coral" key={`${code}-${index}`}>
            <div className="font-bold">{WARNING_LABELS[code] ?? displayValue(warning.code)}</div>
            <div className="mt-1 leading-6">{displayValue(warning.message)}</div>
            <div className="mt-2 flex flex-wrap gap-3 text-xs font-semibold text-coral/75">
              {warning.artifact_type ? <span>{ARTIFACT_LABELS[String(warning.artifact_type)] ?? displayValue(warning.artifact_type)}</span> : null}
              {warning.artifact_id ? <span>成果物 #{displayValue(warning.artifact_id)}</span> : null}
              {warning.paper_result_id ? <span>试卷 #{displayValue(warning.paper_result_id)}</span> : null}
              {warning.scene_type ? <span>{formatScene(warning.scene_type)}</span> : null}
              {warning.difficulty_range ? <span>难度范围 {formatDifficultyRange(warning.difficulty_range)}</span> : null}
            </div>
            {knowledgePointIds.length ? (
              <div className="mt-3">
                <InvalidKnowledgeRefs ids={knowledgePointIds} />
              </div>
            ) : null}
            {questionItemIds.length ? <div className="mt-2 text-xs font-semibold">题目：{questionItemIds.map((id) => `#${id}`).join("、")}</div> : null}
          </div>
        );
      })}
    </div>
  );
}

export function CoverageTab({
  reports,
  selectedReportId,
  onSelectReport,
  report,
  listLoading,
  detailLoading,
  listError,
  detailError,
  task,
  onRefreshCoverage,
  refreshPending,
  refreshError,
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
  onRefreshCoverage: () => void;
  refreshPending: boolean;
  refreshError: unknown;
}) {
  const summary = asRecord(report?.coverage_summary_json);
  const reportJson = asRecord(report?.report_json);
  const importantCoverage = asRecord(reportJson?.important_knowledge_point_coverage);
  const artifactCoverage = asRecord(reportJson?.artifact_coverage);
  const assessmentQuality = asRecord(reportJson?.assessment_quality ?? summary?.assessment_quality);
  const knowledgeScope = asRecord(reportJson?.knowledge_scope ?? summary?.knowledge_scope);
  const warnings = asRecordList(reportJson?.warnings);
  const coveredIds = asNumberList(reportJson?.covered_knowledge_point_ids);
  const uncoveredIds = asNumberList(reportJson?.uncovered_knowledge_point_ids);

  return (
    <div className="space-y-5">
      <TaskSummaryCard
        description="覆盖报告用于校验课程大纲、教案、试卷题目和课件页面的知识点引用，帮助讲清楚生成结果是否覆盖输入基线。"
        title="覆盖报告任务"
        task={task}
      />

      <section className="rounded-md border border-line bg-paper/60 p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="label">质量报告</div>
            <h2 className="mt-1 text-lg font-bold text-ink">按成果物分组的覆盖分析</h2>
          </div>
          <button className="btn btn-primary" disabled={refreshPending} onClick={onRefreshCoverage} type="button">
            <RotateCw className={refreshPending ? "animate-spin" : ""} size={16} />
            {refreshPending ? "重新分析中" : "重新分析"}
          </button>
        </div>
      </section>

      {refreshError ? <ErrorNotice title="覆盖报告刷新失败" message={getErrorMessage(refreshError)} /> : null}
      {listLoading ? <LoadingBlock description="正在读取当前批次的覆盖率、告警和成果物引用。" text="加载覆盖报告" /> : null}
      {listError ? <ErrorNotice title="覆盖报告列表获取失败" message={getErrorMessage(listError)} /> : null}
      {!listLoading && !listError && !reports.length ? (
        <EmptyState
          description={isTaskActiveStatus(task?.task_status) ? "覆盖分析仍在运行，完成后会展示覆盖率与告警。" : "当前批次没有覆盖报告，可以手动重新分析一次。"}
          title={isTaskActiveStatus(task?.task_status) ? "覆盖报告生成中" : "暂未产生覆盖报告"}
        />
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
            {detailLoading ? <LoadingBlock description="正在读取覆盖摘要、告警列表和原始 report_json。" text="加载覆盖报告详情" /> : null}
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
                  <div className="mt-4 grid gap-3 md:grid-cols-3 xl:grid-cols-6">
                    <StatCard label="覆盖率" value={report.coverage_rate != null ? `${report.coverage_rate}%` : "-"} />
                    <StatCard label="已覆盖" value={coveredIds.length || displayValue(summary?.covered_count)} />
                    <StatCard label="未覆盖" value={uncoveredIds.length || displayValue(summary?.uncovered_count)} />
                    <StatCard label="重点覆盖" value={summary?.important_coverage_rate != null ? `${displayValue(summary.important_coverage_rate)}%` : "-"} />
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

                <SectionBlock title="测评质量">
                  <AssessmentQuality assessmentQuality={assessmentQuality} />
                </SectionBlock>

                <SectionBlock title="成果物覆盖矩阵">
                  <ArtifactCoverageMatrix artifactCoverage={artifactCoverage} />
                </SectionBlock>

                <SectionBlock title="告警列表">
                  <WarningList warnings={warnings} />
                </SectionBlock>

                <div className="grid gap-4 xl:grid-cols-2">
                  <JsonViewer title="knowledge_scope" value={knowledgeScope} />
                  <JsonViewer title="report_json" value={report.report_json} />
                </div>
              </>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}
