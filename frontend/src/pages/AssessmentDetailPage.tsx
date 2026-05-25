import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, FileText, Loader2 } from "lucide-react";
import { useParams } from "react-router-dom";
import { api } from "../lib/api";
import type { JsonRecord, PaperResult, QuestionItem } from "../types";
import { cn, formatDate, toNumberId } from "../utils";
import { asRecord, displayValue } from "./batch-detail/helpers";

const questionTypeLabels: Record<string, string> = {
  single_choice: "单选题",
  fill_blank: "填空题",
  short_answer: "简答题",
};

type QuestionRecord = Partial<QuestionItem> & JsonRecord;

function isSuccessfulStatus(status?: string | null) {
  return ["success", "ready", "available", "confirmed"].includes(String(status ?? "").toLowerCase());
}

function getQuestionTypeLabel(value?: unknown) {
  const key = String(value ?? "");
  return questionTypeLabels[key] ?? displayValue(value);
}

function getPaperQuestions(paper?: PaperResult): QuestionRecord[] {
  if (paper?.questions?.length) {
    return paper.questions.map((question) => question as QuestionRecord);
  }
  const paperJson = asRecord(paper?.paper_json);
  const rawQuestions = paperJson?.questions;
  if (!Array.isArray(rawQuestions)) {
    return [];
  }
  return rawQuestions
    .map((question) => asRecord(question))
    .filter((question): question is QuestionRecord => Boolean(question));
}

