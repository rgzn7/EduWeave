import { ArrowLeft, History, LogOut, Menu, PenLine } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { Outlet, Link, useLocation, useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { getResourcePackageTitle } from "../lib/resourceTitle";
import { useAuthStore } from "../stores/auth";
import { cn } from "../utils";
import { BrandWordmark } from "./BrandWordmark";

const sceneLabels: Record<string, string> = {
  homework: "课后作业",
  final_exam: "期末综合测",
};

function normalizePathname(pathname: string) {
  return pathname.replace(/\/+$/u, "") || "/";
}

export function AppShell() {
  const location = useLocation();
  const navigate = useNavigate();
  const clearSession = useAuthStore((state) => state.clearSession);
  const locationState = location.state as { backTo?: unknown } | null;
  const normalizedPathname = normalizePathname(location.pathname);
  const isStartPage = normalizedPathname === "/";
  const isHistoryPage = normalizedPathname === "/history";
  const isMenuPage = isStartPage || isHistoryPage;
  const isProcessPage = /^\/projects\/[^/]+$/.test(location.pathname);
  const batchResourceMatch = location.pathname.match(/^\/projects\/([^/]+)\/batches\/([^/]+)(?:\/(assessments|homework|coverage|learner-profile)\/([^/]+))?\/?$/);
  const standaloneLearnerProfileMatch = location.pathname.match(/^\/projects\/([^/]+)\/learner-profile\/([^/]+)\/?$/);
  const resourceProjectId = Number(batchResourceMatch?.[1] ?? standaloneLearnerProfileMatch?.[1] ?? 0);
  const resourceBatchId = Number(batchResourceMatch?.[2] ?? 0);
  const resourceKind = batchResourceMatch?.[3] ?? (standaloneLearnerProfileMatch ? "learner-profile" : undefined);
  const resourceDetailId = Number(batchResourceMatch?.[4] ?? standaloneLearnerProfileMatch?.[2] ?? 0);
  const hasContextHeader = isProcessPage || Boolean(batchResourceMatch || standaloneLearnerProfileMatch);
  const useQuietHeader = isMenuPage;

  const resourceProjectQuery = useQuery({
    queryKey: ["project", resourceProjectId],
    queryFn: () => api.getProject(resourceProjectId),
    enabled: Boolean(batchResourceMatch && !resourceKind && resourceProjectId > 0),
  });
  const resourceBatchQuery = useQuery({
    queryKey: ["generation-batch", resourceBatchId],
    queryFn: () => api.getGenerationBatch(resourceBatchId),
    enabled: Boolean(batchResourceMatch && !resourceKind && resourceBatchId > 0),
  });
  const resourceCurriculumQuery = useQuery({
    queryKey: ["curriculum-plan", resourceBatchQuery.data?.curriculum_plan_id, "header"],
    queryFn: () => api.getCurriculumPlan(resourceBatchQuery.data!.curriculum_plan_id!),
    enabled: Boolean(batchResourceMatch && !resourceKind && resourceBatchQuery.data?.curriculum_plan_id),
  });
  const paperHeaderQuery = useQuery({
    queryKey: ["paper-result", resourceDetailId],
    queryFn: () => api.getPaperResult(resourceDetailId),
    enabled: Boolean(resourceKind === "assessments" && resourceDetailId > 0),
  });
  const homeworkHeaderQuery = useQuery({
    queryKey: ["homework-result", resourceDetailId],
    queryFn: () => api.getHomeworkResult(resourceDetailId),
    enabled: Boolean(resourceKind === "homework" && resourceDetailId > 0),
  });

  const contextTitle = isProcessPage
    ? "生成过程"
    : resourceKind === "coverage"
      ? "覆盖报告"
      : resourceKind === "learner-profile"
        ? "学情画像"
      : resourceKind === "homework"
        ? homeworkHeaderQuery.data?.title ?? "课后作业"
      : resourceKind === "assessments"
        ? sceneLabels[String(paperHeaderQuery.data?.scene_type ?? "")] ?? "查看题目"
        : batchResourceMatch
          ? getResourcePackageTitle({
              planTitle: resourceCurriculumQuery.data?.plan_title,
              batchName: resourceBatchQuery.data?.batch_name,
              projectName: resourceProjectQuery.data?.name,
            })
          : "";
  const stateBackTo = typeof locationState?.backTo === "string" && locationState.backTo.startsWith("/") ? locationState.backTo : null;
  const resourceBackTo = stateBackTo ?? (resourceKind ? (resourceBatchId > 0 ? `/projects/${resourceProjectId}/batches/${resourceBatchId}` : `/projects/${resourceProjectId}`) : "/history");

  return (
    <div className="min-h-screen bg-paper text-ink">
      <aside className="fixed inset-y-0 left-0 hidden w-64 flex-col border-r border-line bg-[#f2f2f2] lg:flex">
        <div className="flex h-16 items-center gap-3 px-5">
          <BrandWordmark className="text-[36px]" />
        </div>
        <nav className="space-y-1 px-3 py-4">
          <Link
            aria-current={isStartPage ? "page" : undefined}
            className={cn(
              "flex h-11 items-center gap-3 rounded-xl px-3 text-sm font-semibold text-ink/58 transition hover:bg-white hover:text-ink",
              isStartPage && "bg-white text-ink shadow-panel",
            )}
            to="/"
          >
            <PenLine size={18} />
            开始备课
          </Link>
          <Link
            aria-current={isHistoryPage ? "page" : undefined}
            className={cn(
              "flex h-11 items-center gap-3 rounded-xl px-3 text-sm font-semibold text-ink/58 transition hover:bg-white hover:text-ink",
              isHistoryPage && "bg-white text-ink shadow-panel",
            )}
            to="/history"
          >
            <History size={18} />
            备课记录
          </Link>
        </nav>
        <div className="mt-auto px-3 pb-4">
          <button
            className="flex h-11 w-full items-center gap-3 rounded-xl px-3 text-sm font-semibold text-ink/50 transition hover:bg-white hover:text-ink"
            type="button"
            onClick={() => {
              clearSession();
              navigate("/login", { replace: true });
            }}
          >
            <LogOut size={18} />
            退出登录
          </button>
        </div>
      </aside>

      <div className="lg:pl-64">
        <header
          className={cn(
            "sticky top-0 z-10 flex h-14 items-center bg-paper/88 px-4 backdrop-blur lg:px-8",
            hasContextHeader ? "border-b border-line" : useQuietHeader ? "border-b-0 lg:hidden" : "border-b border-line",
          )}
        >
          {hasContextHeader ? (
            <div className="relative flex w-full items-center justify-between">
              {isProcessPage ? (
                <button
                  className="inline-flex h-9 items-center gap-1 text-sm font-semibold text-ink/55 transition hover:text-ink"
                  type="button"
                  onClick={() => navigate(-1)}
                >
                  <ArrowLeft size={16} />
                  返回
                </button>
              ) : (
                <Link
                  className="inline-flex h-9 items-center gap-1 text-sm font-semibold text-ink/55 transition hover:text-ink"
                  to={resourceBackTo}
                >
                  <ArrowLeft size={16} />
                  返回
                </Link>
              )}
              <div className="pointer-events-none absolute left-1/2 max-w-[60%] -translate-x-1/2 truncate text-sm font-semibold text-ink" title={contextTitle}>
                {contextTitle}
              </div>
              <div className="h-9 w-[72px]" />
            </div>
          ) : (
            <div className="flex items-center gap-3">
              <button className="btn btn-ghost h-9 w-9 px-0 lg:hidden" type="button" title="菜单">
                <Menu size={18} />
              </button>
              <div className="lg:hidden">
                <BrandWordmark className="text-[24px]" />
              </div>
            </div>
          )}
        </header>
        <main className="px-4 lg:px-8">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
