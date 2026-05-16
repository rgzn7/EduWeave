import { BookOpen, LayoutDashboard, LogOut, Menu, RefreshCw } from "lucide-react";
import { Outlet, Link, useLocation, useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { useAuthStore } from "../stores/auth";
import { cn } from "../utils";

export function AppShell() {
  const location = useLocation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const user = useAuthStore((state) => state.user);
  const clearSession = useAuthStore((state) => state.clearSession);

  return (
    <div className="min-h-screen bg-paper text-ink">
      <aside className="fixed inset-y-0 left-0 hidden w-64 border-r border-ink/10 bg-ink text-white lg:block">
        <div className="flex h-16 items-center gap-3 border-b border-white/10 px-5">
          <div className="flex h-9 w-9 items-center justify-center rounded-md bg-accent text-white">
            <BookOpen size={20} />
          </div>
          <div>
            <div className="text-sm font-bold">EduWeave</div>
            <div className="text-xs text-white/55">教师工作台</div>
          </div>
        </div>
        <nav className="space-y-1 px-3 py-4">
          <Link
            className={cn(
              "flex h-10 items-center gap-3 rounded-md px-3 text-sm font-semibold text-white/72 hover:bg-white/10 hover:text-white",
              location.pathname === "/" && "bg-white text-ink hover:bg-white hover:text-ink",
            )}
            to="/"
          >
            <LayoutDashboard size={18} />
            项目总览
          </Link>
        </nav>
      </aside>

      <div className="lg:pl-64">
        <header className="sticky top-0 z-10 flex h-16 items-center justify-between border-b border-line bg-paper/90 px-4 backdrop-blur lg:px-8">
          <div className="flex items-center gap-3">
            <button className="btn btn-ghost h-9 w-9 px-0 lg:hidden" type="button" title="菜单">
              <Menu size={18} />
            </button>
            <div>
              <div className="text-sm font-bold">EduWeave</div>
              <div className="text-xs text-ink/55">{user?.display_name ?? user?.username ?? "教师"}</div>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              className="btn btn-secondary h-9 w-9 px-0"
              type="button"
              title="刷新"
              onClick={() => queryClient.invalidateQueries()}
            >
              <RefreshCw size={17} />
            </button>
            <button
              className="btn btn-secondary h-9 w-9 px-0"
              type="button"
              title="退出"
              onClick={() => {
                clearSession();
                navigate("/login", { replace: true });
              }}
            >
              <LogOut size={17} />
            </button>
          </div>
        </header>
        <main className="px-4 py-6 lg:px-8">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
