import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { useParams } from "react-router-dom";
import { api } from "../lib/api";
import type { JsonRecord } from "../types";
import { cn, formatDate, toNumberId } from "../utils";
import { asNumberList, asRecord, asRecordList, displayValue } from "./batch-detail/helpers";

const artifactConfigs = [
  { key: "curriculum_plan", label: "课程方案" },
  { key: "lesson_plan", label: "教案" },
  { key: "courseware_slide", label: "PPT" },
  { key: "question_item", label: "测练" },
] as const;

const warningLabels: Record<string, string> = {
  INVALID_KNOWLEDGE_POINT_REF: "存在范围外知识点引用",
  QUESTION_DIFFICULTY_OUT_OF_RANGE: "题目难度需要关注",
  UNCOVERED_KNOWLEDGE_POINTS: "存在未覆盖知识点",
  IMPORTANT_KNOWLEDGE_POINTS_UNCOVERED: "重点知识点还需强化",
};

const questionTypeLabels: Record<string, string> = {
  single_choice: "单选题",
  fill_blank: "填空题",
  short_answer: "简答题",
  unknown: "未知题型",
};

function isSuccessfulStatus(status?: string | null) {
  return ["success", "ready", "available", "confirmed"].includes(String(status ?? "").toLowerCase());
}

function numberValue(value: unknown) {
  const num = Number(value);
  return Number.isFinite(num) ? num : null;
}

function percentValue(value: unknown) {
  const num = numberValue(value);
  return num == null ? "-" : `${num}%`;
}

function FriendlyNotice({ title, description }: { title: string; description?: string }) {
  return (
    <div className="rounded-2xl border border-dashed border-line bg-[#fafafa] px-5 py-8 text-center">
      <div className="text-sm font-semibold text-ink/72">{title}</div>
      {description ? <p className="mx-auto mt-2 max-w-xl text-sm leading-6 text-ink/45">{description}</p> : null}
    </div>
  );
}

function PageLoading({ text }: { text: string }) {
  return (
    <div className="flex h-[60vh] items-center justify-center text-sm font-medium text-ink/55">
      <Loader2 className="mr-2 animate-spin" size={18} />
      {text}
    </div>
  );
}

function StatCard({ label, value, description }: { label: string; value: string | number; description?: string }) {
  return (
    <div className="rounded-[22px] border border-line bg-white p-5 shadow-panel">
      <div className="text-xs font-semibold text-ink/45">{label}</div>
      <div className="mt-2 text-3xl font-semibold text-ink">{value}</div>
      {description ? <div className="mt-2 text-sm leading-6 text-ink/45">{description}</div> : null}
    </div>
  );
}

