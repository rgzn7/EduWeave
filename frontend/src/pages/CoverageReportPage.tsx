import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  AlertCircle,
  BookOpen,
  CheckCircle2,
  ClipboardCheck,
  FileText,
  Info,
  Loader2,
  Monitor,
  PencilLine,
  Target,
  type LucideIcon,
} from "lucide-react";
import { useParams } from "react-router-dom";
import { api } from "../lib/api";
import type { JsonRecord, KnowledgeChapter, KnowledgePointDetail } from "../types";
import { cn, toNumberId } from "../utils";
import { asNumberList, asRecord, asRecordList, displayValue } from "./batch-detail/helpers";

const SERIF_STACK = "'Songti SC', 'Noto Serif SC', 'STSong', serif";
const RIBBON_BG = "/assets/coverage-report/coverage-flow-ribbon-bg.svg";
const HALOS = {
  mint: "/assets/coverage-report/node-halo-mint.svg",
  amber: "/assets/coverage-report/node-halo-amber.svg",
  coral: "/assets/coverage-report/node-halo-coral.svg",
} as const;

const CHAIN_ARTIFACTS = [
  { key: "curriculum_plan", label: "课程方案", icon: FileText },
  { key: "lesson_plan", label: "教案", icon: ClipboardCheck },
  { key: "courseware_slide", label: "PPT", icon: Monitor },
  { key: "homework_question", label: "作业", icon: PencilLine },
  { key: "question_item", label: "试卷", icon: Target },
] as const;

const BAND_CONFIG = [
  { key: "基础掌握题", label: "基础掌握题", color: "#4a9d78", shortLabel: "基础" },
  { key: "典型应用题", label: "典型应用题", color: "#d89026", shortLabel: "应用" },
  { key: "综合提升题", label: "综合提升题", color: "#e24b36", shortLabel: "综合" },
] as const;

type Tone = "mint" | "amber" | "coral";

type ChainNode = {
  id: string;
  label: string;
  count: number | null;
  percent: number | null;
  status: string;
  tone: Tone;
  icon: LucideIcon;
  summary?: string;
};

function isSuccessfulStatus(status?: string | null) {
  return ["success", "ready", "available", "confirmed"].includes(String(status ?? "").toLowerCase());
}

function numberValue(value: unknown) {
  const num = Number(value);
  return Number.isFinite(num) ? num : null;
}

function countValue(value: unknown) {
  const num = numberValue(value);
  return num == null ? null : Math.max(0, Math.round(num));
}

function percentText(value: unknown, digits = 2) {
  const num = numberValue(value);
  if (num == null) {
    return "-";
  }
  const fractionDigits = Number.isInteger(num) ? 0 : digits;
  const formatted = num.toFixed(fractionDigits);
  return `${formatted.includes(".") ? formatted.replace(/0+$/u, "").replace(/\.$/u, "") : formatted}%`;
}

function compactPercentText(value: unknown) {
  const num = numberValue(value);
  if (num == null) {
    return "-";
  }
  const formatted = num.toFixed(2);
  return `${formatted.replace(/0+$/u, "").replace(/\.$/u, "")}%`;
}

function formatCount(value: unknown) {
  const count = countValue(value);
  return count == null ? "-" : String(count);
}

function stripExtension(value?: unknown) {
  return String(value ?? "")
    .replace(/\.[^.]+$/u, "")
    .trim();
}

function titleFromProject(project: JsonRecord | null, batchName?: string | null) {
  const currentTextbook = asRecord(project?.current_textbook);
  const sourceFile = asRecord(currentTextbook?.source_file);
  return (
    stripExtension(currentTextbook?.textbook_name) ||
    stripExtension(sourceFile?.original_filename) ||
    stripExtension(project?.name) ||
    stripExtension(batchName) ||
    "本次备课资源"
  );
}

function toneFromStatus(status: unknown, rate?: unknown): Tone {
  const normalized = String(status ?? "").toLowerCase();
  if (normalized === "strong") {
    return "mint";
  }
  if (normalized === "missing" || normalized === "critical") {
    return "coral";
  }
  const numericRate = numberValue(rate);
  if (numericRate != null && numericRate <= 0) {
    return "coral";
  }
  return "amber";
}

function toneTextClass(tone: Tone) {
  if (tone === "mint") {
    return "text-[#8be0b9]";
  }
  if (tone === "coral") {
    return "text-[#ff6a4d]";
  }
  return "text-[#f4b846]";
}

