import { BookOpen, History, LogOut, Menu, PenLine } from "lucide-react";
import { Outlet, Link, useLocation, useNavigate } from "react-router-dom";
import { useAuthStore } from "../stores/auth";
import { cn } from "../utils";

export function AppShell() {
  const location = useLocation();
  const navigate = useNavigate();
  const clearSession = useAuthStore((state) => state.clearSession);
  const isDashboard = location.pathname === "/";

  return (
    <div className="min-h-screen bg-paper text-ink">
      <aside className="fixed inset-y-0 left-0 hidden w-64 flex-col border-r border-line bg-[#f2f2f2] lg:flex">
        <div className="flex h-16 items-center gap-3 px-5">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-ink text-white">
            <BookOpen size={19} />
          </div>
          <div className="text-sm font-semibold">EduWeave</div>
        </div>
        <nav className="space-y-1 px-3 py-4">
          <Link
            className={cn(
              "flex h-11 items-center gap-3 rounded-xl px-3 text-sm font-semibold text-ink/58 transition hover:bg-white hover:text-ink",
              location.pathname === "/" && !location.hash && "bg-white text-ink shadow-panel",
            )}
            to="/"
          >
            <PenLine size={18} />
            开始备课
          </Link>
          <a className="flex h-11 items-center gap-3 rounded-xl px-3 text-sm font-semibold text-ink/58 transition hover:bg-white hover:text-ink" href="/#cases">
            <History size={18} />
            历史备课
          </a>
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
            isDashboard ? "border-b-0 lg:hidden" : "border-b border-line",
          )}
        >
          <div className="flex items-center gap-3">
            <button className="btn btn-ghost h-9 w-9 px-0 lg:hidden" type="button" title="菜单">
              <Menu size={18} />
            </button>
            <div className="lg:hidden">
              <div className="text-sm font-semibold">EduWeave</div>
            </div>
          </div>
        </header>
        <main className="px-4 lg:px-8">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
