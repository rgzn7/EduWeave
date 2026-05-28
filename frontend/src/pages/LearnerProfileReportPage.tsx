import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  BookOpen,
  Calculator,
  CalendarClock,
  CheckCircle2,
  ClipboardList,
  Languages,
  Loader2,
  ShieldCheck,
  Target,
  TrendingUp,
  UserRound,
  Users,
} from "lucide-react";
import type { ReactNode } from "react";
import { Link, useParams } from "react-router-dom";
import { EmptyState } from "../components/EmptyState";
import { ErrorNotice } from "../components/ErrorNotice";
import { api } from "../lib/api";
import type {
  JsonRecord,
  LearnerClassProfile,
  LearnerProfileRecord,
  LearnerProfileSubjectOverview,
  LearnerProfileTieredGroup,
} from "../types";
import { cn, getErrorMessage, toNumberId } from "../utils";

const COUNT_FORMATTER = new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 0 });
const SCORE_FORMATTER = new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 1 });

const SUBJECT_LABELS: Record<string, string> = {
  chinese: "语文",
  math: "数学",
  english: "英语",
  science: "科学",
};

const SUBJECT_ORDER = ["chinese", "math", "english", "science"];

const TIER_META: Record<string, { label: string; color: string; bg: string; ring: string }> = {
  high: { label: "高分层", color: "#111111", bg: "bg-white", ring: "bg-[#f2f2f2] text-ink" },
  mid: { label: "中分层", color: "#111111", bg: "bg-white", ring: "bg-[#f2f2f2] text-ink" },
  low: { label: "待提升层", color: "#111111", bg: "bg-white", ring: "bg-[#f2f2f2] text-ink" },
};

function valueAsRecord(value: unknown): JsonRecord | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  return value as JsonRecord;
}

function stringValue(value: unknown) {
  if (typeof value === "string" && value.trim()) {
    return value.trim();
  }
  if (typeof value === "number" && Number.isFinite(value)) {
    return String(value);
  }
  return "";
}

function metricNumber(detail: JsonRecord | null | undefined, key: string) {
  const value = detail?.[key];
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string" && value.trim()) {
    const numericValue = Number(value);
    return Number.isFinite(numericValue) ? numericValue : null;
  }
  return null;
}

function formatCount(value: number) {
  return COUNT_FORMATTER.format(Math.round(value));
}

function formatScore(value: number | null | undefined) {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return "-";
  }
  return Number.isInteger(value) ? String(value) : SCORE_FORMATTER.format(value);
}

function subjectLabel(subjectCode: string) {
  return SUBJECT_LABELS[subjectCode] ?? subjectCode;
}