function toneBorderClass(tone: Tone) {
  if (tone === "mint") {
    return "border-[#7fd8ae]/55";
  }
  if (tone === "coral") {
    return "border-[#ff6048]/55";
  }
  return "border-[#f2b742]/55";
}

function toneDotClass(tone: Tone) {
  if (tone === "mint") {
    return "bg-[#6cc89c]";
  }
  if (tone === "coral") {
    return "bg-[#ef4d36]";
  }
  return "bg-[#eba728]";
}

function buildConclusion(rate: number | null) {
  if (rate != null && rate >= 95) {
    return {
      tone: "mint" as Tone,
      title: "教学资源链路已成型，资源闭环质量较高",
      detail: "课程方案、课堂教学与测练资源覆盖充分，可直接支撑当前备课展示与课堂使用。",
    };
  }
  if (rate != null && rate >= 80) {
    return {
      tone: "amber" as Tone,
      title: "整套资源整体可用，仍有补强空间",
      detail: "建议继续检查各类资源是否形成完整学习反馈闭环。",
    };
  }
  return {
    tone: "coral" as Tone,
    title: "资源链路存在明显缺口，需要优先补齐关键资源",
    detail: "当前覆盖不足以形成完整教学闭环，建议补齐教学资源和测练资源。",
  };
}

function roundedPercent(count: number | null, total: number | null) {
  if (count == null || !total) {
    return null;
  }
  return Math.round((count / total) * 10000) / 100;
}

function coveredCountFromArtifactBucket(bucket: JsonRecord | null) {
  if (!bucket) {
    return null;
  }
  if (Array.isArray(bucket.covered_knowledge_point_ids)) {
    return asNumberList(bucket.covered_knowledge_point_ids).length;
  }
  return countValue(bucket.covered_count ?? bucket.covered_knowledge_point_count);
}

function artifactSummary(label: string, tone: Tone) {
  if (tone === "mint") {
    return `${label}覆盖较充分，可支撑当前知识范围展示。`;
  }
  if (tone === "coral") {
    return `${label}尚未覆盖当前知识范围，需要补充对应成果物。`;
  }
  return `${label}已覆盖部分知识点，仍需补齐未形成闭环的内容。`;
}

function buildBandDistribution(assessmentQualityV2: JsonRecord | null, legacyAssessmentQuality: JsonRecord | null) {
  const semanticDistribution = asRecord(assessmentQualityV2?.difficulty_band_distribution);
  const hasSemanticData = BAND_CONFIG.some((band) => countValue(asRecord(semanticDistribution?.[band.key])?.count) != null);
  if (semanticDistribution && hasSemanticData) {
    return semanticDistribution;
  }

  const difficultyDistribution = asRecord(legacyAssessmentQuality?.difficulty_distribution);
  if (!difficultyDistribution) {
    return null;
  }

  const counts: Record<(typeof BAND_CONFIG)[number]["key"], number> = {
    基础掌握题: (countValue(difficultyDistribution["1"]) ?? 0) + (countValue(difficultyDistribution["2"]) ?? 0),
    典型应用题: countValue(difficultyDistribution["3"]) ?? 0,
    综合提升题: (countValue(difficultyDistribution["4"]) ?? 0) + (countValue(difficultyDistribution["5"]) ?? 0),
  };
  const total = Object.values(counts).reduce((sum, count) => sum + count, 0);
  if (!total) {
    return null;
  }

  return Object.fromEntries(
    BAND_CONFIG.map((band) => [
      band.key,
      {
        count: counts[band.key],
        percent: Math.round((counts[band.key] / total) * 10000) / 100,
      },
    ]),
  ) as JsonRecord;
}

function difficultyBandFromLevel(level?: unknown) {
  const value = countValue(level);
  if (value == null) {
    return "待判断";
  }
  if (value <= 2) {
    return "基础掌握题";
  }
  if (value === 3) {
    return "典型应用题";
  }
  return "综合提升题";
}

function pageRangeText(chapter?: KnowledgeChapter) {
  if (!chapter?.page_start) {
    return null;
  }
  if (chapter.page_end && chapter.page_end !== chapter.page_start) {
    return `${chapter.page_start}-${chapter.page_end}`;
  }
  return String(chapter.page_start);
}

function evidenceLabelFromDetail(point?: KnowledgePointDetail, chapter?: KnowledgeChapter) {
  const pages = Array.from(
    new Set((point?.evidences ?? []).map((evidence) => countValue(evidence.page_no)).filter((page): page is number => page != null)),
  ).sort((a, b) => a - b);
  if (pages.length) {
    return `教材 ${pages.map((page) => `P${page}`).join("、")}`;
  }

  const chapterRange = pageRangeText(chapter);
  return chapterRange ? `章节范围 P${chapterRange}` : null;
}

