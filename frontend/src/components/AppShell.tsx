import { ArrowLeft, History, LogOut, Menu, PanelLeftClose, PanelLeftOpen, PenLine, Sparkles, X } from "lucide-react";
import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Outlet, Link, useLocation, useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { getResourcePackageTitle } from "../lib/resourceTitle";
import { useAuthStore } from "../stores/auth";
import { cn } from "../utils";
import { AssistantPanel } from "./AssistantPanel";
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
  // 侧栏收起状态，持久化到 localStorage，刷新后保持
  const [collapsed, setCollapsed] = useState(() => {
    if (typeof window === "undefined") return false;
    return localStorage.getItem("eduweave.sidebar.collapsed") === "1";
  });
  useEffect(() => {
    localStorage.setItem("eduweave.sidebar.collapsed", collapsed ? "1" : "0");
  }, [collapsed]);
  // 窄屏抽屉开关，仅在 lg 以下生效；路由切换后自动关闭
  const [mobileOpen, setMobileOpen] = useState(false);
  const locationState = location.state as { backTo?: unknown } | null;
  const normalizedPathname = normalizePathname(location.pathname);
  const isStartPage = normalizedPathname === "/";
  const isHistoryPage = normalizedPathname === "/history";
  const isAssistantPage = normalizedPathname === "/assistant";
  const isMenuPage = isStartPage || isHistoryPage || isAssistantPage;
  const isProcessPage = /^\/projects\/[^/]+$/.test(location.pathname);
  const batchResourceMatch = location.pathname.match(/^\/projects\/([^/]+)\/batches\/([^/]+)(?:\/(assessments|homework|coverage|learner-profile)\/([^/]+))?\/?$/);
  const standaloneLearnerProfileMatch = location.pathname.match(/^\/projects\/([^/]+)\/learner-profile\/([^/]+)\/?$/);
  const resourceProjectId = Number(batchResourceMatch?.[1] ?? standaloneLearnerProfileMatch?.[1] ?? 0);
  const resourceBatchId = Number(batchResourceMatch?.[2] ?? 0);
  const resourceKind = batchResourceMatch?.[3] ?? (standaloneLearnerProfileMatch ? "learner-profile" : undefined);
  const resourceDetailId = Number(batchResourceMatch?.[4] ?? standaloneLearnerProfileMatch?.[2] ?? 0);
  const hasContextHeader = isProcessPage || Boolean(batchResourceMatch || standaloneLearnerProfileMatch);
  const useQuietHeader = isMenuPage;

  const navItems = [
    { to: "/", icon: PenLine, label: "开始备课", active: isStartPage },
    { to: "/history", icon: History, label: "备课记录", active: isHistoryPage },
    { to: "/assistant", icon: Sparkles, label: "小助手", active: isAssistantPage },
  ] as const;

  // 路由切换后自动收起窄屏抽屉
  useEffect(() => {
    setMobileOpen(false);
  }, [location.pathname]);

  const handleLogout = () => {
    clearSession();
    navigate("/login", { replace: true });
  };

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
      <aside
        className={cn(
          "fixed inset-y-0 left-0 hidden flex-col border-r border-line bg-[#f2f2f2] transition-[width] duration-200 lg:flex",
          collapsed ? "w-[68px]" : "w-64",
        )}
      >
        <div className={cn("flex h-16 items-center", collapsed ? "justify-center px-0" : "gap-3 px-5")}>
          {collapsed ? (
            <button
              type="button"
              title="展开菜单"
              onClick={() => setCollapsed(false)}
              className="flex h-10 w-10 items-center justify-center rounded-xl text-ink/55 transition hover:bg-white hover:text-ink"
            >
              <PanelLeftOpen size={18} />
            </button>
          ) : (
            <>
              <BrandWordmark className="text-[36px]" />
              <button
                type="button"
                title="收起菜单"
                onClick={() => setCollapsed(true)}
                className="ml-auto flex h-9 w-9 items-center justify-center rounded-xl text-ink/45 transition hover:bg-white hover:text-ink"
              >
                <PanelLeftClose size={18} />
              </button>
            </>
          )}
        </div>
        <nav className={cn("space-y-1 py-4", collapsed ? "px-2" : "px-3")}>
          {navItems.map(({ to, icon: Icon, label, active }) => (
            <Link
              key={to}
              aria-current={active ? "page" : undefined}
              title={collapsed ? label : undefined}
              className={cn(
                "flex h-11 items-center rounded-xl text-sm font-semibold text-ink/58 transition hover:bg-white hover:text-ink",
                collapsed ? "justify-center px-0" : "gap-3 px-3",
                active && "bg-white text-ink shadow-panel",
              )}
              to={to}
            >
              <Icon size={18} className="shrink-0" />
              {collapsed ? null : label}
            </Link>
          ))}
        </nav>
        <div className={cn("mt-auto pb-4", collapsed ? "px-2" : "px-3")}>
          <button
            className={cn(
              "flex h-11 w-full items-center rounded-xl text-sm font-semibold text-ink/50 transition hover:bg-white hover:text-ink",
              collapsed ? "justify-center px-0" : "gap-3 px-3",
            )}
            type="button"
            title={collapsed ? "退出登录" : undefined}
            onClick={handleLogout}
          >
            <LogOut size={18} className="shrink-0" />
            {collapsed ? null : "退出登录"}
          </button>
        </div>
      </aside>

      <div className={cn(collapsed ? "lg:pl-[68px]" : "lg:pl-64")}>
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
              <button
                className="btn btn-ghost h-9 w-9 px-0 lg:hidden"
                type="button"
                title="菜单"
                onClick={() => setMobileOpen(true)}
              >
                <Menu size={18} />
              </button>
              <div className="flex items-center lg:hidden">
                <BrandWordmark className="text-[30px]" />
              </div>
            </div>
          )}
        </header>
        <main className="px-4 lg:px-8">
          <Outlet />
        </main>
      </div>

      {/* 窄屏抽屉：遮罩 + 左侧滑出菜单，仅 lg 以下出现 */}
      {mobileOpen ? (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div
            className="absolute inset-0 bg-ink/40 backdrop-blur-sm"
            onClick={() => setMobileOpen(false)}
            aria-hidden
          />
          <div className="absolute inset-y-0 left-0 flex w-64 flex-col border-r border-line bg-[#f2f2f2] shadow-panel">
            <div className="flex h-16 items-center gap-3 px-5">
              <BrandWordmark className="text-[36px]" />
              <button
                type="button"
                title="关闭菜单"
                onClick={() => setMobileOpen(false)}
                className="ml-auto flex h-9 w-9 items-center justify-center rounded-xl text-ink/45 transition hover:bg-white hover:text-ink"
              >
                <X size={18} />
              </button>
            </div>
            <nav className="space-y-1 px-3 py-4">
              {navItems.map(({ to, icon: Icon, label, active }) => (
                <Link
                  key={to}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "flex h-11 items-center gap-3 rounded-xl px-3 text-sm font-semibold text-ink/58 transition hover:bg-white hover:text-ink",
                    active && "bg-white text-ink shadow-panel",
                  )}
                  to={to}
                >
                  <Icon size={18} className="shrink-0" />
                  {label}
                </Link>
              ))}
            </nav>
            <div className="mt-auto px-3 pb-4">
              <button
                className="flex h-11 w-full items-center gap-3 rounded-xl px-3 text-sm font-semibold text-ink/50 transition hover:bg-white hover:text-ink"
                type="button"
                onClick={handleLogout}
              >
                <LogOut size={18} className="shrink-0" />
                退出登录
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {/* 教案页智能助手：悬浮入口 + 右侧抽屉，仅在教案（批次详情）页常驻 */}
      {batchResourceMatch && !resourceKind ? <AssistantPanel /> : null}
    </div>
  );
}
