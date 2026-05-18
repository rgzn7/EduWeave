import { EmptyState } from "../../components/EmptyState";
import { ErrorNotice } from "../../components/ErrorNotice";
import { JsonViewer } from "../../components/JsonViewer";
import { StatusBadge } from "../../components/StatusBadge";
import { isTaskActiveStatus } from "../../hooks/useTaskPolling";
import type { CoverageReport, Task } from "../../types";
import { cn, formatDate, getErrorMessage } from "../../utils";
import { asNumberList, asRecord, asRecordList, displayValue } from "./helpers";
import { KeyValueGrid, KnowledgeRefs, LoadingBlock, SectionBlock, StatCard, TaskSummaryCard } from "./shared";

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