function chapterDisplayText(value: unknown) {
  return displayValue(value)
    .replace(/^([一二三四五六七八九十]+)\s+(?=年)/u, "$1")
    .replace(/\s+、/gu, "、")
    .replace(/、\s+/gu, "、");
}

function actionForPoint(pointName: string, difficultyBand: string) {
  if (pointName.includes("闰年")) {
    return `建议补充「${pointName}」的成因讲解与平年/闰年判断练习，并在 PPT 中加入年份判断例题。`;
  }
  if (pointName.includes("世纪")) {
    return `建议补充「${pointName}」与年份归属世纪的换算规则，并加入辨析型练习。`;
  }
  if (pointName.includes("月历") || pointName.includes("日期")) {
    return `建议补充「${pointName}」的月历观察活动，并加入日期推理或读日历应用题。`;
  }
  if (difficultyBand.includes("综合")) {
    return `建议围绕「${pointName}」增加综合情境题，并补充讲评要点。`;
  }
  if (difficultyBand.includes("典型")) {
    return `建议围绕「${pointName}」增加典型例题拆解，并配置对应应用练习。`;
  }
  return `建议围绕「${pointName}」补充基础概念辨析，并加入即时巩固题。`;
}

function buildFallbackGap(index: number, point?: KnowledgePointDetail, chapter?: KnowledgeChapter): JsonRecord {
  const difficultyBand = difficultyBandFromLevel(point?.difficulty_level);
  const pointName = point?.point_name ?? `未覆盖知识点 ${index + 1}`;
  const chapterTitle = chapterDisplayText(point?.chapter_title ?? chapter?.title ?? "所属章节待同步");
  const evidenceLabel = evidenceLabelFromDetail(point, chapter);
  return {
    point_name: pointName,
    chapter_title: chapterTitle,
    difficulty_band: difficultyBand,
    evidence: evidenceLabel ? { label: evidenceLabel } : null,
    suggested_action: actionForPoint(pointName, difficultyBand),
  };
}

function evidenceText(value: unknown) {
  const evidence = asRecord(value);
  if (!evidence) {
    return "证据待同步";
  }
  if (evidence.label) {
    return displayValue(evidence.label);
  }
  if (evidence.page_no) {
    return `教材 P${displayValue(evidence.page_no)}`;
  }
  return "证据待同步";
}

function compactEvidenceText(value: unknown) {
  return evidenceText(value).replace(/^教材\s*/u, "");
}

function gapActionChips(pointName: string, difficultyBand: string) {
  const chips = new Set<string>();
  if (pointName.includes("世纪")) {
    chips.add("补充概念辨析");
  } else if (pointName.includes("月历") || pointName.includes("日期")) {
    chips.add("加入综合例题");
  } else {
    chips.add("补充教案讲解");
  }

  chips.add("加入 PPT 页");
  if (difficultyBand.includes("综合")) {
    chips.add("增加 1 道综合提升题");
  } else if (difficultyBand.includes("典型")) {
    chips.add("增加 1 道典型应用题");
  } else {
    chips.add("增加基础掌握题");
  }
  return Array.from(chips).slice(0, 3);
}

function gapStatusText(pointName: string) {
  if (pointName.includes("闰年")) {
    return "建议补充成因讲解与平年、闰年判断练习。";
  }
  if (pointName.includes("世纪")) {
    return "建议补齐年份归属世纪的换算规则与辨析练习。";
  }
  if (pointName.includes("月历") || pointName.includes("日期")) {
    return "建议加入月历观察活动与日期规律推理训练。";
  }
  return "建议在课程讲解、课堂素材与测练资源中补齐该知识点。";
}

function PageLoading({ text }: { text: string }) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-[#edf0f2] text-sm font-medium text-ink/55">
      <Loader2 className="mr-2 animate-spin" size={18} />
      {text}
    </div>
  );
}

function FriendlyNotice({ title, description }: { title: string; description?: string }) {
  return (
    <div className="mx-auto flex min-h-screen max-w-3xl items-center justify-center bg-[#edf0f2] px-6">
      <div className="w-full rounded-[22px] border border-line bg-white px-6 py-10 text-center shadow-panel">
        <div className="text-base font-semibold text-ink">{title}</div>
        {description ? <p className="mx-auto mt-3 max-w-xl text-sm leading-6 text-ink/55">{description}</p> : null}
      </div>
    </div>
  );
}

