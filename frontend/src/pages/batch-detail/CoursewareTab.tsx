import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Download, MessageSquareReply, Plus, Presentation, RefreshCw } from "lucide-react";
import { EmptyState } from "../../components/EmptyState";
import { ErrorNotice } from "../../components/ErrorNotice";
import { JsonViewer } from "../../components/JsonViewer";
import { StatusBadge } from "../../components/StatusBadge";
import { isTaskActiveStatus } from "../../hooks/useTaskPolling";
import { api } from "../../lib/api";
import type { CoursewareResult, GenerationBatch, LessonPlan, Task } from "../../types";
import { cn, formatDate, getErrorMessage } from "../../utils";
import { asRecord } from "./helpers";
import { KeyValueGrid, LoadingBlock, SectionBlock, StatCard, TaskSummaryCard } from "./shared";

function getTextField(record: Record<string, unknown> | null, key: string) {
  const value = record?.[key];
  return typeof value === "string" && value.trim() ? value.trim() : "";
}

function getPreview(result?: CoursewareResult) {
  const preview = asRecord(result?.preview_json);
  return {
    raw: preview,
    jobId: getTextField(preview, "raccoon_job_id"),
    status: getTextField(preview, "raccoon_status"),
    requiredInput: getTextField(preview, "required_user_input"),
    errorMessage: getTextField(preview, "error_message"),
    refreshedAt: getTextField(preview, "refreshed_at"),
  };
}

function getLessonLabel(lesson?: LessonPlan) {
  if (!lesson) {
    return "请选择教案";
  }
  return `第 ${lesson.class_session_no ?? "-"} 课 / ${lesson.lesson_title}`;
}

function CoursewareDetail({ result, lesson }: { result?: CoursewareResult; lesson?: LessonPlan }) {
  if (!result) {
    return null;
  }

  const preview = getPreview(result);
  const structure = asRecord(result.structure_json);
  const promptSummary = asRecord(structure?.prompt_summary);
  const raccoonJob = asRecord(structure?.raccoon_job);

  return (
    <div className="space-y-5">
      <section className="rounded-md border border-line bg-paper/60 p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="label">课件 #{result.id}</div>
            <h2 className="mt-1 break-words text-xl font-bold text-ink">{lesson?.lesson_title ?? `教案 #${result.lesson_plan_id}`}</h2>
            <p className="mt-2 text-sm text-ink/55">
              教案 #{result.lesson_plan_id} / {formatDate(result.updated_at)}
            </p>
          </div>
          <StatusBadge status={result.result_status} />
        </div>
        <div className="mt-4 grid gap-3 md:grid-cols-3">
          <StatCard label="页数" value={result.page_count ?? "-"} />
          <StatCard label="模板" value={result.template_code ?? "-"} />
          <StatCard label="导出文件" value={result.export_file_id ? `#${result.export_file_id}` : "等待 PPTX 归档"} />
        </div>
      </section>

      <div className="grid gap-4 xl:grid-cols-2">
        <SectionBlock title="Raccoon 状态">
          <KeyValueGrid
            record={{
              raccoon_job_id: preview.jobId || "-",
              raccoon_status: preview.status || "-",
              refreshed_at: preview.refreshedAt || "-",
              error_message: preview.errorMessage || "-",
            }}
          />
        </SectionBlock>
        <SectionBlock title="页面类型统计">
          <KeyValueGrid record={asRecord(result.page_type_stats_json)} />
        </SectionBlock>
      </div>

      {preview.requiredInput ? (
        <section className="rounded-md border border-amber-200 bg-amber-50 p-4">
          <div className="text-sm font-bold text-amber-800">Raccoon 需要补充信息</div>
          <p className="mt-2 whitespace-pre-wrap break-words text-sm leading-6 text-amber-900">{preview.requiredInput}</p>
        </section>
      ) : null}

      <div className="grid gap-4 xl:grid-cols-2">
        <SectionBlock title="生成摘要">
          <KeyValueGrid record={promptSummary} />
        </SectionBlock>
        <SectionBlock title="远程任务摘要">
          <KeyValueGrid record={raccoonJob} />
        </SectionBlock>
      </div>

      <JsonViewer title="preview_json" value={result.preview_json} />
      <JsonViewer title="structure_json" value={result.structure_json} />
    </div>
  );
}