function DistributionList({ title, record, labels = {} }: { title: string; record: JsonRecord | null; labels?: Record<string, string> }) {
  const entries = Object.entries(record ?? {}).filter(([, value]) => Number(value) > 0);
  const total = entries.reduce((sum, [, value]) => sum + Number(value), 0);

  return (
    <section className="rounded-[22px] border border-line bg-white p-5 shadow-panel">
      <h2 className="text-lg font-semibold text-ink">{title}</h2>
      {entries.length ? (
        <div className="mt-5 space-y-4">
          {entries.map(([key, value]) => {
            const width = total ? `${Math.max((Number(value) / total) * 100, 5)}%` : "0%";
            return (
              <div key={key}>
                <div className="flex justify-between gap-3 text-sm font-medium text-ink/58">
                  <span>{labels[key] ?? key}</span>
                  <span>{displayValue(value)}</span>
                </div>
                <div className="mt-2 h-2 overflow-hidden rounded-full bg-[#efefef]">
                  <div className="h-full rounded-full bg-ink" style={{ width }} />
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        <div className="mt-5 text-sm text-ink/42">等待资源同步</div>
      )}
    </section>
  );
}

function CoverageMatrix({ artifactCoverage }: { artifactCoverage: JsonRecord | null }) {
  return (
    <section className="rounded-[22px] border border-line bg-white shadow-panel">
      <div className="border-b border-line px-6 py-5">
        <h2 className="text-lg font-semibold text-ink">覆盖矩阵</h2>
        <p className="mt-1 text-sm text-ink/45">查看课程方案、教案、PPT 和测练对知识点的覆盖情况。</p>
      </div>
      <div className="divide-y divide-line">
        {artifactConfigs.map((item) => {
          const bucket = asRecord(artifactCoverage?.[item.key]);
          const coveredCount = asNumberList(bucket?.covered_knowledge_point_ids).length;
          const invalidCount = asNumberList(bucket?.invalid_knowledge_point_ids).length;
          const itemCount = numberValue(bucket?.item_count) ?? 0;
          const referenceCount = numberValue(bucket?.reference_count) ?? 0;
          return (
            <div className="grid gap-4 px-6 py-5 md:grid-cols-[160px_repeat(4,1fr)] md:items-center" key={item.key}>
              <div className="font-semibold text-ink">{item.label}</div>
              <div>
                <div className="text-xs font-semibold text-ink/40">资源数量</div>
                <div className="mt-1 text-sm font-semibold text-ink">{itemCount || "-"}</div>
              </div>
              <div>
                <div className="text-xs font-semibold text-ink/40">引用数量</div>
                <div className="mt-1 text-sm font-semibold text-ink">{referenceCount || "-"}</div>
              </div>
              <div>
                <div className="text-xs font-semibold text-ink/40">已覆盖</div>
                <div className="mt-1 text-sm font-semibold text-ink">{coveredCount || "-"}</div>
              </div>
              <div>
                <span
                  className={cn(
                    "inline-flex h-8 items-center rounded-full px-3 text-xs font-semibold",
                    invalidCount ? "bg-[#fff4ed] text-[#9a3412]" : "bg-[#f2f2f2] text-ink/62",
                  )}
                >
                  {invalidCount ? "需要关注" : "覆盖正常"}
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function QualitySuggestions({ warnings }: { warnings: JsonRecord[] }) {
  return (
    <section className="rounded-[22px] border border-line bg-white p-5 shadow-panel">
      <h2 className="text-lg font-semibold text-ink">质量建议</h2>
      {warnings.length ? (
        <div className="mt-5 space-y-3">
          {warnings.slice(0, 8).map((warning, index) => {
            const code = String(warning.code ?? "");
            return (
              <div className="rounded-2xl border border-line bg-[#fafafa] p-4" key={`${code}-${index}`}>
                <div className="font-semibold text-ink">{warningLabels[code] ?? "需要关注的覆盖项"}</div>
                <p className="mt-2 text-sm leading-6 text-ink/58">{displayValue(warning.message)}</p>
              </div>
            );
          })}
        </div>
      ) : (
        <div className="mt-5 rounded-2xl border border-line bg-[#fafafa] p-4 text-sm leading-6 text-ink/58">
          当前未发现明显覆盖风险，可以继续查看具体资源内容。
        </div>
      )}
    </section>
  );
}

export function CoverageReportPage() {
  const coverageReportId = toNumberId(useParams().coverageReportId);

  const reportQuery = useQuery({
    queryKey: ["coverage-report", coverageReportId],
    queryFn: () => api.getCoverageReport(coverageReportId),
    enabled: coverageReportId > 0,
  });

  const report = reportQuery.data;
  const reportJson = asRecord(report?.report_json);
  const summary = asRecord(report?.coverage_summary_json);
  const artifactCoverage = asRecord(reportJson?.artifact_coverage);
  const assessmentQuality = asRecord(reportJson?.assessment_quality ?? summary?.assessment_quality);
  const importantCoverage = asRecord(reportJson?.important_knowledge_point_coverage);
  const warnings = useMemo(() => asRecordList(reportJson?.warnings), [reportJson]);

  if (reportQuery.isLoading && !report) {
    return <PageLoading text="正在打开覆盖报告" />;
  }

  if (!report || !isSuccessfulStatus(report.report_status)) {
    return (
      <div className="mx-auto max-w-[1540px] px-2 pb-10 pt-6">
        <FriendlyNotice title="覆盖报告暂未准备好" description="报告生成完成后，可以在这里查看覆盖矩阵和质量建议。" />
      </div>
    );
  }

  const questionBucket = asRecord(artifactCoverage?.question_item);
  const coursewareBucket = asRecord(artifactCoverage?.courseware_slide);
  const questionCoverage = asNumberList(questionBucket?.covered_knowledge_point_ids).length;
  const pptCoverage = asNumberList(coursewareBucket?.covered_knowledge_point_ids).length;

  return (
    <div className="mx-auto w-full max-w-[1540px] space-y-8 px-2 pb-10 pt-6 text-ink">
      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <StatCard label="知识点覆盖" value={percentValue(report.coverage_rate)} description="整套资源覆盖教材知识点的比例。" />
        <StatCard label="题目覆盖" value={questionCoverage || "-"} description="测练题目覆盖到的知识点数量。" />
        <StatCard label="PPT 覆盖" value={pptCoverage || "-"} description="PPT 页面覆盖到的知识点数量。" />
        <StatCard
          label="重点强化"
          value={percentValue(summary?.important_coverage_rate ?? importantCoverage?.coverage_rate)}
          description="重点知识点在资源中的覆盖情况。"
        />
      </section>

      <CoverageMatrix artifactCoverage={artifactCoverage} />

      <div className="grid gap-5 xl:grid-cols-[1fr_420px]">
        <QualitySuggestions warnings={warnings} />
        <div className="space-y-5">
          <DistributionList title="题型分布" record={asRecord(assessmentQuality?.question_type_distribution)} labels={questionTypeLabels} />
          <DistributionList
            title="难度分布"
            record={asRecord(assessmentQuality?.difficulty_distribution)}
            labels={{ "1": "1 级", "2": "2 级", "3": "3 级", "4": "4 级", "5": "5 级", unknown: "未知" }}
          />
        </div>
      </div>
    </div>
  );
}