function InlineInfoTip({ children, label }: { children: string; label: string }) {
  return (
    <span className="group relative inline-flex">
      <button
        aria-label={label}
        className="inline-flex h-5 w-5 items-center justify-center rounded-full text-ink/72 outline-none transition hover:bg-ink/5 hover:text-ink focus-visible:bg-ink/5 focus-visible:ring-2 focus-visible:ring-[#4a9d78]/35"
        type="button"
      >
        <Info size={15} />
      </button>
      <span
        className="pointer-events-none absolute left-1/2 top-full z-30 mt-2 w-72 -translate-x-1/2 rounded-xl border border-line bg-white px-3 py-2 text-left text-xs font-medium leading-5 text-ink/68 opacity-0 shadow-[0_14px_36px_rgba(17,17,17,0.12)] transition group-hover:opacity-100 group-focus-within:opacity-100"
        role="tooltip"
      >
        {children}
      </span>
    </span>
  );
}

function MetricColumn({
  icon: Icon,
  value,
  label,
  tone = "ink",
}: {
  icon: LucideIcon;
  value: string | number;
  label: string;
  tone?: "ink" | Tone;
}) {
  return (
    <div className="flex min-w-[120px] flex-1 flex-col items-center justify-center border-t border-line px-4 py-5 text-center sm:border-l sm:border-t-0">
      <Icon
        className={cn(
          "mb-3",
          tone === "mint" && "text-[#2f8c65]",
          tone === "amber" && "text-[#b36d00]",
          tone === "coral" && "text-[#ef3f24]",
          tone === "ink" && "text-ink/72",
        )}
        size={28}
        strokeWidth={1.8}
      />
      <div className="text-[34px] leading-none text-ink" style={{ fontFamily: SERIF_STACK }}>
        {value}
      </div>
      <div className="mt-2 text-sm text-ink/58">{label}</div>
    </div>
  );
}

function ChainNodeView({ node }: { node: ChainNode }) {
  const Icon = node.icon;
  return (
    <div className="relative min-h-[210px] text-center">
      <div className="relative z-20">
        <div className="text-sm font-semibold text-white">{node.label}</div>
        <div className="mt-3 text-[30px] leading-none text-white" style={{ fontFamily: SERIF_STACK }}>
          {formatCount(node.count)}
        </div>
        <div className={cn("mt-2 text-sm font-medium", toneTextClass(node.tone))}>{compactPercentText(node.percent)}</div>
        <div className={cn("mx-auto mt-3 h-9 w-px border-l border-dashed", toneBorderClass(node.tone))} />
      </div>
      <div className="absolute left-1/2 top-[118px] z-20 flex h-[82px] w-[82px] -translate-x-1/2 items-center justify-center">
        <img className="absolute inset-0 h-full w-full object-contain" src={HALOS[node.tone]} alt="" aria-hidden="true" />
        <div className="relative flex h-[48px] w-[48px] items-center justify-center rounded-full bg-[#111920]/78 text-white ring-1 ring-white/15">
          <Icon className={toneTextClass(node.tone)} size={27} strokeWidth={1.8} />
        </div>
      </div>
    </div>
  );
}

function FlowPanel({ nodes }: { nodes: ChainNode[] }) {
  return (
    <section className="relative overflow-hidden rounded-[22px] bg-[#081018] px-5 py-6 shadow-[0_22px_56px_rgba(2,8,15,0.28)] md:px-8">
      <div className="relative z-20 flex flex-wrap items-center gap-2 text-white">
        <h2 className="text-lg font-semibold">教学资源闭环链路图谱</h2>
      </div>
      <img
        className="pointer-events-none absolute left-0 top-[138px] z-0 h-[180px] w-full object-cover opacity-95 md:top-[130px] md:h-[210px]"
        src={RIBBON_BG}
        alt=""
        aria-hidden="true"
      />
      <div className="relative z-10 mt-8 grid gap-y-9 sm:grid-cols-2 md:grid-cols-3 xl:grid-cols-6">
        {nodes.map((node) => (
          <ChainNodeView key={node.id} node={node} />
        ))}
      </div>
    </section>
  );
}