function getOptions(record: QuestionRecord) {
  const options = asRecord(record.options_json) ?? asRecord(record.options);
  if (!options) {
    return [];
  }
  return Object.entries(options).filter(([, value]) => value !== undefined && value !== null && value !== "");
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

function StatCard({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-2xl border border-line bg-white px-5 py-4">
      <div className="text-xs font-semibold text-ink/45">{label}</div>
      <div className="mt-2 text-2xl font-semibold text-ink">{value}</div>
    </div>
  );
}

function QuestionCard({ question, index }: { question: QuestionRecord; index: number }) {
  const options = getOptions(question);
  const knowledgePointName = typeof question.knowledge_point_name === "string" ? question.knowledge_point_name : "";

  return (
    <article className="rounded-[22px] border border-line bg-white p-6 shadow-panel">
      <div className="flex flex-wrap items-center gap-2">
        <span className="inline-flex h-8 items-center rounded-full bg-ink px-3 text-xs font-semibold text-white">
          第 {displayValue(question.question_no ?? index + 1)} 题
        </span>
        <span className="inline-flex h-8 items-center rounded-full bg-[#f2f2f2] px-3 text-xs font-semibold text-ink/62">
          {getQuestionTypeLabel(question.question_type)}
        </span>
        {question.difficulty_level ? (
          <span className="inline-flex h-8 items-center rounded-full bg-[#f2f2f2] px-3 text-xs font-semibold text-ink/62">
            难度 {displayValue(question.difficulty_level)}
          </span>
        ) : null}
        {knowledgePointName ? (
          <span className="inline-flex h-8 items-center rounded-full bg-[#f2f2f2] px-3 text-xs font-semibold text-ink/62">
            {knowledgePointName}
          </span>
        ) : question.knowledge_point_id ? (
          <span className="inline-flex h-8 items-center rounded-full bg-[#f2f2f2] px-3 text-xs font-semibold text-ink/62">
            已关联知识点
          </span>
        ) : null}
      </div>

      <p className="mt-5 whitespace-pre-wrap break-words text-base font-semibold leading-8 text-ink">
        {displayValue(question.stem_text ?? question.stem)}
      </p>

      {options.length ? (
        <div className="mt-5 grid gap-3 md:grid-cols-2">
          {options.map(([key, value]) => (
            <div className="rounded-2xl border border-line bg-[#fafafa] px-4 py-3 text-sm leading-6 text-ink/70" key={key}>
              <span className="mr-2 font-semibold text-ink">{key}.</span>
              {displayValue(value)}
            </div>
          ))}
        </div>
      ) : null}

      <div className="mt-6 grid gap-4 md:grid-cols-2">
        <section className="rounded-2xl border border-line bg-[#fafafa] p-4">
          <h3 className="text-sm font-semibold text-ink">答案</h3>
          <p className="mt-2 whitespace-pre-wrap break-words text-sm leading-6 text-ink/62">
            {displayValue(question.answer_text ?? question.answer)}
          </p>
        </section>
        <section className="rounded-2xl border border-line bg-[#fafafa] p-4">
          <h3 className="text-sm font-semibold text-ink">解析</h3>
          <p className="mt-2 whitespace-pre-wrap break-words text-sm leading-6 text-ink/62">
            {displayValue(question.analysis_text ?? question.analysis)}
          </p>
        </section>
      </div>
    </article>
  );
}

export function AssessmentDetailPage() {
  const paperResultId = toNumberId(useParams().paperResultId);
  const queryClient = useQueryClient();
  const [typeFilter, setTypeFilter] = useState("");

  const paperQuery = useQuery({
    queryKey: ["paper-result", paperResultId],
    queryFn: () => api.getPaperResult(paperResultId),
    enabled: paperResultId > 0,
  });

  const paper = paperQuery.data;
  const questions = useMemo(() => getPaperQuestions(paper), [paper]);
  const filteredQuestions = typeFilter ? questions.filter((question) => String(question.question_type ?? "") === typeFilter) : questions;
  const typeStats = useMemo(() => {
    return questions.reduce<Record<string, number>>((acc, question) => {
      const key = String(question.question_type ?? "unknown");
      acc[key] = (acc[key] ?? 0) + 1;
      return acc;
    }, {});
  }, [questions]);

  const downloadMutation = useMutation({
    mutationFn: async () => {
      if (!paper) {
        throw new Error("测练暂未准备好");
      }
      const result = paper.export_file_id ? await api.getFileDownloadUrl(paper.export_file_id) : await api.exportPaperResultDocx(paper.id);
      if (!result.signed_url) {
        throw new Error("下载地址暂未准备好");
      }
      return result.signed_url;
    },
    onSuccess: (url) => {
      queryClient.invalidateQueries({ queryKey: ["paper-result", paperResultId] });
      window.open(url, "_blank", "noopener,noreferrer");
    },
  });

  if (paperQuery.isLoading && !paper) {
    return <PageLoading text="正在打开题目" />;
  }

  if (!paper || !isSuccessfulStatus(paper.result_status)) {
    return (
      <div className="mx-auto max-w-[1540px] px-2 pb-10 pt-6">
        <FriendlyNotice title="题目暂未准备好" description="生成完成后，可以在这里查看题目、答案和解析。" />
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-[1540px] space-y-8 px-2 pb-10 pt-6 text-ink">
      <section className="grid gap-4 md:grid-cols-3">
        <StatCard label="题目数量" value={questions.length || paper.question_count || "-"} />
        <StatCard label="题型数量" value={Object.keys(typeStats).length || "-"} />
        <StatCard label="更新时间" value={formatDate(paper.updated_at)} />
      </section>

      <section className="rounded-[22px] border border-line bg-white p-5 shadow-panel">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold text-ink">题目预览</h2>
            <p className="mt-1 text-sm text-ink/45">{paper.title || "按题型筛选查看题干、答案和解析。"}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button className="btn btn-primary h-9 rounded-full" disabled={downloadMutation.isPending} onClick={() => downloadMutation.mutate()} type="button">
              <Download size={15} />
              {downloadMutation.isPending ? "准备下载" : "下载 DOCX"}
            </button>
            <div className="flex flex-wrap gap-2">
              {[
                ["", "全部"],
                ["single_choice", "单选题"],
                ["fill_blank", "填空题"],
                ["short_answer", "简答题"],
              ].map(([value, label]) => (
                <button
                  className={cn(
                    "h-9 rounded-full border px-4 text-sm font-semibold transition",
                    typeFilter === value ? "border-ink bg-ink text-white" : "border-line bg-white text-ink/62 hover:border-ink/28",
                  )}
                  key={value}
                  onClick={() => setTypeFilter(value)}
                  type="button"
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
        </div>
      </section>

      {filteredQuestions.length ? (
        <div className="space-y-4">
          {filteredQuestions.map((question, index) => (
            <QuestionCard question={question} index={index} key={`${question.id ?? question.question_no ?? index}-${index}`} />
          ))}
        </div>
      ) : (
        <FriendlyNotice title="暂无匹配题目" description="可以切换筛选条件查看其它题型。" />
      )}

      {downloadMutation.error ? <FriendlyNotice title="下载暂时没有完成" description="请稍后再试，页面会保留当前题目内容。" /> : null}
    </div>
  );
}
