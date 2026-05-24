import { createBrowserRouter, Navigate } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { BatchDetailPage } from "./pages/BatchDetailPage";
import { DashboardPage } from "./pages/DashboardPage";
import { LoginPage } from "./pages/LoginPage";
import { ProjectWorkspacePage } from "./pages/ProjectWorkspacePage";
import { TaskDetailPage } from "./pages/TaskDetailPage";
import { useAuthStore } from "./stores/auth";

function RequireAuth() {
  const token = useAuthStore((state) => state.token);
  if (!token) {
    return <Navigate to="/login" replace />;
  }
  return <AppShell />;
}

export const router = createBrowserRouter([
  {
    path: "/login",
    element: <LoginPage />,
  },
  {
    path: "/",
    element: <RequireAuth />,
    children: [
      {
        index: true,
        element: <DashboardPage />,
      },
      {
        path: "history",
        element: <DashboardPage />,
      },
      {
        path: "projects/:projectId",
        element: <ProjectWorkspacePage />,
      },
      {
        path: "projects/:projectId/batches/:batchId",
        element: <BatchDetailPage />,
      },
      {
        path: "tasks/:taskId",
        element: <TaskDetailPage />,
      },
    ],
  },
]);