function GapTable({ coveredCount, gaps, totalCount }: { coveredCount: number; gaps: JsonRecord[]; totalCount: number | null }) {
  const rows = gaps.map((gap) => ({
    gap,
    pointName: displayValue(gap.point_name),
    chapterTitle: chapterDisplayText(gap.chapter_title),
    evidenceLabel: evidenceText(gap.evidence),
    evidenceShort: compactEvidenceText(gap.evidence),
    difficultyBand: String(gap.difficulty_band ?? "待判断"),
  }));
  const chapters = Array.from(new Set(rows.map((row) => row.chapterTitle).filter((chapter) => chapter !== "—")));
  const evidenceLabels = Array.from(new Set(rows.map((row) => row.evidenceShort).filter((label) => label !== "证据待同步")));
  const evidenceSummary = evidenceLabels.length ? `，教材定位为 ${evidenceLabels.join("、")}` : "";
  const clusterText =
    gaps.length > 1 && chapters.length === 1
      ? `发现 ${gaps.length} 个可补强知识点，集中在「${chapters[0]}」章节${evidenceSummary}。`
      : "以下知识点按教材定位排序，便于快速补齐资源链路。";

  return (
    <section className="rounded-[18px] border border-line bg-white p-5 shadow-panel md:p-7">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex items-baseline gap-2">
          <h2 className="text-xl font-semibold text-ink">{gaps.length ? "优先补强建议" : "关键缺口检查"}</h2>
          {gaps.length ? <span className="text-sm font-medium uppercase text-ink/45">Top3</span> : null}
        </div>
        {gaps.length ? <span className="text-xs font-medium text-ink/40">报告数据</span> : null}
      </div>
      {gaps.length ? (
        <>
          <div className="mt-5 flex items-start gap-3 rounded-2xl border border-[#f0dfbd] bg-[#fffaf0] px-4 py-3 text-sm leading-6 text-[#7b5a1c]">
            <AlertCircle className="mt-0.5 shrink-0 text-[#c88a21]" size={16} />
            <span>{clusterText}</span>
          </div>
          <div className="mt-5 grid gap-3 xl:grid-cols-3">
            {rows.map((row, index) => {
              const rankTone = row.difficultyBand.includes("综合") ? "coral" : row.difficultyBand.includes("典型") ? "amber" : "mint";
              const chips = gapActionChips(row.pointName, row.difficultyBand);
              return (
                <article
                  className="rounded-2xl border border-line bg-[#fcfcfb] p-5 transition-colors hover:border-ink/16"
                  key={`${row.pointName}-${index}`}
                >
                  <div className="flex items-start gap-3">
                    <span
                      className={cn(
                        "mt-0.5 inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-sm font-semibold text-white",
                        toneDotClass(rankTone),
                      )}
                    >
                      {index + 1}
                    </span>
                    <div className="min-w-0">
                      <div className="text-base font-semibold leading-6 text-ink">{row.pointName}</div>
                      <div className="mt-2 flex flex-wrap items-center gap-2 text-xs font-medium">
                        <span className="inline-flex items-center gap-1.5 rounded-full bg-white px-2.5 py-1 text-ink/58 ring-1 ring-line">
                          <BookOpen size={13} />
                          {row.evidenceShort}
                        </span>
                        <span className="inline-flex rounded-full bg-white px-2.5 py-1 text-ink/58 ring-1 ring-line">{row.chapterTitle}</span>
                      </div>
                    </div>
                  </div>
                  <p className="mt-4 min-h-[48px] text-sm leading-6 text-ink/68">{gapStatusText(row.pointName)}</p>
                  <div className="mt-4 flex flex-wrap gap-2">
                    {chips.map((chip) => (
                      <span
                        className="inline-flex rounded-full bg-[#f4f6f5] px-3 py-1 text-xs font-semibold text-ink/60 ring-1 ring-line"
                        key={chip}
                      >
                        {chip}
                      </span>
                    ))}
                  </div>
                </article>
              );
            })}
          </div>
        </>
      ) : (
        <div className="mt-6 grid gap-6 lg:grid-cols-[1.05fr_0.95fr] lg:items-center">
          <div className="min-w-0">
            <div className="grid gap-5 sm:grid-cols-[16px_116px_minmax(0,1fr)] sm:items-center">
              <span className="hidden h-36 w-1.5 rounded-full bg-[#39a987] shadow-[0_0_28px_rgba(57,169,135,0.22)] sm:block" />
              <span className="flex h-24 w-24 items-center justify-center rounded-full bg-[#e7f5ef] text-[#2f9a78] ring-1 ring-[#c7eadc] sm:h-28 sm:w-28">
                <CheckCircle2 size={54} strokeWidth={1.6} />
              </span>
              <div className="min-w-0">
                <div className="text-2xl font-semibold leading-tight text-ink md:text-[28px]">未发现关键缺口</div>
                <p className="mt-4 max-w-xl text-sm font-medium leading-7 text-ink/70">
                  课程方案、教案与测练资源已覆盖当前教材知识点，可进入课堂使用。
                </p>
                <p className="mt-2 max-w-xl text-sm font-medium leading-7 text-ink/70">
                  后续可继续补充 PPT、作业或试卷，增强资源颗粒度。
                </p>
              </div>
            </div>
          </div>

          <div className="border-t border-line pt-6 lg:border-l lg:border-t-0 lg:pl-8 lg:pt-0">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-3">
                <span className="flex h-9 w-9 items-center justify-center rounded-full bg-[#ecf8f2] text-[#2f9a78]">
                  <ClipboardCheck size={20} strokeWidth={1.9} />
                </span>
                <div className="text-xl font-semibold text-ink">检查结论</div>
              </div>
              <span className="rounded-full border border-[#d3eadf] bg-[#f1faf6] px-4 py-1.5 text-sm font-semibold text-[#2f8c65]">检查通过</span>
            </div>
            <p className="mt-5 text-sm leading-6 text-ink/52">基于教材知识点、教学目标与学情特征的综合评估</p>
            <div className="mt-6 flex items-center gap-4">
              <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-[#e6ece8]">
                <div className="h-full rounded-full bg-[#34a782]" style={{ width: "100%" }} />
              </div>
              <span className="text-lg font-semibold text-[#2f9a78]">100%</span>
            </div>
            <div className="mt-7 grid grid-cols-3 divide-x divide-line/80 text-center">
              <div className="px-3">
                <BookOpen className="mx-auto text-[#2f9a78]" size={28} strokeWidth={1.8} />
                <div className="mt-3 text-[24px] leading-none text-ink" style={{ fontFamily: SERIF_STACK }}>
                  {formatCount(coveredCount)} / {formatCount(totalCount)}
                </div>
                <div className="mt-2 text-sm text-ink/50">知识点已覆盖</div>
              </div>
              <div className="px-3">
                <AlertCircle className="mx-auto text-[#2f9a78]" size={28} strokeWidth={1.8} />
                <div className="mt-3 text-[24px] leading-none text-ink" style={{ fontFamily: SERIF_STACK }}>
                  0
                </div>
                <div className="mt-2 text-sm text-ink/50">个关键缺口</div>
              </div>
              <div className="px-3">
                <CheckCircle2 className="mx-auto text-[#2f9a78]" size={28} strokeWidth={1.8} />
                <div className="mt-3 text-[24px] leading-none text-ink" style={{ fontFamily: SERIF_STACK }}>
                  可用
                </div>
                <div className="mt-2 text-sm text-ink/50">可支撑课堂使用</div>
              </div>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}

function AssessmentBlueprint({ distribution }: { distribution: JsonRecord | null }) {
  const bands = BAND_CONFIG.map((band) => {
    const item = asRecord(distribution?.[band.key]);
    return {
      ...band,
      count: countValue(item?.count) ?? 0,
      percent: numberValue(item?.percent) ?? 0,
    };
  });
  const totalCount = bands.reduce((sum, band) => sum + band.count, 0);
  const hasData = totalCount > 0;

  return (
    <section className="rounded-[18px] border border-line bg-white p-5 shadow-panel">
      <h2 className="text-xl font-semibold text-ink">测练难度分布 <span className="text-sm font-medium text-ink/45">（语义化难度分布）</span></h2>
      {hasData ? (
        <>
          <div className="mt-6 flex h-4 overflow-hidden rounded-full bg-[#eeeeee]">
            {bands.map((band) => (
              <div
                className="h-full border-r border-white/70 last:border-r-0"
                key={band.key}
                style={{ width: `${Math.max(band.percent, band.count ? 7 : 0)}%`, backgroundColor: band.color }}
              />
            ))}
          </div>
          <div className="mt-8 grid gap-3 sm:grid-cols-3">
            {bands.map((band) => (
              <div className="text-center" key={band.key}>
                <div className="text-sm text-ink/55">{band.label}</div>
                <div className="mt-3 whitespace-nowrap text-[27px] leading-none text-ink md:text-[30px]" style={{ fontFamily: SERIF_STACK }}>
                  {percentText(band.percent, 2)}
                </div>
                <div className="mt-3 text-sm font-medium" style={{ color: band.color }}>
                  {band.count} 题
                </div>
              </div>
            ))}
          </div>
        </>
      ) : (
        <div className="mt-5 rounded-2xl border border-line bg-[#fafafa] p-5 text-sm text-ink/55">测练题目生成后，这里会展示难度语义分布。</div>
      )}
      <div className="mt-7 border-t border-line pt-4 text-xs leading-5 text-ink/48">
        <Info className="mr-1.5 inline" size={14} />
        说明：题目难度 1-5 已映射为教学语义层级，更贴合教学目标与学情特征。
      </div>
    </section>
  );
}

export function CoverageReportPage() {
  const params = useParams();
  const projectId = toNumberId(params.projectId);
  const batchId = toNumberId(params.batchId);
  const coverageReportId = toNumberId(params.coverageReportId);

  const reportQuery = useQuery({
    queryKey: ["coverage-report", coverageReportId],
    queryFn: () => api.getCoverageReport(coverageReportId),
    enabled: coverageReportId > 0,
  });
  const projectQuery = useQuery({
    queryKey: ["project", projectId],
    queryFn: () => api.getProject(projectId),
    enabled: projectId > 0,
  });
  const batchQuery = useQuery({
    queryKey: ["generation-batch", batchId],
    queryFn: () => api.getGenerationBatch(batchId),
    enabled: batchId > 0,
  });

  const report = reportQuery.data;
  const reportJson = asRecord(report?.report_json);
  const summary = asRecord(report?.coverage_summary_json);
  const artifactGapAnalysis = asRecord(reportJson?.artifact_gap_analysis);
  const artifactCoverage = asRecord(reportJson?.artifact_coverage);
  const assessmentQuality = asRecord(reportJson?.assessment_quality ?? summary?.assessment_quality);
  const assessmentQualityV2 = asRecord(reportJson?.assessment_quality_v2);
  const bandDistribution = buildBandDistribution(assessmentQualityV2, assessmentQuality);

  const totalCount =
    countValue(reportJson?.total_knowledge_point_count) ??
    countValue(summary?.total_count) ??
    countValue(reportJson?.knowledge_point_summaries ? Object.keys(asRecord(reportJson?.knowledge_point_summaries) ?? {}).length : null);
  const coveredIds = asNumberList(reportJson?.covered_knowledge_point_ids);
  const uncoveredIds = asNumberList(reportJson?.uncovered_knowledge_point_ids);
  const coveredCount = coveredIds.length || countValue(summary?.covered_count) || 0;
  const uncoveredCount = uncoveredIds.length || countValue(summary?.uncovered_count) || 0;
  const coverageRate = numberValue(report?.coverage_rate ?? summary?.coverage_rate);
  const reportTopGaps = asRecordList(reportJson?.uncovered_knowledge_points).slice(0, 3);
  const knowledgeVersionId = batchQuery.data?.knowledge_version_id ?? 0;
  const needsGapFallback = uncoveredIds.length > 0 && reportTopGaps.length === 0;

  const fallbackPointIds = uncoveredIds.slice(0, 3);
  const knowledgePointDetailsQuery = useQuery({
    queryKey: ["knowledge-point-details", fallbackPointIds],
    queryFn: () => Promise.all(fallbackPointIds.map((pointId) => api.getKnowledgePoint(pointId))),
    enabled: Boolean(report && needsGapFallback && fallbackPointIds.length > 0),
  });
  const chaptersQuery = useQuery({
    queryKey: ["knowledge-chapters", knowledgeVersionId, "coverage-gap-fallback"],
    queryFn: () => api.listKnowledgeChapters(knowledgeVersionId),
    enabled: Boolean(report && knowledgeVersionId > 0 && needsGapFallback),
  });

  const chainNodes = useMemo<ChainNode[]>(() => {
    const baseline: ChainNode = {
      id: "knowledge",
      label: "教材知识点",
      count: totalCount,
      percent: totalCount ? 100 : null,
      status: "strong",
      tone: "mint",
      icon: BookOpen,
      summary: "当前覆盖范围内的教材知识点基线。",
    };
    const artifactNodes = CHAIN_ARTIFACTS.map((config) => {
      const gap = asRecord(artifactGapAnalysis?.[config.key]);
      const bucket = asRecord(artifactCoverage?.[config.key]);
      const fallbackCount = coveredCountFromArtifactBucket(bucket);
      const count = countValue(gap?.covered_count) ?? fallbackCount;
      const rate = numberValue(gap?.coverage_rate) ?? roundedPercent(count, totalCount);
      const status = String(gap?.coverage_status ?? "");
      const tone = toneFromStatus(status, rate);
      return {
        id: config.key,
        label: config.label,
        count,
        percent: rate,
        status,
        tone,
        icon: config.icon,
        summary: String(gap?.gap_summary ?? artifactSummary(config.label, tone)),
      };
    });
    return [baseline, ...artifactNodes];
  }, [artifactCoverage, artifactGapAnalysis, totalCount]);

  const conclusion = buildConclusion(coverageRate);
  const topGaps = useMemo(() => {
    if (reportTopGaps.length) {
      return reportTopGaps;
    }
    const pointMap = new Map((knowledgePointDetailsQuery.data ?? []).map((point) => [point.id, point]));
    const chapterMap = new Map((chaptersQuery.data ?? []).map((chapter) => [chapter.id, chapter]));
    return uncoveredIds.slice(0, 3).map((pointId, index) => {
      const point = pointMap.get(pointId);
      const chapter = point?.chapter_node_id ? chapterMap.get(point.chapter_node_id) : undefined;
      return buildFallbackGap(index, point, chapter);
    });
  }, [chaptersQuery.data, knowledgePointDetailsQuery.data, reportTopGaps, uncoveredIds]);
  const title = titleFromProject(projectQuery.data as unknown as JsonRecord | null, batchQuery.data?.batch_name);

  if (reportQuery.isLoading && !report) {
    return <PageLoading text="正在打开覆盖评审报告" />;
  }

  if (!report || !isSuccessfulStatus(report.report_status)) {
    return <FriendlyNotice title="覆盖报告暂未准备好" description="报告生成完成后，可以在这里查看教学资源闭环评审结果。" />;
  }

  return (
    <div className="mx-auto w-full max-w-[1540px] space-y-5 px-2 pb-10 pt-6 text-ink">
      <section className="rounded-[22px] border border-line bg-white p-6 shadow-panel md:p-8">
          <section>
            <h1
              className="text-[26px] font-semibold leading-tight text-ink lg:text-[28px] xl:whitespace-nowrap xl:text-[30px]"
              style={{ fontFamily: SERIF_STACK }}
            >
              《{title}》教学资源闭环评审报告
            </h1>
            <p className="mt-4 text-base text-ink/58">基于教学目标、学情特征与教材知识点的全链路覆盖评审</p>
          </section>

          <section className="mt-7 grid gap-6 xl:grid-cols-[260px_minmax(0,1fr)_360px] xl:items-stretch">
            <div className="border-b border-line pb-6 xl:border-b-0 xl:border-r xl:pb-0 xl:pr-6">
              <div className="text-[72px] leading-none text-ink md:text-[86px]" style={{ fontFamily: SERIF_STACK }}>
                {percentText(coverageRate, 2)}
              </div>
              <div className="mt-3 flex items-center gap-2 text-sm text-ink/62">
                知识点覆盖率
                <InlineInfoTip label="知识点覆盖率说明">
                  覆盖率 = 已被整套备课资源覆盖的知识点数 / 教材知识点总数；它反映整体资源闭环，不代表每一种资源都已单独覆盖全部知识点。
                </InlineInfoTip>
              </div>
            </div>

            <div className="flex items-start gap-4 border-b border-line pb-6 xl:border-b-0 xl:pb-0">
              <span className={cn("mt-2 h-3 w-3 rounded-full", toneDotClass(conclusion.tone))} />
              <div>
                <div className="text-sm font-medium text-ink/62">评审结论</div>
                <h2 className="mt-3 text-xl font-semibold leading-snug text-ink 2xl:text-2xl">{conclusion.title}</h2>
                <p className="mt-4 max-w-2xl text-sm leading-7 text-ink/58">{conclusion.detail}</p>
              </div>
            </div>

            <div className="grid overflow-hidden rounded-[18px] border border-line bg-[#fbfbfb] sm:grid-cols-3">
              <MetricColumn icon={BookOpen} value={formatCount(totalCount)} label="个知识点" />
              <MetricColumn icon={CheckCircle2} value={formatCount(coveredCount)} label="已覆盖" tone="mint" />
              <MetricColumn icon={AlertCircle} value={formatCount(uncoveredCount)} label="个关键缺口" tone={uncoveredCount ? "coral" : "mint"} />
            </div>
          </section>
      </section>

      <FlowPanel nodes={chainNodes} />

      <section className="space-y-4">
        <GapTable coveredCount={coveredCount} gaps={topGaps} totalCount={totalCount} />
        <AssessmentBlueprint distribution={bandDistribution} />
      </section>
    </div>
  );
}