export function CoursewareTab({
  batch,
  lessons,
  selectedLessonId,
  selectedLesson,
  onSelectLesson,
  task,
  results,
  selectedResultId,
  onSelectResult,
  result,
  listLoading,
  detailLoading,
  listError,
  detailError,
}: {
  batch: GenerationBatch;
  lessons: LessonPlan[];
  selectedLessonId: number | null;
  selectedLesson?: LessonPlan;
  onSelectLesson: (id: number) => void;
  task?: Task;
  results: CoursewareResult[];
  selectedResultId: number | null;
  onSelectResult: (id: number | null) => void;
  result?: CoursewareResult;
  listLoading: boolean;
  detailLoading: boolean;
  listError: unknown;
  detailError: unknown;
}) {
  const queryClient = useQueryClient();
  const [replyText, setReplyText] = useState("");
  const selectedLessonResult = selectedLessonId ? results.find((item) => item.lesson_plan_id === selectedLessonId) : undefined;
  const activeTask = isTaskActiveStatus(task?.task_status);
  const preview = getPreview(result);

  const invalidateCourseware = () => {
    queryClient.invalidateQueries({ queryKey: ["generation-batch", batch.id] });
    queryClient.invalidateQueries({ queryKey: ["courseware-results", batch.id] });
    if (result) {
      queryClient.invalidateQueries({ queryKey: ["courseware-result", result.id] });
    }
  };

  const createMutation = useMutation({
    mutationFn: () => {
      if (!selectedLesson) {
        throw new Error("缺少选中的教案");
      }
      return api.createCoursewareTask(selectedLesson.id);
    },
    onSuccess: invalidateCourseware,
  });

  const refreshMutation = useMutation({
    mutationFn: () => {
      if (!result) {
        throw new Error("缺少课件结果");
      }
      return api.refreshCoursewareResult(result.id);
    },
    onSuccess: invalidateCourseware,
  });

  const replyMutation = useMutation({
    mutationFn: () => {
      if (!result) {
        throw new Error("缺少课件结果");
      }
      const answer = replyText.trim();
      if (!answer) {
        throw new Error("请输入补充回答");
      }
      return api.replyCoursewareResult(result.id, { answer });
    },
    onSuccess: () => {
      setReplyText("");
      invalidateCourseware();
    },
  });

  const downloadMutation = useMutation({
    mutationFn: async () => {
      if (!result?.export_file_id) {
        throw new Error("课件尚未归档 PPTX 文件");
      }
      const download = await api.getFileDownloadUrl(result.export_file_id);
      if (!download.signed_url) {
        throw new Error("后端未返回有效下载地址");
      }
      return download;
    },
    onSuccess: (download) => {
      window.open(download.signed_url!, "_blank", "noopener,noreferrer");
    },
  });

  const createDisabledReason = !lessons.length
    ? "需要先生成至少一份教案"
    : !selectedLesson
      ? "请选择教案"
      : selectedLesson.version_status !== "ready"
        ? "当前教案尚未 ready"
        : activeTask
          ? "当前教案课件任务运行中"
          : selectedLessonResult
            ? "当前教案已存在课件结果"
            : createMutation.isPending
              ? "正在创建课件任务"
              : null;

  const canRefresh = result?.result_status === "processing";
  const canReply = Boolean(result && preview.requiredInput);
  const canDownload = Boolean(result?.export_file_id);

  return (
    <div className="space-y-5">
      <TaskSummaryCard title={selectedLesson ? `课件任务：第 ${selectedLesson.class_session_no ?? "-"} 课` : "课件任务"} task={task} />

      <section className="rounded-md border border-line bg-paper/60 p-5">
        <div className="flex flex-col justify-between gap-4 xl:flex-row xl:items-center">
          <div className="min-w-0">
            <div className="label">当前教案</div>
            <h3 className="mt-1 break-words text-lg font-bold text-ink">{getLessonLabel(selectedLesson)}</h3>
            <p className="mt-2 text-sm leading-6 text-ink/55">课件由当前选中的 ready 教案生成，生成结果会绑定到这个教案。</p>
          </div>
          <button className="btn btn-primary" disabled={Boolean(createDisabledReason)} onClick={() => createMutation.mutate()} type="button">
            <Plus size={16} />
            生成课件
          </button>
        </div>
        {createDisabledReason ? <div className="mt-3 text-xs font-semibold text-ink/45">{createDisabledReason}</div> : null}
        {createMutation.error ? <ErrorNotice title="课件任务创建失败" message={getErrorMessage(createMutation.error)} /> : null}
      </section>

      {listLoading ? <LoadingBlock text="加载课件结果" /> : null}
      {listError ? <ErrorNotice title="课件列表获取失败" message={getErrorMessage(listError)} /> : null}

      <div className="grid gap-5 xl:grid-cols-[300px_1fr]">
        <aside className="space-y-5">
          <section className="space-y-2">
            <div className="label">教案列表</div>
            {lessons.length ? (
              <div className="divide-y divide-line rounded-md border border-line">
                {lessons.map((lesson) => {
                  const lessonResult = results.find((item) => item.lesson_plan_id === lesson.id);
                  return (
                    <button
                      className={cn(
                        "flex w-full items-center justify-between gap-3 bg-white px-4 py-3 text-left transition hover:bg-paper",
                        selectedLessonId === lesson.id && "bg-accent/10",
                      )}
                      key={lesson.id}
                      onClick={() => onSelectLesson(lesson.id)}
                      type="button"
                    >
                      <div className="min-w-0">
                        <div className="truncate text-sm font-bold">{lesson.lesson_title}</div>
                        <div className="mt-1 text-xs text-ink/50">第 {lesson.class_session_no ?? "-"} 课</div>
                      </div>
                      {lessonResult ? <StatusBadge status={lessonResult.result_status} /> : <span className="text-xs font-semibold text-ink/35">未生成</span>}
                    </button>
                  );
                })}
              </div>
            ) : (
              <EmptyState title="暂无 ready 教案" />
            )}
          </section>

          <section className="space-y-2">
            <div className="label">课件结果列表</div>
            {results.length ? (
              <div className="divide-y divide-line rounded-md border border-line">
                {results.map((item) => {
                  const lesson = lessons.find((entry) => entry.id === item.lesson_plan_id);
                  return (
                    <button
                      className={cn(
                        "flex w-full items-center justify-between gap-3 bg-white px-4 py-3 text-left transition hover:bg-paper",
                        selectedResultId === item.id && "bg-accent/10",
                      )}
                      key={item.id}
                      onClick={() => {
                        onSelectLesson(item.lesson_plan_id);
                        onSelectResult(item.id);
                      }}
                      type="button"
                    >
                      <div className="min-w-0">
                        <div className="truncate text-sm font-bold">课件 #{item.id}</div>
                        <div className="mt-1 text-xs text-ink/50">
                          第 {lesson?.class_session_no ?? "-"} 课 / {formatDate(item.updated_at)}
                        </div>
                      </div>
                      <StatusBadge status={item.result_status} />
                    </button>
                  );
                })}
              </div>
            ) : (
              <EmptyState title={activeTask ? "课件生成中" : "暂未产生课件结果"} />
            )}
          </section>
        </aside>

        <div className="space-y-5">
          {!listLoading && !listError && selectedLesson && !selectedLessonResult ? <EmptyState title="当前教案暂未产生课件结果" /> : null}

          <section className="grid gap-3 md:grid-cols-3">
            <button className="btn btn-secondary" disabled={!canRefresh || refreshMutation.isPending} onClick={() => refreshMutation.mutate()} type="button">
              <RefreshCw className={refreshMutation.isPending ? "animate-spin" : ""} size={16} />
              {refreshMutation.isPending ? "刷新中" : "刷新状态"}
            </button>
            <button className="btn btn-secondary" disabled={!canDownload || downloadMutation.isPending} onClick={() => downloadMutation.mutate()} type="button">
              <Download size={16} />
              {downloadMutation.isPending ? "准备下载" : canDownload ? "下载 PPTX" : "等待 PPTX"}
            </button>
            <div className="flex items-center justify-center gap-2 rounded-md border border-line bg-paper/60 px-3 py-2 text-sm font-semibold text-ink/55">
              <Presentation size={16} />
              {result ? `课件 #${result.id}` : "未选择课件"}
            </div>
          </section>

          {refreshMutation.error ? <ErrorNotice title="课件状态刷新失败" message={getErrorMessage(refreshMutation.error)} /> : null}
          {downloadMutation.error ? <ErrorNotice title="PPTX 下载失败" message={getErrorMessage(downloadMutation.error)} /> : null}

          {canReply ? (
            <form className="rounded-md border border-line bg-paper/60 p-4" onSubmit={(event) => {
              event.preventDefault();
              replyMutation.mutate();
            }}>
              <div className="flex items-center gap-2 text-sm font-bold">
                <MessageSquareReply size={16} />
                回复补充问题
              </div>
              <p className="mt-2 whitespace-pre-wrap break-words text-sm leading-6 text-ink/60">{preview.requiredInput}</p>
              <textarea
                className="mt-3 min-h-24 w-full rounded-md border border-line bg-white px-3 py-2 text-sm outline-none focus:border-accent"
                maxLength={2000}
                onChange={(event) => setReplyText(event.target.value)}
                placeholder="输入给 Raccoon 的补充回答"
                value={replyText}
              />
              <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
                <span className="text-xs font-semibold text-ink/40">{replyText.length}/2000</span>
                <button className="btn btn-primary" disabled={!replyText.trim() || replyMutation.isPending} type="submit">
                  <MessageSquareReply size={16} />
                  {replyMutation.isPending ? "提交中" : "提交回复"}
                </button>
              </div>
              {replyMutation.error ? <ErrorNotice title="课件补充回复失败" message={getErrorMessage(replyMutation.error)} /> : null}
            </form>
          ) : null}

          {detailLoading ? <LoadingBlock text="加载课件详情" /> : null}
          {detailError ? <ErrorNotice title="课件详情获取失败" message={getErrorMessage(detailError)} /> : null}
          <CoursewareDetail result={result} lesson={selectedLesson} />
        </div>
      </div>
    </div>
  );
}
