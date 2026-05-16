import { FormEvent, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, FolderPlus, Loader2, Search } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import { EmptyState } from "../components/EmptyState";
import { StatusBadge } from "../components/StatusBadge";
import { TaskTable } from "../components/TaskTable";
import { api } from "../lib/api";
import { formatDate } from "../utils";

const subjectOptions = [
  { value: "math", label: "数学" },
  { value: "chinese", label: "语文" },
  { value: "english", label: "英语" },
  { value: "science", label: "科学" },
];

const gradeOptions = [
  { value: "grade_1", label: "一年级" },
  { value: "grade_2", label: "二年级" },
  { value: "grade_3", label: "三年级" },
  { value: "grade_4", label: "四年级" },
  { value: "grade_5", label: "五年级" },
  { value: "grade_6", label: "六年级" },
  { value: "grade_7", label: "七年级" },
  { value: "grade_8", label: "八年级" },
  { value: "grade_9", label: "九年级" },
];

export function DashboardPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [keyword, setKeyword] = useState("");
  const [name, setName] = useState("小学数学秋季提升班");
  const [subjectCode, setSubjectCode] = useState("math");
  const [gradeCode, setGradeCode] = useState("grade_3");
  const [target, setTarget] = useState("基础巩固与能力提升");

  const projectsQuery = useQuery({
    queryKey: ["projects"],
    queryFn: () => api.listProjects({ page: 1, page_size: 50 }),
  });

  const tasksQuery = useQuery({
    queryKey: ["tasks", "recent"],
    queryFn: () => api.listTasks({ page: 1, page_size: 8 }),
    refetchInterval: 5_000,
  });

  const createProject = useMutation({
    mutationFn: api.createProject,
    onSuccess: (project) => {
      queryClient.invalidateQueries({ queryKey: ["projects"] });
      navigate(`/projects/${project.id}`);
    },
  });

  const projects = projectsQuery.data?.items ?? [];
  const filteredProjects = projects.filter((project) => {
    const haystack = `${project.name} ${project.subject_code} ${project.grade_code}`.toLowerCase();
    return haystack.includes(keyword.trim().toLowerCase());
  });

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    createProject.mutate({
      name,
      subject_code: subjectCode,
      grade_code: gradeCode,
      applicable_target: target,
    });
  }

  return (
    <div className="space-y-6">
      <section className="flex flex-col justify-between gap-4 lg:flex-row lg:items-end">
        <div>
          <div className="text-sm font-semibold text-accent">EduWeave</div>
          <h1 className="mt-1 text-3xl font-bold">项目总览</h1>
        </div>
        <div className="relative w-full lg:w-80">
          <Search className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink/35" size={17} />
          <input
            className="field pl-10"
            placeholder="搜索项目"
            value={keyword}
            onChange={(event) => setKeyword(event.target.value)}
          />
        </div>
      </section>

      <section className="grid gap-6 xl:grid-cols-[380px_1fr]">
        <form className="panel p-5" onSubmit={handleSubmit}>
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-md bg-accent/10 text-accent">
              <FolderPlus size={20} />
            </div>
            <div>
              <h2 className="text-lg font-bold">新建项目</h2>
              <div className="text-sm text-ink/55">Project</div>
            </div>
          </div>

          <div className="mt-5 space-y-4">
            <label className="block">
              <span className="label">项目名称</span>
              <input className="field mt-2" value={name} onChange={(event) => setName(event.target.value)} required />
            </label>
            <div className="grid grid-cols-2 gap-3">
              <label className="block">
                <span className="label">学科</span>
                <select className="field mt-2" value={subjectCode} onChange={(event) => setSubjectCode(event.target.value)}>
                  {subjectOptions.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="block">
                <span className="label">年级</span>
                <select className="field mt-2" value={gradeCode} onChange={(event) => setGradeCode(event.target.value)}>
                  {gradeOptions.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <label className="block">
              <span className="label">适用对象</span>
              <input className="field mt-2" value={target} onChange={(event) => setTarget(event.target.value)} />
            </label>
          </div>

          {createProject.error ? <div className="mt-4 text-sm font-semibold text-coral">{createProject.error.message}</div> : null}
          <button className="btn btn-primary mt-5 w-full" disabled={createProject.isPending || !name.trim()} type="submit">
            {createProject.isPending ? <Loader2 className="animate-spin" size={17} /> : <FolderPlus size={17} />}
            创建项目
          </button>
        </form>

        <div className="panel overflow-hidden">
          <div className="panel-header">
            <div>
              <h2 className="text-lg font-bold">项目列表</h2>
              <div className="text-sm text-ink/55">{projects.length} 个项目</div>
            </div>
          </div>
          <div className="grid gap-3 p-5 md:grid-cols-2 xl:grid-cols-3">
            {projectsQuery.isLoading ? (
              <div className="col-span-full flex h-36 items-center justify-center text-sm text-ink/55">
                <Loader2 className="mr-2 animate-spin" size={17} />
                加载中
              </div>
            ) : filteredProjects.length ? (
              filteredProjects.map((project) => (
                <Link
                  className="group flex min-h-40 flex-col justify-between rounded-lg border border-line bg-paper/75 p-4 transition hover:border-accent/45 hover:bg-white"
                  key={project.id}
                  to={`/projects/${project.id}`}
                >
                  <div>
                    <div className="flex items-start justify-between gap-3">
                      <h3 className="line-clamp-2 text-base font-bold text-ink">{project.name}</h3>
                      <StatusBadge status={project.status} />
                    </div>
                    <div className="mt-3 flex flex-wrap gap-2 text-xs font-semibold text-ink/55">
                      <span className="rounded-md bg-white px-2 py-1">{project.subject_code}</span>
                      <span className="rounded-md bg-white px-2 py-1">{project.grade_code}</span>
                    </div>
                  </div>
                  <div className="mt-5 flex items-center justify-between text-sm text-ink/55">
                    <span>{formatDate(project.last_activity_at ?? project.updated_at)}</span>
                    <ArrowRight className="transition group-hover:translate-x-1" size={18} />
                  </div>
                </Link>
              ))
            ) : (
              <div className="col-span-full">
                <EmptyState title="暂无项目" />
              </div>
            )}
          </div>
        </div>
      </section>

      <section className="panel overflow-hidden">
        <div className="panel-header">
          <div>
            <h2 className="text-lg font-bold">最近任务</h2>
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
