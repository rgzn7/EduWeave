import { FormEvent, useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowRight,
  BookOpen,
  Brain,
  ChevronLeft,
  FileText,
  Layers,
  Loader2,
  Play,
  Upload,
  Wand2,
} from "lucide-react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { EmptyState } from "../components/EmptyState";
import { StatusBadge } from "../components/StatusBadge";
import { TaskTable } from "../components/TaskTable";
import { api } from "../lib/api";
import type { KnowledgeVersion, LearnerProfileVersion, ParseVersion, TextbookVersion } from "../types";
import { firstValue, formatDate } from "../utils";

function toId(value: string | undefined) {
  const id = Number(value);
  return Number.isFinite(id) ? id : 0;
}

function latestById<T extends { id: number }>(items: T[] | undefined) {
  return [...(items ?? [])].sort((a, b) => b.id - a.id)[0];
}

function SelectRow<T extends { id: number }>({
  items,
  selectedId,
  onChange,
  renderLabel,
}: {
  items: T[];
  selectedId: number | null;
  onChange: (id: number) => void;
  renderLabel: (item: T) => string;
}) {
  if (!items.length) {
    return null;
  }
  return (
    <select className="field" value={selectedId ?? ""} onChange={(event) => onChange(Number(event.target.value))}>
      {items.map((item) => (
        <option key={item.id} value={item.id}>
          {renderLabel(item)}
        </option>
      ))}
    </select>
  );
}

function VersionList<T extends { id: number; version_no?: number; created_at: string; updated_at: string }>({
  items,
  title,
  selectedId,
  onSelect,
  renderStatus,
  renderMeta,
}: {
  items: T[];
  title: string;
  selectedId: number | null;
  onSelect: (id: number) => void;
  renderStatus: (item: T) => string;
  renderMeta?: (item: T) => string;
}) {
  if (!items.length) {
    return <EmptyState title={`暂无${title}`} />;
  }
  return (
    <div className="divide-y divide-line rounded-md border border-line">
      {items.map((item) => (
        <button
          className={`flex w-full items-center justify-between gap-3 px-4 py-3 text-left transition hover:bg-paper ${
            selectedId === item.id ? "bg-accent/10" : "bg-white"
          }`}
          key={item.id}
          onClick={() => onSelect(item.id)}
          type="button"
        >
          <div>
            <div className="text-sm font-bold">
              {title} #{item.version_no ?? item.id}
            </div>
            <div className="mt-1 text-xs text-ink/50">{renderMeta?.(item) ?? formatDate(item.updated_at)}</div>
          </div>
          <StatusBadge status={renderStatus(item)} />
        </button>
      ))}
    </div>
  );
}