function SubjectMark({ subjectCode }: { subjectCode: string }) {
  const Icon = subjectCode === "math" ? Calculator : subjectCode === "english" ? Languages : BookOpen;

  return (
    <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-line bg-[#f7f7f6] text-ink/50">
      {subjectCode === "english" ? <span className="text-xs font-black">ABC</span> : <Icon size={18} />}
    </span>
  );
}

function SectionHeading({
  description,
  icon,
  title,
}: {
  description?: string;
  icon: ReactNode;
  title: string;
}) {
  return (
    <div className="mb-5 flex items-start justify-between gap-4">
      <div className="flex min-w-0 items-start gap-3">
        <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-[#f7f7f6] text-ink/42">{icon}</span>
        <div className="min-w-0">
          <h2 className="text-lg font-semibold text-ink">{title}</h2>
          {description ? <p className="mt-1 text-sm leading-6 text-ink/45">{description}</p> : null}
        </div>
      </div>
    </div>
  );
}

function uniqueItems(items: string[], limit = 5) {
  return [...new Set(items.map((item) => item.trim()).filter(Boolean))].slice(0, limit);
}

function extractTagItems(value: unknown): string[] {
  if (!value) {
    return [];
  }
  if (Array.isArray(value)) {
    return value.flatMap((item) => extractTagItems(item)).filter(Boolean);
  }
  if (typeof value === "string" || typeof value === "number") {
    return [String(value)];
  }
  const record = valueAsRecord(value);
  if (!record) {
    return [];
  }
  const preferred = record.items ?? record.tags ?? record.values ?? record.list;
  if (preferred) {
    return extractTagItems(preferred);
  }
  return Object.values(record).flatMap((item) => extractTagItems(item)).filter(Boolean);
}

function tagsFromRecord(record: JsonRecord | null | undefined) {
  return uniqueItems(extractTagItems(record), 8);
}

function scorePercent(value: number | null | undefined) {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return 0;
  }
  return Math.max(0, Math.min(100, value));
}

function scoreFromRecord(record: LearnerProfileRecord) {
  const value = record.score_value;
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function sortedSubjects<T extends { subject_code: string }>(items: T[]) {
  return [...items].sort((a, b) => {
    const orderA = SUBJECT_ORDER.indexOf(a.subject_code);
    const orderB = SUBJECT_ORDER.indexOf(b.subject_code);
    return (orderA === -1 ? 99 : orderA) - (orderB === -1 ? 99 : orderB);
  });
}

function classProfileFrom(raw: JsonRecord | null | undefined, direct?: LearnerClassProfile | null) {
  if (direct) {
    return direct;
  }
  const rawClassProfile = valueAsRecord(raw?.class_profile);
  return rawClassProfile ? (rawClassProfile as unknown as LearnerClassProfile) : null;
}

function subjectOverviewsFrom(profile: LearnerClassProfile | null) {
  return Array.isArray(profile?.subject_overview) ? profile.subject_overview : [];
}

function tieredGroupsFrom(profile: LearnerClassProfile | null) {
  return Array.isArray(profile?.tiered_groups) ? profile.tiered_groups : [];
}

function uniqueStudentKeys(records: LearnerProfileRecord[]) {
  return uniqueItems(
    records.map((record) => record.student_name || record.student_key).filter(Boolean),
    300,
  );
}

function learnerStudentCount(raw: JsonRecord | null, classProfile: LearnerClassProfile | null, records: LearnerProfileRecord[]) {
  const rawCount = metricNumber(raw, "student_count");
  if (rawCount !== null) {
    return rawCount;
  }
  const subjectCount = Math.max(0, ...subjectOverviewsFrom(classProfile).map((item) => item.student_count || 0));
  if (subjectCount > 0) {
    return subjectCount;
  }
  return uniqueStudentKeys(records).length || null;
}

function normalizeTierStudentKey(key: string) {
  return key.replace(/_(chinese|math|english|science|physics|chemistry|biology|history|geography|politics)$/i, "");
}

function tierStudentCount(group: LearnerProfileTieredGroup) {
  return new Set((group.student_keys ?? []).map((key) => normalizeTierStudentKey(key))).size;
}

function tierSortValue(tier: string) {
  const index = ["high", "mid", "low"].indexOf(tier);
  return index === -1 ? 99 : index;
}

function tierMeta(tier: string) {
  return TIER_META[tier] ?? { label: tier, color: "#111111", bg: "bg-white", ring: "bg-[#f2f2f2] text-ink" };
}

function distributionWidths(item: LearnerProfileSubjectOverview) {
  const total = Math.max(1, item.high_count + item.mid_count + item.low_count);
  return {
    high: `${Math.max(4, (item.high_count / total) * 100)}%`,
    mid: `${Math.max(4, (item.mid_count / total) * 100)}%`,
    low: `${Math.max(4, (item.low_count / total) * 100)}%`,
  };
}

function listText(items: string[], emptyText: string, limit = 4) {
  const visibleItems = uniqueItems(items, limit);
  if (!visibleItems.length) {
    return <p className="text-sm leading-6 text-ink/45">{emptyText}</p>;
  }
  return (
    <ul className="space-y-2">
      {visibleItems.map((item) => (
        <li className="flex gap-2 text-sm leading-6" key={item}>
          <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-current opacity-70" />
          <span className="text-ink/72">{item}</span>
        </li>
      ))}
    </ul>
  );
}

function PageMetric({
  icon,
  label,
  value,
}: {
  icon: ReactNode;
  label: string;
  value: string;
}) {
  return (
    <div className="flex min-h-[82px] min-w-[148px] items-center gap-3 rounded-lg border border-line/80 bg-white px-4">
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[#f4f4f4] text-ink/45">{icon}</div>
      <div>
        <div className="text-xs text-ink/45">{label}</div>
        <div className={cn("mt-1 text-xl font-semibold text-ink", value === "无异常" && "text-[#0f8f7a]")}>{value}</div>
      </div>
    </div>
  );
}

function SummaryPanel({
  metrics,
  summary,
  title,
}: {
  metrics: ReactNode;
  summary: string;
  title: string;
}) {
  return (
    <section className="rounded-xl border border-line bg-white p-5 shadow-[0_16px_36px_rgba(17,17,17,0.035)]">
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_auto] xl:items-center">
        <div>
          <h2 className="text-lg font-semibold text-ink">{title}</h2>
          <p className="mt-2 max-w-4xl text-sm leading-7 text-ink/72">{summary}</p>
        </div>
        <div className="grid gap-3 sm:grid-cols-3">{metrics}</div>
      </div>
    </section>
  );
}

function ClassSubjectTable({ items }: { items: LearnerProfileSubjectOverview[] }) {
  const visibleItems = sortedSubjects(items).slice(0, 5);
  if (!visibleItems.length) {
    return <p className="rounded-lg bg-white px-4 py-5 text-sm text-ink/45">班级基础数据暂未返回。</p>;
  }
  return (
    <div className="overflow-hidden rounded-lg border border-line bg-white">
      <div className="grid grid-cols-[1fr_0.9fr_0.9fr_1fr_2fr] border-b border-line/80 bg-[#f7f8f6] text-sm font-medium text-ink/45">
        <div className="px-4 py-3">学科</div>
        <div className="px-4 py-3 text-center">覆盖学生</div>
        <div className="px-4 py-3 text-center">平均分</div>
        <div className="px-4 py-3 text-center">最高 / 最低</div>
        <div className="px-4 py-3 text-center">高 / 中 / 待提升</div>
      </div>
      {visibleItems.map((item) => {
        const widths = distributionWidths(item);
        return (
          <div className="grid grid-cols-[1fr_0.9fr_0.9fr_1fr_2fr] items-center border-b border-line/70 last:border-b-0" key={item.subject_code}>
            <div className="px-4 py-4 font-semibold text-ink">
              {subjectLabel(item.subject_code)}
            </div>
            <div className="px-4 py-4 text-center text-sm text-ink/68">{formatCount(item.student_count)} 人</div>
            <div className="px-4 py-4 text-center font-semibold text-[#0f8f7a]">{formatScore(item.score_avg)} 分</div>
            <div className="px-4 py-4 text-center text-sm text-ink/72">
              {formatScore(item.score_max)} / {formatScore(item.score_min)}
            </div>
            <div className="px-4 py-4">
              <div className="flex items-center gap-4">
                <div className="flex h-2 min-w-0 flex-1 overflow-hidden rounded-full bg-[#eeeeee]">
                  <span className="bg-ink" style={{ width: widths.high }} />
                  <span className="bg-[#9a9a9a]" style={{ width: widths.mid }} />
                  <span className="bg-[#d7d7d7]" style={{ width: widths.low }} />
                </div>
                <div className="w-20 text-sm font-medium">
                  <span className="text-ink">{formatCount(item.high_count)}</span>
                  <span className="px-1 text-ink/30">/</span>
                  <span className="text-ink/58">{formatCount(item.mid_count)}</span>
                  <span className="px-1 text-ink/30">/</span>
                  <span className="text-ink/36">{formatCount(item.low_count)}</span>
                </div>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function ClassFeatureCard({ classProfile }: { classProfile: LearnerClassProfile }) {
  return (
    <section className="rounded-xl border border-line bg-white p-5 shadow-[0_18px_48px_rgba(17,17,17,0.035)]">
      <h2 className="mb-4 text-lg font-semibold text-ink">共性特征</h2>
      <div className="grid gap-6 lg:grid-cols-3">
        <div className="border-line/70 lg:border-r lg:pr-6">
          <div className="mb-2 text-sm font-semibold text-ink">共性优势</div>
          {listText([...(classProfile.common_strengths ?? []), ...(classProfile.common_behaviors ?? [])], "暂未返回共性优势。")}
        </div>
        <div className="border-line/70 lg:border-r lg:pr-6">
          <div className="mb-2 text-sm font-semibold text-ink">共性薄弱点</div>
          {listText(classProfile.common_weaknesses ?? [], "暂未发现明显薄弱点。")}
        </div>
        <div>
          <div className="mb-2 text-sm font-semibold text-ink">学习习惯</div>
          {listText(classProfile.common_habits ?? [], "学习习惯摘要暂未返回。")}
        </div>
      </div>
    </section>
  );
}

function ClassSuggestionCard({ groups, recommendations }: { groups: LearnerProfileTieredGroup[]; recommendations: string[] }) {
  const visibleGroups = [...groups].sort((a, b) => tierSortValue(a.tier) - tierSortValue(b.tier)).slice(0, 3);
  return (
    <section className="rounded-xl border border-line bg-white p-5 shadow-[0_18px_48px_rgba(17,17,17,0.035)]">
      <h2 className="mb-4 text-lg font-semibold text-ink">教学建议</h2>
      {visibleGroups.length ? (
        <div className="grid gap-3 lg:grid-cols-3">
          {visibleGroups.map((group) => {
            const meta = tierMeta(group.tier);
            return (
              <div className={`rounded-lg border border-line/80 ${meta.bg} p-4`} key={group.tier}>
                <div className="mb-3 flex items-center justify-between gap-3">
                  <div className="flex items-center gap-3 font-semibold" style={{ color: meta.color }}>
                    <span className="h-1.5 w-1.5 rounded-full bg-[#0f8f7a]" />
                    {meta.label}
                  </div>
                  <div className="text-sm text-ink/58">{formatCount(tierStudentCount(group))} 人</div>
                </div>
                <p className="text-sm leading-7 text-ink/72">{uniqueItems(group.teaching_suggestions ?? [], 1)[0] ?? "暂无建议。"}</p>
              </div>
            );
          })}
        </div>
      ) : (
        <div className="rounded-lg border border-line/80 bg-[#f8f9f7] p-4">{listText(recommendations, "教学建议暂未返回。", 3)}</div>
      )}
    </section>
  );
}

function ClassProfileReport({
  classProfile,
  raw,
  records,
}: {
  classProfile: LearnerClassProfile;
  raw: JsonRecord | null;
  records: LearnerProfileRecord[];
}) {
  const subjectOverviews = subjectOverviewsFrom(classProfile);
  const studentCount = learnerStudentCount(raw, classProfile, records);
  const warningCount = classProfile.warnings?.length ?? 0;
  const subjectCount = new Set(subjectOverviews.map((item) => item.subject_code).filter(Boolean)).size;

  return (
    <section className="space-y-4">
      <div className="flex items-center gap-3">
        <span className="flex h-8 w-8 items-center justify-center rounded-full bg-[#f4f4f4] text-ink/45">
          <CheckCircle2 size={18} />
        </span>
        <h1 className="text-2xl font-semibold text-ink">班级学情画像</h1>
      </div>
      <div className="space-y-4">
        <SummaryPanel
          metrics={
            <>
              <PageMetric icon={<Users size={17} />} label="学生人数" value={studentCount !== null ? `${formatCount(studentCount)} 人` : "-"} />
              <PageMetric icon={<BookOpen size={17} />} label="学科数量" value={`${formatCount(subjectCount)} 科`} />
              <PageMetric icon={warningCount ? <AlertTriangle size={17} /> : <ShieldCheck size={17} />} label="异常预警" value={warningCount ? `${formatCount(warningCount)} 条` : "无异常"} />
            </>
          }
          summary={classProfile.class_summary || "班级画像摘要暂未返回。"}
          title="综合结论"
        />
        <section className="rounded-xl border border-line bg-white p-5">
          <div className="mb-4 flex items-center justify-between gap-3">
            <h2 className="text-lg font-semibold text-ink">班级基础</h2>
            <span className="text-xs text-ink/40">平均分、最高/最低与分层人数</span>
          </div>
          <ClassSubjectTable items={subjectOverviews} />
        </section>
        <div className="space-y-4">
          <ClassFeatureCard classProfile={classProfile} />
          <ClassSuggestionCard groups={tieredGroupsFrom(classProfile)} recommendations={classProfile.teaching_recommendations ?? []} />
        </div>
      </div>
    </section>
  );
}

function recordSummary(record: LearnerProfileRecord) {
  return record.summary_text?.replace(/\s+/g, " ").trim() || "暂无简述。";
}

function TagPills({
  emptyText,
  items,
  limit = 4,
  tone = "neutral",
}: {
  emptyText: string;
  items: string[];
  limit?: number;
  tone?: "neutral" | "strength" | "weakness";
}) {
  const visibleItems = uniqueItems(items, limit);
  if (!visibleItems.length) {
    return <p className="text-sm text-ink/38">{emptyText}</p>;
  }
  const toneClass =
    tone === "strength"
      ? "border-line bg-[#f7f7f6] text-ink/65"
      : tone === "weakness"
        ? "border-line bg-white text-ink/65"
        : "border-line bg-[#f7f7f6] text-ink/68";
  return (
    <div className="flex flex-wrap gap-2">
      {visibleItems.map((item) => (
        <span className={cn("rounded-md border px-2.5 py-1 text-xs font-semibold", toneClass)} key={item}>
          {item}
        </span>
      ))}
    </div>
  );
}

function StudentMetric({
  icon,
  label,
  value,
}: {
  icon: ReactNode;
  label: string;
  value: string;
}) {
  return (
    <div className="flex min-h-[88px] items-center gap-4 px-0 py-2 lg:px-7">
      <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-[#f7f7f6] text-ink/42">{icon}</span>
      <div className="min-w-0">
        <div className="text-sm font-medium text-ink/45">{label}</div>
        <div className="mt-1 truncate text-[26px] font-semibold leading-tight text-ink">{value}</div>
      </div>
    </div>
  );
}

function StudentHeroPanel({
  highestScore,
  improvementTag,
  studentName,
  subjectCount,
  summary,
}: {
  highestScore: number | null;
  improvementTag: string;
  studentName: string;
  subjectCount: number;
  summary: string;
}) {
  return (
    <section className="rounded-lg border border-line bg-white p-5 shadow-[0_18px_44px_rgba(17,17,17,0.045)] lg:p-7">
      <h2 className="text-xl font-semibold text-ink">学生学情画像</h2>

      <div className="mt-6 grid gap-4 border-line/75 lg:grid-cols-[1.25fr_1fr_1fr_1.35fr] lg:divide-x lg:divide-line/75">
        <div className="flex min-h-[88px] items-center gap-5 py-2 lg:pr-7">
          <span className="flex h-16 w-16 shrink-0 items-center justify-center rounded-full bg-[#f7f7f6] text-ink/45">
            <UserRound size={34} strokeWidth={1.7} />
          </span>
          <div className="min-w-0">
            <div className="text-sm font-medium text-ink/45">学生</div>
            <div className="mt-1 truncate text-[28px] font-semibold leading-tight text-ink">{studentName}</div>
            <div className="mt-1 text-sm text-ink/45">综合学习画像总结</div>
          </div>
        </div>

        <StudentMetric icon={<BookOpen size={23} strokeWidth={1.8} />} label="学科学习情况" value={subjectCount ? `${formatCount(subjectCount)} 科` : "-"} />
        <StudentMetric icon={<TrendingUp size={23} strokeWidth={1.8} />} label="最高分" value={highestScore !== null ? `${formatScore(highestScore)} 分` : "-"} />
        <StudentMetric icon={<Target size={23} strokeWidth={1.8} />} label="重点提升" value={improvementTag} />
      </div>

      <div className="relative mt-7 overflow-hidden rounded-lg border border-line bg-[#fafafa] px-5 py-5 sm:px-8">
        <div className="pointer-events-none absolute left-5 top-3 text-6xl font-serif leading-none text-ink/10">“</div>
        <p className="relative z-[1] px-1 text-sm font-medium leading-7 text-ink/78 sm:px-8">{summary}</p>
        <div className="pointer-events-none absolute bottom-0 right-5 text-6xl font-serif leading-none text-ink/10">”</div>
      </div>
    </section>
  );
}

function StudentPerformancePanel({ records }: { records: LearnerProfileRecord[] }) {
  const visibleRecords = sortedSubjects(records).slice(0, 4);

  if (!visibleRecords.length) {
    return <p className="rounded-lg bg-white px-4 py-5 text-sm text-ink/45">学生画像记录加载中。</p>;
  }

  return (
    <section className="rounded-lg border border-line bg-white p-5 shadow-[0_18px_48px_rgba(17,17,17,0.035)] lg:p-7">
      <SectionHeading
        description="分数、能力标签、薄弱点与学习简述"
        icon={<ClipboardList size={17} />}
        title="基础表现"
      />

      <div className="space-y-3">
        {visibleRecords.map((record) => {
          const score = scoreFromRecord(record);
          const abilityTags = uniqueItems([...tagsFromRecord(record.ability_tags_json), ...tagsFromRecord(record.advantage_tags_json)], 5);
          const weaknessTags = uniqueItems(tagsFromRecord(record.weakness_tags_json), 4);
          const summary = recordSummary(record);

          return (
            <article className="rounded-lg border border-line bg-white p-4" key={record.id}>
              <div className="grid gap-5 xl:grid-cols-[220px_minmax(0,1fr)]">
                <div className="flex min-w-0 items-center gap-4 xl:block">
                  <div className="flex items-center gap-3">
                    <SubjectMark subjectCode={record.subject_code} />
                    <span className="text-lg font-semibold text-ink">{subjectLabel(record.subject_code)}</span>
                  </div>
                  <div className="min-w-[180px] flex-1 xl:mt-7">
                    <div className="flex items-end gap-1">
                      <span className="text-3xl font-semibold leading-none text-[#0f8f7a]">{formatScore(score)}</span>
                      <span className="text-sm font-medium text-ink/45">分</span>
                    </div>
                    <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-[#e8e8e6]">
                      <span className="block h-full rounded-full bg-[#0f8f7a]" style={{ width: `${scorePercent(score)}%` }} />
                    </div>
                  </div>
                </div>

                <div className="min-w-0 space-y-4">
                  <div className="grid gap-4 md:grid-cols-2">
                    <div className="rounded-lg border border-line/70 bg-[#fafafa] px-4 py-3">
                      <div className="mb-2 text-sm font-semibold text-ink">能力标签</div>
                      <TagPills emptyText="暂未返回能力标签。" items={abilityTags} limit={5} tone="strength" />
                    </div>
                    <div className="rounded-lg border border-line/70 bg-[#fafafa] px-4 py-3">
                      <div className="mb-2 text-sm font-semibold text-ink">薄弱点</div>
                      <TagPills emptyText="暂未返回薄弱点。" items={weaknessTags} tone="weakness" />
                    </div>
                  </div>
                  <div className="rounded-lg border border-line/70 bg-white px-4 py-3">
                    <div className="mb-2 text-sm font-semibold text-ink">学习简述</div>
                    <p className="text-sm leading-7 text-ink/68">{summary}</p>
                  </div>
                </div>
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}

function StudentFeaturePanel({ records }: { records: LearnerProfileRecord[] }) {
  const abilityTags = uniqueItems(records.flatMap((record) => [...tagsFromRecord(record.ability_tags_json), ...tagsFromRecord(record.advantage_tags_json)]), 8);
  const weaknessTags = uniqueItems(records.flatMap((record) => tagsFromRecord(record.weakness_tags_json)), 8);
  const habits = uniqueItems(records.flatMap((record) => [...tagsFromRecord(record.habit_tags_json), ...tagsFromRecord(record.behavior_traits_json)]), 4);
  const rows = mergeTimePlanRows(timePlanRowsFrom(records)).slice(0, 4);

  return (
    <section className="rounded-lg border border-line bg-white p-5 shadow-[0_18px_48px_rgba(17,17,17,0.035)] lg:p-7">
      <SectionHeading
        description="沉淀学生优势、待补方向与后续课时安排"
        icon={<CalendarClock size={17} />}
        title="学习特征与安排"
      />

      <div className="space-y-5">
        <div className="overflow-hidden rounded-lg border border-line bg-white">
          <div className="grid gap-3 border-b border-line/70 px-4 py-4 md:grid-cols-[118px_minmax(0,1fr)] md:items-center">
            <div className="flex items-center gap-2 text-sm font-semibold text-ink">
              <CheckCircle2 className="text-ink/35" size={17} />
              优势能力
            </div>
            <TagPills emptyText="暂未返回优势能力。" items={abilityTags} limit={8} tone="strength" />
          </div>

          <div className={cn("grid gap-3 px-4 py-4 md:grid-cols-[118px_minmax(0,1fr)] md:items-center", habits.length && "border-b border-line/70")}>
            <div className="flex items-center gap-2 text-sm font-semibold text-ink">
              <AlertTriangle className="text-ink/35" size={17} />
              薄弱点
            </div>
            <TagPills emptyText="暂未返回薄弱点。" items={weaknessTags} limit={8} tone="weakness" />
          </div>

          {habits.length ? (
            <div className="grid gap-3 px-4 py-4 md:grid-cols-[118px_minmax(0,1fr)] md:items-center">
              <div className="flex items-center gap-2 text-sm font-semibold text-ink">
                <ClipboardList className="text-ink/35" size={17} />
                学习习惯
              </div>
              <TagPills emptyText="" items={habits} limit={6} />
            </div>
          ) : null}
        </div>

        <div className="rounded-lg border border-line/80 bg-white px-4 py-4">
          <div className="mb-4 text-sm font-semibold text-ink">学习安排</div>
          {rows.length ? (
            <div className="grid gap-3 xl:grid-cols-2">
              {rows.map((row, index) => (
                <article
                  className={cn(
                    "rounded-lg border border-line/80 bg-[#fafafa] px-4 py-4",
                    rows.length === 1 && "xl:col-span-2",
                    rows.length === 3 && index === 2 && "xl:col-span-2",
                  )}
                  key={`${row.subject}-${index}`}
                >
                  <div className="flex items-center gap-3">
                    <SubjectMark subjectCode={row.subjectCode} />
                    <div className="min-w-0">
                      <div className="font-semibold text-ink">{row.subject}</div>
                      <div className="mt-1 text-sm font-semibold text-ink/70">{row.meta || "安排建议"}</div>
                    </div>
                  </div>
                  <p className="mt-3 text-sm leading-7 text-ink/62">{row.text}</p>
                </article>
              ))}
            </div>
          ) : (
            <p className="text-sm leading-6 text-ink/45">学习安排暂未返回。</p>
          )}
        </div>

      </div>
    </section>
  );
}

function timePlanRowsFrom(records: LearnerProfileRecord[]): Array<{ subject: string; subjectCode: string; text: string; meta?: string }> {
  return records.flatMap((record) => {
    const detail = valueAsRecord(record.time_plan_json);
    const items = Array.isArray(detail?.items) ? detail.items : [];
    return items.flatMap((item) => {
      const itemRecord = valueAsRecord(item);
      if (!itemRecord) {
        const text = stringValue(item);
        return text ? [{ subject: subjectLabel(record.subject_code), subjectCode: record.subject_code, text }] : [];
      }
      const subject = stringValue(itemRecord.subject_name) || subjectLabel(record.subject_code);
      const text = stringValue(itemRecord.raw_text) || stringValue(itemRecord.description) || stringValue(itemRecord.summary);
      const lessonsPerWeek = metricNumber(itemRecord, "lessons_per_week");
      const hoursPerSession = metricNumber(itemRecord, "class_hours_per_session");
      const meta = [
        lessonsPerWeek !== null ? `每周 ${formatCount(lessonsPerWeek)} 次` : "",
        hoursPerSession !== null ? `每次 ${formatScore(hoursPerSession)} 课时` : "",
      ]
        .filter(Boolean)
        .join(" · ");
      return [{ subject, subjectCode: record.subject_code, text: text || meta || "暂无安排摘要。", meta }];
    });
  });
}

function mergeTimePlanRows(rows: Array<{ subject: string; subjectCode: string; text: string; meta?: string }>) {
  const rowMap = new Map<string, { subject: string; subjectCode: string; text: string; meta?: string }>();

  rows.forEach((row) => {
    const key = row.subjectCode || row.subject;
    const existing = rowMap.get(key);
    if (!existing) {
      rowMap.set(key, row);
      return;
    }

    const textItems = uniqueItems([existing.text, row.text], 3);
    rowMap.set(key, {
      ...existing,
      meta: existing.meta || row.meta,
      text: textItems.join("；"),
    });
  });

  return [...rowMap.values()];
}

function StudentProfileReport({ records, summary }: { records: LearnerProfileRecord[]; summary?: string | null }) {
  const studentName = uniqueItems(records.map((record) => record.student_name || "").filter(Boolean), 1)[0] ?? "学生";
  const scores = records.map(scoreFromRecord).filter((value): value is number => value !== null);
  const highestScore = scores.length ? Math.max(...scores) : null;
  const improvementTag = uniqueItems(records.flatMap((record) => tagsFromRecord(record.weakness_tags_json)), 1)[0] ?? "待补充";
  const subjectCount = new Set(records.map((record) => record.subject_code).filter(Boolean)).size;
  const profileSummary = summary || records.map((record) => record.summary_text).find(Boolean) || "学生画像摘要暂未返回。";

  return (
    <section className="space-y-5">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-[28px] font-semibold leading-tight text-ink">学情信息分析</h1>
          <p className="mt-2 text-sm leading-6 text-ink/45">基于学生成绩、能力标签与课时规划生成的个体学习画像。</p>
        </div>
      </div>

      <div className="space-y-4">
        <StudentHeroPanel
          highestScore={highestScore}
          improvementTag={improvementTag}
          studentName={studentName}
          subjectCount={subjectCount}
          summary={profileSummary}
        />
        <StudentPerformancePanel records={records} />
        <StudentFeaturePanel records={records} />
      </div>
    </section>
  );
}

export function LearnerProfileReportPage() {
  const projectId = toNumberId(useParams().projectId);
  const batchId = toNumberId(useParams().batchId);
  const profileVersionId = toNumberId(useParams().profileVersionId);

  const profileQuery = useQuery({
    queryKey: ["learner-profile-version-detail", profileVersionId],
    queryFn: () => api.getLearnerProfileVersion(profileVersionId),
    enabled: profileVersionId > 0,
  });

  const profile = profileQuery.data;
  const raw = valueAsRecord(profile?.raw_result_json);
  const records = profile?.records ?? [];
  const classProfile = classProfileFrom(raw, profile?.class_profile);
  const studentCount = learnerStudentCount(raw, classProfile, records);
  const backTo = batchId ? `/projects/${projectId}/batches/${batchId}` : `/projects/${projectId}`;

  if (projectId <= 0 || profileVersionId <= 0) {
    return <EmptyState title="地址无效" action={<Link className="btn btn-secondary" to="/history">返回备课记录</Link>} />;
  }

  if (profileQuery.isLoading) {
    return (
      <div className="flex h-[70vh] items-center justify-center text-sm text-ink/55">
        <Loader2 className="mr-2 animate-spin" size={17} />
        加载中
      </div>
    );
  }

  if (profileQuery.error) {
    return <ErrorNotice title="学情画像加载失败" message={getErrorMessage(profileQuery.error)} />;
  }

  if (!profile) {
    return <EmptyState title="没有找到学情画像" action={<Link className="btn btn-secondary" to={backTo}>返回备课资源</Link>} />;
  }

  return (
    <div className="mx-auto w-full max-w-[1500px] pb-10 pt-6 text-ink">
      {classProfile && (studentCount ?? 0) > 1 ? (
        <ClassProfileReport classProfile={classProfile} raw={raw} records={records} />
      ) : records.length ? (
        <StudentProfileReport records={records} summary={profile.summary_text} />
      ) : (
        <EmptyState title="画像详情同步中" description="学情版本已创建，结构化记录仍在同步。" />
      )}
    </div>
  );
}