export function ProjectWorkspacePage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const projectId = toId(useParams().projectId);
  const [textbookFile, setTextbookFile] = useState<File | null>(null);
  const [textbookName, setTextbookName] = useState("");
  const [profileFile, setProfileFile] = useState<File | null>(null);
  const [profileTitle, setProfileTitle] = useState("");
  const [batchName, setBatchName] = useState("第一轮课程规划");
  const [courseCount, setCourseCount] = useState(12);
  const [duration, setDuration] = useState(90);
  const [selectedTextbookId, setSelectedTextbookId] = useState<number | null>(null);
  const [selectedProfileFileId, setSelectedProfileFileId] = useState<number | null>(null);
  const [selectedProfileVersionId, setSelectedProfileVersionId] = useState<number | null>(null);
  const [selectedParseVersionId, setSelectedParseVersionId] = useState<number | null>(null);
  const [selectedKnowledgeVersionId, setSelectedKnowledgeVersionId] = useState<number | null>(null);

  const projectQuery = useQuery({
    queryKey: ["project", projectId],
    queryFn: () => api.getProject(projectId),
    enabled: projectId > 0,
  });

  const dashboardQuery = useQuery({
    queryKey: ["project-dashboard", projectId],
    queryFn: () => api.getProjectDashboard(projectId),
    enabled: projectId > 0,
    refetchInterval: 10_000,
  });

  const textbooksQuery = useQuery({
    queryKey: ["textbooks", projectId],
    queryFn: () => api.listTextbooks(projectId),
    enabled: projectId > 0,
  });

  const learnerProfilesQuery = useQuery({
    queryKey: ["learner-profiles", projectId],
    queryFn: () => api.listLearnerProfiles(projectId),
    enabled: projectId > 0,
  });

  const parseVersionsQuery = useQuery({
    queryKey: ["parse-versions", selectedTextbookId],
    queryFn: () => api.listParseVersions(selectedTextbookId!),
    enabled: Boolean(selectedTextbookId),
    refetchInterval: 8_000,
  });

  const profileVersionsQuery = useQuery({
    queryKey: ["learner-profile-versions", projectId, selectedProfileFileId],
    queryFn: () => api.listLearnerProfileVersions(projectId, selectedProfileFileId!),
    enabled: Boolean(projectId && selectedProfileFileId),
    refetchInterval: 8_000,
  });

  const knowledgeVersionsQuery = useQuery({
    queryKey: ["knowledge-versions", selectedParseVersionId],
    queryFn: () => api.listKnowledgeVersions(selectedParseVersionId!),
    enabled: Boolean(selectedParseVersionId),
    refetchInterval: 8_000,
  });

  const generationBatchesQuery = useQuery({
    queryKey: ["generation-batches", projectId],
    queryFn: () => api.listGenerationBatches(projectId),
    enabled: projectId > 0,
    refetchInterval: 8_000,
  });

  const tasksQuery = useQuery({
    queryKey: ["tasks", projectId],
    queryFn: () => api.listTasks({ project_id: projectId, page: 1, page_size: 12 }),
    enabled: projectId > 0,
    refetchInterval: 5_000,
  });

  const textbooks = textbooksQuery.data?.items ?? [];
  const learnerProfiles = learnerProfilesQuery.data?.items ?? [];
  const parseVersions = parseVersionsQuery.data?.items ?? [];
  const profileVersions = profileVersionsQuery.data?.items ?? [];
  const knowledgeVersions = knowledgeVersionsQuery.data?.items ?? [];
  const generationBatches = generationBatchesQuery.data?.items ?? [];

  useEffect(() => {
    if (!selectedTextbookId) {
      const current = textbooks.find((item) => item.is_current) ?? latestById(textbooks);
      if (current) {
        setSelectedTextbookId(current.id);
      }
    }
  }, [selectedTextbookId, textbooks]);

  useEffect(() => {
    if (!selectedProfileFileId) {
      const current = latestById(learnerProfiles);
      if (current) {
        setSelectedProfileFileId(current.id);
      }
    }
  }, [learnerProfiles, selectedProfileFileId]);

  useEffect(() => {
    const latest = latestById(parseVersions);
    if (latest && !selectedParseVersionId) {
      setSelectedParseVersionId(latest.id);
    }
  }, [parseVersions, selectedParseVersionId]);

  useEffect(() => {
    const latest = latestById(profileVersions);
    if (latest && !selectedProfileVersionId) {
      setSelectedProfileVersionId(latest.id);
    }
  }, [profileVersions, selectedProfileVersionId]);

  useEffect(() => {
    const latest = latestById(knowledgeVersions);
    if (latest && !selectedKnowledgeVersionId) {
      setSelectedKnowledgeVersionId(latest.id);
    }
  }, [knowledgeVersions, selectedKnowledgeVersionId]);

  const selectedTextbook = useMemo(
    () => textbooks.find((item) => item.id === selectedTextbookId) ?? latestById(textbooks),
    [selectedTextbookId, textbooks],
  );
  const selectedParseVersion = useMemo(
    () => parseVersions.find((item) => item.id === selectedParseVersionId) ?? latestById(parseVersions),
    [parseVersions, selectedParseVersionId],
  );
  const selectedProfileVersion = useMemo(
    () => profileVersions.find((item) => item.id === selectedProfileVersionId) ?? latestById(profileVersions),
    [profileVersions, selectedProfileVersionId],
  );
  const selectedKnowledgeVersion = useMemo(
    () => knowledgeVersions.find((item) => item.id === selectedKnowledgeVersionId) ?? latestById(knowledgeVersions),
    [knowledgeVersions, selectedKnowledgeVersionId],
  );

  const invalidateWorkspace = () => {
    queryClient.invalidateQueries({ queryKey: ["project", projectId] });
    queryClient.invalidateQueries({ queryKey: ["project-dashboard", projectId] });
    queryClient.invalidateQueries({ queryKey: ["textbooks", projectId] });
    queryClient.invalidateQueries({ queryKey: ["learner-profiles", projectId] });
    queryClient.invalidateQueries({ queryKey: ["tasks", projectId] });
    queryClient.invalidateQueries({ queryKey: ["generation-batches", projectId] });
    if (selectedTextbookId) {
      queryClient.invalidateQueries({ queryKey: ["parse-versions", selectedTextbookId] });
    }
    if (selectedParseVersionId) {
      queryClient.invalidateQueries({ queryKey: ["knowledge-versions", selectedParseVersionId] });
    }
    if (selectedProfileFileId) {
      queryClient.invalidateQueries({ queryKey: ["learner-profile-versions", projectId, selectedProfileFileId] });
    }
  };

  const uploadTextbook = useMutation({
    mutationFn: () =>
      api.uploadTextbook(projectId, {
        file: textbookFile!,
        textbook_name: textbookName || textbookFile?.name,
        set_as_current: true,
      }),
    onSuccess: (textbook) => {
      setTextbookFile(null);
      setTextbookName("");
      setSelectedTextbookId(textbook.id);
      invalidateWorkspace();
    },
  });

  const createParseTask = useMutation({
    mutationFn: () => api.createParseTask(selectedTextbook!.id),
    onSuccess: invalidateWorkspace,
  });

  const confirmParseVersion = useMutation({
    mutationFn: () => api.confirmParseVersion(selectedParseVersion!.id),
    onSuccess: invalidateWorkspace,
  });

  const uploadProfile = useMutation({
    mutationFn: () =>
      api.uploadLearnerProfile(projectId, {
        file: profileFile!,
        title: profileTitle || profileFile?.name,
        auto_extract: true,
        set_as_current: true,
      }),
    onSuccess: (profile) => {
      setProfileFile(null);
      setProfileTitle("");
      setSelectedProfileFileId(profile.id);
      invalidateWorkspace();
    },
  });

  const createKnowledgeTask = useMutation({
    mutationFn: () => api.createKnowledgeTask(selectedParseVersion!.id),
    onSuccess: invalidateWorkspace,
  });

  const createBatch = useMutation({
    mutationFn: () =>
      api.createGenerationBatch({
        project_id: projectId,
        knowledge_version_id: selectedKnowledgeVersion!.id,
        learner_profile_version_id: selectedProfileVersion!.id,
        batch_name: batchName,
        course_count: courseCount,
        session_duration_minutes: duration,
      }),
    onSuccess: (batch) => {
      invalidateWorkspace();
      navigate(`/projects/${projectId}/batches/${batch.id}`);
    },
  });

  function handleTextbookSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (textbookFile) {
      uploadTextbook.mutate();
    }
  }

  function handleProfileSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (profileFile) {
      uploadProfile.mutate();
    }
  }

  function handleBatchSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (selectedKnowledgeVersion && selectedProfileVersion) {
      createBatch.mutate();
    }
  }

  const stats = dashboardQuery.data?.stats ?? {};
  const statEntries = Object.entries(stats).slice(0, 4);
  const latestTask = firstValue(tasksQuery.data?.items);

  if (projectQuery.isLoading) {
    return (
      <div className="flex h-[60vh] items-center justify-center text-sm text-ink/55">
        <Loader2 className="mr-2 animate-spin" size={17} />
        加载中
      </div>
    );
  }

  if (!projectQuery.data) {
    return <EmptyState title="项目不存在" action={<Link className="btn btn-secondary" to="/">返回总览</Link>} />;
  }

  return (
    <div className="space-y-6">
      <section className="flex flex-col justify-between gap-4 xl:flex-row xl:items-end">
        <div>
          <Link className="mb-4 inline-flex items-center gap-2 text-sm font-semibold text-ink/55 hover:text-ink" to="/">
            <ChevronLeft size={16} />
            项目总览
          </Link>
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-3xl font-bold">{projectQuery.data.name}</h1>
            <StatusBadge status={projectQuery.data.status} />
          </div>
          <div className="mt-2 flex flex-wrap gap-2 text-sm text-ink/55">
            <span>{projectQuery.data.subject_code}</span>
            <span>/</span>
            <span>{projectQuery.data.grade_code}</span>
            <span>/</span>
            <span>{formatDate(projectQuery.data.updated_at)}</span>
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {statEntries.length ? (
            statEntries.map(([key, value]) => (
              <div className="min-w-32 rounded-lg border border-line bg-white px-4 py-3" key={key}>
                <div className="label">{key}</div>
                <div className="mt-1 text-xl font-bold">{String(value ?? "-")}</div>
              </div>
            ))
          ) : (
            <div className="rounded-lg border border-line bg-white px-4 py-3">
              <div className="label">最近任务</div>
              <div className="mt-1 text-xl font-bold">{latestTask ? latestTask.task_status : "-"}</div>
            </div>
          )}
        </div>
      </section>

      <section className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_380px]">
        <div className="space-y-6">
          <div className="grid gap-6 2xl:grid-cols-2">
            <form className="panel overflow-hidden" onSubmit={handleTextbookSubmit}>
              <div className="panel-header">
                <div className="flex items-center gap-3">
                  <div className="flex h-10 w-10 items-center justify-center rounded-md bg-accent/10 text-accent">
                    <BookOpen size={20} />
                  </div>
                  <div>
                    <h2 className="text-lg font-bold">教材</h2>
                    <div className="text-sm text-ink/55">{selectedTextbook?.textbook_name ?? "未上传"}</div>
                  </div>
                </div>
              </div>
              <div className="space-y-4 p-5">
                <input className="field" placeholder="教材名称" value={textbookName} onChange={(event) => setTextbookName(event.target.value)} />
                <input
                  className="file-field"
                  type="file"
                  accept="application/pdf,.pdf"
                  onChange={(event) => setTextbookFile(event.target.files?.[0] ?? null)}
                />
                {uploadTextbook.error ? <div className="text-sm font-semibold text-coral">{uploadTextbook.error.message}</div> : null}
                <button className="btn btn-primary w-full" disabled={!textbookFile || uploadTextbook.isPending} type="submit">
                  {uploadTextbook.isPending ? <Loader2 className="animate-spin" size={17} /> : <Upload size={17} />}
                  上传教材
                </button>
                <SelectRow<TextbookVersion>
                  items={textbooks}
                  selectedId={selectedTextbookId}
                  onChange={(id) => {
                    setSelectedTextbookId(id);
                    setSelectedParseVersionId(null);
                    setSelectedKnowledgeVersionId(null);
                  }}
                  renderLabel={(item) => `v${item.version_no} ${item.textbook_name}`}
                />
                <button
                  className="btn btn-secondary w-full"
                  disabled={!selectedTextbook || createParseTask.isPending}
                  onClick={() => createParseTask.mutate()}
                  type="button"
                >
                  {createParseTask.isPending ? <Loader2 className="animate-spin" size={17} /> : <Play size={17} />}
                  发起解析
                </button>
              </div>
            </form>

            <form className="panel overflow-hidden" onSubmit={handleProfileSubmit}>
              <div className="panel-header">
                <div className="flex items-center gap-3">
                  <div className="flex h-10 w-10 items-center justify-center rounded-md bg-coral/10 text-coral">
                    <FileText size={20} />
                  </div>
                  <div>
                    <h2 className="text-lg font-bold">学情</h2>
                    <div className="text-sm text-ink/55">{selectedProfileVersion ? `v${selectedProfileVersion.version_no}` : "未上传"}</div>
                  </div>
                </div>
              </div>
              <div className="space-y-4 p-5">
                <input className="field" placeholder="学情标题" value={profileTitle} onChange={(event) => setProfileTitle(event.target.value)} />
                <input
                  className="file-field"
                  type="file"
                  accept=".doc,.docx,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                  onChange={(event) => setProfileFile(event.target.files?.[0] ?? null)}
                />
                {uploadProfile.error ? <div className="text-sm font-semibold text-coral">{uploadProfile.error.message}</div> : null}
                <button className="btn btn-primary w-full" disabled={!profileFile || uploadProfile.isPending} type="submit">
                  {uploadProfile.isPending ? <Loader2 className="animate-spin" size={17} /> : <Upload size={17} />}
                  上传学情
                </button>
                <SelectRow
                  items={learnerProfiles}
                  selectedId={selectedProfileFileId}
                  onChange={(id) => {
                    setSelectedProfileFileId(id);
                    setSelectedProfileVersionId(null);
                  }}
                  renderLabel={(item) => `${item.id} ${item.title}`}
                />
              </div>
            </form>
          </div>

          <div className="grid gap-6 2xl:grid-cols-2">
            <section className="panel overflow-hidden">
              <div className="panel-header">
                <div className="flex items-center gap-3">
                  <div className="flex h-10 w-10 items-center justify-center rounded-md bg-gold/10 text-gold">
                    <Layers size={20} />
                  </div>
                  <div>
                    <h2 className="text-lg font-bold">解析版本</h2>
                    <div className="text-sm text-ink/55">{parseVersions.length} 个版本</div>
                  </div>
                </div>
                <button
                  className="btn btn-secondary"
                  disabled={!selectedParseVersion || confirmParseVersion.isPending}
                  onClick={() => confirmParseVersion.mutate()}
                  type="button"
                >
                  {confirmParseVersion.isPending ? <Loader2 className="animate-spin" size={17} /> : null}
                  确认
                </button>
              </div>
              <div className="p-5">
                <VersionList<ParseVersion>
                  items={parseVersions}
                  title="解析"
                  selectedId={selectedParseVersionId}
                  onSelect={(id) => {
                    setSelectedParseVersionId(id);
                    setSelectedKnowledgeVersionId(null);
                  }}
                  renderStatus={(item) => item.review_status || item.parse_status}
                  renderMeta={(item) => `${item.strategy_code} / ${item.page_count ?? "-"} 页 / ${formatDate(item.updated_at)}`}
                />
              </div>
            </section>

            <section className="panel overflow-hidden">
              <div className="panel-header">
                <div className="flex items-center gap-3">
                  <div className="flex h-10 w-10 items-center justify-center rounded-md bg-leaf/10 text-leaf">
                    <Brain size={20} />
                  </div>
                  <div>
                    <h2 className="text-lg font-bold">知识结构</h2>
                    <div className="text-sm text-ink/55">{selectedKnowledgeVersion ? `${selectedKnowledgeVersion.point_count} 个知识点` : "未生成"}</div>
                  </div>
                </div>
                <button
                  className="btn btn-secondary"
                  disabled={!selectedParseVersion || createKnowledgeTask.isPending}
                  onClick={() => createKnowledgeTask.mutate()}
                  type="button"
                >
                  {createKnowledgeTask.isPending ? <Loader2 className="animate-spin" size={17} /> : <Wand2 size={17} />}
                  抽取
                </button>
              </div>
              <div className="p-5">
                <VersionList<KnowledgeVersion>
                  items={knowledgeVersions}
                  title="知识"
                  selectedId={selectedKnowledgeVersionId}
                  onSelect={setSelectedKnowledgeVersionId}
                  renderStatus={(item) => item.version_status}
                  renderMeta={(item) => `${item.chapter_count} 章 / ${item.point_count} 点 / ${formatDate(item.updated_at)}`}
                />
              </div>
            </section>
          </div>

          <section className="panel overflow-hidden">
            <div className="panel-header">
              <div className="flex items-center gap-3">
                  <div className="flex h-10 w-10 items-center justify-center rounded-md bg-ink/10 text-ink">
                  <Wand2 size={20} />
                </div>
                <div>
                  <h2 className="text-lg font-bold">生成批次</h2>
                  <div className="text-sm text-ink/55">{generationBatches.length} 个批次</div>
                </div>
              </div>
            </div>
            <div className="grid gap-5 p-5 xl:grid-cols-[340px_1fr]">
              <form className="space-y-4" onSubmit={handleBatchSubmit}>
                <label className="block">
                  <span className="label">批次名称</span>
                  <input className="field mt-2" value={batchName} onChange={(event) => setBatchName(event.target.value)} />
                </label>
                <div className="grid grid-cols-2 gap-3">
                  <label className="block">
                    <span className="label">课次</span>
                    <input
                      className="field mt-2"
                      min={1}
                      type="number"
                      value={courseCount}
                      onChange={(event) => setCourseCount(Number(event.target.value))}
                    />
                  </label>
                  <label className="block">
                    <span className="label">分钟</span>
                    <input
                      className="field mt-2"
                      min={1}
                      type="number"
                      value={duration}
                      onChange={(event) => setDuration(Number(event.target.value))}
                    />
                  </label>
                </div>
                <button
                  className="btn btn-primary w-full"
                  disabled={!selectedKnowledgeVersion || !selectedProfileVersion || createBatch.isPending}
                  type="submit"
                >
                  {createBatch.isPending ? <Loader2 className="animate-spin" size={17} /> : <Play size={17} />}
                  创建批次
                </button>
                {createBatch.error ? <div className="text-sm font-semibold text-coral">{createBatch.error.message}</div> : null}
              </form>
              {generationBatches.length ? (
                <div className="divide-y divide-line rounded-md border border-line">
                  {generationBatches.map((batch) => (
                    <Link
                      className="flex flex-col gap-3 bg-white px-4 py-3 transition hover:bg-paper md:flex-row md:items-center md:justify-between"
                      key={batch.id}
                      to={`/projects/${projectId}/batches/${batch.id}`}
                    >
                      <div>
                        <div className="text-sm font-bold">{batch.batch_name ?? `批次 #${batch.batch_no}`}</div>
                        <div className="mt-1 text-xs text-ink/50">
                          {batch.course_count ?? "-"} 课次 / {batch.session_duration_minutes ?? "-"} 分钟 / {formatDate(batch.updated_at)}
                        </div>
                      </div>
                      <div className="flex items-center gap-3">
                        <StatusBadge status={batch.batch_status} />
                        <ArrowRight className="text-ink/35" size={16} />
                      </div>
                    </Link>
                  ))}
                </div>
              ) : (
                <EmptyState title="暂无生成批次" />
              )}
            </div>
          </section>
        </div>

        <aside className="space-y-6">
          <section className="panel overflow-hidden">
            <div className="panel-header">
              <div>
                <h2 className="text-lg font-bold">学情版本</h2>
                <div className="text-sm text-ink/55">{profileVersions.length} 个版本</div>
              </div>
            </div>
            <div className="p-5">
              <VersionList<LearnerProfileVersion>
                items={profileVersions}
                title="学情"
                selectedId={selectedProfileVersionId}
                onSelect={setSelectedProfileVersionId}
                renderStatus={(item) => item.review_status || item.extract_status}
                renderMeta={(item) => `${item.subject_scope ?? "-"} / ${formatDate(item.updated_at)}`}
              />
            </div>
          </section>

          <section className="panel overflow-hidden">
            <div className="panel-header">
              <div>
                <h2 className="text-lg font-bold">基线</h2>
                <div className="text-sm text-ink/55">当前选择</div>
              </div>
            </div>
            <div className="space-y-3 p-5 text-sm">
              <div className="flex items-center justify-between border-b border-line pb-3">
                <span className="text-ink/55">教材</span>
                <strong className="max-w-48 truncate">{selectedTextbook?.textbook_name ?? "-"}</strong>
              </div>
              <div className="flex items-center justify-between border-b border-line pb-3">
                <span className="text-ink/55">解析</span>
                <strong>{selectedParseVersion ? `#${selectedParseVersion.id}` : "-"}</strong>
              </div>
              <div className="flex items-center justify-between border-b border-line pb-3">
                <span className="text-ink/55">学情</span>
                <strong>{selectedProfileVersion ? `#${selectedProfileVersion.id}` : "-"}</strong>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-ink/55">知识</span>
                <strong>{selectedKnowledgeVersion ? `#${selectedKnowledgeVersion.id}` : "-"}</strong>
              </div>
            </div>
          </section>
        </aside>
      </section>

      <section className="panel overflow-hidden">
        <div className="panel-header">
          <div>
            <h2 className="text-lg font-bold">任务中心</h2>
            <div className="text-sm text-ink/55">{tasksQuery.data?.items?.length ?? 0} 条记录</div>
          </div>
        </div>
        {tasksQuery.data?.items?.length ? (
          <TaskTable tasks={tasksQuery.data.items} />
        ) : (
          <div className="p-5">
            <EmptyState title="暂无任务" />
          </div>
        )}
      </section>
    </div>
  );
}
